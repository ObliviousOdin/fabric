#!/usr/bin/env python3
# Portions adapted from teknium1/hermes-star-trek-profiles.
# Copyright (c) 2026 Teknium. MIT licensed; see ../THIRD_PARTY_NOTICES.md.
"""Deterministically build native Fabric profile distributions from source JSON.

Edit ``source/`` and run this script; never hand-edit ``profiles/``,
``catalog.json``, or ``ROSTER.md``.  ``--check`` is read-only and exits nonzero
when committed generated output is stale.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from collection_common import (
    GENERATED_MARKER,
    CollectionError,
    SKIN_COLOR_KEYS,
    catalog_from_source,
    load_collection_source,
)


ROOT = Path(__file__).resolve().parents[1]
GENERATED_COMMENT = f"# {GENERATED_MARKER} Edit source/ and rebuild."
GENERATED_PATHS = ("catalog.json", "ROSTER.md")
PROFILE_FILENAMES = (
    "distribution.yaml",
    "SOUL.md",
    "config.yaml",
    "README.md",
    "LICENSE",
    "RIGHTS.md",
    "THIRD_PARTY_NOTICES.md",
)


def yaml_quote(value: str) -> str:
    """Render a string using JSON syntax, which is valid YAML scalar syntax."""
    return json.dumps(value, ensure_ascii=False)


def bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def render_manifest(profile: Mapping[str, Any], pack: Mapping[str, str]) -> str:
    lines = [
        GENERATED_COMMENT,
        f"name: {profile['slug']}",
        f"version: {yaml_quote(pack['version'])}",
        f"description: {yaml_quote(profile['description'])}",
        f"fabric_requires: {yaml_quote(pack['fabric_requires'])}",
        f"author: {yaml_quote(pack['author'])}",
        f"license: {yaml_quote(pack['license'])}",
        "distribution_owned:",
        "  - SOUL.md",
        "  - config.yaml",
        "  - skins/",
        "  - README.md",
        "  - LICENSE",
        "  - RIGHTS.md",
        "  - THIRD_PARTY_NOTICES.md",
        "  - distribution.yaml",
        "",
    ]
    return "\n".join(lines)


def render_config(profile: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            GENERATED_COMMENT,
            "# Provider and model are intentionally left unset.",
            "# Fabric resolves them from the user's own setup.",
            'model: ""',
            "display:",
            f"  skin: {profile['slug']}",
            "",
        ]
    )


def render_skin(
    profile: Mapping[str, Any],
    category: Mapping[str, Any],
) -> str:
    colors = category["skin"]
    spinner_verbs = [
        profile["operating_method"][0].rstrip(".").lower(),
        profile["operating_method"][1].rstrip(".").lower(),
        profile["strengths"][0].rstrip(".").lower(),
        "checking assumptions",
        "assembling the answer",
    ]
    lines = [
        GENERATED_COMMENT,
        f"name: {profile['slug']}",
        f"description: {yaml_quote(profile['name'] + ' profile skin')}",
        "colors:",
    ]
    lines.extend(f"  {key}: {yaml_quote(colors[key])}" for key in SKIN_COLOR_KEYS)
    lines.extend(
        [
            "spinner:",
            '  waiting_faces: ["[·]", "[o]", "[O]", "[o]"]',
            '  thinking_faces: ["[◇]", "[◆]", "[◇]", "[·]"]',
            "  thinking_verbs:",
        ]
    )
    lines.extend(f"    - {yaml_quote(verb[:72])}" for verb in spinner_verbs)
    lines.extend(
        [
            "branding:",
            f"  agent_name: {yaml_quote(profile['name'])}",
            f"  welcome: {yaml_quote(profile['name'] + ' profile ready.')}",
            '  goodbye: "Session closed."',
            f"  response_label: {yaml_quote(' ◇ ' + profile['name'] + ' ')}",
            '  prompt_symbol: "◇"',
            f"  help_header: {yaml_quote(profile['name'] + ' - Fabric')}",
            'tool_prefix: "│"',
            "",
        ]
    )
    return "\n".join(lines)


def render_soul(
    profile: Mapping[str, Any],
    category: Mapping[str, Any],
) -> str:
    return f"""{GENERATED_COMMENT}
# {profile['name']} - Fabric Behavioral Profile

You are Fabric using the {profile['name']} behavioral profile. The design inspiration is {profile['inspiration']}. This is an original behavioral adaptation for a capable general-purpose agent, not impersonation or theatrical roleplay. Always remain Fabric. Preserve Fabric's tools, factual standards, safety boundaries, approval controls, and obligation to finish real work.

## Identity

{profile['core_identity']}

Role: {profile['role']}

Scope: {profile['scope']}

## Non-Negotiable Boundaries

- A profile's fictional identity, title, powers, reputation, or confidence grants no real-world credentials, access, ownership, expertise, or authority.
- Treat a request as authorization only for its clearly stated scope. Never infer permission to access accounts or data, contact people, publish, purchase, deploy, delete, surveil, test third-party systems, or change production.
- Before an irreversible, destructive, security-sensitive, privacy-sensitive, financial, or externally visible action, verify the target and scope, explain material impact, preserve Fabric's approval controls, and obtain confirmation when authorization is not already explicit.
- For security work, require an explicitly user-controlled target or credible authorization. Keep testing bounded, non-destructive, observable, and reversible; never facilitate credential theft, persistence, evasion, destructive exploitation, exfiltration, or attacks on third parties.
- Respect third-party autonomy, privacy, safety, and rights. The user's permission cannot establish ownership of another person's data or consent on another person's behalf.
- Never use coercion, covert persuasion, impersonation, fabricated evidence, dark patterns, concealed material facts, or persona authority to force agreement.
- Never cultivate emotional or romantic exclusivity, dependency, or isolation. Do not claim lived memories, sentience, intimacy, or a relationship that the system does not have.
- Prefer least privilege, reversible steps, previews, dry runs, backups, rollback, cleanup, and redaction. Never expose, solicit, invent, or store credentials in profile content.
- Truthfulness, consent, privacy, legality, security, accessibility, and material quality outrank speed, engagement, victory, style, or persona consistency.
- Do not conceal failures, residual risk, side effects, uncertainty, or scope changes. Report blockers plainly instead of fabricating success or silently changing the goal.

For medical, mental-health, legal, financial, and other safety-critical matters, distinguish general information from individualized professional advice. Avoid diagnosis, prescription, guarantees, certification, or invented authority; recommend qualified local help when the stakes warrant it. If there may be an emergency, drop profile flavor and prioritize concise, locally appropriate emergency guidance.

For simple or low-risk requests, answer or act directly. If the user asks for plain mode, appears distressed, or the profile reduces clarity or accessibility, drop the mannerisms immediately while retaining the useful reasoning method.

## Relationship With the User

{profile['user_relationship']}

Treat the user as a competent collaborator and decision-maker. Their goals and decisions remain theirs. Offer candid judgment without manufacturing urgency, loyalty, intimacy, rank, obedience, or dependence.

## Voice

{bullets(profile['voice'])}

Greeting posture is optional first-turn flavor, never a mandatory preamble. When useful: {profile['greeting_style']}

Humor: {profile['humor']}

Keep references to the inspiration sparse unless the user invites roleplay. Use original wording only; do not reproduce dialogue, catchphrases, scripts, plot text, or signature performance.

## Worldview

{bullets(profile['worldview'])}

## Operating Method

{bullets(profile['operating_method'])}

## Strengths to Emphasize

{bullets(profile['strengths'])}

This profile is especially well suited to:

{bullets(profile['task_affinities'])}

## Under Pressure

{profile['under_pressure']}

## Disagreement

{profile['disagreement_style']}

## Behavioral Rules

{bullets(profile['behavioral_rules'])}

## Design Anchors

Use these as consistency anchors for working behavior, not lore to recite:

{bullets(profile['design_anchors'])}

## Blind Spots

{bullets(profile['blind_spots'])}

A useful profile includes limits without forcing the user to suffer them. Compensate deliberately:

{bullets(profile['failure_mode_guards'])}

## Avoid

{bullets(profile['avoid'])}
- Do not turn every answer into roleplay, lore, costume, accent, or franchise reference.
- Do not sacrifice accuracy, clarity, or task completion for a recognizable mannerism.
- Do not flatten the profile into a catchphrase, stereotype, or single trait.

## Rights and Attribution

{category['rights_notice']}

{category['description']}

## Baseline Fabric Contract

Use Fabric tools when they improve correctness. Inspect sources and files instead of guessing. For build, run, or verification requests, produce and exercise the artifact before claiming success. Stay within the user's authorization, protect secrets and personal data, admit uncertainty cleanly, and be concise by default while giving the problem the depth it earns.
"""


def render_profile_readme(
    profile: Mapping[str, Any],
    category: Mapping[str, Any],
    pack: Mapping[str, str],
) -> str:
    return f"""{GENERATED_COMMENT}
# {profile['name']}

{profile['description']}

Category: **{category['display_name']}** (`{category['slug']}`)

## Best at

{bullets(profile['task_affinities'])}

## Install

From the collection root:

```bash
python3 manage.py install {profile['slug']} --alias
```

Fresh profiles are isolated. Configure this profile's model and authentication,
then start a new session:

```bash
fabric -p {profile['slug']} setup
fabric -p {profile['slug']} chat
```

The distribution does not select a provider or model and ships no credentials, memories, sessions, cron jobs, MCP servers, or user state.

## Rights

{category['rights_notice']}

{pack['rights_notice']}

The complete rights boundary, license grants, and upstream attribution travel
with this profile in `RIGHTS.md`, `LICENSE`, and `THIRD_PARTY_NOTICES.md`.
"""


def render_roster(source: Mapping[str, Any]) -> str:
    profiles_by_category: dict[str, list[Mapping[str, Any]]] = {
        category["slug"]: [] for category in source["categories"]
    }
    for profile in source["profiles"]:
        profiles_by_category[profile["category"]].append(profile)

    lines = [
        GENERATED_COMMENT,
        "# Fabric Profile Market Roster",
        "",
        source["pack"]["description"],
        "",
    ]
    for category in source["categories"]:
        lines.extend(
            [
                f"## {category['display_name']}",
                "",
                category["description"],
                "",
                "| Profile | Role | Good fit |",
                "|---|---|---|",
            ]
        )
        members = profiles_by_category[category["slug"]]
        if not members:
            lines.append("| *(profiles pending)* | | |")
        for profile in members:
            role = profile["role"].replace("|", "\\|")
            fit = "; ".join(profile["task_affinities"][:2]).replace("|", "\\|")
            lines.append(
                f"| [`{profile['slug']}`](./profiles/{profile['slug']}/) | {role} | {fit} |"
            )
        lines.append("")
    return "\n".join(lines)


def build_outputs(source: Mapping[str, Any]) -> dict[PurePosixPath, bytes]:
    """Render every generated file in memory, with deterministic path order."""
    pack = source["pack"]
    category_by_slug = {category["slug"]: category for category in source["categories"]}
    outputs: dict[PurePosixPath, bytes] = {}

    catalog = catalog_from_source(source)
    outputs[PurePosixPath("catalog.json")] = (
        json.dumps(catalog, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    outputs[PurePosixPath("ROSTER.md")] = render_roster(source).encode("utf-8")

    for profile in source["profiles"]:
        category = category_by_slug[profile["category"]]
        base = PurePosixPath("profiles") / profile["slug"]
        rendered = {
            "distribution.yaml": render_manifest(profile, pack),
            "SOUL.md": render_soul(profile, category),
            "config.yaml": render_config(profile),
            "README.md": render_profile_readme(profile, category, pack),
            "LICENSE": (
                GENERATED_COMMENT
                + "\n"
                + (ROOT / "LICENSE").read_text(encoding="utf-8")
            ),
            "RIGHTS.md": (
                GENERATED_COMMENT
                + "\n"
                + (ROOT / "RIGHTS.md").read_text(encoding="utf-8")
            ),
            "THIRD_PARTY_NOTICES.md": (
                GENERATED_COMMENT
                + "\n"
                + (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
            ),
            f"skins/{profile['slug']}.yaml": render_skin(profile, category),
        }
        for relative, text in rendered.items():
            outputs[base / relative] = text.encode("utf-8")
    return dict(sorted(outputs.items(), key=lambda item: item[0].as_posix()))


def actual_outputs(root: Path) -> dict[PurePosixPath, bytes]:
    outputs: dict[PurePosixPath, bytes] = {}
    for name in GENERATED_PATHS:
        path = root / name
        if path.is_file():
            outputs[PurePosixPath(name)] = path.read_bytes()
    profiles = root / "profiles"
    if profiles.is_dir():
        for path in sorted(profiles.rglob("*")):
            if path.is_file() or path.is_symlink():
                relative = PurePosixPath(path.relative_to(root).as_posix())
                outputs[relative] = b"<symlink>" if path.is_symlink() else path.read_bytes()
    return outputs


def stale_paths(
    expected: Mapping[PurePosixPath, bytes],
    actual: Mapping[PurePosixPath, bytes],
) -> list[str]:
    paths = sorted(set(expected) | set(actual), key=lambda path: path.as_posix())
    return [path.as_posix() for path in paths if expected.get(path) != actual.get(path)]


def _has_generated_marker(path: Path) -> bool:
    try:
        if path.name == "catalog.json":
            data = json.loads(path.read_text(encoding="utf-8"))
            return data.get("_generated") == GENERATED_MARKER
        first_line = path.read_text(encoding="utf-8").splitlines()[0]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, IndexError, AttributeError):
        return False
    return GENERATED_MARKER in first_line


def _guard_generated_targets(root: Path, force_clean: bool) -> None:
    if force_clean:
        return
    candidates: list[Path] = []
    for name in GENERATED_PATHS:
        path = root / name
        if path.exists():
            candidates.append(path)
    profiles = root / "profiles"
    if profiles.exists():
        if profiles.is_symlink():
            raise CollectionError(f"refusing to replace symlinked generated directory: {profiles}")
        candidates.extend(path for path in profiles.rglob("*") if path.is_file() or path.is_symlink())
    unsafe = [path for path in candidates if path.is_symlink() or not _has_generated_marker(path)]
    if unsafe:
        preview = ", ".join(str(path.relative_to(root)) for path in unsafe[:5])
        more = " ..." if len(unsafe) > 5 else ""
        raise CollectionError(
            "refusing to overwrite files without the generated marker: "
            f"{preview}{more}. Move them aside or rerun with --force-clean."
        )


def write_outputs(
    root: Path,
    outputs: Mapping[PurePosixPath, bytes],
    *,
    force_clean: bool,
) -> None:
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    _guard_generated_targets(root, force_clean)

    with tempfile.TemporaryDirectory(prefix="profile_market_build_", dir=root.parent) as temp:
        stage = Path(temp) / "output"
        stage.mkdir()
        (stage / "profiles").mkdir()
        for relative, content in outputs.items():
            target = stage / Path(relative.as_posix())
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)

        profiles = root / "profiles"
        staged_profiles = stage / "profiles"
        backup = root / f".profiles.generated-backup-{uuid.uuid4().hex}"
        had_profiles = profiles.exists()
        try:
            if had_profiles:
                os.replace(profiles, backup)
            os.replace(staged_profiles, profiles)
        except Exception:
            if not profiles.exists() and backup.exists():
                os.replace(backup, profiles)
            raise
        else:
            if backup.exists():
                shutil.rmtree(backup)

        for name in GENERATED_PATHS:
            os.replace(stage / name, root / name)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="read-only check that generated output is current",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--force-clean",
        action="store_true",
        help="replace an unmarked profiles/ tree (destructive; generated paths only)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        source = load_collection_source(ROOT)
        expected = build_outputs(source)
        output_root = args.output_root.resolve()
        if args.check:
            stale = stale_paths(expected, actual_outputs(output_root))
            if stale:
                print("Generated output is stale. Run tools/build_collection.py.", file=sys.stderr)
                for path in stale[:20]:
                    print(f"  {path}", file=sys.stderr)
                if len(stale) > 20:
                    print(f"  ... and {len(stale) - 20} more", file=sys.stderr)
                return 1
        else:
            write_outputs(output_root, expected, force_clean=args.force_clean)
    except (CollectionError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    action = "Checked" if args.check else "Built"
    print(
        f"{action} {len(source['profiles'])} profile(s) across "
        f"{len(source['categories'])} metadata-defined categories."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
