"""Tests for the fabric-achievements team leaderboard client + backend helpers.

These exercise the invite codec, the points/profile model, the ``RelayClient``,
and the ``team_*`` backend helpers end-to-end against an in-process relay store
(no sockets), with an isolated ``FABRIC_HOME`` so ``team.json`` doesn't collide.
"""
from __future__ import annotations

import importlib.util
import json
import urllib.parse
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[2] / "plugins" / "fabric-achievements"
PLUGIN_API_PATH = PLUGIN_DIR / "dashboard" / "plugin_api.py"
STORE_PATH = PLUGIN_DIR / "relay" / "store.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_transport(store, store_mod):
    """Bridge RelayClient HTTP calls straight into an in-process store."""

    def transport(method, url, headers, body):
        path = urllib.parse.urlparse(url).path
        data = json.loads(body.decode()) if body else {}
        try:
            if method == "POST" and path == "/api/teams":
                return 200, store.create_team(name=data.get("name", ""), display_name=data.get("display_name", ""))
            parts = path.strip("/").split("/")  # api teams <id> <action>
            team_id = urllib.parse.unquote(parts[2])
            action = parts[3]
            if action == "join":
                return 200, store.join_team(team_id=team_id, join_secret=data.get("join_secret", ""), display_name=data.get("display_name", ""))
            if action == "publish":
                return 200, store.publish(team_id=team_id, member_id=data["member_id"], member_token=data["member_token"], profile=data.get("profile"), display_name=data.get("display_name"))
            if action == "leave":
                return 200, store.leave(team_id=team_id, member_id=data["member_id"], member_token=data["member_token"])
            if action == "unpublish":
                return 200, store.unpublish(team_id=team_id, member_id=data["member_id"], member_token=data["member_token"])
            if action == "rotate":
                return 200, store.rotate_join_secret(team_id=team_id, member_id=data["member_id"], member_token=data["member_token"])
            if action == "kick":
                return 200, store.kick_member(team_id=team_id, member_id=data["member_id"], member_token=data["member_token"], target_member_id=data["target_member_id"])
            if action == "leaderboard":
                return 200, store.leaderboard(team_id=team_id, join_secret=headers.get("X-Join-Secret"), member_id=headers.get("X-Member-Id"), member_token=headers.get("X-Member-Token"))
        except store_mod.RelayError as exc:
            return exc.status, {"error": exc.message}
        return 404, {"error": "not found"}

    return transport


SAMPLE_ACHIEVEMENTS = [
    {"id": "a", "name": "Let Him Cook", "tier": "Gold", "category": "Agent Autonomy", "icon": "flame", "unlocked": True, "state": "unlocked"},
    {"id": "b", "name": "Terminal Goblin", "tier": "Diamond", "category": "Tool Mastery", "icon": "terminal", "unlocked": True, "state": "unlocked"},
    {"id": "c", "name": "Full Send", "tier": None, "category": "Agent Autonomy", "icon": "rocket", "unlocked": True, "state": "unlocked"},  # multi-condition, no tier
    {"id": "d", "name": "Weekend Warrior", "tier": "Copper", "category": "Lifestyle", "icon": "calendar", "unlocked": False, "state": "discovered"},
    {"id": "e", "name": "Secret One", "tier": None, "category": "Debugging Chaos", "icon": "secret", "unlocked": False, "state": "secret"},
]


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("FABRIC_HOME", raising=False)
    module = _load(PLUGIN_API_PATH, f"plugin_api_lb_{id(tmp_path)}")
    # Keep the leaderboard logic independent of the session scanner.
    monkeypatch.setattr(module, "_current_achievements", lambda: SAMPLE_ACHIEVEMENTS)
    return module


@pytest.fixture
def store():
    store_mod = _load(STORE_PATH, "lb_store_for_api_test")
    return store_mod.LeaderboardStore(), store_mod


# ---- invite codec --------------------------------------------------------
def test_invite_round_trip(api):
    code = api.encode_invite("http://relay.test:9137", "tm_123", "Crew", "s3cr3t")
    assert code.startswith("fbl1_")
    decoded = api.decode_invite(code)
    assert decoded == {
        "relay_url": "http://relay.test:9137",
        "team_id": "tm_123",
        "team_name": "Crew",
        "join_secret": "s3cr3t",
    }


def test_invite_tolerates_whitespace_and_quotes(api):
    code = api.encode_invite("https://x.example", "tm_1", "T", "sek")
    assert api.decode_invite(f'  "{code}"  ')["team_id"] == "tm_1"


@pytest.mark.parametrize("bad", ["", "hello", "fbl1_not-base64!!", "fbl1_"])
def test_invite_rejects_malformed(api, bad):
    with pytest.raises(ValueError):
        api.decode_invite(bad)


def test_invite_rejects_non_http_relay(api):
    with pytest.raises(ValueError):
        api._validate_relay_url("ftp://evil/relay")
    with pytest.raises(ValueError):
        api._validate_relay_url("")


# ---- points / profile ----------------------------------------------------
def test_score_and_profile(api):
    # Gold(60) + Diamond(150) + no-tier(60) = 270
    profile = api.build_leaderboard_profile(SAMPLE_ACHIEVEMENTS, "Channa")
    assert profile["score"] == 270
    assert profile["unlocked_count"] == 3
    assert profile["total_count"] == 5
    assert profile["discovered_count"] == 1
    assert profile["secret_count"] == 1
    assert profile["highest_tier"] == "Diamond"
    assert profile["tier_counts"] == {"Copper": 0, "Silver": 0, "Gold": 1, "Diamond": 1, "Olympian": 0}
    assert profile["category_counts"] == {"Agent Autonomy": 2, "Tool Mastery": 1}
    assert profile["display_name"] == "Channa"
    # Top list ordered by tier rank desc, metadata only.
    assert profile["top_achievements"][0]["name"] == "Terminal Goblin"


# ---- backend helpers e2e -------------------------------------------------
def test_create_publishes_and_board_shows_me(api, store):
    st, store_mod = store
    transport = _make_transport(st, store_mod)
    state = api.team_create("http://relay.test", "Crew", "Channa", publish_opt_in=True, transport=transport)
    assert state["ok"] is True
    assert state["membership"]["team_name"] == "Crew"
    assert state["membership"]["role"] == "owner"
    assert state["membership"]["invite_code"].startswith("fbl1_")
    assert state["publish_opt_in"] is True

    board = api.team_leaderboard(transport=transport)
    assert board["member_count"] == 1
    me = board["leaderboard"][0]
    assert me["display_name"] == "Channa"
    assert me["score"] == 270
    assert board["my_member_id"] == me["member_id"]


def test_create_without_optin_does_not_publish(api, store):
    st, store_mod = store
    transport = _make_transport(st, store_mod)
    api.team_create("http://relay.test", "Crew", "Channa", publish_opt_in=False, transport=transport)
    board = api.team_leaderboard(transport=transport)
    # Owner still appears as a member, but with no published profile.
    row = board["leaderboard"][0]
    assert row["has_published"] is False
    assert row["score"] == 0


def test_action_followup_can_read_board_without_duplicate_publish(api, store):
    st, store_mod = store
    base_transport = _make_transport(st, store_mod)
    calls = []

    def counting_transport(method, url, headers, body):
        calls.append((method, urllib.parse.urlparse(url).path))
        return base_transport(method, url, headers, body)

    api.team_create(
        "http://relay.test",
        "Crew",
        "Channa",
        publish_opt_in=True,
        transport=counting_transport,
    )
    calls.clear()

    api.team_leaderboard(
        transport=counting_transport,
        refresh_profile=False,
    )

    team_id = api.load_team_config()["membership"]["team_id"]
    assert calls == [("GET", f"/api/teams/{team_id}/leaderboard")]


def test_join_flow_second_member(api, store):
    st, store_mod = store
    transport = _make_transport(st, store_mod)
    # Owner created directly on the store; the plugin user joins via invite.
    owner = st.create_team(name="Crew", display_name="Owner")
    invite = api.encode_invite("http://relay.test", owner["team_id"], "Crew", owner["join_secret"])
    st.publish(team_id=owner["team_id"], member_id=owner["member_id"], member_token=owner["member_token"], profile={"score": 999, "unlocked_count": 20, "highest_tier": "Olympian"})

    state = api.team_join(invite, "Channa", publish_opt_in=True, transport=transport)
    assert state["membership"]["role"] == "member"
    board = api.team_leaderboard(transport=transport)
    assert board["member_count"] == 2
    names = {r["display_name"]: r for r in board["leaderboard"]}
    assert names["Owner"]["rank"] == 1  # higher score ranks first
    assert names["Channa"]["score"] == 270


def test_join_can_opt_in_without_filling_a_display_name(api, store):
    """The simple join action needs only an invite and affirmative consent."""
    st, store_mod = store
    transport = _make_transport(st, store_mod)
    owner = st.create_team(name="Crew", display_name="Owner")
    invite = api.encode_invite(
        "http://relay.test", owner["team_id"], "Crew", owner["join_secret"]
    )

    state = api.team_join(invite, "", publish_opt_in=True, transport=transport)

    assert state["publish_opt_in"] is True
    assert state["membership"]["display_name"] == "Member"
    board = api.team_leaderboard(transport=transport)
    member = next(
        row
        for row in board["leaderboard"]
        if row["member_id"] == board["my_member_id"]
    )
    assert member["display_name"] == "Member"
    assert member["has_published"] is True
    assert member["score"] == 270


def test_settings_toggle_and_rename(api, store):
    st, store_mod = store
    transport = _make_transport(st, store_mod)
    api.team_create("http://relay.test", "Crew", "Channa", publish_opt_in=True, transport=transport)
    # Turn sharing off.
    state = api.team_settings(publish_opt_in=False, transport=transport)
    assert state["publish_opt_in"] is False
    # Rename + turn sharing back on republishes under the new name.
    api.team_settings(publish_opt_in=True, transport=transport)
    state = api.team_settings(display_name="Chan", transport=transport)
    assert state["membership"]["display_name"] == "Chan"
    board = api.team_leaderboard(transport=transport)
    assert board["leaderboard"][0]["display_name"] == "Chan"


def test_leave_clears_membership(api, store):
    st, store_mod = store
    transport = _make_transport(st, store_mod)
    api.team_create("http://relay.test", "Crew", "Channa", publish_opt_in=True, transport=transport)
    state = api.team_leave(transport=transport)
    assert state["membership"] is None
    assert state["publish_opt_in"] is False


def test_owner_rotate_updates_local_invite(api, store):
    st, store_mod = store
    transport = _make_transport(st, store_mod)
    before = api.team_create("http://relay.test", "Crew", "Channa", publish_opt_in=True, transport=transport)
    old_invite = before["membership"]["invite_code"]
    after = api.team_rotate(transport=transport)
    assert after["membership"]["invite_code"] != old_invite
    # The old invite secret should no longer be accepted by the relay.
    with pytest.raises(store_mod.RelayError):
        st.join_team(team_id=before["membership"]["team_id"], join_secret=api.decode_invite(old_invite)["join_secret"], display_name="Late")


def test_relay_unreachable_on_create_raises(api):
    # A dead relay during create is fatal to the operation; the helper raises
    # and the async route handler converts it to an {ok:false} payload.
    def dead(method, url, headers, body):
        raise api.RelayClientError("Could not reach the relay: timed out", status=0)

    with pytest.raises(api.RelayClientError):
        api.team_create("http://relay.test", "Crew", "Channa", publish_opt_in=True, transport=dead)


def test_relay_unreachable_on_read_returns_error_payload(api, store):
    st, store_mod = store
    good = _make_transport(st, store_mod)
    api.team_create("http://relay.test", "Crew", "Channa", publish_opt_in=True, transport=good)

    def dead(method, url, headers, body):
        raise api.RelayClientError("Could not reach the relay: timed out", status=0)

    # Reading the board with a dead relay is non-fatal — local membership
    # stays intact and the caller gets an error field, not an exception.
    state = api.team_leaderboard(transport=dead)
    assert state["ok"] is False
    assert "reach the relay" in state["error"]
    assert state["membership"] is not None


def test_leaderboard_without_membership_is_empty(api):
    state = api.team_leaderboard()
    assert state["membership"] is None
    assert state["leaderboard"] == []


def test_create_against_non_relay_2xx_raises_clean_error(api):
    # A URL that returns HTTP 200 but isn't a relay (typo'd homepage) parses to
    # {} — team_create must raise a RelayClientError, not a bare KeyError.
    def not_a_relay(method, url, headers, body):
        return 200, {}  # empty/non-relay body

    with pytest.raises(api.RelayClientError) as exc:
        api.team_create("http://example.com", "Crew", "Channa", transport=not_a_relay)
    assert "unexpected response" in str(exc.value)


def test_opt_out_retracts_published_row(api, store):
    st, store_mod = store
    transport = _make_transport(st, store_mod)
    api.team_create("http://relay.test", "Crew", "Channa", publish_opt_in=True, transport=transport)
    board = api.team_leaderboard(transport=transport)
    assert board["leaderboard"][0]["has_published"] is True
    assert board["leaderboard"][0]["score"] == 270

    # Turning sharing off must actively retract the row from the relay.
    state = api.team_settings(publish_opt_in=False, transport=transport)
    assert state["publish_opt_in"] is False
    board2 = api.team_leaderboard(transport=transport)
    row = board2["leaderboard"][0]
    assert row["has_published"] is False
    assert row["score"] == 0


def test_save_team_config_is_atomic(api):
    # A crash mid-write must not leave a partial team.json; the writer renames a
    # temp file into place, so no stray .tmp remains after a successful save.
    api.save_team_config({"membership": {"team_id": "tm_x"}, "publish_opt_in": True,
                          "last_published_at": None, "last_error": None})
    cfg_path = api.team_config_path()
    assert cfg_path.exists()
    assert not cfg_path.with_suffix(cfg_path.suffix + ".tmp").exists()
    reloaded = api.load_team_config()
    assert reloaded["membership"]["team_id"] == "tm_x"
    assert reloaded["publish_opt_in"] is True
