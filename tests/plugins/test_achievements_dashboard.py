"""Dashboard integration contracts for the bundled Fabric Journey page."""

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
    assert manifest["version"] == "2.0.0"
    assert "local Fabric Journey" in manifest["description"]
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


def test_bundle_uses_only_the_authenticated_host_sdk_and_host_page_shell() -> None:
    bundle = (DIST_DIR / "index.js").read_text()

    assert 'registry.register("achievements", AchievementsPage)' in bundle
    assert "window.__FABRIC_PLUGIN_SDK__" in bundle
    assert "window.__FABRIC_PLUGINS__" in bundle
    assert "SDK.fetchJSON" in bundle
    assert 'h("main"' not in bundle
    assert 'h("h1"' not in bundle
    assert "ReactDOM.createRoot" not in bundle
    assert "__DASHBOARD_AUTH_TOKEN__" not in bundle
    assert "dangerouslySetInnerHTML" not in bundle
    assert ".innerHTML" not in bundle
    assert re.search(r"(?<![\w.])fetch\s*\(", bundle) is None
    assert "new WebSocket" not in bundle
    assert "window.confirm" not in bundle
    assert "props.onImport(review.raw)" in bundle
    assert "body: raw" in bundle
    assert "maxLength: 40" in bundle


def test_bundle_implements_journey_routes_actions_and_honest_attestation() -> None:
    bundle = (DIST_DIR / "index.js").read_text()

    for endpoint in (
        'API + "/journey"',
        'API + "/settings"',
        'API + "/activity/export"',
        'API + "/activity"',
        'API + "/leaderboard"',
        'API + "/leaderboard/import"',
    ):
        assert endpoint in bundle
    assert '"/journey/refresh"' in bundle
    assert '"/challenges/" + kind + "/reroll"' in bundle
    assert '"Swap quest"' in bundle
    assert '"Swap expedition"' in bundle

    assert 'LINKEDIN_QUEST_ID = "content.linkedin_launch"' in bundle
    assert '"0 rank XP"' in bundle
    assert '"Mark as published"' in bundle
    assert '"Confirm self-attested publish"' in bundle
    assert '"/attest"' in bundle
    assert 'JSON.stringify({ days: 7 })' in bundle
    assert 'JSON.stringify({ confirm: true })' in bundle
    assert "preferred_outcome" in bundle
    assert "tracking_enabled" in bundle
    assert "active_time_enabled" in bundle
    assert "celebration_mode" in bundle
    assert 'return "/workspace/chat?" + params.toString()' in bundle
    assert "fresh: createFreshId()" in bundle
    assert "draft:" in bundle

    for route_key in ("view", "path", "status", "board", "focus"):
        assert f'params.get("{route_key}")' in bundle
    assert 'params.delete("tab")' in bundle
    assert "location.hash" in bundle
    assert "prefers-reduced-motion: reduce" in bundle
    assert 'behavior: reduceMotion ? "auto" : "smooth"' in bundle


def test_bundle_uses_only_icons_exposed_by_the_plugin_sdk() -> None:
    bundle = (DIST_DIR / "index.js").read_text()
    exposed = {
        "AlertTriangle",
        "ArrowRight",
        "Bot",
        "CheckCircle2",
        "ChevronDown",
        "ChevronRight",
        "Circle",
        "Clock3",
        "ExternalLink",
        "FileText",
        "Film",
        "Filter",
        "GitBranch",
        "HelpCircle",
        "LayoutGrid",
        "ListTree",
        "Maximize2",
        "PanelRightClose",
        "Pause",
        "Play",
        "Plus",
        "RotateCcw",
        "Search",
        "Target",
        "Workflow",
        "X",
    }
    literal_icons = set(re.findall(r'icon\("([A-Za-z0-9]+)"', bundle))

    assert literal_icons
    assert literal_icons <= exposed


def test_styles_follow_host_tokens_accessibility_and_responsive_contracts() -> None:
    stylesheet = (DIST_DIR / "style.css").read_text()

    assert "--theme-font-sans" in stylesheet
    assert "var(--color-foreground)" in stylesheet
    assert "var(--color-border)" in stylesheet
    assert "var(--color-ring)" in stylesheet
    assert ":focus-visible" in stylesheet
    assert "min-height: 2.75rem" in stylesheet
    assert "prefers-reduced-motion: reduce" in stylesheet
    assert "linear-gradient" not in stylesheet
    assert re.search(r"#[0-9a-fA-F]{3,8}\b", stylesheet) is None
    rem_sizes = [
        float(value)
        for value in re.findall(r"font-size:\s*([0-9.]+)rem", stylesheet)
    ]
    assert rem_sizes and min(rem_sizes) >= 0.75

    root_rule = re.search(r"\.fabric-achievements\s*\{(?P<body>.*?)\}", stylesheet, re.S)
    assert root_rule is not None
    assert "overflow-y" not in root_rule.group("body")
    assert re.search(r"(^|\s)height\s*:", root_rule.group("body")) is None

    assert ".fabric-achievements-path-layout" in stylesheet
    assert ".fabric-achievements-profile-record" in stylesheet
    assert ".fabric-achievements-activity-reflection" in stylesheet
    assert "@media (max-width: 820px)" in stylesheet
    assert "@media (max-width: 680px)" in stylesheet


def test_readme_documents_privacy_fallback_and_board_boundaries() -> None:
    readme = (DASHBOARD_DIR.parent / "README.md").read_text()
    normalized = " ".join(readme.split())

    assert "default-on and device-local" in normalized
    assert "does not record prompts" in normalized
    assert "0 rank XP" in normalized
    assert "Legacy local snapshots" in normalized
    assert "Self-reported" in normalized or "self-reported" in normalized
    assert "DELETE /api/plugins/achievements/activity" in normalized
