from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOKEN_PATH = ROOT / "apps" / "design-system" / "src" / "tokens" / "tokens.json"


def _luminance(hex_color: str) -> float:
    channels = [
        int(hex_color[index : index + 2], 16) / 255 for index in (1, 3, 5)
    ]
    linear = [
        channel / 12.92
        if channel <= 0.04045
        else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(first: str, second: str) -> float:
    light, dark = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def _resolve(tokens: dict[str, object], value: str) -> str:
    current: object = value
    seen: set[str] = set()
    while isinstance(current, str) and current.startswith("{"):
        assert current not in seen
        seen.add(current)
        node: object = tokens
        for part in current[1:-1].split("."):
            assert isinstance(node, dict)
            node = node[part]
        current = node
    assert isinstance(current, str)
    return current


def test_canonical_primary_and_font_policy() -> None:
    tokens = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))

    assert tokens["meta"]["canonicalPrimary"] == "#4628CC"
    assert tokens["color"]["primary"]["600"] == "#4628CC"
    assert tokens["typography"]["family"]["sans"].startswith("system-ui")
    assert "pending committed license" in tokens["meta"]["fontPolicy"]
    assert not list((TOKEN_PATH.parents[1] / "fonts").glob("*.woff*"))


def test_semantic_text_and_status_tokens_hold_wcag_aa() -> None:
    tokens = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))

    for appearance, semantic in tokens["semantic"].items():
        canvas = _resolve(tokens, semantic["canvas"])
        pairs = {
            "text": (semantic["text"], canvas),
            "textMuted": (semantic["textMuted"], canvas),
            "action": (semantic["action"], _resolve(tokens, semantic["actionForeground"])),
            "success": (semantic["success"], canvas),
            "warning": (semantic["warning"], canvas),
            "danger": (semantic["danger"], canvas),
        }
        for role, (foreground, background) in pairs.items():
            ratio = _contrast(
                _resolve(tokens, foreground),
                background,
            )
            assert ratio >= 4.5, f"{appearance}.{role} contrast is {ratio:.2f}:1"
