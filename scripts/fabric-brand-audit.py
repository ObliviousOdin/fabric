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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("public",), default="public")
    parser.parse_args()

    issues = [*audit_resolved(), *audit_native_guides()]
    if issues:
        print("FABRIC BRAND AUDIT FAILED:")
        for issue in issues:
            print(f"  - {issue}")
        return 1

    print("fabric-brand-audit: OK (public identity and first-run guides)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
