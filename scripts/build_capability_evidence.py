#!/usr/bin/env python3
"""Build deterministic, repository-only capability evidence for R0-03.

This collector is deliberately *not* a runtime registry.  It parses Python
source, YAML/Markdown data, and filesystem layout without importing Fabric
runtime modules, provider/plugin code, or tool implementations.  It never
reads user configuration, starts subprocesses, probes dependencies, or opens
network connections.  Dynamic/user registrations are represented explicitly
as unknown rows instead of being guessed.
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any, Iterable

import yaml


SCHEMA_VERSION = 1
RECORD_ID = "r0-03-repository-capability-evidence-2026-07-10"
RECORD_DATE = "2026-07-10"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = (
    ROOT / "parity" / "capabilities" / "2026-07-10-r0-03-repository.json"
)

LIFECYCLE_AXES = (
    "declared",
    "shipped",
    "installed",
    "configured",
    "enabled",
    "active",
    "available",
)
EXPECTED_CATEGORIES = frozenset(
    {
        "automation",
        "channel",
        "command",
        "cron_provider",
        "goal",
        "mcp",
        "memory_provider",
        "model_provider",
        "platform",
        "plugin",
        "product_surface",
        "skill",
        "terminal_backend",
        "tool",
        "toolset",
    }
)
CONFIDENCE_VALUES = frozenset({"exact", "declared", "inferred", "unknown"})
RECONCILIATION_STATUSES = frozenset({"pass", "fail", "unknown"})
COLLECTION_CONTRACT = {
    "allowed_inputs": [
        "repository Python source parsed with ast",
        "repository YAML and Markdown data parsed as data",
        "repository filesystem presence and content hashes",
    ],
    "forbidden_actions": [
        "Fabric runtime imports",
        "provider/plugin/tool module imports",
        "subprocess execution",
        "network access",
        "active-profile or user-secret reads",
        "configuration or runtime-state writes",
    ],
    "unknown_dynamic_registrations": "represented_as_explicit_capabilities",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_TOKEN_RE = re.compile(r"[^a-z0-9._/-]+")
_SENSITIVE_KEY_RE = re.compile(
    r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret|headers?)",
    re.IGNORECASE,
)
_SKILL_EXCLUDED_DIRS = frozenset(
    {
        ".archive",
        ".git",
        ".github",
        ".hub",
        ".governance",
        ".mypy_cache",
        ".nox",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "node_modules",
        "site-packages",
        "venv",
    }
)
_SKILL_SUPPORT_DIRS = frozenset({"assets", "references", "scripts", "templates"})
_UNRESOLVED = object()


class CapabilityEvidenceError(ValueError):
    """Raised when an evidence manifest violates its static contract."""

    def __init__(self, errors: Iterable[str]):
        self.errors = tuple(errors)
        super().__init__("\n".join(f"- {error}" for error in self.errors))


def canonical_json(data: Any) -> str:
    """Return the canonical JSON representation used on disk."""

    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _safe_relative_path(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        return False
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and all(part not in {"", ".", ".."} for part in path.parts)
        and path.as_posix() == value
    )


def _id_token(value: str) -> str:
    normalized = _ID_TOKEN_RE.sub("-", value.strip().lower()).strip("-")
    return normalized or "unnamed"


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    except (OSError, UnicodeError, yaml.YAMLError):
        return {}
    return value if isinstance(value, dict) else {}


def _parse_python(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _evidence(
    root: Path,
    path: Path,
    *,
    kind: str,
    symbol: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "kind": kind,
        "path": _relative(root, path),
        "sha256": _sha256(path),
    }
    if symbol:
        result["symbol"] = symbol
    return result


def _authority(path: str, symbol: str, role: str) -> dict[str, str]:
    return {"path": path, "role": role, "symbol": symbol}


def _lifecycle(
    *,
    declared: bool | None,
    shipped: bool | None,
    installed: bool | None = None,
    configured: bool | None = None,
    enabled: bool | None = None,
    active: bool | None = None,
    available: bool | None = None,
) -> dict[str, bool | None]:
    return {
        "active": active,
        "available": available,
        "configured": configured,
        "declared": declared,
        "enabled": enabled,
        "installed": installed,
        "shipped": shipped,
    }


def _capability(
    *,
    category: str,
    key: str,
    label: str,
    origin: str,
    lifecycle: dict[str, bool | None],
    authorities: list[dict[str, str]],
    evidence: list[dict[str, Any]],
    confidence: str,
    metadata: dict[str, Any] | None = None,
    identity: str | None = None,
) -> dict[str, Any]:
    return {
        "authorities": authorities,
        "category": category,
        "confidence": confidence,
        "evidence": evidence,
        "id": f"{category}:{_id_token(origin)}:{_id_token(identity or key)}",
        "key": key,
        "label": label,
        "lifecycle": lifecycle,
        "metadata": metadata or {},
        "origin": origin,
    }


def _dynamic_capability(
    *,
    category: str,
    key: str,
    label: str,
    authorities: list[dict[str, str]],
    evidence: list[dict[str, Any]],
    reason: str,
) -> dict[str, Any]:
    return _capability(
        category=category,
        key=key,
        label=label,
        origin="dynamic",
        lifecycle=_lifecycle(declared=None, shipped=None),
        authorities=authorities,
        evidence=evidence,
        confidence="unknown",
        metadata={
            "enumeration": "intentionally_not_executed",
            "reason": reason,
        },
    )


def _safe_eval(node: ast.AST | None, env: dict[str, Any]) -> Any:
    """Evaluate a deliberately tiny, side-effect-free Python expression set."""

    if node is None:
        return None
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return env.get(node.id, _UNRESOLVED)
    if isinstance(node, ast.List):
        values = [_safe_eval(item, env) for item in node.elts]
        return _UNRESOLVED if _UNRESOLVED in values else values
    if isinstance(node, ast.Tuple):
        values = [_safe_eval(item, env) for item in node.elts]
        return _UNRESOLVED if _UNRESOLVED in values else tuple(values)
    if isinstance(node, ast.Set):
        values = [_safe_eval(item, env) for item in node.elts]
        return _UNRESOLVED if _UNRESOLVED in values else set(values)
    if isinstance(node, ast.Dict):
        keys = [_safe_eval(item, env) for item in node.keys]
        values = [_safe_eval(item, env) for item in node.values]
        if _UNRESOLVED in keys or _UNRESOLVED in values:
            return _UNRESOLVED
        try:
            return dict(zip(keys, values))
        except (TypeError, ValueError):
            return _UNRESOLVED
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _safe_eval(node.left, env)
        right = _safe_eval(node.right, env)
        if _UNRESOLVED in (left, right):
            return _UNRESOLVED
        try:
            return left + right
        except TypeError:
            return _UNRESOLVED
    if isinstance(node, ast.UnaryOp):
        operand = _safe_eval(node.operand, env)
        if operand is _UNRESOLVED:
            return _UNRESOLVED
        if isinstance(node.op, ast.Not):
            return not operand
        if isinstance(node.op, ast.USub) and isinstance(operand, (int, float)):
            return -operand
    if isinstance(node, ast.BoolOp):
        values = [_safe_eval(value, env) for value in node.values]
        if _UNRESOLVED in values:
            return _UNRESOLVED
        if isinstance(node.op, ast.And):
            return all(values)
        if isinstance(node.op, ast.Or):
            return any(values)
    if isinstance(node, ast.Compare) and len(node.ops) == len(node.comparators) == 1:
        left = _safe_eval(node.left, env)
        right = _safe_eval(node.comparators[0], env)
        if _UNRESOLVED in (left, right):
            return _UNRESOLVED
        op = node.ops[0]
        try:
            if isinstance(op, ast.Eq):
                return left == right
            if isinstance(op, ast.NotEq):
                return left != right
            if isinstance(op, ast.In):
                return left in right
            if isinstance(op, ast.NotIn):
                return left not in right
        except TypeError:
            return _UNRESOLVED
    if isinstance(node, ast.Subscript):
        container = _safe_eval(node.value, env)
        key = _safe_eval(node.slice, env)
        if _UNRESOLVED in (container, key):
            return _UNRESOLVED
        try:
            return container[key]
        except (KeyError, IndexError, TypeError):
            return _UNRESOLVED
    return _UNRESOLVED


def _assign_static(target: ast.AST, value: Any, env: dict[str, Any]) -> None:
    if value is _UNRESOLVED:
        return
    if isinstance(target, ast.Name):
        env[target.id] = value
        return
    if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name):
        container = env.get(target.value.id)
        key = _safe_eval(target.slice, env)
        if isinstance(container, dict) and key is not _UNRESOLVED:
            container[key] = value


def _static_environment(tree: ast.Module) -> dict[str, Any]:
    env: dict[str, Any] = {}

    def visit(nodes: list[ast.stmt]) -> None:
        for node in nodes:
            if isinstance(node, ast.Assign):
                value = _safe_eval(node.value, env)
                for target in node.targets:
                    _assign_static(target, value, env)
            elif isinstance(node, ast.AnnAssign):
                _assign_static(node.target, _safe_eval(node.value, env), env)
            elif isinstance(node, ast.If):
                condition = _safe_eval(node.test, env)
                if condition is True:
                    visit(node.body)
                elif condition is False:
                    visit(node.orelse)

    visit(tree.body)
    return env


def _call_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _call_value(
    call: ast.Call,
    env: dict[str, Any],
    keyword: str,
    position: int,
) -> Any:
    for item in call.keywords:
        if item.arg == keyword:
            return _safe_eval(item.value, env)
    if len(call.args) > position:
        return _safe_eval(call.args[position], env)
    return _UNRESOLVED


def _find_assignment_value(tree: ast.Module, name: str) -> ast.AST | None:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return node.value
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
        ):
            return node.value
    return None


def _class_symbols(tree: ast.Module) -> set[str]:
    return {node.name for node in tree.body if isinstance(node, ast.ClassDef)}


def _function_symbols(tree: ast.Module) -> set[str]:
    return {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}


def _model_provider_capabilities(root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    models_path = root / "fabric_cli" / "models.py"
    providers_path = root / "fabric_cli" / "providers.py"
    models_tree = _parse_python(models_path)
    providers_tree = _parse_python(providers_path)
    provider_env = _static_environment(providers_tree)
    raw_aliases = provider_env.get("ALIASES")
    provider_aliases = (
        {
            str(alias): str(target)
            for alias, target in raw_aliases.items()
            if isinstance(alias, str) and isinstance(target, str)
        }
        if isinstance(raw_aliases, dict)
        else {}
    )
    value = _find_assignment_value(models_tree, "CANONICAL_PROVIDERS")
    entries = value.elts if isinstance(value, (ast.List, ast.Tuple)) else []
    literal_entries: dict[str, dict[str, str]] = {}
    for item in entries:
        if not isinstance(item, ast.Call) or _call_name(item) != "ProviderEntry":
            continue
        slug = _call_value(item, {}, "slug", 0)
        label = _call_value(item, {}, "label", 1)
        description = _call_value(item, {}, "tui_desc", 2)
        if not isinstance(slug, str):
            continue
        literal_entries[slug] = {
            "description": description if isinstance(description, str) else "",
            "label": label if isinstance(label, str) else slug,
        }

    profile_records: dict[str, dict[str, Any]] = {}
    for manifest_path in sorted((root / "plugins" / "model-providers").glob("*/plugin.y*ml")):
        plugin_dir = manifest_path.parent
        init_path = plugin_dir / "__init__.py"
        if not init_path.is_file():
            continue
        tree = _parse_python(init_path)
        variables: dict[str, dict[str, Any]] = {}
        for node in tree.body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            call = node.value
            if not isinstance(call, ast.Call):
                continue
            name = _call_value(call, {}, "name", 0)
            aliases = _call_value(call, {}, "aliases", 2)
            if not isinstance(name, str):
                continue
            record = {
                "aliases": tuple(str(alias) for alias in aliases)
                if isinstance(aliases, (list, tuple))
                else (),
                "auth_type": _call_value(call, {}, "auth_type", 999),
                "description": _call_value(call, {}, "description", 999),
                "display_name": _call_value(call, {}, "display_name", 999),
                "name": name,
            }
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    variables[target.id] = record
        for node in tree.body:
            if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
                continue
            call = node.value
            if _call_name(call) != "register_provider":
                continue
            record: dict[str, Any] | None = None
            if call.args and isinstance(call.args[0], ast.Name):
                record = variables.get(call.args[0].id)
            elif call.args and isinstance(call.args[0], ast.Call):
                candidate = _call_value(call.args[0], {}, "name", 0)
                if isinstance(candidate, str):
                    record = {
                        "aliases": (),
                        "auth_type": _call_value(call.args[0], {}, "auth_type", 999),
                        "description": _call_value(call.args[0], {}, "description", 999),
                        "display_name": _call_value(call.args[0], {}, "display_name", 999),
                        "name": candidate,
                    }
            if not record or not isinstance(record.get("name"), str):
                continue
            record = dict(record)
            record["auth_type"] = (
                record["auth_type"]
                if isinstance(record.get("auth_type"), str)
                else "api_key"
            )
            record["init_path"] = init_path
            record["manifest"] = _read_yaml(manifest_path)
            record["manifest_path"] = manifest_path
            profile_records[record["name"]] = record

    excluded_auto_auth_types = {
        "aws_sdk",
        "copilot",
        "external_process",
        "oauth_device_code",
        "oauth_external",
        "vertex",
    }
    auto_canonical = {
        name
        for name, record in profile_records.items()
        if record["auth_type"] not in excluded_auto_auth_types
    }
    canonical = set(literal_entries) | auto_canonical
    rows: dict[str, dict[str, Any]] = {}
    for name in sorted(set(literal_entries) | set(profile_records)):
        literal = literal_entries.get(name)
        profile = profile_records.get(name)
        authorities: list[dict[str, str]] = []
        evidence: list[dict[str, Any]] = []
        if literal is not None or name in auto_canonical:
            authorities.append(
                _authority(
                    "fabric_cli/models.py",
                    "CANONICAL_PROVIDERS",
                    "literal_or_profile_extended_surface_membership",
                )
            )
            evidence.append(
                _evidence(root, models_path, kind="python_ast", symbol="CANONICAL_PROVIDERS")
            )
        if literal is not None:
            authorities.append(
                _authority(
                    "fabric_cli/providers.py",
                    "resolve_provider_full",
                    "generic_runtime_provider_resolution",
                )
            )
        if profile is not None:
            authorities.append(
                _authority(
                    "providers/__init__.py",
                    "_REGISTRY",
                    "runtime_profile_registry",
                )
            )
            evidence.extend(
                [
                    _evidence(root, profile["manifest_path"], kind="yaml_manifest"),
                    _evidence(
                        root,
                        profile["init_path"],
                        kind="python_ast",
                        symbol="register_provider",
                    ),
                ]
            )
        profile_manifest = profile.get("manifest", {}) if profile else {}
        label = (
            literal["label"]
            if literal
            else profile.get("display_name")
            if profile and isinstance(profile.get("display_name"), str)
            else str(profile_manifest.get("name") or name)
        )
        description = (
            literal["description"]
            if literal
            else profile.get("description")
            if profile and isinstance(profile.get("description"), str)
            else str(profile_manifest.get("description") or "")
        )
        rows[name] = _capability(
            category="model_provider",
            key=name,
            label=label,
            origin="bundled",
            lifecycle=_lifecycle(declared=True, shipped=True),
            authorities=authorities,
            evidence=evidence,
            confidence="exact" if literal is not None else "declared",
            metadata={
                "auth_type": profile.get("auth_type") if profile else "generic",
                "canonical_surface_member": name in canonical,
                "description": description,
                "literal_canonical_member": literal is not None,
                "profile_aliases": sorted(profile.get("aliases", ())) if profile else [],
                "registered_profile": profile is not None,
            },
        )

    custom = rows["custom"]
    custom["label"] = "Custom / local OpenAI-compatible endpoint (including Ollama)"
    custom["confidence"] = "exact"
    custom["authorities"].extend(
        [
            _authority("fabric_cli/providers.py", "ALIASES", "provider_alias_resolution"),
            _authority(
                "fabric_cli/providers.py",
                "resolve_provider_full",
                "custom_provider_resolution",
            ),
        ]
    )
    custom["evidence"].append(
        _evidence(root, providers_path, kind="python_ast", symbol="ALIASES")
    )
    custom["metadata"].update(
        {
            "aliases": sorted(
                alias for alias, target in provider_aliases.items() if target == "custom"
            ),
            "local_model_path": True,
            "ollama_cloud_is_separate": "ollama-cloud",
        }
    )
    rows["dynamic-user-providers"] = _dynamic_capability(
        category="model_provider",
        key="user-providers-and-custom-providers",
        label="User-defined provider registrations",
        authorities=[
            _authority(
                "fabric_cli/providers.py",
                "resolve_provider_full",
                "runtime_config_resolution",
            )
        ],
        evidence=[
            _evidence(
                root,
                providers_path,
                kind="python_ast",
                symbol="resolve_provider_full",
            )
        ],
        reason=(
            "Repository-only evidence does not read providers/custom_providers from "
            "the active profile or execute user provider plugins."
        ),
    )
    return list(rows.values()), {
        "aliases": provider_aliases,
        "auto_canonical": auto_canonical,
        "canonical": canonical,
        "literal_canonical": set(literal_entries),
        "profile_auth_types": {
            name: record["auth_type"] for name, record in profile_records.items()
        },
        "registered_profiles": set(profile_records),
    }


def _memory_capabilities(root: Path) -> tuple[list[dict[str, Any]], set[str]]:
    discovery_path = root / "plugins" / "memory" / "__init__.py"
    abc_path = root / "agent" / "memory_provider.py"
    rows = [
        _capability(
            category="memory_provider",
            key="builtin",
            label="Built-in persistent memory",
            origin="builtin",
            lifecycle=_lifecycle(declared=True, shipped=True),
            authorities=[
                _authority(
                    "agent/memory_provider.py",
                    "MemoryProvider",
                    "provider_contract",
                ),
                _authority(
                    "agent/memory_manager.py",
                    "MemoryManager",
                    "active_provider_orchestration",
                ),
            ],
            evidence=[
                _evidence(root, abc_path, kind="python_ast", symbol="MemoryProvider")
            ],
            confidence="exact",
            metadata={
                "repository_default": "selected when memory.provider is empty",
                "runtime_enablement": "profile-dependent",
            },
        )
    ]
    names: set[str] = set()
    for manifest_path in sorted((root / "plugins" / "memory").glob("*/plugin.y*ml")):
        meta = _read_yaml(manifest_path)
        name = str(meta.get("name") or manifest_path.parent.name)
        names.add(name)
        init_path = manifest_path.parent / "__init__.py"
        evidence = [_evidence(root, manifest_path, kind="yaml_manifest")]
        if init_path.is_file():
            evidence.append(
                _evidence(root, init_path, kind="python_ast", symbol="register")
            )
        rows.append(
            _capability(
                category="memory_provider",
                key=name,
                label=str(meta.get("description") or name),
                origin="bundled",
                lifecycle=_lifecycle(declared=True, shipped=True),
                authorities=[
                    _authority(
                        "plugins/memory/__init__.py",
                        "load_memory_provider",
                        "runtime_discovery_and_loading",
                    ),
                    _authority(
                        "agent/memory_provider.py",
                        "MemoryProvider",
                        "provider_contract",
                    ),
                ],
                evidence=evidence,
                confidence="declared",
                metadata={"manifest_version": str(meta.get("version") or "")},
            )
        )
    rows.append(
        _dynamic_capability(
            category="memory_provider",
            key="user-memory-provider",
            label="User-installed memory provider",
            authorities=[
                _authority(
                    "plugins/memory/__init__.py",
                    "_iter_provider_dirs",
                    "runtime_user_discovery",
                )
            ],
            evidence=[
                _evidence(
                    root,
                    discovery_path,
                    kind="python_ast",
                    symbol="_iter_provider_dirs",
                )
            ],
            reason=(
                "User memory modules are arbitrary code; repository evidence records "
                "the extension point without importing or calling is_available()."
            ),
        )
    )
    return rows, names


def _is_skill_support_path(path: Path) -> bool:
    parts = path.parts
    for index, part in enumerate(parts[:-1]):
        if part not in _SKILL_SUPPORT_DIRS or index == 0:
            continue
        skill_root = Path(*parts[:index])
        if (skill_root / "SKILL.md").is_file():
            return True
    return False


def _skill_markdown_paths(base: Path) -> list[Path]:
    if not base.is_dir():
        return []
    result = []
    for path in base.rglob("SKILL.md"):
        if any(part in _SKILL_EXCLUDED_DIRS for part in path.parts):
            continue
        if _is_skill_support_path(path):
            continue
        result.append(path)
    return sorted(result)


def _skill_frontmatter(path: Path) -> dict[str, Any]:
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return {}
    if not content.startswith("---"):
        return {}
    match = re.search(r"\n---\s*\n", content[3:])
    if match is None:
        return {}
    try:
        parsed = yaml.safe_load(content[3 : match.start() + 3]) or {}
    except yaml.YAMLError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _skill_capabilities(root: Path) -> tuple[list[dict[str, Any]], set[str]]:
    rows: list[dict[str, Any]] = []
    scanned_paths: set[str] = set()
    for origin, base, activation_default in (
        ("bundled", root / "skills", "bundled_source"),
        ("optional", root / "optional-skills", "not_active_by_default"),
    ):
        for path in _skill_markdown_paths(base):
            frontmatter = _skill_frontmatter(path)
            name = str(frontmatter.get("name") or path.parent.name)
            relative_package = path.parent.relative_to(base).as_posix()
            scanned_paths.add(_relative(root, path))
            rows.append(
                _capability(
                    category="skill",
                    key=name,
                    label=str(frontmatter.get("description") or name),
                    origin=origin,
                    lifecycle=_lifecycle(declared=True, shipped=True),
                    authorities=[
                        _authority(
                            "agent/skill_utils.py",
                            "get_all_skills_dirs",
                            "runtime_active_skill_roots",
                        ),
                        _authority(
                            "tools/skills_sync.py",
                            "_get_bundled_dir" if origin == "bundled" else "_get_optional_dir",
                            "shipped_skill_source",
                        ),
                    ],
                    evidence=[_evidence(root, path, kind="skill_markdown")],
                    confidence="declared",
                    metadata={
                        "package_path": relative_package,
                        "platforms": frontmatter.get("platforms") or [],
                        "repository_activation_default": activation_default,
                    },
                    identity=relative_package,
                )
            )
    skill_utils = root / "agent" / "skill_utils.py"
    plugin_manager = root / "fabric_cli" / "plugins.py"
    rows.extend(
        [
            _dynamic_capability(
                category="skill",
                key="active-user-and-external-skills",
                label="Active user-installed and external skills",
                authorities=[
                    _authority(
                        "agent/skill_utils.py",
                        "get_all_skills_dirs",
                        "runtime_active_skill_roots",
                    )
                ],
                evidence=[
                    _evidence(
                        root,
                        skill_utils,
                        kind="python_ast",
                        symbol="get_all_skills_dirs",
                    )
                ],
                reason=(
                    "Repository-only scope excludes FABRIC_HOME/skills and "
                    "skills.external_dirs."
                ),
            ),
            _dynamic_capability(
                category="skill",
                key="plugin-registered-skills",
                label="Plugin-registered namespaced skills",
                authorities=[
                    _authority(
                        "fabric_cli/plugins.py",
                        "PluginContext.register_skill",
                        "runtime_plugin_skill_registration",
                    )
                ],
                evidence=[
                    _evidence(
                        root,
                        plugin_manager,
                        kind="python_ast",
                        symbol="PluginContext.register_skill",
                    )
                ],
                reason="Plugin skill registrations are known only after executing plugin code.",
            ),
        ]
    )
    return rows, scanned_paths


def _general_plugin_capabilities(root: Path) -> list[dict[str, Any]]:
    manager_path = root / "fabric_cli" / "plugins.py"
    excluded = {"memory", "model-providers", "platforms"}
    rows: list[dict[str, Any]] = []
    manifests = sorted((root / "plugins").glob("*/plugin.y*ml"))
    manifests.extend(sorted((root / "plugins").glob("*/*/plugin.y*ml")))
    for manifest_path in manifests:
        relative_dir = manifest_path.parent.relative_to(root / "plugins")
        if relative_dir.parts[0] in excluded:
            continue
        meta = _read_yaml(manifest_path)
        key = (
            relative_dir.as_posix()
            if len(relative_dir.parts) > 1
            else str(meta.get("name") or relative_dir.name)
        )
        rows.append(
            _capability(
                category="plugin",
                key=key,
                label=str(meta.get("description") or meta.get("name") or key),
                origin="bundled",
                lifecycle=_lifecycle(declared=True, shipped=True),
                authorities=[
                    _authority(
                        "fabric_cli/plugins.py",
                        "PluginManager",
                        "runtime_plugin_registry",
                    )
                ],
                evidence=[_evidence(root, manifest_path, kind="yaml_manifest")],
                confidence="declared",
                metadata={
                    "kind": str(meta.get("kind") or "standalone"),
                    "runtime_enablement": (
                        "bundled_backend_auto_load_unless_disabled"
                        if meta.get("kind") == "backend"
                        else "profile-dependent"
                    ),
                    "manifest_name": str(meta.get("name") or relative_dir.name),
                    "provides_tools": sorted(
                        str(value) for value in (meta.get("provides_tools") or [])
                    ),
                },
            )
        )
    rows.append(
        _dynamic_capability(
            category="plugin",
            key="user-project-and-entrypoint-plugins",
            label="User, project, and Python entry-point plugins",
            authorities=[
                _authority(
                    "fabric_cli/plugins.py",
                    "PluginManager.discover_and_load",
                    "runtime_plugin_discovery",
                )
            ],
            evidence=[
                _evidence(
                    root,
                    manager_path,
                    kind="python_ast",
                    symbol="PluginManager.discover_and_load",
                )
            ],
            reason=(
                "Repository evidence neither reads operator enablement nor executes "
                "user/project/entry-point plugin code."
            ),
        )
    )
    return rows


def _mcp_capabilities(root: Path) -> tuple[list[dict[str, Any]], set[str]]:
    catalog_path = root / "fabric_cli" / "mcp_catalog.py"
    runtime_path = root / "tools" / "mcp_tool.py"
    rows: list[dict[str, Any]] = []
    names: set[str] = set()
    for manifest_path in sorted((root / "optional-mcps").glob("*/manifest.yaml")):
        meta = _read_yaml(manifest_path)
        name = str(meta.get("name") or manifest_path.parent.name)
        names.add(name)
        transport = meta.get("transport") if isinstance(meta.get("transport"), dict) else {}
        auth = meta.get("auth") if isinstance(meta.get("auth"), dict) else {}
        rows.append(
            _capability(
                category="mcp",
                key=name,
                label=str(meta.get("description") or name),
                origin="optional_catalog",
                lifecycle=_lifecycle(declared=True, shipped=True),
                authorities=[
                    _authority(
                        "fabric_cli/mcp_catalog.py",
                        "list_catalog",
                        "curated_catalog",
                    ),
                    _authority(
                        "tools/mcp_tool.py",
                        "register_mcp_servers",
                        "runtime_server_and_tool_registration",
                    ),
                ],
                evidence=[_evidence(root, manifest_path, kind="yaml_manifest")],
                confidence="declared",
                metadata={
                    "auth_type": str(auth.get("type") or "none"),
                    "repository_activation_default": "catalog_only_not_installed_by_default",
                    "transport_type": str(transport.get("type") or "unknown"),
                },
            )
        )
    rows.append(
        _dynamic_capability(
            category="mcp",
            key="configured-servers-and-live-tools",
            label="Configured MCP servers and live discovered tools",
            authorities=[
                _authority(
                    "tools/mcp_tool.py",
                    "discover_mcp_tools",
                    "runtime_server_and_tool_discovery",
                )
            ],
            evidence=[
                _evidence(
                    root,
                    runtime_path,
                    kind="python_ast",
                    symbol="discover_mcp_tools",
                ),
                _evidence(
                    root,
                    catalog_path,
                    kind="python_ast",
                    symbol="list_catalog",
                ),
            ],
            reason=(
                "Live MCP tools require reading profile config/secrets and connecting to or "
                "spawning servers; those actions are forbidden in this collector."
            ),
        )
    )
    return rows, names


def _platform_capabilities(root: Path) -> tuple[list[dict[str, Any]], set[str]]:
    config_path = root / "gateway" / "config.py"
    registry_path = root / "gateway" / "platform_registry.py"
    tree = _parse_python(config_path)
    builtins: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != "Platform":
            continue
        for child in node.body:
            if (
                isinstance(child, ast.Assign)
                and len(child.targets) == 1
                and isinstance(child.targets[0], ast.Name)
                and isinstance(child.value, ast.Constant)
                and isinstance(child.value.value, str)
            ):
                builtins[child.value.value] = child.targets[0].id

    plugin_manifests = sorted((root / "plugins" / "platforms").glob("*/plugin.y*ml"))
    plugin_paths: dict[str, Path] = {path.parent.name: path for path in plugin_manifests}
    keys = set(builtins) | set(plugin_paths)
    rows: list[dict[str, Any]] = []
    for key in sorted(keys):
        evidence = [
            _evidence(root, config_path, kind="python_ast", symbol="Platform")
        ] if key in builtins else []
        metadata: dict[str, Any] = {
            "builtin_enum": key in builtins,
            "deferred_plugin": key in plugin_paths,
        }
        if key in plugin_paths:
            evidence.append(_evidence(root, plugin_paths[key], kind="yaml_manifest"))
            meta = _read_yaml(plugin_paths[key])
            label = str(meta.get("description") or meta.get("name") or key)
            metadata["manifest_name"] = str(meta.get("name") or key)
        else:
            label = key.replace("_", " ").title()
        rows.append(
            _capability(
                category="platform",
                key=key,
                label=label,
                origin="bundled",
                lifecycle=_lifecycle(declared=True, shipped=True),
                authorities=[
                    _authority("gateway/config.py", "Platform", "platform_identity"),
                    _authority(
                        "gateway/platform_registry.py",
                        "platform_registry",
                        "dynamic_adapter_registry",
                    ),
                ],
                evidence=evidence,
                confidence="exact" if key in builtins else "declared",
                metadata=metadata,
            )
        )
    rows.append(
        _dynamic_capability(
            category="platform",
            key="user-platform-plugins",
            label="User-installed platform adapters",
            authorities=[
                _authority(
                    "gateway/platform_registry.py",
                    "PlatformRegistry.register",
                    "runtime_adapter_registration",
                )
            ],
            evidence=[
                _evidence(
                    root,
                    registry_path,
                    kind="python_ast",
                    symbol="PlatformRegistry.register",
                )
            ],
            reason="User platform identities exist only after plugin discovery/registration.",
        )
    )
    return rows, set(plugin_paths)


def _channel_capabilities(root: Path) -> list[dict[str, Any]]:
    directory_path = root / "gateway" / "channel_directory.py"
    return [
        _capability(
            category="channel",
            key="channel-directory",
            label="Reachable channel/contact directory",
            origin="bundled",
            lifecycle=_lifecycle(declared=True, shipped=True),
            authorities=[
                _authority(
                    "gateway/channel_directory.py",
                    "build_channel_directory",
                    "runtime_reachable_target_directory",
                )
            ],
            evidence=[
                _evidence(
                    root,
                    directory_path,
                    kind="python_ast",
                    symbol="build_channel_directory",
                )
            ],
            confidence="exact",
            metadata={
                "distinction": "directory entries are live targets, not platform identities"
            },
        ),
        _dynamic_capability(
            category="channel",
            key="live-channel-targets",
            label="Live reachable channels and contacts",
            authorities=[
                _authority(
                    "gateway/channel_directory.py",
                    "build_channel_directory",
                    "runtime_live_enumeration",
                )
            ],
            evidence=[
                _evidence(
                    root,
                    directory_path,
                    kind="python_ast",
                    symbol="build_channel_directory",
                )
            ],
            reason=(
                "Live target enumeration depends on connected adapters, platform APIs, "
                "session data, and the active profile."
            ),
        ),
    ]


def _command_capabilities(
    root: Path,
) -> tuple[list[dict[str, Any]], list[str], list[tuple[str, str]]]:
    """Collect the central command registry and mark profile extensions unknown."""

    path = root / "fabric_cli" / "commands.py"
    rows: list[dict[str, Any]] = []
    names: list[str] = []
    alias_targets: list[tuple[str, str]] = []
    for call in _catalog_calls(path, "COMMAND_REGISTRY"):
        name = _call_value(call, {}, "name", 0)
        description = _call_value(call, {}, "description", 1)
        command_category = _call_value(call, {}, "category", 2)
        if not isinstance(name, str):
            continue
        aliases_value = _call_value(call, {}, "aliases", 3)
        aliases = (
            [str(alias) for alias in aliases_value]
            if isinstance(aliases_value, (list, tuple))
            else []
        )
        names.append(name)
        for alias in aliases:
            alias_targets.append((alias, name))
        rows.append(
            _capability(
                category="command",
                key=name,
                label=description if isinstance(description, str) else name,
                origin="bundled",
                lifecycle=_lifecycle(declared=True, shipped=True),
                authorities=[
                    _authority(
                        "fabric_cli/commands.py",
                        "COMMAND_REGISTRY",
                        "cross_surface_command_registry",
                    )
                ],
                evidence=[
                    _evidence(
                        root,
                        path,
                        kind="python_ast",
                        symbol="COMMAND_REGISTRY",
                    )
                ],
                confidence="exact",
                metadata={
                    "aliases": aliases,
                    "args_hint": _call_value(call, {}, "args_hint", 4)
                    if isinstance(_call_value(call, {}, "args_hint", 4), str)
                    else "",
                    "cli_only": _call_value(call, {}, "cli_only", 6) is True,
                    "command_category": command_category
                    if isinstance(command_category, str)
                    else "",
                    "gateway_config_gate": _call_value(
                        call, {}, "gateway_config_gate", 8
                    )
                    if isinstance(
                        _call_value(call, {}, "gateway_config_gate", 8), str
                    )
                    else "",
                    "gateway_only": _call_value(call, {}, "gateway_only", 7) is True,
                    "subcommands": [
                        str(value)
                        for value in (
                            _call_value(call, {}, "subcommands", 5)
                            if isinstance(
                                _call_value(call, {}, "subcommands", 5),
                                (list, tuple),
                            )
                            else []
                        )
                    ],
                },
            )
        )
    rows.append(
        _dynamic_capability(
            category="command",
            key="profile-skill-and-quick-commands",
            label="Profile skill commands and user quick commands",
            authorities=[
                _authority(
                    "agent/skill_commands.py",
                    "scan_skill_commands",
                    "runtime_skill_command_discovery",
                ),
                _authority(
                    "cli.py",
                    "HermesCLI.process_command",
                    "runtime_quick_command_dispatch",
                ),
            ],
            evidence=[
                _evidence(
                    root,
                    root / "agent" / "skill_commands.py",
                    kind="python_ast",
                    symbol="scan_skill_commands",
                )
            ],
            reason=(
                "Skill-derived and quick commands depend on active profile files and "
                "config, which repository-only evidence does not read."
            ),
        )
    )
    return rows, names, alias_targets


def _registry_register_calls(path: Path) -> list[tuple[str | None, str | None, int]]:
    tree = _parse_python(path)
    env = _static_environment(tree)
    result: list[tuple[str | None, str | None, int]] = []
    for node in tree.body:
        if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
            continue
        call = node.value
        if not (
            isinstance(call.func, ast.Attribute)
            and call.func.attr == "register"
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "registry"
        ):
            continue
        name = _call_value(call, env, "name", 0)
        toolset = _call_value(call, env, "toolset", 1)
        result.append(
            (
                name if isinstance(name, str) else None,
                toolset if isinstance(toolset, str) else None,
                node.lineno,
            )
        )
    return result


def _tool_capabilities(root: Path) -> tuple[list[dict[str, Any]], set[str], dict[str, str]]:
    registry_path = root / "tools" / "registry.py"
    rows: list[dict[str, Any]] = []
    names: set[str] = set()
    name_to_toolset: dict[str, str] = {}
    for path in sorted((root / "tools").glob("*.py")):
        if path.name in {"__init__.py", "mcp_tool.py", "registry.py"}:
            continue
        for index, (name, toolset, line) in enumerate(_registry_register_calls(path), start=1):
            identity = name or f"unresolved-{path.stem}-{index}"
            if name:
                names.add(name)
                if toolset:
                    name_to_toolset[name] = toolset
            rows.append(
                _capability(
                    category="tool",
                    key=identity,
                    label=name or f"Unresolved static registration in {path.name}",
                    origin="bundled",
                    lifecycle=_lifecycle(declared=True, shipped=True),
                    authorities=[
                        _authority(
                            "tools/registry.py",
                            "registry",
                            "runtime_tool_registry",
                        )
                    ],
                    evidence=[
                        _evidence(
                            root,
                            path,
                            kind="python_ast",
                            symbol=f"registry.register@L{line}",
                        )
                    ],
                    confidence="exact" if name and toolset else "unknown",
                    metadata={"declared_toolset": toolset},
                )
            )
    rows.append(
        _dynamic_capability(
            category="tool",
            key="runtime-plugin-memory-and-mcp-tools",
            label="Runtime plugin, memory-provider, and MCP tools",
            authorities=[
                _authority("tools/registry.py", "registry", "runtime_tool_registry")
            ],
            evidence=[
                _evidence(root, registry_path, kind="python_ast", symbol="registry")
            ],
            reason=(
                "These tool names are registered only after executing provider/plugin "
                "code or connecting to MCP servers."
            ),
        )
    )
    return rows, names, name_to_toolset


def _toolset_capabilities(root: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    path = root / "toolsets.py"
    tree = _parse_python(path)
    env = _static_environment(tree)
    toolsets = env.get("TOOLSETS")
    if not isinstance(toolsets, dict):
        toolsets = {}
    rows: list[dict[str, Any]] = []
    normalized: dict[str, dict[str, Any]] = {}
    for name, definition in sorted(toolsets.items()):
        if not isinstance(name, str) or not isinstance(definition, dict):
            continue
        tools = definition.get("tools") if isinstance(definition.get("tools"), list) else []
        includes = (
            definition.get("includes")
            if isinstance(definition.get("includes"), list)
            else []
        )
        normalized[name] = {
            "includes": [str(value) for value in includes],
            "tools": [str(value) for value in tools],
        }
        rows.append(
            _capability(
                category="toolset",
                key=name,
                label=str(definition.get("description") or name),
                origin="bundled",
                lifecycle=_lifecycle(declared=True, shipped=True),
                authorities=[
                    _authority("toolsets.py", "TOOLSETS", "static_toolset_definitions"),
                    _authority(
                        "tools/registry.py",
                        "ToolRegistry",
                        "runtime_toolset_extensions",
                    ),
                ],
                evidence=[
                    _evidence(root, path, kind="python_ast", symbol=f"TOOLSETS[{name!r}]")
                ],
                confidence="exact",
                metadata=normalized[name],
            )
        )
    rows.append(
        _dynamic_capability(
            category="toolset",
            key="runtime-plugin-and-mcp-toolsets",
            label="Runtime plugin and MCP toolsets",
            authorities=[
                _authority(
                    "tools/registry.py",
                    "ToolRegistry.register_toolset_alias",
                    "runtime_toolset_registration",
                )
            ],
            evidence=[
                _evidence(
                    root,
                    root / "tools" / "registry.py",
                    kind="python_ast",
                    symbol="ToolRegistry.register_toolset_alias",
                )
            ],
            reason="Dynamic toolsets depend on runtime plugin/MCP registration.",
        )
    )
    return rows, normalized


def _catalog_calls(path: Path, symbol: str) -> list[ast.Call]:
    tree = _parse_python(path)
    value = _find_assignment_value(tree, symbol)
    if not isinstance(value, (ast.List, ast.Tuple)):
        return []
    return [item for item in value.elts if isinstance(item, ast.Call)]


def _automation_capabilities(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    blueprint_path = root / "cron" / "blueprint_catalog.py"
    suggestion_path = root / "cron" / "suggestion_catalog.py"
    for kind, path in (
        ("blueprint", blueprint_path),
        ("starter_suggestion", suggestion_path),
    ):
        for call in _catalog_calls(path, "CATALOG"):
            key = _call_value(call, {}, "key", 0)
            title = _call_value(call, {}, "title", 1)
            description = _call_value(call, {}, "description", 2)
            if not isinstance(key, str):
                continue
            category = _call_value(call, {}, "category", 3)
            rows.append(
                _capability(
                    category="automation",
                    key=key,
                    label=title if isinstance(title, str) else key,
                    origin="bundled_catalog",
                    lifecycle=_lifecycle(declared=True, shipped=True),
                    authorities=[
                        _authority(
                            _relative(root, path),
                            "CATALOG",
                            "curated_automation_catalog",
                        ),
                        _authority(
                            "cron/jobs.py",
                            "create_job",
                            "runtime_job_creation",
                        ),
                    ],
                    evidence=[_evidence(root, path, kind="python_ast", symbol="CATALOG")],
                    confidence="exact",
                    metadata={
                        "automation_kind": kind,
                        "category": category if isinstance(category, str) else "",
                        "repository_activation_default": "catalog_only_not_scheduled_by_default",
                    },
                    identity=f"{kind}/{key}",
                )
            )
    jobs_path = root / "cron" / "jobs.py"
    rows.append(
        _dynamic_capability(
            category="automation",
            key="installed-cron-jobs",
            label="Installed and active scheduled jobs",
            authorities=[
                _authority("cron/jobs.py", "JOBS_FILE", "runtime_job_store")
            ],
            evidence=[_evidence(root, jobs_path, kind="python_ast", symbol="JOBS_FILE")],
            reason=(
                "Repository-only scope excludes the active profile jobs.json; load_jobs() "
                "is intentionally not called because it can create or repair state."
            ),
        )
    )
    return rows


def _cron_provider_capabilities(root: Path) -> list[dict[str, Any]]:
    provider_path = root / "cron" / "scheduler_provider.py"
    discovery_path = root / "plugins" / "cron_providers" / "__init__.py"
    rows = [
        _capability(
            category="cron_provider",
            key="builtin",
            label="Built-in in-process cron scheduler",
            origin="builtin",
            lifecycle=_lifecycle(declared=True, shipped=True),
            authorities=[
                _authority(
                    "cron/scheduler_provider.py",
                    "CronScheduler",
                    "scheduler_provider_contract",
                ),
                _authority(
                    "cron/scheduler_provider.py",
                    "resolve_cron_scheduler",
                    "active_provider_resolution",
                ),
            ],
            evidence=[
                _evidence(root, provider_path, kind="python_ast", symbol="CronScheduler")
            ],
            confidence="exact",
            metadata={
                "repository_default": "default and fail-safe fallback",
                "runtime_enablement": "profile-dependent",
            },
        )
    ]
    for manifest_path in sorted((root / "plugins" / "cron_providers").glob("*/plugin.y*ml")):
        meta = _read_yaml(manifest_path)
        name = str(meta.get("name") or manifest_path.parent.name)
        rows.append(
            _capability(
                category="cron_provider",
                key=name,
                label=str(meta.get("description") or name),
                origin="bundled",
                lifecycle=_lifecycle(declared=True, shipped=True),
                authorities=[
                    _authority(
                        "plugins/cron_providers/__init__.py",
                        "load_cron_scheduler",
                        "runtime_scheduler_plugin_loading",
                    )
                ],
                evidence=[_evidence(root, manifest_path, kind="yaml_manifest")],
                confidence="declared",
            )
        )
    rows.append(
        _dynamic_capability(
            category="cron_provider",
            key="user-cron-provider",
            label="User-installed cron scheduler provider",
            authorities=[
                _authority(
                    "plugins/cron_providers/__init__.py",
                    "_iter_provider_dirs",
                    "runtime_user_discovery",
                )
            ],
            evidence=[
                _evidence(
                    root,
                    discovery_path,
                    kind="python_ast",
                    symbol="_iter_provider_dirs",
                )
            ],
            reason="User scheduler modules are arbitrary code and are not imported.",
        )
    )
    return rows


def _goal_capabilities(root: Path) -> list[dict[str, Any]]:
    path = root / "fabric_cli" / "goals.py"
    tree = _parse_python(path)
    classes = _class_symbols(tree)
    functions = _function_symbols(tree)
    required = {"GoalContract", "GoalManager", "GoalState"}
    return [
        _capability(
            category="goal",
            key="persistent-session-goals",
            label="Persistent session goal loop with completion contracts",
            origin="bundled",
            lifecycle=_lifecycle(declared=True, shipped=True),
            authorities=[
                _authority("fabric_cli/goals.py", "GoalManager", "goal_orchestration"),
                _authority("fabric_cli/goals.py", "GoalState", "persisted_goal_state"),
            ],
            evidence=[
                _evidence(root, path, kind="python_ast", symbol="GoalManager")
            ],
            confidence="exact" if required <= classes and "load_goal" in functions else "unknown",
            metadata={
                "active_goal_state": "not_read",
                "required_symbols_present": sorted(required & classes),
            },
        )
    ]


def _function_string_comparisons(path: Path, function_name: str, variable: str) -> set[str]:
    tree = _parse_python(path)
    result: set[str] = set()
    function = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == function_name
        ),
        None,
    )
    if function is None:
        return result
    for node in ast.walk(function):
        if not isinstance(node, ast.Compare) or len(node.ops) != 1:
            continue
        if not isinstance(node.ops[0], ast.Eq) or len(node.comparators) != 1:
            continue
        if not isinstance(node.left, ast.Name) or node.left.id != variable:
            continue
        comparator = node.comparators[0]
        if isinstance(comparator, ast.Constant) and isinstance(comparator.value, str):
            result.add(comparator.value)
    return result


def _terminal_capabilities(root: Path) -> tuple[list[dict[str, Any]], set[str], set[str]]:
    path = root / "tools" / "terminal_tool.py"
    factory = _function_string_comparisons(path, "_create_environment", "env_type")
    requirements = _function_string_comparisons(path, "check_terminal_requirements", "env_type")
    class_map = {
        "daytona": "tools/environments/daytona.py::DaytonaEnvironment",
        "docker": "tools/environments/docker.py::DockerEnvironment",
        "local": "tools/environments/local.py::LocalEnvironment",
        "modal": "tools/environments/modal.py::ModalEnvironment",
        "singularity": "tools/environments/singularity.py::SingularityEnvironment",
        "ssh": "tools/environments/ssh.py::SSHEnvironment",
    }
    rows = []
    for name in sorted(factory):
        metadata: dict[str, Any] = {
            "environment_class": class_map.get(name, "unknown"),
            "requirements_branch": name in requirements,
        }
        if name == "modal":
            metadata["modes"] = ["auto", "direct", "managed"]
            metadata["managed_class"] = (
                "tools/environments/managed_modal.py::ManagedModalEnvironment"
            )
        rows.append(
            _capability(
                category="terminal_backend",
                key=name,
                label=f"{name.title()} terminal backend",
                origin="bundled",
                lifecycle=_lifecycle(declared=True, shipped=True),
                authorities=[
                    _authority(
                        "tools/terminal_tool.py",
                        "_create_environment",
                        "runtime_backend_factory",
                    ),
                    _authority(
                        "tools/terminal_tool.py",
                        "check_terminal_requirements",
                        "runtime_availability_check",
                    ),
                ],
                evidence=[
                    _evidence(
                        root,
                        path,
                        kind="python_ast",
                        symbol="_create_environment",
                    )
                ],
                confidence="exact",
                metadata=metadata,
            )
        )
    return rows, factory, requirements


_SURFACE_SPECS = (
    ("classic-cli", "Classic interactive CLI", "cli.py", "HermesCLI"),
    ("ink-tui", "Ink terminal UI", "ui-tui/src/app.tsx", "App"),
    ("tui-gateway", "TUI JSON-RPC gateway", "tui_gateway/entry.py", "main"),
    ("web-dashboard", "Web dashboard", "web/src/App.tsx", "App"),
    ("headless-serve", "Headless desktop/web backend", "fabric_cli/main.py", "cmd_dashboard"),
    (
        "electron-desktop",
        "Electron desktop application",
        "apps/desktop/src/app/desktop-controller.tsx",
        "DesktopController",
    ),
    ("messaging-gateway", "Multi-platform messaging gateway", "gateway/run.py", "GatewayRunner"),
    ("api-server", "OpenAI-compatible API server platform", "gateway/platforms/api_server.py", "APIServerAdapter"),
    ("acp", "Agent Client Protocol editor server", "acp_adapter/entry.py", "main"),
    ("cron", "Cron automation scheduler", "cron/scheduler.py", "tick"),
    ("batch", "Parallel batch runner", "batch_runner.py", "main"),
    (
        "bootstrap-installer",
        "Native bootstrap installer",
        "apps/bootstrap-installer/src/app.tsx",
        "App",
    ),
    ("documentation-site", "Documentation website", "website/docusaurus.config.ts", "config"),
)


def _source_symbol_exists(path: Path, symbol: str) -> bool:
    """Check a declared entrypoint/authority symbol without importing code."""

    if not path.is_file() or not symbol:
        return False
    if path.suffix == ".py":
        tree = _parse_python(path)
        parts = symbol.split(".")
        nodes: list[ast.stmt] = list(tree.body)
        for index, part in enumerate(parts):
            found: ast.AST | None = None
            for node in nodes:
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name == part:
                        found = node
                        break
                elif isinstance(node, ast.Assign) and any(
                    isinstance(target, ast.Name) and target.id == part
                    for target in node.targets
                ):
                    found = node
                    break
                elif (
                    isinstance(node, ast.AnnAssign)
                    and isinstance(node.target, ast.Name)
                    and node.target.id == part
                ):
                    found = node
                    break
            if found is None:
                return False
            if index < len(parts) - 1:
                if not isinstance(found, ast.ClassDef):
                    return False
                nodes = list(found.body)
        return True
    if path.suffix == ".json":
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return False
        current: Any = value
        for part in symbol.split("."):
            if not isinstance(current, dict) or part not in current:
                return False
            current = current[part]
        return True
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    return bool(
        re.search(
            rf"\b(?:class|function|const|let|var)\s+{re.escape(symbol)}\b",
            source,
        )
    )


def _surface_capabilities(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    rows = []
    missing = []
    for key, label, relative_path, symbol in _SURFACE_SPECS:
        path = root / relative_path
        if not path.is_file():
            missing.append(key)
            continue
        entrypoint_present = _source_symbol_exists(path, symbol)
        if not entrypoint_present:
            missing.append(key)
        rows.append(
            _capability(
                category="product_surface",
                key=key,
                label=label,
                origin="bundled",
                lifecycle=_lifecycle(declared=True, shipped=True),
                authorities=[
                    _authority(relative_path, symbol, "surface_entrypoint")
                ],
                evidence=[_evidence(root, path, kind="entrypoint_presence", symbol=symbol)],
                confidence="declared" if entrypoint_present else "unknown",
                metadata={"entrypoint_present": entrypoint_present},
            )
        )
    return rows, missing


def _attach_and_validate_authority_evidence(
    root: Path,
    capabilities: list[dict[str, Any]],
) -> None:
    """Hash every authority source and reject stale/nonexistent symbols."""

    errors: list[str] = []
    for row in capabilities:
        evidence_paths = {item["path"] for item in row["evidence"]}
        for authority in row["authorities"]:
            relative_path = authority["path"]
            symbol = authority["symbol"]
            path = root / relative_path
            if not path.is_file():
                errors.append(f"{row['id']}: authority path is missing: {relative_path}")
                continue
            if not _source_symbol_exists(path, symbol):
                errors.append(
                    f"{row['id']}: authority symbol is missing: {relative_path}::{symbol}"
                )
                continue
            if relative_path not in evidence_paths:
                row["evidence"].append(
                    _evidence(
                        root,
                        path,
                        kind="authority_source",
                        symbol=symbol,
                    )
                )
                evidence_paths.add(relative_path)
        row["evidence"].sort(
            key=lambda item: (
                item["path"],
                item.get("kind", ""),
                item.get("symbol", ""),
            )
        )
    if errors:
        raise CapabilityEvidenceError(errors)


def _reconciliation(
    identifier: str,
    *,
    relation: str,
    status: str,
    details: dict[str, Any],
) -> dict[str, Any]:
    return {
        "details": details,
        "id": identifier,
        "relation": relation,
        "runtime_gate": False,
        "status": status,
    }


def _summary(
    capabilities: list[dict[str, Any]],
    reconciliations: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "capability_count": len(capabilities),
        "category_counts": dict(
            sorted(Counter(row["category"] for row in capabilities).items())
        ),
        "confidence_counts": dict(
            sorted(Counter(row["confidence"] for row in capabilities).items())
        ),
        "evidence_file_count": len(
            {
                evidence["path"]
                for row in capabilities
                for evidence in row["evidence"]
            }
        ),
        "reconciliation_counts": dict(
            sorted(Counter(item["status"] for item in reconciliations).items())
        ),
    }


def build_manifest(root: Path = ROOT) -> dict[str, Any]:
    """Build repository-only capability evidence without runtime imports."""

    root = root.resolve()
    capabilities: list[dict[str, Any]] = []

    model_rows, model_state = _model_provider_capabilities(root)
    memory_rows, memory_names = _memory_capabilities(root)
    skill_rows, skill_paths = _skill_capabilities(root)
    plugin_rows = _general_plugin_capabilities(root)
    mcp_rows, mcp_names = _mcp_capabilities(root)
    platform_rows, platform_plugin_names = _platform_capabilities(root)
    channel_rows = _channel_capabilities(root)
    command_rows, command_names, command_alias_pairs = _command_capabilities(root)
    tool_rows, tool_names, _tool_map = _tool_capabilities(root)
    toolset_rows, toolsets = _toolset_capabilities(root)
    automation_rows = _automation_capabilities(root)
    cron_provider_rows = _cron_provider_capabilities(root)
    goal_rows = _goal_capabilities(root)
    terminal_rows, terminal_factory, terminal_requirements = _terminal_capabilities(root)
    surface_rows, missing_surfaces = _surface_capabilities(root)

    for group in (
        model_rows,
        memory_rows,
        skill_rows,
        plugin_rows,
        mcp_rows,
        platform_rows,
        channel_rows,
        command_rows,
        tool_rows,
        toolset_rows,
        automation_rows,
        cron_provider_rows,
        goal_rows,
        terminal_rows,
        surface_rows,
    ):
        capabilities.extend(group)
    _attach_and_validate_authority_evidence(root, capabilities)
    capabilities.sort(key=lambda row: row["id"])

    canonical = set(model_state["canonical"])
    registered = set(model_state["registered_profiles"])
    profile_exceptions = {
        "lmstudio",
        "moa",
        "openai-api",
        "tencent-tokenhub",
        "xai-oauth",
    }
    uncovered_providers = sorted(canonical - registered - profile_exceptions)

    command_name_duplicates = sorted(
        name for name, count in Counter(command_names).items() if count > 1
    )
    command_alias_targets: dict[str, set[str]] = {}
    for alias, target in command_alias_pairs:
        command_alias_targets.setdefault(alias, set()).add(target)
    command_alias_collisions = {
        alias: sorted(targets)
        for alias, targets in command_alias_targets.items()
        if len(targets) > 1 or alias in set(command_names)
    }

    static_toolset_tools = {
        tool
        for definition in toolsets.values()
        for tool in definition.get("tools", [])
    }
    plugin_declared_tools = {
        tool
        for row in plugin_rows
        for tool in row.get("metadata", {}).get("provides_tools", [])
    }
    unresolved_toolset_tools = sorted(
        static_toolset_tools - tool_names - plugin_declared_tools
    )

    support_skill_paths = sorted(
        path
        for path in skill_paths
        if any(part in _SKILL_SUPPORT_DIRS for part in PurePosixPath(path).parts)
    )

    reconciliations = [
        _reconciliation(
            "canonical-providers-covered-by-profile-or-explicit-exception",
            relation="coverage",
            status="pass" if not uncovered_providers else "fail",
            details={
                "explicit_exceptions": sorted(profile_exceptions & canonical),
                "uncovered": uncovered_providers,
            },
        ),
        _reconciliation(
            "custom-local-ollama-is-distinct-from-ollama-cloud",
            relation="identity_separation",
            status=(
                "pass"
                if model_state["aliases"].get("ollama") == "custom"
                and any(row["id"] == "model_provider:bundled:custom" for row in capabilities)
                and any(row["key"] == "ollama-cloud" for row in model_rows)
                else "fail"
            ),
            details={
                "alias_authority": "fabric_cli/providers.py::ALIASES",
                "cloud_identity": "ollama-cloud",
                "local_alias": "ollama",
                "observed_local_alias_target": model_state["aliases"].get("ollama"),
            },
        ),
        _reconciliation(
            "central-command-registry-has-unique-names-and-aliases",
            relation="uniqueness",
            status=(
                "pass"
                if not command_name_duplicates and not command_alias_collisions
                else "fail"
            ),
            details={
                "alias_collisions": command_alias_collisions,
                "duplicate_names": command_name_duplicates,
                "registered_command_count": len(command_names),
            },
        ),
        _reconciliation(
            "memory-manifests-have-evidence-rows",
            relation="equality",
            status=(
                "pass"
                if memory_names
                == {
                    row["key"]
                    for row in memory_rows
                    if row["origin"] == "bundled"
                }
                else "fail"
            ),
            details={
                "assurance": "static_collector_completeness",
                "uncovered": sorted(memory_names - {row["key"] for row in memory_rows}),
            },
        ),
        _reconciliation(
            "skill-support-packages-are-not-standalone-skills",
            relation="exclusion",
            status="pass" if not support_skill_paths else "fail",
            details={
                "assurance": "static_collector_exclusion",
                "incorrectly_included": support_skill_paths,
            },
        ),
        _reconciliation(
            "mcp-catalog-and-live-registrations-remain-separate",
            relation="population_separation",
            status=(
                "unknown"
                if mcp_names
                == {
                    row["key"]
                    for row in mcp_rows
                    if row["origin"] == "optional_catalog"
                }
                and any(row["origin"] == "dynamic" for row in mcp_rows)
                else "fail"
            ),
            details={
                "assurance": "catalog_completeness_only",
                "catalog_entries": sorted(mcp_names),
                "live_population": "unknown",
            },
        ),
        _reconciliation(
            "bundled-platform-manifests-have-platform-rows",
            relation="coverage",
            status=(
                "pass"
                if platform_plugin_names
                <= {row["key"] for row in platform_rows}
                else "fail"
            ),
            details={
                "assurance": "static_collector_completeness",
                "uncovered": sorted(
                    platform_plugin_names - {row["key"] for row in platform_rows}
                )
            },
        ),
        _reconciliation(
            "static-toolset-tools-resolve-or-remain-explicitly-dynamic",
            relation="coverage",
            status="pass" if not unresolved_toolset_tools else "unknown",
            details={
                "runtime_dynamic_or_unresolved": unresolved_toolset_tools,
                "static_tool_count": len(static_toolset_tools),
            },
        ),
        _reconciliation(
            "terminal-factory-and-requirement-checker-use-same-backends",
            relation="equality",
            status="pass" if terminal_factory == terminal_requirements else "fail",
            details={
                "factory_only": sorted(terminal_factory - terminal_requirements),
                "requirements_only": sorted(terminal_requirements - terminal_factory),
            },
        ),
        _reconciliation(
            "declared-product-surface-entrypoints-exist",
            relation="presence",
            status="pass" if not missing_surfaces else "fail",
            details={"missing": missing_surfaces},
        ),
        _reconciliation(
            "persistent-goal-contract-symbols-exist",
            relation="presence",
            status="pass" if goal_rows[0]["confidence"] == "exact" else "fail",
            details={"active_goal_state": "intentionally_not_read"},
        ),
    ]
    reconciliations.sort(key=lambda item: item["id"])

    manifest = {
        "capabilities": capabilities,
        "collection_contract": COLLECTION_CONTRACT,
        "evidence_only": True,
        "purpose": "repository_capability_reconciliation",
        "reconciliations": reconciliations,
        "record_date": RECORD_DATE,
        "record_id": RECORD_ID,
        "runtime_authority": False,
        "schema_version": SCHEMA_VERSION,
        "scope": {
            "included": "repository_shipped_sources_and_catalogs",
            "mode": "repository_only",
            "user_state": "excluded",
        },
    }
    manifest["summary"] = _summary(capabilities, reconciliations)
    return manifest


def _walk_mapping_keys(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from _walk_mapping_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_mapping_keys(child)


def validate_manifest(data: Any) -> dict[str, Any]:
    """Validate internal relationships without treating diagnostics as gates."""

    if not isinstance(data, dict):
        raise CapabilityEvidenceError(["manifest root must be a JSON object"])
    errors: list[str] = []
    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    if data.get("record_id") != RECORD_ID:
        errors.append(f"record_id must be {RECORD_ID!r}")
    if data.get("record_date") != RECORD_DATE:
        errors.append(f"record_date must be {RECORD_DATE!r}")
    if data.get("purpose") != "repository_capability_reconciliation":
        errors.append("purpose must be 'repository_capability_reconciliation'")
    if data.get("evidence_only") is not True:
        errors.append("evidence_only must be true")
    if data.get("runtime_authority") is not False:
        errors.append("runtime_authority must be false")
    if data.get("collection_contract") != COLLECTION_CONTRACT:
        errors.append("collection_contract must equal the static collector contract")
    scope = data.get("scope")
    if not isinstance(scope, dict) or scope.get("mode") != "repository_only":
        errors.append("scope.mode must be 'repository_only'")
    if isinstance(scope, dict) and scope.get("user_state") != "excluded":
        errors.append("scope.user_state must be 'excluded'")

    capabilities = data.get("capabilities")
    if not isinstance(capabilities, list):
        errors.append("capabilities must be an array")
        capabilities = []
    ids: list[str] = []
    categories: set[str] = set()
    for index, row in enumerate(capabilities):
        location = f"capabilities[{index}]"
        if not isinstance(row, dict):
            errors.append(f"{location} must be an object")
            continue
        identifier = row.get("id")
        if not isinstance(identifier, str) or not identifier:
            errors.append(f"{location}.id must be a non-empty string")
        else:
            ids.append(identifier)
        category = row.get("category")
        if not isinstance(category, str) or category not in EXPECTED_CATEGORIES:
            errors.append(f"{location}.category is unknown")
        else:
            categories.add(category)
        for field in ("key", "label", "origin"):
            if not isinstance(row.get(field), str) or not row[field]:
                errors.append(f"{location}.{field} must be a non-empty string")
        if not isinstance(row.get("metadata"), dict):
            errors.append(f"{location}.metadata must be an object")
        if row.get("confidence") not in CONFIDENCE_VALUES:
            errors.append(f"{location}.confidence is invalid")
        lifecycle = row.get("lifecycle")
        if not isinstance(lifecycle, dict) or set(lifecycle) != set(LIFECYCLE_AXES):
            errors.append(f"{location}.lifecycle must contain the exact lifecycle axes")
        elif any(value not in {True, False, None} for value in lifecycle.values()):
            errors.append(f"{location}.lifecycle values must be boolean or null")
        authorities = row.get("authorities")
        if not isinstance(authorities, list) or not authorities:
            errors.append(f"{location}.authorities must be a non-empty array")
            authorities = []
        else:
            for authority_index, authority in enumerate(authorities):
                authority_location = f"{location}.authorities[{authority_index}]"
                if not isinstance(authority, dict):
                    errors.append(f"{authority_location} must be an object")
                    continue
                if set(authority) != {"path", "role", "symbol"}:
                    errors.append(
                        f"{authority_location} must contain path, role, and symbol"
                    )
                if not _safe_relative_path(authority.get("path")):
                    errors.append(f"{authority_location}.path must be safe and relative")
                for field in ("role", "symbol"):
                    if not isinstance(authority.get(field), str) or not authority[field]:
                        errors.append(
                            f"{authority_location}.{field} must be a non-empty string"
                        )
        evidence = row.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            errors.append(f"{location}.evidence must be a non-empty array")
            evidence = []
        evidence_paths: set[str] = set()
        for evidence_index, item in enumerate(evidence):
            evidence_location = f"{location}.evidence[{evidence_index}]"
            if not isinstance(item, dict):
                errors.append(f"{evidence_location} must be an object")
                continue
            if not _safe_relative_path(item.get("path")):
                errors.append(f"{evidence_location}.path must be safe and relative")
            else:
                evidence_paths.add(item["path"])
            if not isinstance(item.get("kind"), str) or not item["kind"]:
                errors.append(f"{evidence_location}.kind must be a non-empty string")
            if not isinstance(item.get("sha256"), str) or not _SHA256_RE.fullmatch(
                item["sha256"]
            ):
                errors.append(f"{evidence_location}.sha256 must be a 64-character SHA-256")
        for authority_index, authority in enumerate(authorities):
            if not isinstance(authority, dict):
                continue
            authority_path = authority.get("path")
            if isinstance(authority_path, str) and authority_path not in evidence_paths:
                errors.append(
                    f"{location}.authorities[{authority_index}] path must be hashed "
                    "in the row evidence"
                )

    if ids != sorted(ids):
        errors.append("capabilities must be sorted by id")
    if len(ids) != len(set(ids)):
        errors.append("capability ids must be unique")
    missing_categories = EXPECTED_CATEGORIES - categories
    if missing_categories:
        errors.append(f"missing required categories: {sorted(missing_categories)}")

    reconciliations = data.get("reconciliations")
    if not isinstance(reconciliations, list):
        errors.append("reconciliations must be an array")
        reconciliations = []
    reconciliation_ids: list[str] = []
    for index, item in enumerate(reconciliations):
        location = f"reconciliations[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{location} must be an object")
            continue
        identifier = item.get("id")
        if isinstance(identifier, str):
            reconciliation_ids.append(identifier)
        else:
            errors.append(f"{location}.id must be a string")
        if item.get("status") not in RECONCILIATION_STATUSES:
            errors.append(f"{location}.status is invalid")
        if item.get("runtime_gate") is not False:
            errors.append(f"{location}.runtime_gate must be false")
    if reconciliation_ids != sorted(reconciliation_ids):
        errors.append("reconciliations must be sorted by id")
    if len(reconciliation_ids) != len(set(reconciliation_ids)):
        errors.append("reconciliation ids must be unique")

    expected_summary = _summary(capabilities, reconciliations)
    if data.get("summary") != expected_summary:
        errors.append("summary must equal the capability/reconciliation relationships")

    sensitive_keys = sorted(
        key for key in _walk_mapping_keys(data) if _SENSITIVE_KEY_RE.fullmatch(key)
    )
    if sensitive_keys:
        errors.append(f"manifest contains forbidden sensitive key names: {sensitive_keys}")
    if errors:
        raise CapabilityEvidenceError(errors)
    return data


def load_and_validate(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CapabilityEvidenceError([f"failed to load {path}: {exc}"]) from exc
    validate_manifest(data)
    if raw != canonical_json(data):
        raise CapabilityEvidenceError([f"{path} is not canonical sorted JSON"])
    return data


def _resolve_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        nargs="?",
        const=str(DEFAULT_OUTPUT),
        help="Validate and compare an existing manifest with a fresh static build.",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="Output path for build mode.",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print canonical JSON instead of writing a file.",
    )
    args = parser.parse_args(argv)

    try:
        built = validate_manifest(build_manifest(ROOT))
        rendered = canonical_json(built)
        if args.check:
            check_path = _resolve_path(args.check)
            existing = load_and_validate(check_path)
            if canonical_json(existing) != rendered:
                raise CapabilityEvidenceError(
                    [f"{check_path} does not match current repository evidence"]
                )
            print(f"Capability evidence OK: {check_path}")
            return 0
        if args.stdout:
            sys.stdout.write(rendered)
            return 0
        output = _resolve_path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        print(f"Wrote capability evidence: {output}")
        return 0
    except CapabilityEvidenceError as exc:
        print(f"Capability evidence failed:\n{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
