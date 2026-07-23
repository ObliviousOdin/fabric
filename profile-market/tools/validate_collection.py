#!/usr/bin/env python3
# Portions adapted from teknium1/hermes-star-trek-profiles.
# Copyright (c) 2026 Teknium. MIT licensed; see ../THIRD_PARTY_NOTICES.md.
"""Validate source, generated profiles, safety boundaries, and behavior contracts."""

from __future__ import annotations

import json
import os
import re
import stat
import sys
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

import yaml

from build_collection import actual_outputs, build_outputs, stale_paths
from collection_common import (
    GENERATED_MARKER,
    CollectionError,
    SKIN_COLOR_KEYS,
    catalog_from_source,
    inspect_tree_safety,
    load_collection_source,
    load_json,
    validate_catalog_document,
)


ROOT = Path(__file__).resolve().parents[1]
PROFILE_FILES = {
    "SOUL.md",
    "README.md",
    "config.yaml",
    "distribution.yaml",
    "LICENSE",
    "RIGHTS.md",
    "THIRD_PARTY_NOTICES.md",
}
MANIFEST_OWNED = [
    "SOUL.md",
    "config.yaml",
    "skins/",
    "README.md",
    "LICENSE",
    "RIGHTS.md",
    "THIRD_PARTY_NOTICES.md",
    "distribution.yaml",
]
SOUL_SECTIONS = {
    "## Identity",
    "## Non-Negotiable Boundaries",
    "## Relationship With the User",
    "## Voice",
    "## Worldview",
    "## Operating Method",
    "## Strengths to Emphasize",
    "## Under Pressure",
    "## Disagreement",
    "## Behavioral Rules",
    "## Design Anchors",
    "## Blind Spots",
    "## Avoid",
    "## Rights and Attribution",
    "## Baseline Fabric Contract",
}
SOUL_INVARIANTS = {
    "Always remain Fabric",
    "grants no real-world credentials, access, ownership, expertise, or authority",
    "authorization only for its clearly stated scope",
    "preserve Fabric's approval controls",
    "explicitly user-controlled target or credible authorization",
    "Respect third-party autonomy, privacy, safety, and rights",
    "Never use coercion, covert persuasion, impersonation, fabricated evidence",
    "Never cultivate emotional or romantic exclusivity, dependency, or isolation",
    "Never expose, solicit, invent, or store credentials in profile content",
    "instead of fabricating success or silently changing the goal",
    "Use Fabric tools when they improve correctness",
}


def fail(message: str) -> None:
    raise CollectionError(message)


def require_generated_marker(path: Path) -> None:
    if path.name == "catalog.json":
        data = load_json(path)
        if not isinstance(data, dict) or data.get("_generated") != GENERATED_MARKER:
            fail(f"{path}: generated marker is missing")
        return
    try:
        first_line = path.read_text(encoding="utf-8").splitlines()[0]
    except (OSError, UnicodeDecodeError, IndexError) as exc:
        fail(f"{path}: cannot read generated marker: {exc}")
    if GENERATED_MARKER not in first_line:
        fail(f"{path}: generated marker is missing")


def validate_generated_freshness(source: Mapping[str, Any]) -> None:
    expected = build_outputs(source)
    actual = actual_outputs(ROOT)
    stale = stale_paths(expected, actual)
    if stale:
        preview = ", ".join(stale[:8])
        more = " ..." if len(stale) > 8 else ""
        fail(f"generated output is stale or unexpected: {preview}{more}")
    for relative in expected:
        require_generated_marker(ROOT / Path(relative.as_posix()))


def validate_catalog(source: Mapping[str, Any]) -> dict[str, Any]:
    path = ROOT / "catalog.json"
    catalog = validate_catalog_document(load_json(path), str(path))
    expected = catalog_from_source(source)
    if catalog != expected:
        fail("catalog.json does not preserve the normalized source relationships")
    source_category_slugs = [category["slug"] for category in source["categories"]]
    catalog_category_slugs = [category["slug"] for category in catalog["categories"]]
    if catalog_category_slugs != source_category_slugs:
        fail("catalog categories must exactly match metadata-defined categories and order")
    return catalog


def validate_category_coverage(source: Mapping[str, Any]) -> None:
    counts = Counter(profile["category"] for profile in source["profiles"])
    missing = [category["slug"] for category in source["categories"] if not counts[category["slug"]]]
    if missing:
        fail(f"metadata-defined categories without profiles: {missing}")


def validate_profile_tree(
    source: Mapping[str, Any],
    catalog: Mapping[str, Any],
) -> None:
    profiles_root = ROOT / "profiles"
    if not profiles_root.is_dir():
        fail("generated profiles/ directory is missing")

    source_profiles = {profile["slug"]: profile for profile in source["profiles"]}
    catalog_profiles = {profile["slug"]: profile for profile in catalog["profiles"]}
    actual_dirs = {path.name for path in profiles_root.iterdir() if path.is_dir()}
    if actual_dirs != set(source_profiles):
        fail(
            "profile directory/source mismatch: "
            f"missing={sorted(set(source_profiles) - actual_dirs)}, "
            f"extra={sorted(actual_dirs - set(source_profiles))}"
        )

    category_by_slug = {category["slug"]: category for category in source["categories"]}
    all_souls: dict[str, str] = {}
    for slug, profile in source_profiles.items():
        root = profiles_root / slug
        direct_files = {path.name for path in root.iterdir() if path.is_file()}
        if direct_files != PROFILE_FILES:
            fail(
                f"{slug}: direct file contract mismatch; "
                f"missing={sorted(PROFILE_FILES - direct_files)}, "
                f"extra={sorted(direct_files - PROFILE_FILES)}"
            )
        direct_dirs = {path.name for path in root.iterdir() if path.is_dir()}
        if direct_dirs != {"skins"}:
            fail(f"{slug}: only the generated skins/ directory is allowed")
        skin_files = {path.name for path in (root / "skins").iterdir() if path.is_file()}
        if skin_files != {f"{slug}.yaml"}:
            fail(f"{slug}: skin file must be skins/{slug}.yaml")

        for path in root.rglob("*"):
            if path.is_file() and stat.S_IMODE(path.stat().st_mode) & (
                stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
            ):
                fail(f"{slug}: executable payload files are not allowed: {path.relative_to(root)}")

        manifest = yaml.safe_load((root / "distribution.yaml").read_text(encoding="utf-8"))
        expected_manifest = {
            "name": slug,
            "version": source["pack"]["version"],
            "description": profile["description"],
            "fabric_requires": source["pack"]["fabric_requires"],
            "author": source["pack"]["author"],
            "license": source["pack"]["license"],
            "distribution_owned": MANIFEST_OWNED,
        }
        if manifest != expected_manifest:
            fail(f"{slug}: distribution manifest does not match source/pack metadata")
        if any(key in manifest for key in ("env_requires", "source", "installed_at")):
            fail(f"{slug}: source manifests cannot ship credentials or install provenance")
        for owned in manifest["distribution_owned"]:
            pure = PurePosixPath(owned.rstrip("/"))
            if pure.is_absolute() or ".." in pure.parts:
                fail(f"{slug}: unsafe distribution_owned path: {owned}")

        config = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
        if config != {"model": "", "display": {"skin": slug}}:
            fail(f"{slug}: config must only leave model empty and select its skin")
        forbidden_config_keys = {"provider", "api_key", "base_url", "env", "mcp", "cron"}
        if forbidden_config_keys & set(config):
            fail(f"{slug}: config contains provider, credential, or service settings")

        skin = yaml.safe_load((root / "skins" / f"{slug}.yaml").read_text(encoding="utf-8"))
        if skin.get("name") != slug:
            fail(f"{slug}: skin name mismatch")
        if skin.get("branding", {}).get("agent_name") != profile["name"]:
            fail(f"{slug}: skin branding identity mismatch")
        expected_colors = category_by_slug[profile["category"]]["skin"]
        if skin.get("colors") != expected_colors:
            fail(f"{slug}: skin palette must come from its metadata category")
        if set(skin.get("colors", {})) != set(SKIN_COLOR_KEYS):
            fail(f"{slug}: skin palette is incomplete")

        soul = (root / "SOUL.md").read_text(encoding="utf-8")
        headings = set(re.findall(r"^## .+$", soul, flags=re.MULTILINE))
        missing_sections = SOUL_SECTIONS - headings
        if missing_sections:
            fail(f"{slug}: SOUL is missing sections {sorted(missing_sections)}")
        missing_invariants = {text for text in SOUL_INVARIANTS if text not in soul}
        if missing_invariants:
            fail(f"{slug}: SOUL is missing safety invariants {sorted(missing_invariants)}")
        for required_text in (
            profile["name"],
            profile["core_identity"],
            profile["user_relationship"],
            category_by_slug[profile["category"]]["rights_notice"],
        ):
            if required_text not in soul:
                fail(f"{slug}: SOUL omitted source-defined behavioral content")
        if len(set(re.findall(r"[A-Za-z]+", soul.casefold()))) < 180:
            fail(f"{slug}: SOUL vocabulary is too thin for a substantive profile")
        all_souls[slug] = soul

        readme = (root / "README.md").read_text(encoding="utf-8")
        if profile["description"] not in readme or profile["slug"] not in readme:
            fail(f"{slug}: generated README omits install/routing metadata")

        license_text = (root / "LICENSE").read_text(encoding="utf-8")
        rights_text = (root / "RIGHTS.md").read_text(encoding="utf-8")
        upstream_notice = (root / "THIRD_PARTY_NOTICES.md").read_text(
            encoding="utf-8"
        )
        if "Fabric Profile Market contributors" not in license_text:
            fail(f"{slug}: generated LICENSE omits this collection's grant")
        if "Neither grant conveys rights in third-party names" not in rights_text:
            fail(f"{slug}: generated RIGHTS.md omits the redistribution boundary")
        for required_notice in (
            "Copyright (c) 2026 Teknium",
            "The above copyright notice and this permission notice",
        ):
            if required_notice not in upstream_notice:
                fail(f"{slug}: generated third-party notice is incomplete")

        if catalog_profiles[slug]["description"] != profile["description"]:
            fail(f"{slug}: catalog routing description diverges from source")

    # Profiles must have genuinely distinct behavioral bodies. This asserts a
    # relationship between entries rather than freezing a profile count.
    normalized_bodies: dict[str, str] = {}
    for slug, soul in all_souls.items():
        body = re.sub(r"[^a-z]+", " ", soul.casefold())
        if body in normalized_bodies:
            fail(f"{slug}: SOUL duplicates {normalized_bodies[body]}")
        normalized_bodies[body] = slug


def validate_safety() -> None:
    findings: list[str] = []
    for relative in ("source", "profiles"):
        findings.extend(
            f"{relative}/{finding}"
            for finding in inspect_tree_safety(ROOT / relative)
        )
    if findings:
        fail("collection safety validation failed: " + "; ".join(findings[:5]))

    # Generated payloads are text-only by contract. Binary files are both a
    # reviewability risk and an easy way to accidentally ship franchise art.
    for path in (ROOT / "profiles").rglob("*") if (ROOT / "profiles").exists() else []:
        if not path.is_file():
            continue
        try:
            path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            fail(f"binary generated payload is not allowed: {path.relative_to(ROOT)}")


def validate() -> tuple[int, int]:
    source = load_collection_source(ROOT)
    validate_safety()
    validate_generated_freshness(source)
    catalog = validate_catalog(source)
    validate_category_coverage(source)
    validate_profile_tree(source, catalog)
    return len(source["profiles"]), len(source["categories"])


def main() -> int:
    try:
        profile_count, category_count = validate()
    except (CollectionError, OSError, yaml.YAMLError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(
        f"Validated {profile_count} profile(s) across {category_count} "
        "metadata-defined categories."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
