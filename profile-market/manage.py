#!/usr/bin/env python3
# Portions adapted from teknium1/hermes-star-trek-profiles.
# Copyright (c) 2026 Teknium. MIT licensed; see THIRD_PARTY_NOTICES.md.
"""Browse, install, and update the Fabric Profile Market.

This manager is intentionally a thin wrapper around Fabric's native profile
distribution CLI.  It never writes into ``FABRIC_HOME`` itself.
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parent
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from collection_common import (  # noqa: E402
    CollectionError,
    catalog_from_source,
    inspect_tree_safety,
    load_collection_source,
    load_json,
    profile_digest,
    validate_catalog_document,
)
from build_collection import build_outputs  # noqa: E402


@dataclass(frozen=True)
class InstalledDistribution:
    """Distribution identity reported by Fabric for an existing profile."""

    name: str | None
    source: str | None


def load_catalog() -> dict[str, Any]:
    """Load generated catalog and verify its categories match source metadata."""
    source = load_collection_source(ROOT)
    expected = catalog_from_source(source)
    path = ROOT / "catalog.json"
    if not path.is_file():
        # Useful while authoring an empty/new pack; installs still require a
        # generated distribution directory below.
        return expected
    catalog = validate_catalog_document(load_json(path), str(path))
    if catalog != expected:
        raise CollectionError(
            "catalog does not exactly match normalized source metadata/personas; "
            "run tools/build_collection.py"
        )
    return catalog


def category_map(catalog: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {item["slug"]: item for item in catalog["categories"]}


def validate_categories(
    requested: Iterable[str] | None,
    catalog: Mapping[str, Any],
) -> list[str]:
    values = list(requested or [])
    known = category_map(catalog)
    unknown = [value for value in values if value not in known]
    if unknown:
        raise CollectionError(
            f"unknown category {unknown[0]!r}; available: {', '.join(known)}"
        )
    # Preserve the metadata-defined category order regardless of CLI order.
    selected = set(values)
    return [item["slug"] for item in catalog["categories"] if item["slug"] in selected]


def filtered_profiles(
    catalog: Mapping[str, Any],
    categories: Iterable[str] | None,
) -> list[dict[str, Any]]:
    selected = validate_categories(categories, catalog)
    if not selected:
        return list(catalog["profiles"])
    selected_set = set(selected)
    return [profile for profile in catalog["profiles"] if profile["category"] in selected_set]


def print_catalog(catalog: Mapping[str, Any], categories: Iterable[str] | None) -> None:
    selected = validate_categories(categories, catalog)
    selected_set = set(selected)
    profiles = list(catalog["profiles"])
    for category in catalog["categories"]:
        if selected_set and category["slug"] not in selected_set:
            continue
        print(f"\n{category['display_name']} ({category['slug']})")
        print("-" * (len(category["display_name"]) + len(category["slug"]) + 3))
        members = [profile for profile in profiles if profile["category"] == category["slug"]]
        if not members:
            print("  (no profiles yet)")
            continue
        width = max(len(profile["slug"]) for profile in members)
        for profile in members:
            affinity = "; ".join(profile["task_affinities"][:2])
            print(f"  {profile['slug']:<{width}}  {profile['name']} - {affinity}")


def searchable_text(
    profile: Mapping[str, Any],
    categories: Mapping[str, Mapping[str, Any]],
) -> str:
    values: list[str] = [
        profile["slug"],
        profile["name"],
        profile["description"],
        profile["role"],
        profile["scope"],
        profile["core_identity"],
        categories[profile["category"]]["display_name"],
    ]
    for field in (
        "task_affinities",
        "strengths",
        "voice",
        "worldview",
        "design_anchors",
    ):
        values.extend(profile[field])
    return "\n".join(values).casefold()


def search_catalog(
    catalog: Mapping[str, Any],
    query: str,
    categories: Iterable[str] | None,
) -> list[dict[str, Any]]:
    terms = [term for term in query.casefold().split() if term]
    category_by_slug = category_map(catalog)
    matches = []
    for profile in filtered_profiles(catalog, categories):
        haystack = searchable_text(profile, category_by_slug)
        if all(term in haystack for term in terms):
            matches.append(profile)
    return matches


def show_profile(catalog: Mapping[str, Any], slug: str) -> None:
    profile = next((item for item in catalog["profiles"] if item["slug"] == slug), None)
    if profile is None:
        raise CollectionError(f"unknown profile {slug!r}")
    category = category_map(catalog)[profile["category"]]
    print(f"\n{profile['name']} ({profile['slug']})")
    print(f"Category: {category['display_name']} [{category['kind']}]")
    print(f"Role:     {profile['role']}")
    print(f"Scope:    {profile['scope']}")
    print(f"\n{profile['description']}")
    print("\nBest at:")
    for item in profile["task_affinities"]:
        print(f"  - {item}")
    print("\nOperating method:")
    for item in profile["operating_method"]:
        print(f"  - {item}")
    print("\nStrengths:")
    for item in profile["strengths"]:
        print(f"  - {item}")
    print("\nBlind spots and guards:")
    for item in profile["blind_spots"]:
        print(f"  - {item}")
    for item in profile["failure_mode_guards"]:
        print(f"  - Guard: {item}")
    print(f"\nRights: {category['rights_notice']}")


def select_profiles(
    args: argparse.Namespace,
    catalog: Mapping[str, Any],
) -> list[dict[str, Any]]:
    by_slug = {profile["slug"]: profile for profile in catalog["profiles"]}
    selected: set[str] = set()
    if args.all:
        selected.update(by_slug)
    categories = validate_categories(args.category, catalog)
    for category in categories:
        selected.update(
            profile["slug"]
            for profile in catalog["profiles"]
            if profile["category"] == category
        )
    for slug in args.targets:
        if slug not in by_slug:
            raise CollectionError(
                f"unknown profile {slug!r}; run `python3 manage.py search {slug}`"
            )
        selected.add(slug)
    if not selected:
        raise CollectionError(
            "select one or more profile slugs, repeatable --category CATEGORY, or --all"
        )
    # Catalog order is already the stable metadata/category order.
    return [profile for profile in catalog["profiles"] if profile["slug"] in selected]


def require_fabric(binary: str) -> str:
    if not binary.strip():
        raise CollectionError("--fabric-bin cannot be empty")
    path = Path(binary).expanduser()
    if path.parent != Path(".") or "/" in binary or "\\" in binary:
        if not path.is_file():
            raise CollectionError(f"Fabric executable not found: {binary}")
        resolved_path = path.resolve()
        if not os.access(resolved_path, os.X_OK):
            raise CollectionError(f"Fabric path is not executable: {binary}")
        return str(resolved_path)
    resolved = shutil.which(binary)
    if resolved is None:
        raise CollectionError(f"Fabric executable not found on PATH: {binary}")
    return resolved


def run(
    command: list[str],
    *,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=False,
            text=True,
            capture_output=capture,
            timeout=600,
        )
    except FileNotFoundError as exc:
        raise CollectionError(f"required command not found: {command[0]}") from exc
    except OSError as exc:
        raise CollectionError(f"could not execute {command[0]}: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise CollectionError(f"command timed out: {' '.join(command)}") from exc


def inspect_installed_distribution(
    fabric_bin: str,
    slug: str,
) -> InstalledDistribution | None:
    """Read the installed manifest through Fabric's public CLI.

    ``None`` means the profile does not exist. Other inspection failures fail
    closed so an install/update cannot accidentally act on an unknown target.
    """
    proc = run([fabric_bin, "profile", "info", slug], capture=True)
    combined = "\n".join(part for part in (proc.stdout, proc.stderr) if part)
    if proc.returncode:
        if "does not exist" in combined.casefold():
            return None
        detail = combined.strip().splitlines()[-1] if combined.strip() else "no diagnostic"
        raise CollectionError(f"could not inspect installed profile {slug!r}: {detail}")

    fields: dict[str, str] = {}
    for raw_line in proc.stdout.splitlines():
        key, separator, value = raw_line.strip().partition(":")
        if separator and key in {"Distribution", "Source"}:
            fields[key] = value.strip()
    return InstalledDistribution(
        name=fields.get("Distribution"),
        source=fields.get("Source"),
    )


def market_ownership_error(
    installed: InstalledDistribution | None,
    slug: str,
) -> str | None:
    """Explain why an installed profile is not owned by this checkout."""
    if installed is None:
        return f"{slug} is not installed"
    if installed.name != slug:
        actual = installed.name or "no distribution manifest"
        return f"{slug} belongs to {actual!r}, not this market distribution"
    if not installed.source:
        return f"{slug} has no recorded distribution source"

    expected = generated_profile_dir(slug)
    source = Path(installed.source).expanduser().resolve()
    if source != expected:
        return (
            f"{slug} was installed from {installed.source!r}; "
            f"this checkout expects {str(expected)!r}"
        )
    return None


def confirm(
    action: str,
    profiles: list[Mapping[str, Any]],
    categories: Mapping[str, Mapping[str, Any]],
    assume_yes: bool,
    notices: Iterable[str] = (),
) -> None:
    print(f"{action} {len(profiles)} profile(s):")
    for profile in profiles:
        print(
            f"  {profile['slug']:<24} {profile['name']} "
            f"({categories[profile['category']]['display_name']})"
        )
    for notice in notices:
        print(f"\nNOTICE: {notice}")
    if assume_yes:
        return
    if not sys.stdin.isatty():
        raise CollectionError("refusing non-interactive operation without --yes")
    try:
        answer = input("Continue? [y/N] ").strip().casefold()
    except (EOFError, KeyboardInterrupt):
        answer = ""
    if answer not in {"y", "yes"}:
        raise CollectionError("cancelled")


def generated_profile_dir(slug: str) -> Path:
    profiles_root = (ROOT / "profiles").resolve()
    path = (profiles_root / slug).resolve()
    try:
        path.relative_to(profiles_root)
    except ValueError as exc:  # Defense in depth after slug validation.
        raise CollectionError(f"profile path escapes generated root: {slug!r}") from exc
    if not (path / "distribution.yaml").is_file():
        raise CollectionError(
            f"generated distribution is missing for {slug!r}; run tools/build_collection.py"
        )
    findings = inspect_tree_safety(path)
    if findings:
        raise CollectionError(f"unsafe generated distribution {slug!r}: {findings[0]}")
    return path


def expected_profile_outputs(slugs: Iterable[str]) -> dict[str, dict[str, bytes]]:
    """Render canonical payload bytes once and select the requested profiles."""
    selected = set(slugs)
    expected = {slug: {} for slug in selected}
    for path, data in build_outputs(load_collection_source(ROOT)).items():
        parts = path.parts
        if len(parts) < 3 or parts[0] != "profiles" or parts[1] not in selected:
            continue
        expected[parts[1]][PurePosixPath(*parts[2:]).as_posix()] = data
    missing = sorted(slug for slug, files in expected.items() if not files)
    if missing:
        raise CollectionError(f"no deterministic generated payload for: {', '.join(missing)}")
    return expected


def validate_generated_profile_bytes(
    slug: str,
    expected_files: Mapping[str, bytes],
) -> Path:
    """Require an exact, text-only, non-executable deterministic payload tree."""
    root = generated_profile_dir(slug)
    actual_files: dict[str, Path] = {}
    actual_dirs: set[str] = set()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise CollectionError(f"{slug}: generated payload contains symlink {relative!r}")
        if path.is_dir():
            actual_dirs.add(relative)
            continue
        if not path.is_file():
            raise CollectionError(f"{slug}: unsupported payload entry {relative!r}")
        if stat.S_IMODE(path.stat().st_mode) & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
            raise CollectionError(f"{slug}: executable payload file is not allowed: {relative}")
        actual_files[relative] = path

    expected_names = set(expected_files)
    expected_dirs: set[str] = set()
    for name in expected_names:
        parent = PurePosixPath(name).parent
        while parent != PurePosixPath("."):
            expected_dirs.add(parent.as_posix())
            parent = parent.parent
    if set(actual_files) != expected_names or actual_dirs != expected_dirs:
        missing = sorted(expected_names - set(actual_files))
        extra = sorted(set(actual_files) - expected_names)
        extra_dirs = sorted(actual_dirs - expected_dirs)
        raise CollectionError(
            f"{slug}: generated tree differs from deterministic source "
            f"(missing={missing}, extra={extra}, extra_dirs={extra_dirs})"
        )
    for name, expected_bytes in expected_files.items():
        if actual_files[name].read_bytes() != expected_bytes:
            raise CollectionError(
                f"{slug}: generated file {name!r} differs from deterministic source; "
                "run tools/build_collection.py and review the change"
            )
    return root


def validate_selected_payloads(
    profiles: Iterable[Mapping[str, Any]],
) -> dict[str, dict[str, bytes]]:
    profile_list = list(profiles)
    expected = expected_profile_outputs(profile["slug"] for profile in profile_list)
    for profile in profile_list:
        validate_generated_profile_bytes(profile["slug"], expected[profile["slug"]])
    return expected


def install(args: argparse.Namespace, catalog: Mapping[str, Any]) -> int:
    profiles = select_profiles(args, catalog)
    fabric_bin = require_fabric(args.fabric_bin)
    expected_payloads = validate_selected_payloads(profiles)
    categories = category_map(catalog)
    notices = []
    if args.force:
        notices.append(
            "--force replaces an existing profile's SOUL.md, config.yaml, and "
            "skins with this distribution. Memories, sessions, credentials, "
            "and profile description remain, but local model/provider config is lost."
        )
    confirm("Install", profiles, categories, args.yes, notices)
    installed_profiles: list[str] = []
    fresh_profiles: list[str] = []
    install_failures: list[str] = []
    description_warnings: list[str] = []
    for profile in profiles:
        slug = profile["slug"]
        try:
            source = validate_generated_profile_bytes(slug, expected_payloads[slug])
        except CollectionError as exc:
            print(f"\nError: {exc}", file=sys.stderr)
            install_failures.append(slug)
            continue
        already_installed = inspect_installed_distribution(fabric_bin, slug) is not None
        command = [
            fabric_bin,
            "profile",
            "install",
            str(source),
            "--name",
            slug,
            "-y",
        ]
        if args.alias:
            command.append("--alias")
        if args.force:
            command.append("--force")
        print(f"\nInstalling {profile['name']} as {slug}")
        print(f"  Payload SHA-256: {profile_digest(source)}")
        if run(command).returncode:
            install_failures.append(slug)
            continue
        installed_profiles.append(slug)
        if not already_installed:
            fresh_profiles.append(slug)
        # profile.yaml is intentionally not part of the distribution: setting
        # this only after a fresh install preserves later user edits on update.
        if not already_installed:
            described = run(
                [
                    fabric_bin,
                    "profile",
                    "describe",
                    slug,
                    "--text",
                    profile["description"],
                ]
            )
            if described.returncode:
                description_warnings.append(slug)
                recovery = shlex.join(
                    [
                        fabric_bin,
                        "profile",
                        "describe",
                        slug,
                        "--text",
                        profile["description"],
                    ]
                )
                print(
                    f"Warning: {slug} installed, but its routing description was not set.\n"
                    f"  Recover with: {recovery}",
                    file=sys.stderr,
                )
    if installed_profiles:
        print(f"\nInstalled profiles: {', '.join(installed_profiles)}")
    if description_warnings:
        print(
            "Routing description warnings: " + ", ".join(description_warnings),
            file=sys.stderr,
        )
    if install_failures:
        print(f"Install failures: {', '.join(install_failures)}", file=sys.stderr)
        return 1
    if fresh_profiles:
        print("\nConfigure each fresh isolated profile before its first chat:")
        for slug in fresh_profiles:
            print(f"  fabric -p {slug} setup")
    print("\nInstalled. Start a new session so the profile enters a stable prompt prefix.")
    return 0


def update(args: argparse.Namespace, catalog: Mapping[str, Any]) -> int:
    profiles = select_profiles(args, catalog)
    fabric_bin = require_fabric(args.fabric_bin)
    owned_profiles: list[dict[str, Any]] = []
    ownership_errors: list[str] = []
    for profile in profiles:
        installed = inspect_installed_distribution(fabric_bin, profile["slug"])
        if args.all and installed is None:
            continue
        issue = market_ownership_error(installed, profile["slug"])
        if issue:
            ownership_errors.append(issue)
        else:
            owned_profiles.append(profile)
    if ownership_errors:
        details = "\n  - ".join(ownership_errors)
        raise CollectionError(
            "refusing to update profiles not installed from this exact market checkout:\n"
            f"  - {details}\n"
            "Review the target, then use `manage.py install <slug> --force` only "
            "if replacing it is intentional."
        )
    profiles = owned_profiles
    if args.all:
        if not profiles:
            print("No profiles from this collection are installed.")
            return 0
    expected_payloads = validate_selected_payloads(profiles)
    categories = category_map(catalog)
    notices = []
    if args.force_config:
        notices.append(
            "--force-config overwrites each selected profile's config.yaml with "
            "this pack's empty model plus skin selection. Local model/provider "
            "choices in that file are lost; credentials and other user state remain."
        )
    confirm("Update", profiles, categories, args.yes, notices)
    updated_profiles: list[str] = []
    update_failures: list[str] = []
    for profile in profiles:
        slug = profile["slug"]
        validate_generated_profile_bytes(slug, expected_payloads[slug])
        command = [fabric_bin, "profile", "update", slug, "-y"]
        if args.force_config:
            command.append("--force-config")
        print(f"\nUpdating {profile['name']} ({slug})")
        source = ROOT / "profiles" / slug
        if source.is_dir():
            print(f"  Current payload SHA-256: {profile_digest(source)}")
        if run(command).returncode:
            update_failures.append(slug)
            continue
        updated_profiles.append(slug)
    if updated_profiles:
        print(f"\nUpdated profiles: {', '.join(updated_profiles)}")
    if update_failures:
        print(f"Update failures: {', '.join(update_failures)}", file=sys.stderr)
        return 1
    print("\nUpdated. Start a new session before expecting identity changes.")
    return 0


def add_category_filter(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--category",
        action="append",
        default=[],
        metavar="CATEGORY",
        help="filter/select one metadata-defined category; repeatable",
    )


def add_selection_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("targets", nargs="*", metavar="PROFILE")
    add_category_filter(parser)
    parser.add_argument("--all", action="store_true", help="select every profile")
    parser.add_argument("-y", "--yes", action="store_true", help="skip collection confirmation")
    parser.add_argument(
        "--fabric-bin",
        default="fabric",
        metavar="PATH",
        help="Fabric executable (default: fabric)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    list_parser = sub.add_parser("list", help="list available profiles")
    add_category_filter(list_parser)

    search_parser = sub.add_parser("search", help="search profile metadata and behavior")
    search_parser.add_argument("query", nargs="+", help="one or more search terms")
    add_category_filter(search_parser)

    show_parser = sub.add_parser("show", help="show one profile in detail")
    show_parser.add_argument("profile", help="profile slug")

    install_parser = sub.add_parser("install", help="install native Fabric profiles")
    add_selection_flags(install_parser)
    install_parser.add_argument("--alias", action="store_true", help="ask Fabric to create wrappers")
    install_parser.add_argument(
        "--force",
        action="store_true",
        help="replace an existing profile's distribution-owned files",
    )

    update_parser = sub.add_parser("update", help="update installed profiles")
    add_selection_flags(update_parser)
    update_parser.add_argument(
        "--force-config",
        action="store_true",
        help="replace local config.yaml instead of preserving it",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        catalog = load_catalog()
        if args.command == "list":
            print_catalog(catalog, args.category)
            return 0
        if args.command == "search":
            matches = search_catalog(catalog, " ".join(args.query), args.category)
            if not matches:
                print("No matching profiles.")
                return 1
            for profile in matches:
                print(f"{profile['slug']:<24} {profile['name']} - {profile['description']}")
            return 0
        if args.command == "show":
            show_profile(catalog, args.profile)
            return 0
        if args.command == "install":
            return install(args, catalog)
        if args.command == "update":
            return update(args, catalog)
        raise AssertionError(args.command)
    except CollectionError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
