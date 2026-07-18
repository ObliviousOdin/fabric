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

import pytest

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

# Copied relay diagnostics are a separate, deliberately narrow egress surface.
# Keep this schema fail-closed: adding exception text, configuration, relay
# payloads, or credentials here must require an explicit privacy review.
EXPECTED_DIAGNOSTIC_KEYS = frozenset({
    "version",
    "state",
    "actor",
    "relay_host",
    "relay_port",
    "tailscale_required",
    "tailscale",
    "checks",
    "checked_at",
})
EXPECTED_DIAGNOSTIC_TAILSCALE_KEYS = frozenset({"installed", "running"})
EXPECTED_DIAGNOSTIC_CHECK_KEYS = frozenset({"name", "status"})


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


@pytest.mark.parametrize("state", sorted(plugin_api.CONNECTION_STATES))
def test_copied_diagnostic_schema_is_a_strict_allowlist_for_every_state(state):
    result = plugin_api._connection_payload(
        state,
        actor="owner",
        title="A safe title",
        message="A safe message",
        relay_host="relay.tail1234.ts.net",
        relay_port=9137,
        team_name="Team name is preview-only",
        checks=[{"name": "health", "status": "fail"}],
        tailscale_required=True,
        tailscale={
            "installed": True,
            "running": True,
            "magicdns": "must-not-be-copied.tail1234.ts.net",
            "tailnet_dns_suffix": "must-not-be-copied.ts.net",
            "ipv4": "100.64.0.8",
            "backend_state": "Running",
        },
        can_restart=True,
    )

    diagnostic = result["diagnostic"]
    assert set(diagnostic) == EXPECTED_DIAGNOSTIC_KEYS
    assert set(diagnostic["tailscale"]) == EXPECTED_DIAGNOSTIC_TAILSCALE_KEYS
    assert all(
        set(check) == EXPECTED_DIAGNOSTIC_CHECK_KEYS
        for check in diagnostic["checks"]
    )
    blob = json.dumps(diagnostic)
    for forbidden in [
        "magicdns",
        "tailnet_dns_suffix",
        "backend_state",
        "100.64.0.8",
        "Team name is preview-only",
        "invite_code",
        "join_secret",
        "member_token",
        "transcript",
        "session_id",
        "raw_metrics",
        "leaderboard",
        "teams",
        "members",
        "schema_version",
    ]:
        assert forbidden not in blob


def test_real_preflight_never_copies_saved_credentials_or_relay_payloads(
    tmp_path, monkeypatch
):
    fabric_home = tmp_path / ".fabric"
    monkeypatch.setattr(plugin_api, "get_fabric_home", lambda: fabric_home)
    config = plugin_api._default_team_config()
    config["membership"] = {
        "relay_url": "https://relay.example",
        "team_id": "tm_private_46",
        "team_name": "Privacy Crew",
        "join_secret": "join-secret-private-46",
        "member_id": "mb_private_46",
        "member_token": "member-token-private-46",
        "role": "member",
    }
    plugin_api.save_team_config(config)
    calls = []

    def transport(method, url, headers, body):
        calls.append((method, url, dict(headers)))
        if url.endswith("/health"):
            return 200, {
                "schema_version": 1,
                "teams": 987654,
                "members": 876543,
                "raw_metrics": "metrics-private-46",
                "transcript": "transcript-private-46",
                "session_id": "session-private-46",
            }
        if url.endswith("/leaderboard"):
            return 200, {
                "team_name": "Privacy Crew",
                "member_count": 1,
                "leaderboard": [{
                    "display_name": "relay-payload-private-46",
                    "score": 31337,
                }],
            }
        raise AssertionError(f"unexpected request: {method} {url}")

    result = plugin_api.team_preflight(
        transport=transport,
        dns_resolver=lambda *_args: True,
        host_probe=lambda *_args: pytest.fail("public relay must skip host probe"),
        tcp_probe=lambda *_args: True,
    )

    assert result["state"] == "CONNECTED"
    assert calls[-1][2]["X-Member-Id"] == "mb_private_46"
    assert calls[-1][2]["X-Member-Token"] == "member-token-private-46"
    assert "X-Join-Secret" not in calls[-1][2]
    diagnostic = result["diagnostic"]
    assert set(diagnostic) == EXPECTED_DIAGNOSTIC_KEYS
    blob = json.dumps(diagnostic)
    for forbidden in [
        "fbl1_",
        "join-secret-private-46",
        "member-token-private-46",
        "mb_private_46",
        "tm_private_46",
        "metrics-private-46",
        "transcript-private-46",
        "session-private-46",
        "relay-payload-private-46",
        "31337",
        "987654",
        "876543",
        "raw_metrics",
        "transcript",
        "session_id",
        "leaderboard",
        "schema_version",
    ]:
        assert forbidden not in blob


def test_invalid_invite_diagnostic_never_echoes_raw_invite_or_decode_error():
    raw_invite = "fbl1_this-is-not-valid-base64-and-contains-private-46"

    result = plugin_api.team_preflight(raw_invite)

    assert result["state"] == "INVITE_INVALID"
    assert set(result["diagnostic"]) == EXPECTED_DIAGNOSTIC_KEYS
    blob = json.dumps(result)
    assert raw_invite not in blob
    assert "private-46" not in blob
    assert "Traceback" not in blob
