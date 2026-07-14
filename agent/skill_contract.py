"""Pure validation for Fabric's optional machine-readable skill contract.

``SKILL.md`` remains the human- and model-facing skill entrypoint.  A sibling
``skill.contract.yaml`` adds governance metadata without changing the existing
frontmatter format or the prompt-caching path.  This module deliberately has no
tool-registry, config, or provider imports so it is safe to use from the CLI,
install gates, and tests.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import re
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

import yaml

from agent.skill_evals import validate_eval_manifest
from agent.skill_utils import is_excluded_skill_path


CONTRACT_FILENAME = "skill.contract.yaml"
SOURCE_FUTURE_SKEW = timedelta(minutes=5)

_SCHEMA_VERSION = 1
_MAX_CONTRACT_BYTES = 512 * 1024
_MAX_YAML_NODES = 10_000
_MAX_YAML_DEPTH = 64
_REQUIRED_SECTIONS = (
    "identity",
    "compatibility",
    "routing",
    "interface",
    "permissions",
    "sources",
    "budgets",
    "outcomes",
    "evals",
    "limitations",
)
_TOP_LEVEL_KEYS = frozenset({"schema_version", *_REQUIRED_SECTIONS})
_SECTION_KEYS = {
    "identity": frozenset({"name", "version", "owner", "license"}),
    "compatibility": frozenset({"fabric", "hosts", "models", "platforms"}),
    "routing": frozenset(
        {"triggers", "non_triggers", "requires", "conflicts", "precedence"}
    ),
    "interface": frozenset({"inputs", "outputs"}),
    "permissions": frozenset(
        {"toolsets_required", "files", "network", "secrets", "actions"}
    ),
    "budgets": frozenset({"context_tokens", "wall_seconds", "tool_calls"}),
    "outcomes": frozenset({"primary", "guardrails"}),
    "evals": frozenset({"suite"}),
}
_INTERFACE_DESCRIPTOR_KEYS = frozenset(
    {"name", "type", "required", "description"}
)
_FILE_PERMISSION_KEYS = frozenset({"scope", "access"})
_NETWORK_PERMISSION_KEYS = frozenset({"host", "methods"})
_ACTION_KEYS = frozenset({"reversible", "approval_required", "prohibited"})
_SOURCE_KEYS = frozenset({"url", "retrieved_at", "ttl_days"})
_SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SEMVER_RE = re.compile(
    r"^(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
_CONSTRAINT_PERMISSION_FIELDS = frozenset(
    {"permissions.actions.approval_required", "permissions.actions.prohibited"}
)
_FILE_ACCESS_VALUES = frozenset({"read", "write", "read_write"})
_FILE_ACCESS_BITS = {"read": 1, "write": 2, "read_write": 3}
_FILE_SCOPES = frozenset({"workspace", "skill", "temp"})
_NETWORK_METHODS = frozenset(
    {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}
)
_DNS_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_SECRET_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_SOURCE_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_SOURCE_TIMESTAMP_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"
    r"[0-9]{2}:[0-9]{2}(?::[0-9]{2}(?:\.[0-9]{1,6})?)?"
    r"(?:Z|[+-][0-9]{2}:[0-9]{2})$"
)
_SOURCE_FRESHNESS_BLOCKING_CODES = frozenset({"source_expired"})


class _DuplicateYamlKeyError(ValueError):
    """Raised when a governance YAML mapping contains an ambiguous key."""


class _UnsafeYamlStructureError(ValueError):
    """Raised when governance YAML exceeds v1's safe structural subset."""


@dataclass(frozen=True)
class ContractIssue:
    """One stable, machine-readable contract validation finding."""

    severity: str
    code: str
    message: str
    field: str | None = None


@dataclass(frozen=True)
class SkillContractValidation:
    """Validation result for one skill directory."""

    path: Path
    status: str
    contract: dict[str, Any] | None
    digest: str | None
    issues: tuple[ContractIssue, ...]

    @property
    def ok(self) -> bool:
        """Whether the skill may proceed under the requested validation mode."""

        return not self.errors

    @property
    def errors(self) -> tuple[ContractIssue, ...]:
        """Return only fail-closed findings."""

        return tuple(issue for issue in self.issues if issue.severity == "error")

    @property
    def warnings(self) -> tuple[ContractIssue, ...]:
        """Return non-blocking migration findings."""

        return tuple(issue for issue in self.issues if issue.severity == "warning")


def discover_skill_directories(root: Path) -> tuple[Path, ...]:
    """Return active skill directories under *root* in deterministic order.

    Discovery follows the same exclusions as the runtime skill scanners, so
    archived skills and ``references/`` copies cannot accidentally enter a
    validation or promotion batch.
    """

    root = Path(root)
    if not root.is_dir():
        return ()

    discovered: set[Path] = set()
    direct = root / "SKILL.md"
    if direct.is_file() and not direct.is_symlink() and not is_excluded_skill_path(direct):
        discovered.add(root)

    for skill_md in root.rglob("SKILL.md"):
        if skill_md.is_symlink() or not skill_md.is_file():
            continue
        if is_excluded_skill_path(skill_md):
            continue
        discovered.add(skill_md.parent)

    return tuple(sorted(discovered, key=lambda path: path.as_posix()))


def validate_skill_directory(
    skill_dir: Path,
    require_contract: bool = False,
    *,
    reference_time: datetime | None = None,
) -> SkillContractValidation:
    """Validate one skill's optional ``skill.contract.yaml``.

    Missing contracts remain loadable during migration and are reported as
    ``legacy_unverified``.  Once a contract is present, every parse, schema,
    identity, and eval-suite check is fail-closed.
    """

    reference_time_utc = _normalize_reference_time(reference_time)
    skill_dir = Path(skill_dir)
    contract_path = skill_dir / CONTRACT_FILENAME
    issues: list[ContractIssue] = []
    skill_frontmatter = _validate_skill_document(skill_dir, issues)

    # ``Path.exists()`` is false for a broken symlink.  Treat any symlink as a
    # present-but-invalid contract so it cannot silently downgrade to legacy.
    if not contract_path.exists() and not contract_path.is_symlink():
        if require_contract:
            _error(
                issues,
                "contract_missing",
                f"required {CONTRACT_FILENAME} is missing",
            )
            return _result(contract_path, None, None, issues)
        issues.append(
            ContractIssue(
                "warning",
                "legacy_unverified",
                f"{CONTRACT_FILENAME} is missing; legacy skill was not verified",
            )
        )
        status = "invalid" if any(issue.severity == "error" for issue in issues) else "legacy_unverified"
        return SkillContractValidation(
            contract_path, status, None, None, tuple(issues)
        )

    if not _is_regular_file_without_symlink(contract_path):
        _error(
            issues,
            "contract_not_regular_file",
            f"{CONTRACT_FILENAME} must be a regular, non-symlink file",
        )
        return _result(contract_path, None, None, issues)

    try:
        size = contract_path.stat().st_size
    except OSError as exc:
        _error(issues, "contract_read_failed", f"could not stat contract: {exc}")
        return _result(contract_path, None, None, issues)
    if size > _MAX_CONTRACT_BYTES:
        _error(
            issues,
            "contract_too_large",
            f"contract exceeds {_MAX_CONTRACT_BYTES} bytes",
        )
        return _result(contract_path, None, None, issues)

    try:
        raw = contract_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        _error(issues, "contract_read_failed", f"could not read contract: {exc}")
        return _result(contract_path, None, None, issues)

    try:
        _reject_duplicate_yaml_keys(raw)
        loaded = yaml.safe_load(raw)
    except _DuplicateYamlKeyError as exc:
        _error(issues, "contract_yaml_duplicate_key", str(exc))
        return _result(contract_path, None, None, issues)
    except _UnsafeYamlStructureError as exc:
        _error(issues, "contract_yaml_unsafe", str(exc))
        return _result(contract_path, None, None, issues)
    except (yaml.YAMLError, ValueError, RecursionError) as exc:
        _error(issues, "contract_yaml_invalid", f"invalid contract YAML: {exc}")
        return _result(contract_path, None, None, issues)

    if not isinstance(loaded, dict):
        _error(issues, "contract_not_mapping", "contract root must be a mapping")
        return _result(contract_path, None, None, issues)

    contract: dict[str, Any] = loaded
    try:
        canonical_issue = _find_noncanonical_value(contract)
        if canonical_issue is not None:
            field, message = canonical_issue
            _error(issues, "contract_non_json_value", message, field)
            digest = None
        else:
            digest = _canonical_digest(contract)
    except (ValueError, RecursionError) as exc:
        _error(
            issues,
            "contract_canonicalization_failed",
            f"could not canonicalize contract: {exc}",
        )
        digest = None

    _validate_contract_schema(
        contract,
        skill_dir,
        skill_frontmatter,
        issues,
        reference_time=reference_time_utc,
    )
    return _result(contract_path, contract, digest, issues)


def source_freshness_blockers(
    validation: SkillContractValidation,
) -> tuple[ContractIssue, ...]:
    """Return non-fatal source findings that block promotion policy.

    Installed skills remain readable when a declared source expires, so expiry
    is a warning rather than a validation error.  Promotion code should first
    require ``validation.ok`` and then require this helper to return an empty
    tuple.  The helper is intentionally policy-only: it performs no I/O and
    does not reinterpret or mutate the validated contract.
    """

    return tuple(
        issue
        for issue in validation.issues
        if issue.code in _SOURCE_FRESHNESS_BLOCKING_CODES
    )


def permission_expansion(
    before: Mapping[str, Any] | SkillContractValidation | None,
    after: Mapping[str, Any] | SkillContractValidation | None,
) -> tuple[str, ...]:
    """Return permission fields whose authority expanded from *before* to *after*.

    Inputs may be complete contracts, permission sections, or validation
    results.  Paths always start with ``permissions`` so promotion logs remain
    unambiguous.  The comparison is deliberately conservative: an incomparable
    non-empty change is treated as expansion, while removing an approval or a
    prohibition is also expansion.
    """

    before_permissions = _permission_mapping(before)
    after_permissions = _permission_mapping(after)
    expanded: set[str] = set()
    _collect_permission_expansion(
        before_permissions,
        after_permissions,
        "permissions",
        expanded,
    )
    return tuple(sorted(expanded))


def _result(
    path: Path,
    contract: dict[str, Any] | None,
    digest: str | None,
    issues: Sequence[ContractIssue],
) -> SkillContractValidation:
    status = "invalid" if any(issue.severity == "error" for issue in issues) else "verified"
    return SkillContractValidation(path, status, contract, digest, tuple(issues))


def _error(
    issues: list[ContractIssue],
    code: str,
    message: str,
    field: str | None = None,
) -> None:
    issues.append(ContractIssue("error", code, message, field))


def _is_regular_file_without_symlink(path: Path) -> bool:
    try:
        mode = path.lstat().st_mode
    except OSError:
        return False
    return stat.S_ISREG(mode) and not path.is_symlink()


def _reject_duplicate_yaml_keys(raw: str) -> None:
    """Enforce v1's bounded, alias-free YAML subset before safe loading."""

    token_count = 0
    for token in yaml.scan(raw, Loader=yaml.SafeLoader):
        token_count += 1
        if token_count > _MAX_YAML_NODES * 4:
            raise _UnsafeYamlStructureError(
                f"YAML token count exceeds {_MAX_YAML_NODES * 4}"
            )
        if isinstance(token, (yaml.tokens.AnchorToken, yaml.tokens.AliasToken)):
            raise _UnsafeYamlStructureError(
                "YAML anchors and aliases are not supported by schema v1"
            )

    document = yaml.compose(raw, Loader=yaml.SafeLoader)
    visited: set[int] = set()
    node_count = 0

    def visit(node: yaml.Node, field: str = "", depth: int = 0) -> None:
        nonlocal node_count
        if depth > _MAX_YAML_DEPTH:
            raise _UnsafeYamlStructureError(
                f"YAML nesting exceeds {_MAX_YAML_DEPTH} levels"
            )
        marker = id(node)
        if marker in visited:
            return
        visited.add(marker)
        node_count += 1
        if node_count > _MAX_YAML_NODES:
            raise _UnsafeYamlStructureError(
                f"YAML node count exceeds {_MAX_YAML_NODES}"
            )

        if isinstance(node, yaml.MappingNode):
            seen: set[tuple[str, str]] = set()
            for key_node, value_node in node.value:
                key_text = str(key_node.value)
                key = (key_node.tag, key_text)
                child = f"{field}.{key_text}" if field else key_text
                if key in seen:
                    location = f" at {field}" if field else ""
                    raise _DuplicateYamlKeyError(
                        f"duplicate YAML key {key_text!r}{location}"
                    )
                seen.add(key)
                visit(key_node, f"{child}.__key__", depth + 1)
                visit(value_node, child, depth + 1)
        elif isinstance(node, yaml.SequenceNode):
            for index, child_node in enumerate(node.value):
                visit(child_node, f"{field}[{index}]", depth + 1)

    if document is not None:
        visit(document)


def _validate_skill_document(
    skill_dir: Path,
    issues: list[ContractIssue],
) -> dict[str, Any] | None:
    """Validate the Agent Skills document shared by legacy and governed skills."""

    skill_md = skill_dir / "SKILL.md"
    if not _is_regular_file_without_symlink(skill_md):
        _error(
            issues,
            "skill_missing",
            "SKILL.md must be a regular, non-symlink file",
            "SKILL.md",
        )
        return None
    try:
        content = skill_md.read_text(encoding="utf-8")
        frontmatter, body = _strict_frontmatter(content)
    except _DuplicateYamlKeyError as exc:
        _error(
            issues,
            "skill_frontmatter_duplicate_key",
            f"invalid SKILL.md frontmatter: {exc}",
            "SKILL.md",
        )
        return None
    except (OSError, UnicodeError, ValueError, RecursionError, yaml.YAMLError) as exc:
        _error(
            issues,
            "skill_frontmatter_invalid",
            f"could not verify SKILL.md frontmatter: {exc}",
            "SKILL.md",
        )
        return None

    for key in ("name", "description"):
        value = frontmatter.get(key)
        if not isinstance(value, str) or not value.strip():
            _error(
                issues,
                f"skill_{key}_missing",
                f"SKILL.md frontmatter must declare a non-empty {key!r}",
                f"SKILL.md.{key}",
            )
    if not body.strip():
        _error(
            issues,
            "skill_body_missing",
            "SKILL.md must contain a non-empty body after frontmatter",
            "SKILL.md",
        )
    return frontmatter


def _find_noncanonical_value(
    value: Any,
    field: str = "",
    ancestors: set[int] | None = None,
) -> tuple[str | None, str] | None:
    """Find values that cannot participate in deterministic canonical JSON."""

    ancestors = set() if ancestors is None else ancestors
    if value is None or isinstance(value, (str, bool, int)):
        return None
    if isinstance(value, float):
        if math.isfinite(value):
            return None
        return field or None, "contract numbers must be finite"

    if isinstance(value, (dict, list)):
        marker = id(value)
        if marker in ancestors:
            return field or None, "contract aliases must not form recursive values"
        ancestors.add(marker)
        try:
            if isinstance(value, dict):
                for key, child in value.items():
                    if not isinstance(key, str):
                        return field or None, "contract mapping keys must be strings"
                    child_field = f"{field}.{key}" if field else key
                    problem = _find_noncanonical_value(child, child_field, ancestors)
                    if problem is not None:
                        return problem
            else:
                for index, child in enumerate(value):
                    child_field = f"{field}[{index}]" if field else f"[{index}]"
                    problem = _find_noncanonical_value(child, child_field, ancestors)
                    if problem is not None:
                        return problem
        finally:
            ancestors.remove(marker)
        return None

    return field or None, f"unsupported YAML value type: {type(value).__name__}"


def _canonical_digest(contract: Mapping[str, Any]) -> str:
    payload = json.dumps(
        contract,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validate_contract_schema(
    contract: dict[str, Any],
    skill_dir: Path,
    skill_frontmatter: Mapping[str, Any] | None,
    issues: list[ContractIssue],
    *,
    reference_time: datetime,
) -> None:
    _reject_unknown_keys(contract, _TOP_LEVEL_KEYS, "", issues)
    version = contract.get("schema_version")
    if type(version) is not int or version != _SCHEMA_VERSION:
        _error(
            issues,
            "schema_version_unsupported",
            f"schema_version must be {_SCHEMA_VERSION}",
            "schema_version",
        )

    for section in _REQUIRED_SECTIONS:
        if section not in contract:
            _error(
                issues,
                "section_missing",
                f"required section {section!r} is missing",
                section,
            )

    identity = _mapping_section(contract, "identity", issues)
    compatibility = _mapping_section(contract, "compatibility", issues)
    routing = _mapping_section(contract, "routing", issues)
    interface = _mapping_section(contract, "interface", issues)
    permissions = _mapping_section(contract, "permissions", issues)
    sources = contract.get("sources")
    if "sources" in contract and not isinstance(sources, list):
        _error(issues, "section_type", "sources must be a list", "sources")
        sources = None
    budgets = _mapping_section(contract, "budgets", issues)
    outcomes = _mapping_section(contract, "outcomes", issues)
    evals = _mapping_section(contract, "evals", issues)
    limitations = contract.get("limitations")
    if "limitations" in contract and not _is_string_list(limitations):
        _error(
            issues,
            "field_type",
            "limitations must be a list of strings",
            "limitations",
        )

    for name, section in (
        ("identity", identity),
        ("compatibility", compatibility),
        ("routing", routing),
        ("interface", interface),
        ("permissions", permissions),
        ("budgets", budgets),
        ("outcomes", outcomes),
        ("evals", evals),
    ):
        if section is not None:
            _reject_unknown_keys(section, _SECTION_KEYS[name], name, issues)

    if identity is not None:
        _require_nonempty_string(identity, "name", "identity", issues)
        _require_nonempty_string(identity, "version", "identity", issues)
        _require_nonempty_string(identity, "owner", "identity", issues)
        _require_nonempty_string(identity, "license", "identity", issues)

        name = identity.get("name")
        if isinstance(name, str) and not _SKILL_NAME_RE.fullmatch(name):
            _error(
                issues,
                "field_value",
                "identity.name must be a lowercase hyphenated skill name",
                "identity.name",
            )
        identity_version = identity.get("version")
        if isinstance(identity_version, str) and not _SEMVER_RE.fullmatch(identity_version):
            _error(
                issues,
                "field_value",
                "identity.version must be a semantic version",
                "identity.version",
            )
        _validate_skill_identity(skill_frontmatter, identity, issues)

    if compatibility is not None:
        _require_nonempty_string(compatibility, "fabric", "compatibility", issues)
        for key in ("hosts", "models", "platforms"):
            _require_string_list(compatibility, key, "compatibility", issues)

    if routing is not None:
        for key in ("triggers", "non_triggers", "requires", "conflicts"):
            _require_string_list(routing, key, "routing", issues)
        if "precedence" in routing and (
            type(routing["precedence"]) is not int or routing["precedence"] < 0
        ):
            _error(
                issues,
                "field_value",
                "routing.precedence must be a nonnegative integer",
                "routing.precedence",
            )

    if interface is not None:
        for key in ("inputs", "outputs"):
            _require_interface_list(interface, key, issues)

    if permissions is not None:
        _require_unique_string_list(
            permissions, "toolsets_required", "permissions", issues
        )
        _require_file_permissions(permissions, issues)
        _require_network_permissions(permissions, issues)
        _require_secret_permissions(permissions, issues)
        actions = _require_mapping_field(permissions, "actions", "permissions", issues)
        if actions is not None:
            _reject_unknown_keys(
                actions, _ACTION_KEYS, "permissions.actions", issues
            )
            for key in ("reversible", "approval_required", "prohibited"):
                _require_unique_string_list(
                    actions, key, "permissions.actions", issues
                )

    if isinstance(sources, list):
        _validate_sources(sources, issues, reference_time=reference_time)

    if budgets is not None:
        for key in ("context_tokens", "wall_seconds", "tool_calls"):
            field = f"budgets.{key}"
            if key not in budgets:
                _error(issues, "field_missing", f"{field} is required", field)
                continue
            value = budgets[key]
            if type(value) is not int or value < 0:
                _error(
                    issues,
                    "field_value",
                    f"{field} must be a nonnegative integer",
                    field,
                )

    if outcomes is not None:
        _require_nonempty_string(outcomes, "primary", "outcomes", issues)
        _require_string_list(outcomes, "guardrails", "outcomes", issues)

    if evals is not None:
        suite = evals.get("suite")
        if "suite" not in evals:
            _error(issues, "field_missing", "evals.suite is required", "evals.suite")
        elif not isinstance(suite, str) or not suite.strip():
            _error(
                issues,
                "field_type",
                "evals.suite must be a non-empty relative path",
                "evals.suite",
            )
        else:
            _validate_eval_suite(skill_dir, suite, issues)


def _mapping_section(
    contract: Mapping[str, Any],
    name: str,
    issues: list[ContractIssue],
) -> dict[str, Any] | None:
    if name not in contract:
        return None
    value = contract[name]
    if not isinstance(value, dict):
        _error(issues, "section_type", f"{name} must be a mapping", name)
        return None
    return value


def _reject_unknown_keys(
    mapping: Mapping[str, Any],
    allowed: frozenset[str],
    prefix: str,
    issues: list[ContractIssue],
) -> None:
    for key in sorted(set(mapping) - allowed, key=str):
        field = f"{prefix}.{key}" if prefix else str(key)
        _error(
            issues,
            "field_unknown",
            f"{field} is not allowed by skill contract schema v1",
            field,
        )


def _require_nonempty_string(
    mapping: Mapping[str, Any],
    key: str,
    prefix: str,
    issues: list[ContractIssue],
) -> None:
    field = f"{prefix}.{key}"
    if key not in mapping:
        _error(issues, "field_missing", f"{field} is required", field)
    elif not isinstance(mapping[key], str) or not mapping[key].strip():
        _error(issues, "field_type", f"{field} must be a non-empty string", field)


def _require_string_list(
    mapping: Mapping[str, Any],
    key: str,
    prefix: str,
    issues: list[ContractIssue],
) -> None:
    field = f"{prefix}.{key}"
    if key not in mapping:
        _error(issues, "field_missing", f"{field} is required", field)
    elif not _is_string_list(mapping[key]):
        _error(issues, "field_type", f"{field} must be a list of strings", field)


def _require_unique_string_list(
    mapping: Mapping[str, Any],
    key: str,
    prefix: str,
    issues: list[ContractIssue],
) -> None:
    _require_string_list(mapping, key, prefix, issues)
    value = mapping.get(key)
    if _is_string_list(value) and len(value) != len(set(value)):
        field = f"{prefix}.{key}"
        _error(
            issues,
            "field_value",
            f"{field} entries must be unique",
            field,
        )


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, str) and bool(item.strip()) for item in value
    )


def _require_interface_list(
    interface: Mapping[str, Any],
    key: str,
    issues: list[ContractIssue],
) -> None:
    field = f"interface.{key}"
    if key not in interface:
        _error(issues, "field_missing", f"{field} is required", field)
        return
    value = interface[key]
    if not isinstance(value, list):
        _error(issues, "field_type", f"{field} must be a list", field)
        return
    for index, item in enumerate(value):
        item_field = f"{field}[{index}]"
        if not isinstance(item, dict):
            _error(
                issues,
                "field_type",
                f"{item_field} must be a descriptor mapping",
                item_field,
            )
            continue
        _reject_unknown_keys(
            item, _INTERFACE_DESCRIPTOR_KEYS, item_field, issues
        )
        _require_nonempty_string(item, "name", item_field, issues)
        _require_nonempty_string(item, "type", item_field, issues)
        if "required" in item and not isinstance(item["required"], bool):
            _error(
                issues,
                "field_type",
                f"{item_field}.required must be a boolean",
                f"{item_field}.required",
            )
        if "description" in item and (
            not isinstance(item["description"], str)
            or not item["description"].strip()
        ):
            _error(
                issues,
                "field_type",
                f"{item_field}.description must be a non-empty string",
                f"{item_field}.description",
            )


def _require_mapping_field(
    mapping: Mapping[str, Any],
    key: str,
    prefix: str,
    issues: list[ContractIssue],
) -> dict[str, Any] | None:
    field = f"{prefix}.{key}"
    if key not in mapping:
        _error(issues, "field_missing", f"{field} is required", field)
        return None
    value = mapping[key]
    if not isinstance(value, dict):
        _error(issues, "field_type", f"{field} must be a mapping", field)
        return None
    return value


def _require_file_permissions(
    permissions: Mapping[str, Any],
    issues: list[ContractIssue],
) -> None:
    field = "permissions.files"
    if "files" not in permissions:
        _error(issues, "field_missing", f"{field} is required", field)
        return
    value = permissions["files"]
    if not isinstance(value, list):
        _error(
            issues,
            "field_type",
            f"{field} must be a list of scope/access mappings",
            field,
        )
        return
    seen_scopes: set[str] = set()
    for index, entry in enumerate(value):
        item_field = f"{field}[{index}]"
        if not isinstance(entry, dict):
            _error(
                issues,
                "field_type",
                f"{item_field} must be a mapping",
                item_field,
            )
            continue
        _reject_unknown_keys(entry, _FILE_PERMISSION_KEYS, item_field, issues)
        _require_nonempty_string(entry, "scope", item_field, issues)
        _require_nonempty_string(entry, "access", item_field, issues)
        scope = entry.get("scope")
        access = entry.get("access")
        if isinstance(scope, str):
            if scope not in _FILE_SCOPES:
                _error(
                    issues,
                    "field_value",
                    f"{item_field}.scope must be workspace, skill, or temp",
                    f"{item_field}.scope",
                )
            elif scope in seen_scopes:
                _error(
                    issues,
                    "field_value",
                    f"{field} scopes must be unique",
                    f"{item_field}.scope",
                )
            seen_scopes.add(scope)
        if isinstance(access, str) and access not in _FILE_ACCESS_VALUES:
            _error(
                issues,
                "field_value",
                f"{item_field}.access must be read, write, or read_write",
                f"{item_field}.access",
            )
        elif scope == "skill" and access != "read":
            _error(
                issues,
                "field_value",
                "permissions.files scope 'skill' is read-only",
                f"{item_field}.access",
            )


def _require_network_permissions(
    permissions: Mapping[str, Any],
    issues: list[ContractIssue],
) -> None:
    field = "permissions.network"
    if "network" not in permissions:
        _error(issues, "field_missing", f"{field} is required", field)
        return
    value = permissions["network"]
    if not isinstance(value, list):
        _error(
            issues,
            "field_type",
            f"{field} must be a list of host/methods mappings",
            field,
        )
        return
    seen_hosts: set[str] = set()
    for index, entry in enumerate(value):
        item_field = f"{field}[{index}]"
        if not isinstance(entry, dict):
            _error(
                issues,
                "field_type",
                f"{item_field} must be a mapping",
                item_field,
            )
            continue
        _reject_unknown_keys(entry, _NETWORK_PERMISSION_KEYS, item_field, issues)
        _require_nonempty_string(entry, "host", item_field, issues)
        _require_unique_string_list(entry, "methods", item_field, issues)
        host = entry.get("host")
        if isinstance(host, str):
            if _parse_canonical_network_host(host) is None:
                _error(
                    issues,
                    "field_value",
                    f"{item_field}.host must be a canonical DNS/IP host with optional port",
                    f"{item_field}.host",
                )
            elif host in seen_hosts:
                _error(
                    issues,
                    "field_value",
                    f"{field} hosts must be unique",
                    f"{item_field}.host",
                )
            seen_hosts.add(host)
        methods = entry.get("methods")
        if _is_string_list(methods):
            if not methods:
                _error(
                    issues,
                    "field_value",
                    f"{item_field}.methods must not be empty",
                    f"{item_field}.methods",
                )
            for method in methods:
                if method not in _NETWORK_METHODS:
                    _error(
                        issues,
                        "field_value",
                        f"{item_field}.methods contains unsupported method {method!r}",
                        f"{item_field}.methods",
                    )


def _require_secret_permissions(
    permissions: Mapping[str, Any],
    issues: list[ContractIssue],
) -> None:
    _require_unique_string_list(permissions, "secrets", "permissions", issues)
    secrets = permissions.get("secrets")
    if not _is_string_list(secrets):
        return
    for index, secret in enumerate(secrets):
        if not _SECRET_NAME_RE.fullmatch(secret):
            _error(
                issues,
                "field_value",
                "permissions.secrets entries must be canonical environment names",
                f"permissions.secrets[{index}]",
            )


def _validate_sources(
    sources: list[Any],
    issues: list[ContractIssue],
    *,
    reference_time: datetime,
) -> None:
    for index, source in enumerate(sources):
        field = f"sources[{index}]"
        if not isinstance(source, dict):
            _error(
                issues,
                "field_type",
                f"{field} must be a mapping",
                field,
            )
            continue
        _reject_unknown_keys(source, _SOURCE_KEYS, field, issues)
        _require_nonempty_string(source, "url", field, issues)
        url = source.get("url")
        if isinstance(url, str) and url.strip():
            _validate_source_url(url, f"{field}.url", issues)

        retrieved_at = source.get("retrieved_at")
        retrieved_field = f"{field}.retrieved_at"
        retrieved_at_utc: datetime | None = None
        if "retrieved_at" not in source:
            _error(
                issues,
                "field_missing",
                f"{retrieved_field} is required",
                retrieved_field,
            )
        elif not isinstance(retrieved_at, str) or not retrieved_at.strip():
            _error(
                issues,
                "field_type",
                f"{retrieved_field} must be a quoted ISO date or timestamp string",
                retrieved_field,
            )
        else:
            try:
                retrieved_at_utc = _parse_source_retrieved_at(retrieved_at)
            except ValueError:
                _error(
                    issues,
                    "source_retrieved_at_invalid",
                    (
                        f"{retrieved_field} must be an ISO date or a timestamp "
                        "with Z or an explicit UTC offset"
                    ),
                    retrieved_field,
                )
            else:
                if retrieved_at_utc - reference_time > SOURCE_FUTURE_SKEW:
                    _error(
                        issues,
                        "source_retrieved_at_future",
                        (
                            f"{retrieved_field} is more than "
                            f"{int(SOURCE_FUTURE_SKEW.total_seconds())} seconds "
                            "in the future"
                        ),
                        retrieved_field,
                    )

        ttl = source.get("ttl_days")
        ttl_field = f"{field}.ttl_days"
        if "ttl_days" not in source:
            _error(issues, "field_missing", f"{ttl_field} is required", ttl_field)
        elif type(ttl) is not int or ttl < 0:
            _error(
                issues,
                "field_value",
                f"{ttl_field} must be a nonnegative integer",
                ttl_field,
            )
        elif (
            retrieved_at_utc is not None
            and retrieved_at_utc - reference_time <= SOURCE_FUTURE_SKEW
        ):
            _report_source_expiry(
                retrieved_at_utc,
                ttl,
                reference_time,
                field,
                issues,
            )


def _normalize_reference_time(value: datetime | None) -> datetime:
    """Return an aware UTC timestamp used for one deterministic validation."""

    if value is None:
        return datetime.now(timezone.utc)
    if not isinstance(value, datetime):
        raise TypeError("reference_time must be a datetime or None")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("reference_time must include an explicit UTC offset")
    return value.astimezone(timezone.utc)


def _parse_source_retrieved_at(value: str) -> datetime:
    """Parse the contract's closed ISO subset and normalize it to UTC.

    Date-only values represent 00:00:00 UTC.  Timestamps require either ``Z``
    or an explicit numeric UTC offset, avoiding host-timezone-dependent
    interpretation.
    """

    if value != value.strip():
        raise ValueError("source timestamp must not contain surrounding whitespace")
    if _SOURCE_DATE_RE.fullmatch(value):
        parsed_date = date.fromisoformat(value)
        return datetime.combine(parsed_date, time.min, tzinfo=timezone.utc)
    if not _SOURCE_TIMESTAMP_RE.fullmatch(value):
        raise ValueError("source timestamp is outside the supported ISO subset")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("source timestamp must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def _report_source_expiry(
    retrieved_at: datetime,
    ttl_days: int,
    reference_time: datetime,
    field: str,
    issues: list[ContractIssue],
) -> None:
    try:
        expires_at = retrieved_at + timedelta(days=ttl_days)
    except OverflowError:
        # A representable retrieval time plus an enormous nonnegative TTL
        # cannot expire within datetime's representable range.
        return
    if reference_time < expires_at:
        return
    expires_text = expires_at.isoformat().replace("+00:00", "Z")
    issues.append(
        ContractIssue(
            "warning",
            "source_expired",
            f"{field} expired at {expires_text}; refresh it before promotion",
            field,
        )
    )


def _parse_canonical_network_host(value: str) -> tuple[str, int | None] | None:
    """Parse a canonical host[:port] without accepting URL-like authority."""

    if (
        not value
        or value != value.strip()
        or any(char.isspace() for char in value)
        or any(char in value for char in ("*", "/", "?", "#", "@", "%"))
    ):
        return None

    host = value
    port: int | None = None
    if value.startswith("["):
        match = re.fullmatch(r"\[([^\]]+)\]:([1-9][0-9]{0,4})", value)
        if match is None:
            return None
        host = match.group(1)
        port = int(match.group(2))
        if port > 65_535:
            return None
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return None
        if address.version != 6 or str(address) != host:
            return None
        return str(address), port

    colon_count = value.count(":")
    if colon_count > 1:
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            return None
        if address.version != 6 or str(address) != value:
            return None
        return str(address), None
    if colon_count == 1:
        host, port_text = value.rsplit(":", 1)
        if not re.fullmatch(r"[1-9][0-9]{0,4}", port_text):
            return None
        port = int(port_text)
        if port > 65_535 or str(port) != port_text:
            return None

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        if address.version != 4 or str(address) != host:
            return None
        return str(address), port

    if len(host) > 253 or host.endswith(".") or host.lower() != host:
        return None
    labels = host.split(".")
    if not labels or not all(_DNS_LABEL_RE.fullmatch(label) for label in labels):
        return None
    return host, port


def _validate_source_url(
    value: str,
    field: str,
    issues: list[ContractIssue],
) -> None:
    if value != value.strip() or any(char.isspace() for char in value):
        _error(issues, "field_value", f"{field} must be a canonical URL", field)
        return
    try:
        parsed = urlsplit(value)
        # Accessing hostname/port triggers urllib's bracket and range checks.
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError:
        _error(issues, "field_value", f"{field} is not a valid URL", field)
        return
    if not hostname:
        _error(issues, "field_value", f"{field} must include a host", field)
        return
    if parsed.username is not None or parsed.password is not None:
        _error(
            issues,
            "field_value",
            f"{field} must not contain embedded credentials",
            field,
        )
        return
    port = parsed.port
    if ":" in hostname:
        authority = f"[{hostname}]" + (f":{port}" if port is not None else "")
    else:
        authority = hostname + (f":{port}" if port is not None else "")
    # Brackets are canonical only when an IPv6 port is present in the runtime
    # permission grammar; validate a portless IPv6 source host directly.
    host_is_valid = (
        _parse_canonical_network_host(authority) is not None
        if port is not None or ":" not in hostname
        else _parse_canonical_network_host(hostname) is not None
    )
    if not host_is_valid:
        _error(issues, "field_value", f"{field} contains an invalid host", field)
        return
    if parsed.scheme == "https":
        return
    if parsed.scheme == "http" and _is_loopback_host(hostname):
        return
    _error(
        issues,
        "field_value",
        f"{field} must use HTTPS (HTTP is allowed only for loopback development)",
        field,
    )


def _is_loopback_host(hostname: str) -> bool:
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _validate_skill_identity(
    frontmatter: Mapping[str, Any] | None,
    identity: Mapping[str, Any],
    issues: list[ContractIssue],
) -> None:
    if frontmatter is None:
        return
    for key in ("name", "version"):
        contract_value = identity.get(key)
        skill_value = frontmatter.get(key)
        field = f"identity.{key}"
        if not isinstance(skill_value, str) or not skill_value.strip():
            _error(
                issues,
                f"identity_{key}_missing_in_skill",
                f"SKILL.md frontmatter must declare {key!r} for contract verification",
                field,
            )
        elif isinstance(contract_value, str) and skill_value != contract_value:
            _error(
                issues,
                f"identity_{key}_mismatch",
                f"{field} does not match SKILL.md frontmatter",
                field,
            )


def _strict_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("missing opening YAML frontmatter delimiter")
    try:
        closing = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration as exc:
        raise ValueError("missing closing YAML frontmatter delimiter") from exc
    raw = "\n".join(lines[1:closing])
    _reject_duplicate_yaml_keys(raw)
    loaded = yaml.safe_load(raw)
    if not isinstance(loaded, dict):
        raise ValueError("YAML frontmatter must be a mapping")
    return loaded, "\n".join(lines[closing + 1 :])


def _validate_eval_suite(
    skill_dir: Path,
    suite: str,
    issues: list[ContractIssue],
) -> None:
    field = "evals.suite"
    if not _portable_relative_path(suite):
        _error(
            issues,
            "eval_suite_unsafe",
            "evals.suite must be a canonical relative POSIX path without traversal",
            field,
        )
        return

    candidate = skill_dir.joinpath(*PurePosixPath(suite).parts)
    try:
        root_resolved = skill_dir.resolve(strict=True)
        candidate_resolved = candidate.resolve(strict=False)
        candidate_resolved.relative_to(root_resolved)
    except (OSError, ValueError):
        _error(
            issues,
            "eval_suite_unsafe",
            "evals.suite resolves outside the skill directory",
            field,
        )
        return

    if _path_contains_symlink(skill_dir, candidate):
        _error(
            issues,
            "eval_suite_unsafe",
            "evals.suite must not traverse symlinks",
            field,
        )
        return
    if not _is_regular_file_without_symlink(candidate):
        _error(
            issues,
            "eval_suite_missing",
            "evals.suite must reference an existing regular file",
            field,
        )
        return

    try:
        validation = validate_eval_manifest(skill_dir, suite)
    except Exception as exc:  # pragma: no cover - fail-closed integration guard
        _error(
            issues,
            "eval_manifest_validation_failed",
            f"eval manifest validation failed safely: {exc}",
            field,
        )
        return

    for issue in validation.errors:
        _error(issues, issue.code, issue.message, issue.field or field)


def _portable_relative_path(value: str) -> bool:
    if not value or "\x00" in value or "\\" in value:
        return False
    if value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        return False
    parts = value.split("/")
    return all(part not in {"", ".", ".."} for part in parts)


def _path_contains_symlink(root: Path, candidate: Path) -> bool:
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        return True
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _permission_mapping(
    value: Mapping[str, Any] | SkillContractValidation | None,
) -> Mapping[str, Any]:
    if isinstance(value, SkillContractValidation):
        contract = value.contract
        if isinstance(contract, Mapping):
            nested = contract.get("permissions")
            return nested if isinstance(nested, Mapping) else {}
        return {}
    if not isinstance(value, Mapping):
        return {}
    nested = value.get("permissions")
    if (
        type(value.get("schema_version")) is int
        and isinstance(value.get("identity"), Mapping)
        and isinstance(nested, Mapping)
        and all(section in value for section in _REQUIRED_SECTIONS)
    ):
        return nested
    return value


def _collect_permission_expansion(
    before: Any,
    after: Any,
    path: str,
    expanded: set[str],
) -> None:
    if path in _CONSTRAINT_PERMISSION_FIELDS:
        if _constraint_was_removed(before, after):
            expanded.add(path)
        return

    if path == "permissions.files":
        if _canonical_authority_expanded(
            _normalize_file_authority(before),
            _normalize_file_authority(after),
        ):
            expanded.add(path)
        return

    if path == "permissions.network":
        if _canonical_authority_expanded(
            _normalize_network_authority(before),
            _normalize_network_authority(after),
        ):
            expanded.add(path)
        return

    if isinstance(before, Mapping) and isinstance(after, Mapping):
        for key in sorted(set(before) | set(after), key=str):
            child_path = f"{path}.{key}"
            _collect_permission_expansion(
                before.get(key),
                after.get(key),
                child_path,
                expanded,
            )
        return

    if isinstance(before, list) and isinstance(after, list):
        before_values = {_stable_permission_value(item) for item in before}
        after_values = {_stable_permission_value(item) for item in after}
        if after_values - before_values:
            expanded.add(path)
        return

    if isinstance(before, bool) and isinstance(after, bool):
        if after and not before:
            expanded.add(path)
        return

    if _is_number(before) and _is_number(after):
        if after > before:
            expanded.add(path)
        return

    if before == after or _permission_value_empty(after):
        return
    if _permission_value_empty(before) or not _permission_value_empty(after):
        expanded.add(path)


def _normalize_file_authority(value: Any) -> dict[str, int] | None:
    if value is None:
        return {}
    if not isinstance(value, list):
        return None
    normalized: dict[str, int] = {}
    for item in value:
        if not isinstance(item, Mapping):
            return None
        scope = item.get("scope")
        access = item.get("access")
        if (
            not isinstance(scope, str)
            or scope not in _FILE_SCOPES
            or scope in normalized
            or not isinstance(access, str)
            or access not in _FILE_ACCESS_BITS
            or (scope == "skill" and access != "read")
            or set(item) - _FILE_PERMISSION_KEYS
        ):
            return None
        normalized[scope] = _FILE_ACCESS_BITS[access]
    return normalized


def _normalize_network_authority(value: Any) -> dict[str, frozenset[str]] | None:
    if value is None:
        return {}
    if not isinstance(value, list):
        return None
    normalized: dict[str, frozenset[str]] = {}
    for item in value:
        if not isinstance(item, Mapping):
            return None
        host = item.get("host")
        methods = item.get("methods")
        if (
            not isinstance(host, str)
            or _parse_canonical_network_host(host) is None
            or host in normalized
            or not _is_string_list(methods)
            or not methods
            or len(methods) != len(set(methods))
            or any(method not in _NETWORK_METHODS for method in methods)
            or set(item) - _NETWORK_PERMISSION_KEYS
        ):
            return None
        normalized[host] = frozenset(methods)
    return normalized


def _canonical_authority_expanded(
    before: Mapping[str, Any] | None,
    after: Mapping[str, Any] | None,
) -> bool:
    if before is None or after is None:
        # Malformed structures have no reliable subset relation.  Fail closed
        # even when the same object was supplied twice: it may have been
        # mutated in place, so identity does not prove the prior authority.
        return True
    for key, after_authority in after.items():
        before_authority = before.get(key, 0 if isinstance(after_authority, int) else frozenset())
        if isinstance(after_authority, int):
            if after_authority & ~int(before_authority):
                return True
        elif set(after_authority) - set(before_authority):
            return True
    return False


def _constraint_was_removed(before: Any, after: Any) -> bool:
    if isinstance(before, list) and isinstance(after, list):
        before_values = {_stable_permission_value(item) for item in before}
        after_values = {_stable_permission_value(item) for item in after}
        return bool(before_values - after_values)
    if isinstance(before, bool) and isinstance(after, bool):
        return before and not after
    return not _permission_value_empty(before) and (
        _permission_value_empty(after) or before != after
    )


def _stable_permission_value(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError):
        return repr(value)


def _permission_value_empty(value: Any) -> bool:
    return value is None or value is False or value == "" or value == [] or value == {}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


__all__ = [
    "CONTRACT_FILENAME",
    "ContractIssue",
    "SkillContractValidation",
    "discover_skill_directories",
    "permission_expansion",
    "validate_skill_directory",
]
