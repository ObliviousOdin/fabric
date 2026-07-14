"""Integration contract for the bundled Team Pages dashboard plugin."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse


REPO_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_DIR = REPO_ROOT / "plugins" / "team-pages" / "dashboard"
DIST_DIR = DASHBOARD_DIR / "dist"


def test_team_pages_manifest_registers_a_fabric_team_route() -> None:
    manifest = json.loads((DASHBOARD_DIR / "manifest.json").read_text())

    assert manifest["name"] == "team-pages"
    assert manifest["label"] == "Team"
    assert manifest["icon"] == "Users"
    assert manifest["tab"] == {
        "path": "/team",
        "layout": "workspace",
        "position": "after:work",
    }
    assert manifest["entry"] == "dist/index.js"
    assert manifest["css"] == "dist/style.css"
    assert "api" not in manifest, "Team Pages should stay inside the existing dashboard runtime"


def test_starter_pages_cover_the_declarative_block_contract() -> None:
    payload = json.loads((DIST_DIR / "pages.default.json").read_text())
    pages = payload["pages"]

    assert payload["version"] == 1
    assert len(pages) >= 2, "The page picker needs more than one useful starter page"
    assert len({page["id"] for page in pages}) == len(pages)

    blocks = [block for page in pages for block in page["blocks"]]
    block_types = {block["type"] for block in blocks}
    assert {
        "title",
        "text",
        "markdown",
        "links",
        "kpi",
        "table",
        "status",
    } <= block_types
    assert len({block["id"] for block in blocks}) == len(blocks)

    for block in blocks:
        if block["type"] != "links":
            continue
        for item in block["items"]:
            href = item["href"]
            parsed = urlparse(href)
            assert href.startswith("/") or parsed.scheme in {"http", "https", "mailto"}

    visible_copy = json.dumps(payload).lower()
    assert "hermes" not in visible_copy
    assert '"href": "/work"' in visible_copy
    assert '"href": "/kanban"' not in visible_copy


def test_bundle_uses_config_and_sanctioned_plugin_sdk_surfaces() -> None:
    bundle = (DIST_DIR / "index.js").read_text()

    assert 'registry.register("team-pages", TeamPages)' in bundle
    assert "window.__FABRIC_PLUGIN_SDK__" in bundle
    assert "window.__FABRIC_PLUGINS__" in bundle
    assert "SDK.api.getConfig()" in bundle
    assert "SDK.authedFetch(DEFAULT_PAGES_URL)" in bundle
    assert "dashboard.team_pages" in bundle
    assert "dangerouslySetInnerHTML" not in bundle
    assert ".innerHTML" not in bundle
    assert "document.write" not in bundle


def test_styles_follow_dashboard_tokens_and_accessibility_basics() -> None:
    stylesheet = (DIST_DIR / "style.css").read_text()

    assert "--theme-font-sans" in stylesheet
    assert "var(--color-foreground)" in stylesheet
    assert "var(--color-border)" in stylesheet
    assert "var(--color-ring)" in stylesheet
    assert ":focus-visible" in stylesheet
    assert "min-height: 2.75rem" in stylesheet
    assert "prefers-reduced-motion: reduce" in stylesheet
    assert "box-shadow" not in stylesheet, "Team Pages should remain flat, not ornamental"
