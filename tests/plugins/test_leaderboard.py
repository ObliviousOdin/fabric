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


# ---- hosting detection (auto-fill the relay URL) -------------------------
def _healthy_relay_transport(schema_version=1, teams=2, members=5):
    """Transport that answers GET /health like a real relay's stats()."""
    def transport(method, url, headers, body):
        assert method == "GET" and url.endswith("/health"), (method, url)
        return 200, {"teams": teams, "members": members, "schema_version": schema_version}
    return transport


def _ts_status_json(dns="my-box.tail1234.ts.net.", ips=("100.101.102.103", "fd7a::1"), state="Running"):
    return json.dumps({"BackendState": state, "Self": {"DNSName": dns, "TailscaleIPs": list(ips)}})


def test_probe_relay_health_accepts_a_real_relay(api):
    result = api._probe_relay_health("http://127.0.0.1:9137", transport=_healthy_relay_transport())
    assert result["ok"] is True
    assert result["url"] == "http://127.0.0.1:9137"
    assert result["schema_version"] == 1
    assert result["teams"] == 2 and result["members"] == 5


def test_probe_relay_health_rejects_a_non_relay_200(api):
    # A URL that answers 200 but isn't a relay (no schema_version) must be
    # reported as not-a-relay, not accepted, so we never auto-fill a bad URL.
    def not_a_relay(method, url, headers, body):
        return 200, {"hello": "world"}

    result = api._probe_relay_health("http://example.com", transport=not_a_relay)
    assert result["ok"] is False
    assert "not a Fabric leaderboard relay" in result["error"]


def test_probe_relay_health_reports_unreachable(api):
    def dead(method, url, headers, body):
        raise api.RelayClientError("Could not reach the relay: Connection refused", status=0)

    result = api._probe_relay_health("http://127.0.0.1:9999", transport=dead)
    assert result["ok"] is False
    assert "Connection refused" in result["error"]


def test_probe_relay_health_rejects_a_bad_url(api):
    result = api._probe_relay_health("not-a-url")
    assert result["ok"] is False
    assert "http(s) URL" in result["error"]


class _FakeTailscaleStatus:
    """Mirror of fabric_cli.tailscale_setup.TailscaleStatus for the reused seam."""

    def __init__(self, *, running, dns_name=None, ip=None, backend_state="Running"):
        self.is_running = running
        self.dns_name = dns_name
        self.ip = ip
        self.backend_state = backend_state


def _use_tailscale(monkeypatch, api, *, binary="/usr/bin/tailscale", status=None):
    """Point the reused ``fabric_cli.tailscale_setup`` seam at fakes.

    detect_tailscale prefers these helpers; setting both to non-None forces the
    reuse path (not the direct-probe fallback).
    """
    monkeypatch.setattr(api, "_ts_find_binary", lambda: binary)
    monkeypatch.setattr(api, "_ts_status", lambda b: status)


def _no_tailscale(monkeypatch, api):
    _use_tailscale(monkeypatch, api, binary=None)


def test_detect_tailscale_absent(api, monkeypatch):
    _use_tailscale(monkeypatch, api, binary=None)
    ts = api.detect_tailscale()
    assert ts == {"installed": False, "running": False, "magicdns": None, "ipv4": None, "ips": []}


def test_detect_tailscale_running_reuses_canonical_helper(api, monkeypatch):
    _use_tailscale(monkeypatch, api, status=_FakeTailscaleStatus(
        running=True, dns_name="my-box.tail1234.ts.net", ip="100.101.102.103"))
    ts = api.detect_tailscale()
    assert ts["installed"] is True and ts["running"] is True
    assert ts["magicdns"] == "my-box.tail1234.ts.net"
    assert ts["ipv4"] == "100.101.102.103"
    assert ts["ips"] == ["100.101.102.103"]


def test_detect_tailscale_installed_but_logged_out(api, monkeypatch):
    # find_tailscale_binary returns a path, but tailscale_status returns None
    # (daemon stopped / logged out).
    _use_tailscale(monkeypatch, api, status=None)
    ts = api.detect_tailscale()
    assert ts["installed"] is True and ts["running"] is False
    assert ts["magicdns"] is None and ts["ipv4"] is None


def test_detect_tailscale_fallback_when_module_unavailable(api, monkeypatch):
    # Simulate fabric_cli.tailscale_setup not being importable: the reuse seam is
    # None, so detect_tailscale must fall back to a direct `tailscale` probe.
    monkeypatch.setattr(api, "_ts_find_binary", None)
    monkeypatch.setattr(api, "_ts_status", None)
    monkeypatch.setattr(api, "_tailscale_exe", lambda: "/usr/bin/tailscale")
    monkeypatch.setattr(api, "_run_tailscale", lambda args, timeout=5: (0, _ts_status_json()))
    ts = api.detect_tailscale()
    assert ts["installed"] is True and ts["running"] is True
    assert ts["magicdns"] == "my-box.tail1234.ts.net"
    assert ts["ipv4"] == "100.101.102.103"


def test_host_status_prefers_tailscale_magicdns(api, monkeypatch):
    _use_tailscale(monkeypatch, api, status=_FakeTailscaleStatus(
        running=True, dns_name="my-box.tail1234.ts.net", ip="100.101.102.103"))
    status = api.host_status(9137, transport=_healthy_relay_transport())
    assert status["suggested_relay_url"] == "http://my-box.tail1234.ts.net:9137"
    assert status["suggested_is_shareable"] is True  # relay is live
    assert status["relay_live"] is True
    assert status["local_relay"]["ok"] is True
    assert status["tailscale"]["running"] is True
    assert status["tailscale_needs_setup"] is False
    assert "python -m relay" in status["run_command"]


def test_host_status_tailscale_up_but_no_relay_is_pending_not_shareable(api, monkeypatch):
    # A MagicDNS URL for a port with no relay behind it must NOT be marked
    # shareable/reachable. The URL is still pre-filled (ready once Host runs),
    # but relay_live is False so the UI shows a "pending" message, not "reachable".
    _use_tailscale(monkeypatch, api, status=_FakeTailscaleStatus(
        running=True, dns_name="box.tail1234.ts.net", ip="100.1.2.3"))

    def dead(method, url, headers, body):
        raise api.RelayClientError("refused", status=0)

    status = api.host_status(9137, transport=dead)
    assert status["suggested_relay_url"] == "http://box.tail1234.ts.net:9137"  # still pre-filled
    assert status["relay_live"] is False
    assert status["suggested_is_shareable"] is False  # not promised as reachable


def test_host_status_falls_back_to_loopback_when_no_tailscale(api, monkeypatch):
    # No Tailscale, but a relay is answering locally: suggest loopback and flag
    # it as NOT shareable (only works for a same-machine trial).
    _no_tailscale(monkeypatch, api)
    status = api.host_status(9137, transport=_healthy_relay_transport())
    assert status["suggested_relay_url"] == "http://127.0.0.1:9137"
    assert status["suggested_is_shareable"] is False


def test_host_status_flags_tailscale_needs_setup(api, monkeypatch):
    # Installed but not connected -> the UI should offer `fabric setup tailscale`.
    _use_tailscale(monkeypatch, api, status=_FakeTailscaleStatus(running=False, backend_state="Stopped"))
    status = api.host_status(9137, transport=_healthy_relay_transport())
    assert status["tailscale"]["installed"] is True
    assert status["tailscale"]["running"] is False
    assert status["tailscale_needs_setup"] is True
    assert status["tailscale_setup_command"] == "fabric setup tailscale"


def test_host_status_no_relay_no_tailscale_suggests_nothing(api, monkeypatch):
    _no_tailscale(monkeypatch, api)

    def dead(method, url, headers, body):
        raise api.RelayClientError("Could not reach the relay: Connection refused", status=0)

    status = api.host_status(9137, transport=dead)
    assert status["suggested_relay_url"] is None
    assert status["suggested_is_shareable"] is False
    assert status["local_relay"]["ok"] is False


def test_host_status_clamps_bad_port(api, monkeypatch):
    _no_tailscale(monkeypatch, api)

    def dead(method, url, headers, body):
        raise api.RelayClientError("unreachable", status=0)

    assert api.host_status(0, transport=dead)["default_port"] == api.DEFAULT_RELAY_PORT
    assert api.host_status(99999, transport=dead)["default_port"] == api.DEFAULT_RELAY_PORT
    assert api.host_status("nope", transport=dead)["default_port"] == api.DEFAULT_RELAY_PORT


# ---- hosting: start / stop a dashboard-managed relay ---------------------
def _stateful_transport(state):
    """Transport that is dead until ``state['up']`` flips True (relay bound)."""
    def transport(method, url, headers, body):
        if state.get("up"):
            return 200, {"teams": 0, "members": 0, "schema_version": 1}
        raise RuntimeError("connection refused")
    return transport


def _managed_relay_env(api, monkeypatch, *, pid=424242, start_time=999):
    """Patch pid/start-time/terminate seams so no real process is touched."""
    monkeypatch.setattr(api, "RELAY_START_HEALTH_ATTEMPTS", 0)  # no sleeping
    monkeypatch.setattr(api, "_process_start_time", lambda p: start_time)
    _no_tailscale(monkeypatch, api)
    state = {"up": False}
    spawned = {}

    def spawn(argv, cwd, log):
        spawned["argv"] = list(argv)
        spawned["cwd"] = str(cwd)
        state["up"] = True
        return pid

    monkeypatch.setattr(api, "_pid_is_alive", lambda p, start_time=None: p == pid and state["up"])
    return state, spawned, spawn


def test_start_local_relay_spawns_records_and_reports(api, monkeypatch):
    state, spawned, spawn = _managed_relay_env(api, monkeypatch)
    transport = _stateful_transport(state)
    result = api.start_local_relay(9137, "0.0.0.0", spawner=spawn, transport=transport)

    # Correct argv: python -m relay --host ... --port ... --state <roster.json>
    assert spawned["argv"][1:3] == ["-m", "relay"]
    assert "--port" in spawned["argv"] and "9137" in spawned["argv"]
    assert spawned["argv"][-1].endswith("roster.json")
    assert spawned["cwd"].endswith("plugins/fabric-achievements")

    assert result["managed_relay"]["managed"] is True
    assert result["managed_relay"]["running"] is True
    assert result["managed_relay"]["healthy"] is True
    assert result.get("note") is None

    saved = api.load_relay_state()
    assert saved["pid"] == 424242 and saved["port"] == 9137 and saved["start_time"] == 999


def test_start_local_relay_is_idempotent_when_ours_is_running(api, monkeypatch):
    state, spawned, spawn = _managed_relay_env(api, monkeypatch)
    transport = _stateful_transport(state)
    api.start_local_relay(9137, "0.0.0.0", spawner=spawn, transport=transport)
    spawned.clear()
    # Second call: our relay is already up -> must not spawn again.
    api.start_local_relay(9137, "0.0.0.0", spawner=spawn, transport=transport)
    assert spawned == {}


def test_start_local_relay_reports_external_relay(api, monkeypatch):
    _no_tailscale(monkeypatch, api)
    monkeypatch.setattr(api, "RELAY_START_HEALTH_ATTEMPTS", 0)
    monkeypatch.setattr(api, "_pid_is_alive", lambda p, start_time=None: False)
    spawned = {}

    def spawn(argv, cwd, log):
        spawned["called"] = True
        return 1

    # A relay already answers on the port but we didn't start it.
    result = api.start_local_relay(9137, "0.0.0.0", spawner=spawn, transport=_healthy_relay_transport())
    assert "already running on this port" in (result.get("note") or "")
    assert spawned == {}  # do not spawn a second binder


def test_start_local_relay_surfaces_spawn_failure(api, monkeypatch):
    _no_tailscale(monkeypatch, api)
    monkeypatch.setattr(api, "RELAY_START_HEALTH_ATTEMPTS", 0)

    def boom(argv, cwd, log):
        raise OSError("cannot exec")

    def dead(method, url, headers, body):
        raise api.RelayClientError("refused", status=0)

    result = api.start_local_relay(9137, "0.0.0.0", spawner=boom, transport=dead)
    assert "Could not start the relay" in (result.get("note") or "")
    assert api.load_relay_state() == {}  # nothing recorded on failure


def test_start_local_relay_binds_all_interfaces_by_default(api, monkeypatch):
    # host unspecified -> 0.0.0.0, which the loopback health/adopt probes rely on
    # AND which the Tailscale interface teammates use is a subset of.
    state, spawned, spawn = _managed_relay_env(api, monkeypatch)
    api.start_local_relay(9137, None, spawner=spawn, transport=_stateful_transport(state))
    host_idx = spawned["argv"].index("--host") + 1
    assert spawned["argv"][host_idx] == "0.0.0.0"


def test_start_local_relay_honors_explicit_host(api, monkeypatch):
    # An explicit bind host (advanced) is passed through verbatim.
    state, spawned, spawn = _managed_relay_env(api, monkeypatch)
    api.start_local_relay(9137, "127.0.0.1", spawner=spawn, transport=_stateful_transport(state))
    host_idx = spawned["argv"].index("--host") + 1
    assert spawned["argv"][host_idx] == "127.0.0.1"


def test_start_local_relay_orphan_guard_on_save_failure(api, monkeypatch):
    # If recording relay.json fails after a successful spawn, the spawned relay
    # must be terminated (not orphaned) and the failure surfaced.
    _no_tailscale(monkeypatch, api)
    monkeypatch.setattr(api, "RELAY_START_HEALTH_ATTEMPTS", 0)
    monkeypatch.setattr(api, "_process_start_time", lambda p: 7)
    monkeypatch.setattr(api, "_pid_is_alive", lambda p, start_time=None: False)

    def save_boom(state):
        raise OSError("disk full")
    monkeypatch.setattr(api, "save_relay_state", save_boom)
    killed = {}
    monkeypatch.setattr(api, "_terminate_relay_pid", lambda p: killed.setdefault("pid", p) or True)

    def dead(method, url, headers, body):
        raise api.RelayClientError("refused", status=0)

    result = api.start_local_relay(9137, "0.0.0.0", spawner=lambda a, c, l: 314, transport=dead)
    assert killed["pid"] == 314  # orphan killed
    assert "could not record it" in (result.get("note") or "")


def test_stop_local_relay_terminates_and_clears(api, monkeypatch):
    state, spawned, spawn = _managed_relay_env(api, monkeypatch)
    transport = _stateful_transport(state)
    api.start_local_relay(9137, "0.0.0.0", spawner=spawn, transport=transport)

    terminated = {}

    def term(p):
        terminated["pid"] = p
        state["up"] = False
        return True  # terminate succeeded
    monkeypatch.setattr(api, "_terminate_relay_pid", term)
    result = api.stop_local_relay(transport=transport)
    assert terminated["pid"] == 424242
    assert api.relay_state_path().exists() is False
    assert result["managed_relay"]["managed"] is False


def test_stop_local_relay_keeps_state_when_terminate_fails(api, monkeypatch):
    # A failed terminate must KEEP the recorded state so Stop can be retried,
    # rather than forgetting a relay we couldn't kill.
    state, spawned, spawn = _managed_relay_env(api, monkeypatch)
    transport = _stateful_transport(state)
    api.start_local_relay(9137, "0.0.0.0", spawner=spawn, transport=transport)

    monkeypatch.setattr(api, "_terminate_relay_pid", lambda p: False)  # kill failed
    result = api.stop_local_relay(transport=transport)
    assert "try again" in (result.get("note") or "")
    assert api.relay_state_path().exists() is True  # state kept for retry
    assert api.load_relay_state().get("pid") == 424242


def test_stop_local_relay_when_nothing_managed(api, monkeypatch):
    _no_tailscale(monkeypatch, api)

    def dead(method, url, headers, body):
        raise api.RelayClientError("refused", status=0)

    result = api.stop_local_relay(transport=dead)
    assert "No dashboard-managed relay" in (result.get("note") or "")


def test_relay_process_status_reports_dead_pid_read_only(api, monkeypatch):
    # A recorded PID that is no longer our live process is reported as not-managed
    # but the state file is NOT cleared here (read-only; avoids racing a start).
    api.save_relay_state({"pid": 555, "port": 9137, "start_time": 1, "log": "x.log"})
    monkeypatch.setattr(api, "_pid_is_alive", lambda p, start_time=None: False)

    def dead(method, url, headers, body):
        raise api.RelayClientError("refused", status=0)

    status = api.relay_process_status(transport=dead)
    assert status["managed"] is False and status["running"] is False
    assert api.relay_state_path().exists() is True  # read-only: not cleared here
