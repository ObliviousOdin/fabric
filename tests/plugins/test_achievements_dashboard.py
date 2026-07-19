"""Dashboard integration contracts for the bundled Achievements page."""

from __future__ import annotations

import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_DIR = REPO_ROOT / "plugins" / "achievements" / "dashboard"
DIST_DIR = DASHBOARD_DIR / "dist"


def test_manifest_keeps_achievements_discoverable_in_workspace() -> None:
    manifest = json.loads((DASHBOARD_DIR / "manifest.json").read_text())

    assert manifest["name"] == "achievements"
    assert manifest["label"] == "Achievements"
    assert manifest["icon"] == "Star"
    assert manifest["tab"] == {
        "path": "/workspace/achievements",
        "aliases": ["/achievements"],
        "layout": "page",
        "position": "after:activity",
    }
    assert manifest["entry"] == "dist/index.js"
    assert manifest["css"] == "dist/style.css"
    assert manifest["api"] == "plugin_api.py"


def test_current_dashboard_loader_discovers_the_bundled_page() -> None:
    from fabric_cli import web_server

    plugins = web_server._discover_dashboard_plugins()
    achievement = next(plugin for plugin in plugins if plugin["name"] == "achievements")

    assert achievement["source"] == "bundled"
    assert achievement["has_api"] is True
    assert achievement["tab"]["path"] == "/workspace/achievements"
    assert achievement["tab"]["position"] == "after:activity"


def test_bundle_uses_only_the_authenticated_host_sdk() -> None:
    bundle = (DIST_DIR / "index.js").read_text()

    assert 'registry.register("achievements", AchievementsPage)' in bundle
    assert "window.__FABRIC_PLUGIN_SDK__" in bundle
    assert "window.__FABRIC_PLUGINS__" in bundle
    assert "SDK.fetchJSON" in bundle
    assert "ReactDOM.createRoot" not in bundle
    assert "__DASHBOARD_AUTH_TOKEN__" not in bundle
    assert "dangerouslySetInnerHTML" not in bundle
    assert ".innerHTML" not in bundle
    assert re.search(r"(?<![\w.])fetch\s*\(", bundle) is None
    assert "new WebSocket" not in bundle
    assert "props.onImport(input)" in bundle
    assert "body: rawCard" in bundle
    assert 'maxLength: 40' in bundle


def test_styles_follow_host_tokens_and_accessibility_basics() -> None:
    stylesheet = (DIST_DIR / "style.css").read_text()

    assert "--theme-font-sans" in stylesheet
    assert "var(--color-foreground)" in stylesheet
    assert "var(--color-border)" in stylesheet
    assert "var(--color-ring)" in stylesheet
    assert ":focus-visible" in stylesheet
    assert "min-height: 2.75rem" in stylesheet
    assert "prefers-reduced-motion: reduce" in stylesheet
    assert re.search(r"#[0-9a-fA-F]{3,8}\b", stylesheet) is None
