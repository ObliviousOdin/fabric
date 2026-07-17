#!/usr/bin/env python3
"""Generate and enforce Fabric's deterministic documentation contracts.

This script is intentionally repository-only: it parses committed source and
manifests, never imports Fabric runtime modules, reads a user profile, calls a
model, or opens the network.  It has four public commands:

``generate``
    Refresh the committed runtime-surface JSON and reference page.
``check``
    Fail when either generated artifact differs from canonical source.
``audit``
    Validate documented Fabric/Hermes tokens and first-party skill metadata.
``impact``
    Require narrative documentation (or an explicit, scoped PR declaration)
    when a mapped public contract changes.
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Iterable, Sequence

import yaml


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_PATH = ROOT / "docs" / "documentation-contracts.json"
RUNTIME_JSON_PATH = ROOT / "website" / "static" / "api" / "runtime-surfaces.json"
RUNTIME_DOC_PATH = ROOT / "website" / "docs" / "reference" / "runtime-surfaces.mdx"

_TOKEN_RE = re.compile(r"(?<![A-Z0-9])(?:FABRIC|FABRIC)_[A-Z0-9_]+")
_DOCS_IMPACT_RE = re.compile(
    r"(?im)^\s*Docs-impact:\s*none\s*\[([^\]]+)\]\s*(?:—|--|-|:)\s*(.+?)\s*$"
)
_BINARY_SUFFIXES = frozenset(
    {
        ".bin",
        ".gif",
        ".gz",
        ".ico",
        ".jpeg",
        ".jpg",
        ".pdf",
        ".png",
        ".pyc",
        ".woff",
        ".woff2",
        ".zip",
    }
)
_SOURCE_EXCLUDED_DIRS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        ".worktrees",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "tests",
        "venv",
    }
)


class DocsSyncError(ValueError):
    """Raised when a generated or audited documentation contract is invalid."""

    def __init__(self, errors: Iterable[str]):
        self.errors = tuple(errors)
        super().__init__("\n".join(f"- {error}" for error in self.errors))


def canonical_json(value: Any) -> str:
    """Return the stable JSON representation committed by this script."""

    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def load_contracts(root: Path = ROOT) -> dict[str, Any]:
    """Load and minimally validate the documentation contract map."""

    path = root / CONTRACTS_PATH.relative_to(ROOT)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DocsSyncError([f"cannot load {path}: {exc}"]) from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise DocsSyncError([f"{path}: schema_version must be 1"])
    contracts = value.get("impact_contracts")
    if not isinstance(contracts, list) or not contracts:
        raise DocsSyncError([f"{path}: impact_contracts must be a non-empty array"])
    seen: set[str] = set()
    errors: list[str] = []
    for contract in contracts:
        if not isinstance(contract, dict):
            errors.append("impact contract entries must be objects")
            continue
        contract_id = contract.get("id")
        if not isinstance(contract_id, str) or not re.fullmatch(
            r"[a-z0-9]+(?:-[a-z0-9]+)*", contract_id
        ):
            errors.append(f"invalid impact contract id: {contract_id!r}")
        elif contract_id in seen:
            errors.append(f"duplicate impact contract id: {contract_id}")
        else:
            seen.add(contract_id)
        for key in ("code_paths", "docs_paths"):
            paths = contract.get(key)
            if not isinstance(paths, list) or not paths or not all(
                isinstance(item, str) and item for item in paths
            ):
                errors.append(f"{contract_id or '<unknown>'}: {key} must list paths")
    if errors:
        raise DocsSyncError(errors)
    return value


def _load_capability_evidence_module() -> Any:
    """Load the existing static collector without importing Fabric runtime."""

    path = Path(__file__).with_name("build_capability_evidence.py")
    spec = importlib.util.spec_from_file_location("fabric_capability_evidence", path)
    if spec is None or spec.loader is None:
        raise DocsSyncError([f"cannot load static capability collector: {path}"])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _matching_delimiter(source: str, start: int, opening: str, closing: str) -> int:
    """Return a matching delimiter while ignoring strings and comments."""

    depth = 0
    quote: str | None = None
    escaped = False
    line_comment = False
    block_comment = False
    index = start
    while index < len(source):
        char = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if line_comment:
            if char == "\n":
                line_comment = False
            index += 1
            continue
        if block_comment:
            if char == "*" and following == "/":
                block_comment = False
                index += 2
                continue
            index += 1
            continue
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue
        if char in {'"', "'", "`"}:
            quote = char
        elif char == "/" and following == "/":
            line_comment = True
            index += 2
            continue
        elif char == "/" and following == "*":
            block_comment = True
            index += 2
            continue
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return index
        index += 1
    raise DocsSyncError([f"unclosed {opening!r} delimiter in dashboard route catalog"])


def _top_level_objects(array_source: str) -> list[str]:
    objects: list[str] = []
    index = 1
    while index < len(array_source) - 1:
        if array_source[index] != "{":
            index += 1
            continue
        end = _matching_delimiter(array_source, index, "{", "}")
        objects.append(array_source[index : end + 1])
        index = end + 1
    return objects


def _quoted_field(source: str, name: str) -> str | None:
    match = re.search(rf"\b{re.escape(name)}:\s*([\"'])(.*?)\1", source, re.S)
    return match.group(2) if match else None


def _quoted_array_field(source: str, name: str) -> list[str]:
    match = re.search(rf"\b{re.escape(name)}:\s*\[(.*?)\]", source, re.S)
    if not match:
        return []
    return [item[1] for item in re.findall(r"([\"'])(.*?)\1", match.group(1), re.S)]


def collect_dashboard_routes(root: Path = ROOT) -> dict[str, Any]:
    """Parse the TypeScript APP_ROUTES data catalog without executing Node."""

    path = root / "web" / "src" / "app" / "routes.tsx"
    source = path.read_text(encoding="utf-8")
    assignment = re.search(r"export\s+const\s+APP_ROUTES\b[^=]*=", source)
    if not assignment:
        raise DocsSyncError([f"{path}: APP_ROUTES assignment not found"])
    start = source.find("[", assignment.end())
    if start < 0:
        raise DocsSyncError([f"{path}: APP_ROUTES array not found"])
    end = _matching_delimiter(source, start, "[", "]")
    array_source = source[start : end + 1]
    routes: list[dict[str, Any]] = []
    errors: list[str] = []
    for block in _top_level_objects(array_source):
        route_id = _quoted_field(block, "id")
        route_path = _quoted_field(block, "path")
        surface = _quoted_field(block, "surface")
        layout = _quoted_field(block, "layout")
        if not all((route_id, route_path, surface, layout)):
            errors.append(
                "APP_ROUTES entry is missing a literal id, path, surface, or layout"
            )
            continue
        nav_block_match = re.search(r"\bnav:\s*\{(.*?)\}\s*,?", block, re.S)
        nav_block = nav_block_match.group(1) if nav_block_match else ""
        routes.append(
            {
                "aliases": _quoted_array_field(block, "aliases"),
                "id": route_id,
                "layout": layout,
                "nav_label": _quoted_field(nav_block, "label"),
                "path": route_path,
                "persistent": bool(re.search(r"\bpersistent:\s*true\b", block)),
                "surface": surface,
                "title": _quoted_field(block, "title"),
            }
        )
    ids = [route["id"] for route in routes]
    paths = [route["path"] for route in routes]
    duplicate_ids = sorted({item for item in ids if ids.count(item) > 1})
    duplicate_paths = sorted({item for item in paths if paths.count(item) > 1})
    if duplicate_ids:
        errors.append(f"APP_ROUTES has duplicate ids: {', '.join(duplicate_ids)}")
    if duplicate_paths:
        errors.append(f"APP_ROUTES has duplicate paths: {', '.join(duplicate_paths)}")
    default_match = re.search(
        r"export\s+const\s+DEFAULT_ROUTE\s*=\s*([\"'])(.*?)\1", source
    )
    if not default_match:
        errors.append("DEFAULT_ROUTE literal was not found")
    if errors:
        raise DocsSyncError(errors)
    return {"default_route": default_match.group(2), "routes": routes}


def collect_dashboard_manifests(root: Path = ROOT) -> list[dict[str, Any]]:
    """Collect the committed dashboard extension manifests as canonical JSON."""

    manifests: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in sorted((root / "plugins").glob("**/dashboard/manifest.json")):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            errors.append(f"{path}: invalid dashboard manifest: {exc}")
            continue
        if not isinstance(manifest, dict):
            errors.append(f"{path}: dashboard manifest root must be an object")
            continue
        missing = [
            key
            for key in ("name", "label", "description", "version", "tab", "entry")
            if key not in manifest
        ]
        if missing:
            errors.append(f"{path}: missing dashboard fields: {', '.join(missing)}")
            continue
        relative = path.relative_to(root).as_posix()
        manifests.append({"manifest": manifest, "source": relative})
    names = [str(item["manifest"]["name"]) for item in manifests]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        errors.append(f"duplicate dashboard manifest names: {', '.join(duplicates)}")
    if errors:
        raise DocsSyncError(errors)
    return sorted(manifests, key=lambda item: (str(item["manifest"]["name"]), item["source"]))


def _literal_value(node: ast.AST | None) -> Any:
    if node is None:
        return None
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        return None


def _builtin_cli_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        targets: list[ast.expr] = []
        value: ast.AST | None = None
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        if not any(
            isinstance(target, ast.Name) and target.id == "_BUILTIN_SUBCOMMANDS"
            for target in targets
        ):
            continue
        if not (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "frozenset"
            and value.args
        ):
            break
        names = _literal_value(value.args[0])
        if isinstance(names, (set, frozenset, list, tuple)) and all(
            isinstance(name, str) for name in names
        ):
            return set(names)
        break
    raise DocsSyncError([f"{path}: static _BUILTIN_SUBCOMMANDS was not found"])


def _top_level_parser_calls(path: Path) -> list[dict[str, Any]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    rows: list[dict[str, Any]] = []
    top_level_receivers = {"parent_subparsers", "subparsers"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_parser"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in top_level_receivers
            and node.args
        ):
            continue
        name = _literal_value(node.args[0])
        if not isinstance(name, str):
            continue
        keywords = {item.arg: item.value for item in node.keywords if item.arg}
        help_text = _literal_value(keywords.get("help"))
        visibility = "public" if isinstance(help_text, str) else "compatibility"
        aliases = _literal_value(keywords.get("aliases"))
        rows.append(
            {
                "aliases": [
                    alias
                    for alias in (aliases if isinstance(aliases, (list, tuple)) else [])
                    if isinstance(alias, str)
                ],
                "help": help_text if isinstance(help_text, str) else "",
                "name": name,
                "source": path,
                "visibility": visibility,
            }
        )
    return rows


def collect_top_level_cli_commands(root: Path = ROOT) -> list[dict[str, Any]]:
    """Collect top-level ``fabric <command>`` registrations without imports."""

    main_path = root / "fabric_cli" / "main.py"
    builtin_names = _builtin_cli_names(main_path)
    source_paths = [
        root / "fabric_cli" / "_parser.py",
        main_path,
        root / "fabric_cli" / "kanban.py",
        root / "fabric_cli" / "portal_cli.py",
        root / "fabric_cli" / "projects_cmd.py",
        root / "fabric_cli" / "send_cmd.py",
        root / "agent" / "lsp" / "cli.py",
        *sorted((root / "fabric_cli" / "subcommands").glob("*.py")),
    ]
    canonical: dict[str, dict[str, Any]] = {}
    aliases: dict[str, str] = {}
    errors: list[str] = []
    for path in source_paths:
        if not path.is_file():
            continue
        for row in _top_level_parser_calls(path):
            name = row["name"]
            relative = path.relative_to(root).as_posix()
            normalized = {
                "alias_of": None,
                "aliases": row["aliases"],
                "help": row["help"],
                "name": name,
                "source": relative,
                "visibility": row["visibility"],
            }
            if name in canonical and canonical[name] != normalized:
                errors.append(f"top-level CLI command {name!r} is registered more than once")
                continue
            canonical[name] = normalized
            for alias in row["aliases"]:
                previous = aliases.get(alias)
                if previous and previous != name:
                    errors.append(
                        f"top-level CLI alias {alias!r} targets both {previous!r} and {name!r}"
                    )
                aliases[alias] = name
    registered_names = set(canonical) | set(aliases)
    static_missing = sorted(registered_names - builtin_names)
    # ``help`` is an early parser/help sentinel rather than an add_parser call.
    parser_missing = sorted(builtin_names - registered_names - {"help"})
    if static_missing:
        errors.append(
            "top-level CLI registrations missing from _BUILTIN_SUBCOMMANDS: "
            + ", ".join(static_missing)
        )
    if parser_missing:
        errors.append(
            "_BUILTIN_SUBCOMMANDS entries have no statically discoverable parser: "
            + ", ".join(parser_missing)
        )
    if errors:
        raise DocsSyncError(errors)
    rows = list(canonical.values())
    for alias, target in aliases.items():
        owner = canonical[target]
        rows.append(
            {
                "alias_of": target,
                "aliases": [],
                "help": owner["help"],
                "name": alias,
                "source": owner["source"],
                "visibility": owner["visibility"],
            }
        )
    return sorted(rows, key=lambda row: row["name"])


def _public_capability_row(row: dict[str, Any]) -> dict[str, Any]:
    metadata_keys = {
        "command": (
            "aliases",
            "args_hint",
            "cli_only",
            "command_category",
            "gateway_config_gate",
            "gateway_only",
            "subcommands",
        ),
        "model_provider": (
            "auth_type",
            "canonical_surface_member",
            "description",
            "profile_aliases",
        ),
        "platform": ("builtin_enum", "deferred_plugin", "manifest_name"),
        "product_surface": ("entrypoint_present",),
        "toolset": ("includes", "tools"),
    }
    category = str(row["category"])
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    return {
        "authorities": [
            {"path": item["path"], "symbol": item["symbol"]}
            for item in row.get("authorities", [])
            if isinstance(item, dict) and "path" in item and "symbol" in item
        ],
        "confidence": row.get("confidence"),
        "key": row.get("key"),
        "label": row.get("label"),
        "metadata": {
            key: metadata[key]
            for key in metadata_keys.get(category, ())
            if key in metadata
        },
        "origin": row.get("origin"),
    }


def build_runtime_catalog(root: Path = ROOT) -> dict[str, Any]:
    """Build the machine-readable catalog from static repository authorities."""

    evidence_module = _load_capability_evidence_module()
    evidence = evidence_module.build_manifest(root)
    categories = (
        "command",
        "model_provider",
        "platform",
        "product_surface",
        "toolset",
    )
    capabilities: dict[str, list[dict[str, Any]]] = {}
    for category in categories:
        rows = [
            _public_capability_row(row)
            for row in evidence["capabilities"]
            if row.get("category") == category
        ]
        capabilities[category] = sorted(rows, key=lambda row: str(row["key"]))
    capabilities["cli_command"] = collect_top_level_cli_commands(root)
    dashboard = collect_dashboard_routes(root)
    dashboard["plugin_manifests"] = collect_dashboard_manifests(root)
    summary = {category: len(rows) for category, rows in capabilities.items()}
    summary["dashboard_route"] = len(dashboard["routes"])
    summary["dashboard_plugin_manifest"] = len(dashboard["plugin_manifests"])
    return {
        "capabilities": capabilities,
        "dashboard": dashboard,
        "generated_from": [
            "fabric_cli/commands.py::COMMAND_REGISTRY",
            "fabric_cli/main.py::_BUILTIN_SUBCOMMANDS and static argparse registrations",
            "fabric_cli/models.py and bundled model-provider manifests",
            "gateway/config.py::Platform and bundled platform manifests",
            "toolsets.py::TOOLSETS",
            "scripts/build_capability_evidence.py",
            "web/src/app/routes.tsx::APP_ROUTES",
            "plugins/**/dashboard/manifest.json",
        ],
        "generation_mode": "repository_only_no_runtime_imports",
        "schema_version": 1,
        "summary": dict(sorted(summary.items())),
    }


def _cell(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (list, tuple)):
        value = ", ".join(str(item) for item in value) or "—"
    value = re.sub(r"\s+", " ", str(value)).strip()
    return (
        value.replace("{", "&#123;")
        .replace("}", "&#125;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("|", "\\|")
        or "—"
    )


def _table(headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> list[str]:
    result = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    result.extend("| " + " | ".join(_cell(value) for value in row) + " |" for row in rows)
    return result


def render_runtime_reference(catalog: dict[str, Any]) -> str:
    """Render a concise generated MDX reference from the machine catalog."""

    capabilities = catalog["capabilities"]
    dashboard = catalog["dashboard"]
    lines = [
        "---",
        "title: Runtime Surface Catalog",
        "description: Generated inventory of Fabric commands, product surfaces, providers, platforms, toolsets, dashboard routes, and dashboard plugins.",
        "---",
        "",
        "<!-- GENERATED by scripts/docs_sync.py. Edit canonical source, then regenerate. -->",
        "",
        "This page is generated from repository-owned registries and manifests. It is an",
        "inventory of **shipped declarations**, not a claim that every optional service is",
        "installed, configured, or active in a particular profile. The same data is published",
        "as [`runtime-surfaces.json`](https://obliviousodin.github.io/fabric/api/runtime-surfaces.json).",
        "",
        "## Product surfaces",
        "",
    ]
    lines.extend(
        _table(
            ("Surface", "Description", "Authority"),
            (
                (
                    row["key"],
                    row["label"],
                    ", ".join(
                        f"`{item['path']}::{item['symbol']}`"
                        for item in row["authorities"]
                    ),
                )
                for row in capabilities["product_surface"]
                if row["origin"] != "dynamic"
            ),
        )
    )
    lines.extend(["", "## Dashboard routes", ""])
    lines.extend(
        _table(
            ("Route", "Path", "Surface", "Aliases", "Layout", "Persistent"),
            (
                (
                    route["nav_label"] or route["title"] or route["id"],
                    f"`{route['path']}`",
                    route["surface"],
                    [f"`{alias}`" for alias in route["aliases"]],
                    route["layout"],
                    route["persistent"],
                )
                for route in dashboard["routes"]
            ),
        )
    )
    lines.extend(
        [
            "",
            f"Default route: `{dashboard['default_route']}`.",
            "",
            "## Dashboard plugin manifests",
            "",
        ]
    )
    lines.extend(
        _table(
            ("Plugin", "Tab path", "Override", "Layout", "Slots", "Manifest"),
            (
                (
                    item["manifest"]["label"],
                    f"`{item['manifest']['tab']['path']}`",
                    (
                        f"`{item['manifest']['tab']['override']}`"
                        if item["manifest"]["tab"].get("override")
                        else None
                    ),
                    item["manifest"]["tab"].get("layout", "page"),
                    item["manifest"].get("slots", []),
                    f"`{item['source']}`",
                )
                for item in dashboard["plugin_manifests"]
            ),
        )
    )
    lines.extend(["", "## Top-level CLI commands", ""])
    lines.extend(
        _table(
            ("Command", "Aliases", "Summary", "Registration"),
            (
                (
                    f"`fabric {row['name']}`",
                    [f"`fabric {alias}`" for alias in row["aliases"]],
                    row["help"],
                    f"`{row['source']}`",
                )
                for row in capabilities["cli_command"]
                if row["alias_of"] is None and row["visibility"] == "public"
            ),
        )
    )
    lines.extend(
        [
            "",
            "Aliases are folded into their canonical command row. Hidden compatibility parsers",
            "and plugin-registered commands are intentionally not presented as new public commands.",
            "",
            "## Slash commands",
            "",
        ]
    )

    def command_scope(row: dict[str, Any]) -> str:
        metadata = row["metadata"]
        if metadata.get("cli_only"):
            gate = metadata.get("gateway_config_gate")
            return f"CLI; gateway when `{gate}` is enabled" if gate else "CLI"
        if metadata.get("gateway_only"):
            return "Messaging gateway"
        return "CLI, TUI, and messaging gateway"

    lines.extend(
        _table(
            ("Command", "Scope", "Category", "Arguments", "Aliases", "Summary"),
            (
                (
                    f"`/{row['key']}`",
                    command_scope(row),
                    row["metadata"].get("command_category"),
                    row["metadata"].get("args_hint"),
                    [f"`/{alias}`" for alias in row["metadata"].get("aliases", [])],
                    row["label"],
                )
                for row in capabilities["command"]
                if row["origin"] != "dynamic"
            ),
        )
    )
    lines.extend(
        [
            "",
            "Profile skill commands and user quick commands are discovered at runtime and are",
            "therefore intentionally not enumerated here. Desktop availability is curated",
            "separately and can be narrower than this registry scope.",
            "",
            "## Model providers",
            "",
        ]
    )
    lines.extend(
        _table(
            ("Provider", "Display name", "Auth", "Aliases"),
            (
                (
                    f"`{row['key']}`",
                    row["label"],
                    row["metadata"].get("auth_type"),
                    row["metadata"].get("profile_aliases", []),
                )
                for row in capabilities["model_provider"]
                if row["origin"] != "dynamic"
            ),
        )
    )
    lines.extend(["", "## Messaging platforms", ""])
    lines.extend(
        _table(
            ("Platform", "Description", "Implementation"),
            (
                (
                    f"`{row['key']}`",
                    row["label"],
                    "deferred plugin"
                    if row["metadata"].get("deferred_plugin")
                    else "built in",
                )
                for row in capabilities["platform"]
                if row["origin"] != "dynamic"
            ),
        )
    )
    lines.extend(
        [
            "",
            "## Toolsets",
            "",
            "IDs beginning with `fabric-` are live pre-Fabric compatibility identifiers.",
            "Keep them for existing configuration, but use canonical `fabric-` IDs for new",
            "toolsets and integrations.",
            "",
        ]
    )
    lines.extend(
        _table(
            ("Toolset", "Status", "Description", "Tools", "Includes"),
            (
                (
                    f"`{row['key']}`",
                    (
                        "pre-Fabric compatibility ID"
                        if str(row["key"]).startswith("fabric-")
                        else "canonical"
                    ),
                    row["label"],
                    len(row["metadata"].get("tools", [])),
                    row["metadata"].get("includes", []),
                )
                for row in capabilities["toolset"]
                if row["origin"] != "dynamic"
            ),
        )
    )
    lines.extend(
        [
            "",
            "Runtime plugin and MCP registrations may add providers, platforms, commands, or",
            "toolsets after startup; those profile-dependent values are deliberately excluded.",
            "",
        ]
    )
    return "\n".join(lines)


def generated_outputs(root: Path = ROOT) -> dict[Path, str]:
    catalog = build_runtime_catalog(root)
    return {
        root / RUNTIME_JSON_PATH.relative_to(ROOT): canonical_json(catalog),
        root / RUNTIME_DOC_PATH.relative_to(ROOT): render_runtime_reference(catalog),
    }


def generate(root: Path = ROOT, *, check: bool = False) -> list[str]:
    """Write or compare every deterministic generated documentation artifact."""

    changed: list[str] = []
    for path, expected in generated_outputs(root).items():
        existing = path.read_text(encoding="utf-8") if path.is_file() else None
        if existing == expected:
            continue
        relative = path.relative_to(root).as_posix()
        changed.append(relative)
        if not check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(expected, encoding="utf-8")
    if check and changed:
        raise DocsSyncError(
            [
                "generated documentation is stale: " + ", ".join(changed),
                "run `python scripts/docs_sync.py generate` and commit the result",
            ]
        )
    return changed


def _path_matches(path: str, patterns: Sequence[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def authored_doc_paths(root: Path, contracts: dict[str, Any]) -> list[Path]:
    config = contracts.get("authored_docs", {})
    includes = config.get("include", ["**/*.md", "**/*.mdx"])
    excludes = config.get("exclude", [])
    result: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if _path_matches(relative, includes) and not _path_matches(relative, excludes):
            result.append(path)
    return sorted(result)


def non_doc_source_tokens(root: Path) -> set[str]:
    """Collect tokens from non-document, non-generated repository source."""

    tokens: set[str] = set()
    for path in root.rglob("*"):
        if not path.is_file() or any(
            part in _SOURCE_EXCLUDED_DIRS for part in path.relative_to(root).parts
        ):
            continue
        relative = path.relative_to(root).as_posix()
        if path.suffix.lower() in _BINARY_SUFFIXES | {".md", ".mdx"}:
            continue
        if relative.startswith("website/static/"):
            continue
        try:
            tokens.update(_TOKEN_RE.findall(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeError):
            continue
    return tokens


def audit_documented_tokens(root: Path, contracts: dict[str, Any]) -> list[str]:
    """Return authored-doc tokens that have no backing non-doc source."""

    documented: dict[str, set[str]] = {}
    for path in authored_doc_paths(root, contracts):
        relative = path.relative_to(root).as_posix()
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        for token in _TOKEN_RE.findall(content):
            documented.setdefault(token, set()).add(relative)
    source_tokens = non_doc_source_tokens(root)
    exemptions = contracts.get("documented_token_exemptions", {})
    errors: list[str] = []
    for token in sorted(documented):
        if token in source_tokens:
            continue
        reason = exemptions.get(token) if isinstance(exemptions, dict) else None
        if isinstance(reason, str) and len(reason.strip()) >= 20:
            continue
        errors.append(
            f"{token} is documented but absent from non-doc source "
            f"({', '.join(sorted(documented[token]))})"
        )
    return errors


def audit_first_party_skill_metadata(root: Path) -> list[str]:
    """Reject newly authored legacy ``metadata.fabric`` in shipped skills."""

    errors: list[str] = []
    for relative_root in ("skills", "optional-skills", "plugins"):
        directory = root / relative_root
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("**/SKILL.md")):
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            frontmatter = ""
            if content.startswith("---\n"):
                marker = content.find("\n---", 4)
                if marker >= 0:
                    frontmatter = content[4:marker]
            try:
                parsed = yaml.safe_load(frontmatter) or {}
            except yaml.YAMLError as exc:
                errors.append(
                    f"{path.relative_to(root).as_posix()}: invalid YAML frontmatter: {exc}"
                )
                continue
            metadata = parsed.get("metadata") if isinstance(parsed, dict) else None
            if isinstance(metadata, dict) and "hermes" in metadata:
                errors.append(
                    f"{path.relative_to(root).as_posix()}: use canonical metadata.fabric, "
                    "not metadata.fabric"
                )
    return errors


def audit(root: Path = ROOT) -> None:
    contracts = load_contracts(root)
    errors = audit_documented_tokens(root, contracts)
    errors.extend(audit_first_party_skill_metadata(root))
    if errors:
        raise DocsSyncError(errors)


def parse_impact_declarations(body: str) -> dict[str, str]:
    """Parse scoped ``Docs-impact: none [id] — reason`` declarations."""

    declarations: dict[str, str] = {}
    for match in _DOCS_IMPACT_RE.finditer(body or ""):
        ids = [item.strip() for item in match.group(1).split(",")]
        reason = match.group(2).strip()
        invalid_reason = (
            len(reason) < 12
            or "<" in reason
            or "todo" in reason.lower()
            or "explain why" in reason.lower()
            or reason.lower() in {"none", "n/a", "not applicable", "reason"}
        )
        if invalid_reason:
            continue
        for contract_id in ids:
            if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", contract_id):
                declarations[contract_id] = reason
    return declarations


def evaluate_impact(
    changed_paths: Sequence[str], contracts: dict[str, Any], declarations: dict[str, str]
) -> tuple[list[str], list[str]]:
    """Return missing-doc errors and accepted scoped bypass messages."""

    errors: list[str] = []
    bypasses: list[str] = []
    for contract in contracts["impact_contracts"]:
        code_changes = sorted(
            path
            for path in changed_paths
            if _path_matches(path, contract["code_paths"])
        )
        if not code_changes:
            continue
        docs_changes = sorted(
            path
            for path in changed_paths
            if _path_matches(path, contract["docs_paths"])
        )
        contract_id = contract["id"]
        if docs_changes:
            continue
        if contract_id in declarations:
            bypasses.append(f"{contract_id}: {declarations[contract_id]}")
            continue
        errors.append(
            f"{contract_id}: code changed ({', '.join(code_changes)}) but none of its "
            f"mapped narrative docs changed ({', '.join(contract['docs_paths'])}); "
            f"update a mapped page or add `Docs-impact: none [{contract_id}] — <reason>` "
            "to the PR description"
        )
    return errors, bypasses


def _git_changed_paths(root: Path, base_ref: str, head_ref: str) -> list[str]:
    result = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            "--diff-filter=ACMRD",
            f"{base_ref}...{head_ref}",
            "--",
        ],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise DocsSyncError(
            [
                f"cannot compute documentation impact from {base_ref} to {head_ref}",
                result.stderr.strip() or "git diff failed without stderr",
            ]
        )
    return sorted({line.strip() for line in result.stdout.splitlines() if line.strip()})


def _event_body(path: str | None) -> str:
    if not path:
        return ""
    try:
        event = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DocsSyncError([f"cannot load GitHub event payload {path}: {exc}"]) from exc
    pull_request = event.get("pull_request") if isinstance(event, dict) else None
    body = pull_request.get("body") if isinstance(pull_request, dict) else ""
    return body if isinstance(body, str) else ""


def impact(
    root: Path = ROOT,
    *,
    base_ref: str | None,
    head_ref: str,
    changed_files: Sequence[str],
    event_path: str | None,
    declaration_text: str,
) -> list[str]:
    contracts = load_contracts(root)
    if changed_files:
        changed_paths = sorted(set(changed_files))
    else:
        if not base_ref:
            env_base = os.environ.get("GITHUB_BASE_REF", "").strip()
            base_ref = f"origin/{env_base}" if env_base else "origin/main"
        changed_paths = _git_changed_paths(root, base_ref, head_ref)
    body = "\n".join((_event_body(event_path), declaration_text))
    declarations = parse_impact_declarations(body)
    errors, bypasses = evaluate_impact(changed_paths, contracts, declarations)
    if errors:
        raise DocsSyncError(errors)
    return bypasses


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("generate", help="refresh generated documentation")
    subparsers.add_parser("check", help="check generated documentation drift")
    subparsers.add_parser("audit", help="audit token and skill metadata contracts")
    impact_parser = subparsers.add_parser(
        "impact", help="enforce narrative docs impact for changed contracts"
    )
    impact_parser.add_argument("--base-ref")
    impact_parser.add_argument("--head-ref", default="HEAD")
    impact_parser.add_argument("--changed-file", action="append", default=[])
    impact_parser.add_argument("--event-path", default=os.environ.get("GITHUB_EVENT_PATH"))
    impact_parser.add_argument(
        "--declaration",
        default="",
        help="local equivalent of a PR Docs-impact declaration",
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "generate":
            changed = generate(ROOT)
            print(
                "Generated documentation refreshed: "
                + (", ".join(changed) if changed else "already current")
            )
        elif args.command == "check":
            generate(ROOT, check=True)
            print("Generated documentation is current.")
        elif args.command == "audit":
            audit(ROOT)
            print("Documentation source and skill metadata audit passed.")
        else:
            bypasses = impact(
                ROOT,
                base_ref=args.base_ref,
                head_ref=args.head_ref,
                changed_files=args.changed_file,
                event_path=args.event_path,
                declaration_text=args.declaration,
            )
            print("Documentation impact check passed.")
            for bypass in bypasses:
                print(f"Accepted scoped docs bypass: {bypass}")
        return 0
    except DocsSyncError as exc:
        print(f"Documentation sync failed:\n{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
