#!/usr/bin/env python3
"""Audit Fabric's public product identity.

This is the fast, focused brand check.  The repository-wide publication gate
lives in ``scripts/public-release-audit.py``.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_REPOSITORY = "https://github.com/ObliviousOdin/fabric"
CANONICAL_DOCS = "https://obliviousodin.github.io/fabric/"

NATIVE_GUIDE_PATHS = (
    "website/docs/getting-started/quickstart.md",
    "website/docs/getting-started/repair.md",
    "website/docs/guides/chatgpt-codex-subscription.md",
    "website/docs/guides/local-ollama-setup.md",
    "website/docs/guides/oauth-over-ssh.md",
    "website/docs/guides/xai-grok-oauth.md",
)

PUBLIC_SITE_DISCOVERY_PATHS = (
    "website/docs/index.mdx",
    "website/docs/developer-guide/architecture.md",
    "website/docs/getting-started/installation.md",
    "website/docs/getting-started/quickstart.md",
    "website/docs/integrations/index.md",
    "website/docs/reference/index.md",
    "website/docs/user-guide/index.md",
    "website/docusaurus.config.ts",
    "website/scripts/generate-llms-txt.py",
    "website/sidebars.ts",
    "website/src/components/Homepage/index.tsx",
    "website/src/pages/index.tsx",
    "website/src/pages/skills/index.tsx",
)

BUILT_PUBLIC_DISCOVERY_PATHS = (
    "index.html",
    "developer-guide/architecture/index.html",
    "docs/index.html",
    "getting-started/installation/index.html",
    "getting-started/quickstart/index.html",
    "integrations/index.html",
    "llms.txt",
    "reference/index.html",
    "skills/index.html",
    "sitemap.xml",
    "user-guide/index.html",
)

BUILT_POSITIONING_ARTIFACT_PATHS = (
    "api/skills-index.json",
    "api/skills.json",
    "llms-full.txt",
    "search-index.json",
)

POSITIONING_SOURCE_ROOTS = (
    "apps/desktop/src",
    "fabric_cli/tips.py",
    "web/src",
    "website/docs",
    "website/src",
)

PUBLIC_DISCOVERY_EXACT_ALLOWLIST = {
    "website/docusaurus.config.ts": (
        "/integrations/nous-portal",
        "/guides/run-fabric-with-nous-portal",
        "/guides/run-nemotron-3-ultra-free",
    ),
}

_FENCED_BLOCK_RE = re.compile(r"(?ms)^```[^\n]*\n(.*?)^```")
_LEGACY_COMMAND_LINE_RE = re.compile(
    r"^[ \t]*(?:[$>]\s*)?hermes(?:[ \t]|$)", re.IGNORECASE
)
_LEGACY_INLINE_COMMAND_RE = re.compile(
    r"`hermes(?:\s+(?:setup|install|doctor|status|chat|gateway|dashboard|"
    r"serve|model|skills|plugins|config|auth|update|logs|cron)\b|`)",
    re.IGNORECASE,
)
_LEGACY_PRODUCT_RE = re.compile(
    r"\bHermes\s+(?:Agent|Desktop|CLI|TUI|Gateway|Console|Dashboard|"
    r"installation|application)\b",
    re.IGNORECASE,
)
_LEGACY_REPOSITORY_RE = re.compile(
    r"(?:github\.com|raw\.githubusercontent\.com)/NousResearch/"
    r"(?:hermes-agent|fabric-agent)|github:NousResearch/(?:hermes-agent|fabric-agent)|"
    r"fabric-agent\.nousresearch\.com",
    re.IGNORECASE,
)
_HISTORICAL_PROVENANCE_URL_RE = re.compile(
    r"https://github\.com/NousResearch/hermes-agent/(?:issues|pull)/[0-9]+"
    r"(?=$|[\s\]\[(){}<>\"'`,.;:!?#])",
    re.IGNORECASE,
)
_PRIVATE_PRODUCT_IDENTITY = "Ra" + "bot"
_UPSTREAM_PRODUCT_IDENTITY_RE = re.compile(
    rf"(?<![A-Za-z0-9])(?:Nous(?:[\s_-]*(?:Portal|Research))?|"
    rf"Hermes(?:[\s_-]*Agent)?|{_PRIVATE_PRODUCT_IDENTITY}"
    rf"(?:[\s_-]*(?:Inc|Home))?)(?![A-Za-z0-9])|nousresearch",
    re.IGNORECASE,
)
_SENTENCE_GAP_180 = r"(?:(?!\r?\n[ \t]*\r?\n)[^.!?]){0,180}"
_SENTENCE_GAP_220 = r"(?:(?!\r?\n[ \t]*\r?\n)[^.!?]){0,220}"
_SENTENCE_GAP_260 = r"(?:(?!\r?\n[ \t]*\r?\n)[^.!?]){0,260}"
_MARKDOWN_INLINE_LINK_RE = re.compile(
    r"\[(?P<label>[^\]\r\n]+)\]\([^\r\n)]*\)"
)
_HTML_TAG_RE = re.compile(r"<[^>\r\n]+>")

_VENDOR_POSITIONING_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "upstream recommendation",
        re.compile(
            rf"(?:Nous(?:[\s_-]*(?:Portal|Research))?){_SENTENCE_GAP_180}"
            r"(?:recommended|fastest|easiest)\s+(?:way|path|provider|option)|"
            r"(?:recommended|fastest|easiest)\s+(?:way|path|provider|option)"
            rf"{_SENTENCE_GAP_180}Nous",
            re.IGNORECASE,
        ),
    ),
    (
        "upstream bundle promotion",
        re.compile(
            rf"(?:Nous(?:[\s_-]*(?:Portal|Research))?){_SENTENCE_GAP_220}"
            r"one\s+(?:subscription|login|bill)|"
            r"one\s+(?:subscription|login|bill)"
            rf"{_SENTENCE_GAP_220}Nous|"
            rf"If\s+you\s+only\s+have\s+time{_SENTENCE_GAP_220}Nous|"
            r"(?:paid\s+)?Nous\s+Portal\s+subscribers?"
            rf"{_SENTENCE_GAP_260}"
            r"(?:no|without)(?:\s+a)?\s+separate\s+API\s+keys?|"
            r"(?:Nous(?:[\s_-]*(?:Portal|Research))?)"
            rf"{_SENTENCE_GAP_220}\bsubscription\b{_SENTENCE_GAP_220}"
            r"(?:no|without)(?:\s+a)?\s+separate\s+API\s+keys?|"
            r"Nous\s+Portal\s+covers\s+both|Pay\s+Nous",
            re.IGNORECASE,
        ),
    ),
    (
        "upstream ownership wording",
        re.compile(
            r"Nous[-\s]+approved|Nous\s+staff|Fabric\s*\(\s*Nous\s*\)",
            re.IGNORECASE,
        ),
    ),
)


def audit_resolved() -> list[str]:
    """Verify the small dependency-free set of canonical brand helpers."""

    os.environ["FABRIC_BRAND"] = "1"
    sys.path.insert(0, str(ROOT))

    from fabric_cli.fabric_brand import (  # pylint: disable=import-outside-toplevel
        docs_url,
        messaging_bridge_description,
        product_label,
        resolve_agent_identity,
        resolve_default_soul,
        resolve_help_guidance,
        status_header,
        vendor_label,
        version_title,
    )

    samples = {
        "identity": resolve_agent_identity(),
        "help": resolve_help_guidance(),
        "soul": resolve_default_soul(),
        "product": product_label(),
        "vendor": vendor_label(),
        "version": version_title("1.0.0", "2026-01-01"),
        "bridge": messaging_bridge_description(),
        "status": status_header(),
        "docs": docs_url(),
    }

    issues: list[str] = []
    for name, value in samples.items():
        if name != "docs" and "Fabric" not in value:
            issues.append(f"{name}: missing Fabric identity: {value[:100]!r}")
        if _LEGACY_PRODUCT_RE.search(value):
            issues.append(f"{name}: legacy product identity: {value[:100]!r}")

    if samples["product"] != "Fabric":
        issues.append(f"product: expected 'Fabric', got {samples['product']!r}")
    if samples["vendor"] != "Fabric":
        issues.append(f"vendor: expected 'Fabric', got {samples['vendor']!r}")
    if not samples["docs"].startswith(CANONICAL_DOCS):
        issues.append(f"docs: expected canonical documentation URL, got {samples['docs']!r}")
    return issues


def audit_native_guides(
    root: Path = ROOT,
    paths: Iterable[str] = NATIVE_GUIDE_PATHS,
) -> list[str]:
    """Verify that first-run guides route users through Fabric."""

    issues: list[str] = []
    for relative in paths:
        path = root / relative
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            issues.append(f"{relative}: unavailable or invalid UTF-8 ({exc})")
            continue

        if "Fabric" not in text:
            issues.append(f"{relative}: missing Fabric identity")
        if not re.search(
            r"(?m)(?:`fabric(?:[ \t]|`)|^[ \t]*(?:[$>]\s*)?fabric(?:[ \t]|$))",
            text,
        ):
            issues.append(f"{relative}: missing a Fabric CLI command")

        for block in _FENCED_BLOCK_RE.finditer(text):
            for offset, line_text in enumerate(block.group(1).splitlines()):
                if not _LEGACY_COMMAND_LINE_RE.search(line_text):
                    continue
                line = text.count("\n", 0, block.start(1)) + offset + 1
                issues.append(f"{relative}:{line}: legacy CLI command")

        provenance_spans = [
            (match.start(), match.end())
            for match in _HISTORICAL_PROVENANCE_URL_RE.finditer(text)
        ]
        for label, pattern in (
            ("legacy inline CLI command", _LEGACY_INLINE_COMMAND_RE),
            ("legacy product identity", _LEGACY_PRODUCT_RE),
            ("legacy repository/docs route", _LEGACY_REPOSITORY_RE),
        ):
            for match in pattern.finditer(text):
                if label == "legacy repository/docs route" and any(
                    start <= match.start() and end >= match.end()
                    for start, end in provenance_spans
                ):
                    continue
                line = text.count("\n", 0, match.start()) + 1
                issues.append(f"{relative}:{line}: {label}")
    return issues


def _audit_public_discovery_files(
    root: Path,
    paths: Iterable[str],
    *,
    missing_is_error: bool,
) -> list[str]:
    """Reject upstream/private product identity on top-level public surfaces."""

    issues: list[str] = []
    for relative in paths:
        path = root / relative
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            if missing_is_error:
                issues.append(f"{relative}: required public discovery artifact is missing")
            continue
        except (OSError, UnicodeError) as exc:
            issues.append(f"{relative}: unavailable or invalid UTF-8 ({exc})")
            continue

        for allowed in PUBLIC_DISCOVERY_EXACT_ALLOWLIST.get(relative, ()):
            text = text.replace(allowed, " " * len(allowed))

        for match in _UPSTREAM_PRODUCT_IDENTITY_RE.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            issues.append(
                f"{relative}:{line}: upstream/private product identity on a public "
                "discovery surface"
            )
    return issues


def _normalize_positioning_markup(text: str) -> str:
    """Expose linked visible text while preserving offsets and line numbers."""

    def replace_markdown_link(match: re.Match[str]) -> str:
        label = match.group("label")
        prefix_length = match.start("label") - match.start()
        suffix_length = match.end() - match.end("label")
        return " " * prefix_length + label + " " * suffix_length

    normalized = _MARKDOWN_INLINE_LINK_RE.sub(replace_markdown_link, text)
    return _HTML_TAG_RE.sub(lambda match: " " * len(match.group(0)), normalized)


def _positioning_issues(relative: str, text: str) -> list[str]:
    """Return upstream endorsement/ownership findings for public copy."""

    issues: list[str] = []
    normalized = _normalize_positioning_markup(text)
    for label, pattern in _VENDOR_POSITIONING_PATTERNS:
        for match in pattern.finditer(normalized):
            line = normalized.count("\n", 0, match.start()) + 1
            issues.append(f"{relative}:{line}: {label} in public content")
    return issues


def audit_public_positioning_sources(root: Path = ROOT) -> list[str]:
    """Reject vendor-first positioning anywhere customer copy can be rendered."""

    issues: list[str] = []
    for relative_root in POSITIONING_SOURCE_ROOTS:
        source = root / relative_root
        if source.is_file():
            candidates = (source,)
        elif source.is_dir():
            candidates = (
                path
                for path in source.rglob("*")
                if path.is_file()
                and path.suffix.lower() in {".js", ".jsx", ".md", ".mdx", ".py", ".ts", ".tsx"}
            )
        else:
            continue

        for path in candidates:
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                relative = path.relative_to(root).as_posix()
                issues.append(f"{relative}: unavailable or invalid UTF-8 ({exc})")
                continue
            relative = path.relative_to(root).as_posix()
            issues.extend(_positioning_issues(relative, text))
    return issues


def audit_built_positioning_artifacts(build_dir: Path) -> list[str]:
    """Audit generated search, skills, and full-document exports."""

    issues: list[str] = []
    for relative in BUILT_POSITIONING_ARTIFACT_PATHS:
        path = build_dir / relative
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            issues.append(f"{relative}: required public positioning artifact is missing")
            continue
        except (OSError, UnicodeError) as exc:
            issues.append(f"{relative}: unavailable or invalid UTF-8 ({exc})")
            continue
        issues.extend(_positioning_issues(relative, text))
    return issues


def audit_public_site_sources(
    root: Path = ROOT,
    paths: Iterable[str] = PUBLIC_SITE_DISCOVERY_PATHS,
) -> list[str]:
    """Audit homepage, navigation, sidebar, and short-index source content."""

    return _audit_public_discovery_files(root, paths, missing_is_error=True)


def audit_built_public_site(build_dir: Path) -> list[str]:
    """Audit the rendered entry points that GitHub Pages actually publishes."""

    return _audit_public_discovery_files(
        build_dir,
        BUILT_PUBLIC_DISCOVERY_PATHS,
        missing_is_error=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("public",), default="public")
    parser.add_argument(
        "--build-dir",
        type=Path,
        help="also audit rendered GitHub Pages discovery artifacts",
    )
    args = parser.parse_args()

    issues = [
        *audit_resolved(),
        *audit_native_guides(),
        *audit_public_site_sources(),
        *audit_public_positioning_sources(),
    ]
    if args.build_dir is not None:
        build_dir = args.build_dir.resolve()
        issues.extend(audit_built_public_site(build_dir))
        issues.extend(audit_built_positioning_artifacts(build_dir))
    if issues:
        print("FABRIC BRAND AUDIT FAILED:")
        for issue in issues:
            print(f"  - {issue}")
        return 1

    print("fabric-brand-audit: OK (public identity, discovery surfaces, and first-run guides)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
