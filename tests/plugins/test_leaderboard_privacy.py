"""Golden privacy test for the team leaderboard egress surface.

The whole point of the achievements plugin is that it does not send session
history anywhere. The leaderboard adds a *narrow, aggregate-only* egress. This
test pins that surface: it asserts the exact set of keys that
``build_leaderboard_profile`` emits, and — crucially — that no session-derived
content (titles, ids, file paths, evidence, raw metrics) can leak through even
when the achievement records handed in are stuffed full of it.

If a future change adds a field that carries content, this test fails closed.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

PLUGIN_API_PATH = (
    Path(__file__).resolve().parents[2]
    / "plugins" / "fabric-achievements" / "dashboard" / "plugin_api.py"
)

spec = importlib.util.spec_from_file_location("plugin_api_privacy", PLUGIN_API_PATH)
plugin_api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plugin_api)


# The complete, frozen set of keys allowed to leave the machine. Adding a key
# here is a deliberate act that must be reviewed against the privacy promise.
EXPECTED_PROFILE_KEYS = frozenset({
    "display_name",
    "score",
    "unlocked_count",
    "discovered_count",
    "secret_count",
    "total_count",
    "tier_counts",
    "highest_tier",
    "category_counts",
    "top_achievements",
    "generated_at",
})

# The only keys allowed inside a top_achievements entry — all static catalogue
# metadata, never session-derived.
EXPECTED_TOP_KEYS = frozenset({"id", "name", "tier", "category", "icon"})


def test_profile_key_set_is_frozen():
    profile = plugin_api.build_leaderboard_profile([], "Someone")
    assert set(profile.keys()) == EXPECTED_PROFILE_KEYS


def test_no_session_content_leaks_even_when_records_carry_it():
    # Achievement records as they exist AFTER evaluation can carry evidence
    # (session id + title), unlocked_at, raw progress values, etc. None of that
    # may appear in the published profile.
    leaky_records = [
        {
            "id": "let_him_cook",
            "name": "Let Him Cook",
            "tier": "Gold",
            "category": "Agent Autonomy",
            "icon": "flame",
            "unlocked": True,
            "state": "unlocked",
            # --- everything below must NOT leak ---
            "evidence": {
                "session_id": "sess-SUPER-SECRET",
                "title": "Fixing /home/user/private/passwords.py",
                "value": 4242,
            },
            "unlocked_at": 1699999999,
            "progress": 999999,
            "next_threshold": 1000000,
            "description": "internal note: client ACME confidential",
            "criteria": "raw metric leak: total_errors=31337",
        },
        {
            "id": "night_shift_operator",
            "name": "Night Shift Operator",
            "tier": "Silver",
            "category": "Lifestyle",
            "icon": "moon",
            "unlocked": True,
            "state": "unlocked",
            "evidence": {"session_id": "sess-2", "title": "/mnt/secrets/keys.env"},
        },
    ]
    profile = plugin_api.build_leaderboard_profile(leaky_records, "Channa")

    # Structural guarantees.
    assert set(profile.keys()) == EXPECTED_PROFILE_KEYS
    for entry in profile["top_achievements"]:
        assert set(entry.keys()) == EXPECTED_TOP_KEYS

    # Content guarantees: serialize the whole thing and assert no leaked token
    # appears anywhere.
    blob = json.dumps(profile)
    for forbidden in [
        "sess-SUPER-SECRET",
        "sess-2",
        "passwords.py",
        "/home/user/private",
        "/mnt/secrets",
        "keys.env",
        "ACME confidential",
        "total_errors",
        "31337",
        "1699999999",  # unlocked_at
        "evidence",
        "unlocked_at",
        "next_threshold",
        "criteria",
        "description",
    ]:
        assert forbidden not in blob, f"leaked {forbidden!r} into published profile"

    # Sanity: the aggregate numbers are still correct.
    assert profile["unlocked_count"] == 2
    assert profile["display_name"] == "Channa"


def test_top_achievements_only_carry_catalogue_metadata():
    records = [
        {"id": "x", "name": "X", "tier": "Olympian", "category": "Cat", "icon": "flame",
         "unlocked": True, "state": "unlocked", "evidence": {"title": "leak-here"}},
    ]
    top = plugin_api.build_leaderboard_profile(records, "Me")["top_achievements"]
    assert len(top) == 1
    assert "leak-here" not in json.dumps(top)
    assert top[0] == {"id": "x", "name": "X", "tier": "Olympian", "category": "Cat", "icon": "flame"}
