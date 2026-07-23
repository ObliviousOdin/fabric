#!/usr/bin/env python3
# Portions adapted from teknium1/hermes-star-trek-profiles.
# Copyright (c) 2026 Teknium. MIT licensed; see ../THIRD_PARTY_NOTICES.md.
"""Shared schema and safety helpers for the Fabric Profile Market.

The collection deliberately keeps its editable source separate from generated
Fabric profile distributions.  ``source/metadata.json`` defines the complete
category vocabulary.  Persona records live in JSON arrays under
``source/personas/`` and may only reference values declared by that metadata.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping


CATALOG_SCHEMA_VERSION = 1
SOURCE_SCHEMA_VERSION = 1
GENERATED_MARKER = "GENERATED FILE - DO NOT EDIT."

SLUG_RE = re.compile(r"[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?\Z")
IDENTIFIER_RE = re.compile(r"[a-z0-9](?:[a-z0-9_-]*[a-z0-9])?\Z")
PACK_FIELDS = (
    "name",
    "version",
    "description",
    "author",
    "license",
    "fabric_requires",
    "rights_notice",
)
CATEGORY_REQUIRED_FIELDS = (
    "slug",
    "display_name",
    "description",
    "kind",
    "rights_notice",
    "skin",
)
CATEGORY_KINDS = frozenset({"fan-inspired", "public-domain", "original"})

PROFILE_SCALAR_FIELDS = (
    "slug",
    "name",
    "category",
    "inspiration",
    "role",
    "scope",
    "description",
    "core_identity",
    "user_relationship",
    "under_pressure",
    "disagreement_style",
    "humor",
    "greeting_style",
)
PROFILE_LIST_FIELDS = (
    "task_affinities",
    "voice",
    "worldview",
    "operating_method",
    "strengths",
    "blind_spots",
    "behavioral_rules",
    "design_anchors",
    "failure_mode_guards",
    "avoid",
)
PROFILE_FIELDS = frozenset((*PROFILE_SCALAR_FIELDS, *PROFILE_LIST_FIELDS))

# These are quality floors for each persona, not collection-size snapshots.
MIN_LIST_ITEMS = {
    "task_affinities": 5,
    "voice": 4,
    "worldview": 4,
    "operating_method": 5,
    "strengths": 4,
    "blind_spots": 3,
    "behavioral_rules": 6,
    "design_anchors": 5,
    "failure_mode_guards": 4,
    "avoid": 4,
}

MIN_SCALAR_LENGTHS = {
    "description": 80,
    "core_identity": 80,
}

SKIN_COLOR_KEYS = (
    "banner_border",
    "banner_title",
    "banner_accent",
    "banner_dim",
    "banner_text",
    "ui_accent",
    "ui_label",
    "prompt",
    "input_rule",
    "response_border",
    "status_bar_bg",
    "session_label",
    "session_border",
)
HEX_COLOR_RE = re.compile(r"#[0-9A-Fa-f]{6}\Z")

# Keep generated distribution ids clear of Fabric's profile-name denylist.
# Alias collisions with optional CLI subcommands are handled separately by
# Fabric when --alias is requested; these names cannot be installed at all.
FABRIC_RESERVED_PROFILE_NAMES = frozenset(
    {"hermes", "default", "test", "tmp", "root", "sudo"}
)

FORBIDDEN_FILE_NAMES = frozenset(
    {
        ".env",
        ".env.example",
        ".env.local",
        "auth.json",
        "auth.lock",
        "credentials.json",
        "fabric_state.db",
        "gateway.pid",
        "gateway_state.json",
        "hermes_state.db",
        "processes.json",
        "response_store.db",
        "state.db",
        "state.db-shm",
        "state.db-wal",
    }
)
FORBIDDEN_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        "backups",
        "browser_screenshots",
        "cache",
        "checkpoints",
        "home",
        "local",
        "logs",
        "memories",
        "node_modules",
        "plans",
        "sandboxes",
        "sessions",
        "workspace",
    }
)

SECRET_PATTERNS = (
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----")),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("provider API key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b")),
    (
        "assigned secret",
        re.compile(
            r"(?im)^\s*(?:api[_-]?key|access[_-]?token|password|secret)\s*[:=]\s*"
            r"[\"']?(?!$|<|your[_-]|replace[_-]|example)([A-Za-z0-9_./+=-]{12,})"
        ),
    ),
)


class CollectionError(ValueError):
    """Raised when collection source or generated data violates its contract."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CollectionError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def load_json(path: Path) -> Any:
    """Load UTF-8 JSON while rejecting duplicate object keys."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise CollectionError(f"missing required file: {path}") from exc
    except OSError as exc:
        raise CollectionError(f"cannot read {path}: {exc}") from exc
    try:
        return json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except (json.JSONDecodeError, CollectionError) as exc:
        raise CollectionError(f"invalid JSON in {path}: {exc}") from exc


def _mapping(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CollectionError(f"{where} must be an object")
    return value


def _single_line_text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CollectionError(f"{where} must be a non-empty string")
    normalized = value.strip()
    if "\n" in normalized or "\r" in normalized:
        raise CollectionError(f"{where} must be a single-line string")
    return normalized


def _string_list(
    value: Any,
    where: str,
    *,
    minimum: int = 0,
    identifiers: bool = False,
) -> list[str]:
    if not isinstance(value, list):
        raise CollectionError(f"{where} must be a list")
    items = [_single_line_text(item, f"{where}[{index}]") for index, item in enumerate(value)]
    if len(items) < minimum:
        raise CollectionError(f"{where} needs at least {minimum} item(s)")
    if len(items) != len(set(items)):
        raise CollectionError(f"{where} contains duplicate items")
    if identifiers:
        invalid = [item for item in items if not IDENTIFIER_RE.fullmatch(item)]
        if invalid:
            raise CollectionError(f"{where} contains invalid identifiers: {invalid}")
    return items


def _exact_fields(
    value: Mapping[str, Any],
    where: str,
    *,
    required: Iterable[str],
    optional: Iterable[str] = (),
) -> None:
    required_set = set(required)
    allowed = required_set | set(optional)
    missing = required_set - set(value)
    unknown = set(value) - allowed
    if missing:
        raise CollectionError(f"{where} is missing fields: {sorted(missing)}")
    if unknown:
        raise CollectionError(f"{where} has unknown fields: {sorted(unknown)}")


def _normalize_pack(value: Any, where: str) -> dict[str, str]:
    pack = _mapping(value, where)
    _exact_fields(pack, where, required=PACK_FIELDS)
    return {field: _single_line_text(pack[field], f"{where}.{field}") for field in PACK_FIELDS}


def _normalize_category(value: Any, where: str) -> dict[str, Any]:
    category = _mapping(value, where)
    _exact_fields(category, where, required=CATEGORY_REQUIRED_FIELDS)
    slug = _single_line_text(category["slug"], f"{where}.slug")
    if not SLUG_RE.fullmatch(slug):
        raise CollectionError(f"{where}.slug is invalid: {slug!r}")
    kind = _single_line_text(category["kind"], f"{where}.kind")
    if kind not in CATEGORY_KINDS:
        raise CollectionError(
            f"{where}.kind must be one of {sorted(CATEGORY_KINDS)}"
        )
    return {
        "slug": slug,
        "display_name": _single_line_text(
            category["display_name"], f"{where}.display_name"
        ),
        "description": _single_line_text(category["description"], f"{where}.description"),
        "kind": kind,
        "rights_notice": _single_line_text(
            category["rights_notice"], f"{where}.rights_notice"
        ),
        "skin": _normalize_skin(category["skin"], f"{where}.skin"),
    }


def _normalize_skin(value: Any, where: str) -> dict[str, Any]:
    raw_colors = _mapping(value, where)
    _exact_fields(raw_colors, where, required=SKIN_COLOR_KEYS)
    colors: dict[str, str] = {}
    for key in SKIN_COLOR_KEYS:
        color = _single_line_text(raw_colors[key], f"{where}.{key}")
        if not HEX_COLOR_RE.fullmatch(color):
            raise CollectionError(f"{where}.{key} must be a six-digit hex color")
        colors[key] = color.upper()
    return colors


def _normalize_profile(
    value: Any,
    where: str,
    *,
    category_slugs: set[str],
) -> dict[str, Any]:
    profile = _mapping(value, where)
    _exact_fields(profile, where, required=PROFILE_FIELDS)
    normalized: dict[str, Any] = {}
    for field in PROFILE_SCALAR_FIELDS:
        normalized[field] = _single_line_text(profile[field], f"{where}.{field}")
    for field, minimum in MIN_SCALAR_LENGTHS.items():
        if len(normalized[field]) < minimum:
            raise CollectionError(
                f"{where}.{field} needs at least {minimum} characters"
            )

    slug = normalized["slug"]
    if not SLUG_RE.fullmatch(slug):
        raise CollectionError(f"{where}.slug is invalid: {slug!r}")
    if slug in FABRIC_RESERVED_PROFILE_NAMES:
        raise CollectionError(f"{where}.slug is reserved by Fabric: {slug!r}")
    if normalized["category"] not in category_slugs:
        raise CollectionError(
            f"{where}.category references undeclared category {normalized['category']!r}"
        )
    for field in PROFILE_LIST_FIELDS:
        normalized[field] = _string_list(
            profile[field],
            f"{where}.{field}",
            minimum=MIN_LIST_ITEMS[field],
        )
    return normalized


def load_collection_source(root: Path) -> dict[str, Any]:
    """Load and normalize metadata plus every source persona deterministically."""
    root = root.resolve()
    metadata_path = root / "source" / "metadata.json"
    metadata = _mapping(load_json(metadata_path), str(metadata_path))
    _exact_fields(
        metadata,
        str(metadata_path),
        required=("pack", "categories"),
        optional=("schema_version",),
    )
    schema_version = metadata.get("schema_version", SOURCE_SCHEMA_VERSION)
    if schema_version != SOURCE_SCHEMA_VERSION:
        raise CollectionError(
            f"{metadata_path}.schema_version must be {SOURCE_SCHEMA_VERSION}"
        )

    pack = _normalize_pack(metadata["pack"], f"{metadata_path}.pack")
    raw_categories = metadata["categories"]
    if not isinstance(raw_categories, list) or not raw_categories:
        raise CollectionError(f"{metadata_path}.categories must be a non-empty list")
    categories = [
        _normalize_category(item, f"{metadata_path}.categories[{index}]")
        for index, item in enumerate(raw_categories)
    ]
    category_slugs = [item["slug"] for item in categories]
    if len(category_slugs) != len(set(category_slugs)):
        raise CollectionError(f"{metadata_path}.categories contains duplicate slugs")
    persona_dir = root / "source" / "personas"
    paths = sorted(persona_dir.glob("*.json")) if persona_dir.is_dir() else []
    profiles: list[dict[str, Any]] = []
    for path in paths:
        if path.is_symlink():
            raise CollectionError(f"source persona files cannot be symlinks: {path}")
        raw = load_json(path)
        if not isinstance(raw, list):
            raise CollectionError(f"{path} must contain a top-level JSON array")
        profiles.extend(
            _normalize_profile(
                item,
                f"{path}[{index}]",
                category_slugs=set(category_slugs),
            )
            for index, item in enumerate(raw)
        )

    slugs = [item["slug"] for item in profiles]
    if len(slugs) != len(set(slugs)):
        duplicates = sorted({slug for slug in slugs if slugs.count(slug) > 1})
        raise CollectionError(f"duplicate profile slugs: {duplicates}")
    descriptions = [item["description"] for item in profiles]
    if len(descriptions) != len(set(descriptions)):
        raise CollectionError("profile routing descriptions must be unique")
    operating_methods = [tuple(item["operating_method"]) for item in profiles]
    if len(operating_methods) != len(set(operating_methods)):
        raise CollectionError("profile operating methods must be behaviorally distinct")
    category_rank = {category["slug"]: index for index, category in enumerate(categories)}
    profiles.sort(
        key=lambda item: (
            category_rank[item["category"]],
            item["name"].casefold(),
            item["slug"],
        )
    )
    return {
        "schema_version": schema_version,
        "pack": pack,
        "categories": categories,
        "profiles": profiles,
    }


def public_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
    """Return catalog-safe profile data, omitting source-only inspiration/skin data."""
    return {
        key: profile[key]
        for key in (
            "category",
            "slug",
            "name",
            "description",
            "role",
            "scope",
            "task_affinities",
            "core_identity",
            "user_relationship",
            "voice",
            "worldview",
            "operating_method",
            "strengths",
            "under_pressure",
            "disagreement_style",
            "humor",
            "behavioral_rules",
            "design_anchors",
            "blind_spots",
            "failure_mode_guards",
            "avoid",
            "greeting_style",
        )
    }


def catalog_from_source(source: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "_generated": GENERATED_MARKER,
        "schema_version": CATALOG_SCHEMA_VERSION,
        "pack": dict(source["pack"]),
        "categories": [dict(item) for item in source["categories"]],
        "profiles": [public_profile(profile) for profile in source["profiles"]],
    }


def validate_catalog_document(data: Any, where: str = "catalog.json") -> dict[str, Any]:
    catalog = _mapping(data, where)
    _exact_fields(
        catalog,
        where,
        required=("_generated", "schema_version", "pack", "categories", "profiles"),
    )
    if catalog["_generated"] != GENERATED_MARKER:
        raise CollectionError(f"{where} is missing the generated-file marker")
    if catalog["schema_version"] != CATALOG_SCHEMA_VERSION:
        raise CollectionError(
            f"{where}.schema_version must be {CATALOG_SCHEMA_VERSION}"
        )
    if not isinstance(catalog["categories"], list):
        raise CollectionError(f"{where}.categories must be a list")
    if not isinstance(catalog["profiles"], list):
        raise CollectionError(f"{where}.profiles must be a list")
    category_slugs = {
        item.get("slug")
        for item in catalog["categories"]
        if isinstance(item, dict) and isinstance(item.get("slug"), str)
    }
    if len(category_slugs) != len(catalog["categories"]):
        raise CollectionError(f"{where}.categories contains invalid or duplicate slugs")
    seen_profiles: set[str] = set()
    for index, profile in enumerate(catalog["profiles"]):
        if not isinstance(profile, dict):
            raise CollectionError(f"{where}.profiles[{index}] must be an object")
        slug = profile.get("slug")
        if not isinstance(slug, str) or not SLUG_RE.fullmatch(slug):
            raise CollectionError(f"{where}.profiles[{index}].slug is invalid")
        if slug in seen_profiles:
            raise CollectionError(f"{where} contains duplicate profile slug {slug!r}")
        seen_profiles.add(slug)
        if profile.get("category") not in category_slugs:
            raise CollectionError(
                f"{where}.profiles[{index}] references an undeclared category"
            )
    return catalog


def profile_digest(profile_dir: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in profile_dir.rglob("*") if item.is_file()):
        digest.update(path.relative_to(profile_dir).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def find_secret(text: str) -> str | None:
    for label, pattern in SECRET_PATTERNS:
        if pattern.search(text):
            return label
    return None


def inspect_tree_safety(root: Path) -> list[str]:
    """Return portable-path, symlink, user-state, and secret findings."""
    findings: list[str] = []
    if not root.exists():
        return findings
    for path in sorted(root.rglob("*")):
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            relative = str(path)
        if path.is_symlink():
            findings.append(f"symlink is not allowed: {relative}")
            continue
        lower_name = path.name.casefold()
        if path.is_dir() and lower_name in FORBIDDEN_DIRECTORY_NAMES:
            findings.append(f"forbidden runtime/user directory: {relative}")
            continue
        if not path.is_file():
            continue
        if lower_name in FORBIDDEN_FILE_NAMES or lower_name.endswith((".pem", ".key", ".p12", ".pfx")):
            findings.append(f"forbidden secret/runtime file: {relative}")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        except OSError as exc:
            findings.append(f"cannot inspect {relative}: {exc}")
            continue
        secret_kind = find_secret(text)
        if secret_kind:
            findings.append(f"possible {secret_kind} in {relative}")
    return findings
