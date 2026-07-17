"""Tests for the fabric-achievements team leaderboard client + backend helpers.

These exercise the invite codec, the points/profile model, the ``RelayClient``,
and the ``team_*`` backend helpers against an in-process relay store, plus one
real managed-relay lifecycle smoke test. ``FABRIC_HOME`` is isolated throughout.
"""
from __future__ import annotations

import importlib.util
import json
import multiprocessing
import os
import socket
import stat
import urllib.parse
from pathlib import Path

import psutil
import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[2] / "plugins" / "fabric-achievements"
PLUGIN_API_PATH = PLUGIN_DIR / "dashboard" / "plugin_api.py"
STORE_PATH = PLUGIN_DIR / "relay" / "store.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _concurrent_relay_start_worker(home, port, gate, ready, spawn_log, results):
    """Start through a fresh plugin import, simulating another dashboard worker."""
    os.environ["FABRIC_HOME"] = home
    os.environ.pop("HERMES_HOME", None)
    api = _load(PLUGIN_API_PATH, f"plugin_api_worker_{os.getpid()}")
    setattr(api, "detect_tailscale", lambda: {
        "installed": False,
        "running": False,
        "magicdns": None,
        "ip": None,
        "ipv4": None,
        "ipv6": None,
    })
    original_spawner = api._default_relay_spawner

    def recording_spawner(argv, cwd, log_path):
        pid, start_time = original_spawner(argv, cwd, log_path)
        try:
            payload = f"{pid},{start_time}\n".encode()
            fd = os.open(spawn_log, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
            try:
                os.write(fd, payload)
            finally:
                os.close(fd)
        except Exception:
            api._terminate_relay_pid(pid, start_time)
            raise
        return pid, start_time

    ready.put(True)
    if not gate.wait(timeout=10):
        results.put({"error": "start gate timed out"})
        return
    result = api.start_local_relay(
        port=port,
        host="127.0.0.1",
        spawner=recording_spawner,
    )
    results.put({
        "action_ok": result.get("action_ok", True),
        "error": result.get("error"),
        "pid": result.get("managed_relay", {}).get("pid"),
    })


def _cleanup_test_relays(state_path: Path) -> None:
    """Stop detached test relays even if a worker died before recording its PID."""
    marker = str(state_path)
    for process in psutil.process_iter(["cmdline"]):
        try:
            cmdline = process.info.get("cmdline") or []
            is_relay = any(
                cmdline[index : index + 2] == ["-m", "relay"]
                for index in range(len(cmdline) - 1)
            )
            owns_state = any(
                cmdline[index : index + 2] == ["--state", marker]
                for index in range(len(cmdline) - 1)
            )
            if not (is_relay and owns_state):
                continue
            process.terminate()
            try:
                process.wait(timeout=3)
            except psutil.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            continue


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
    fabric_home = tmp_path / ".fabric"
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("FABRIC_HOME", str(fabric_home))
    monkeypatch.delenv("HERMES_HOME", raising=False)
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


def test_relay_leave_rolls_back_after_persistence_failure(tmp_path, monkeypatch):
    store_mod = _load(STORE_PATH, f"lb_store_persist_{id(tmp_path)}")
    roster_path = tmp_path / "state" / "roster.json"
    relay = store_mod.LeaderboardStore(roster_path)
    owner = relay.create_team(name="Crew", display_name="Owner")
    original_persist = relay._persist_locked

    def fail_persist():
        raise OSError("disk full")

    monkeypatch.setattr(relay, "_persist_locked", fail_persist)
    with pytest.raises(OSError, match="disk full"):
        relay.leave(
            team_id=owner["team_id"],
            member_id=owner["member_id"],
            member_token=owner["member_token"],
        )
    assert owner["team_id"] in relay._teams

    monkeypatch.setattr(relay, "_persist_locked", original_persist)
    assert relay.leave(
        team_id=owner["team_id"],
        member_id=owner["member_id"],
        member_token=owner["member_token"],
    ) == {"ok": True}
    reloaded = store_mod.LeaderboardStore(roster_path)
    assert owner["team_id"] not in reloaded._teams


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits only")
def test_relay_roster_permissions_are_private_and_hardened(tmp_path):
    store_mod = _load(STORE_PATH, f"lb_store_modes_{id(tmp_path)}")
    roster_path = tmp_path / "state" / "roster.json"
    relay = store_mod.LeaderboardStore(roster_path)
    relay.create_team(name="Crew", display_name="Owner")

    assert stat.S_IMODE(roster_path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(roster_path.stat().st_mode) == 0o600

    roster_path.parent.chmod(0o755)
    roster_path.chmod(0o644)
    store_mod.LeaderboardStore(roster_path)
    assert stat.S_IMODE(roster_path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(roster_path.stat().st_mode) == 0o600


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


def test_failed_unpublish_is_reported_and_retried(api, store):
    st, store_mod = store
    transport = _make_transport(st, store_mod)
    api.team_create("http://relay.test", "Crew", "Channa", publish_opt_in=True, transport=transport)
    failed_once = False

    def flaky_unpublish(method, url, headers, body):
        nonlocal failed_once
        if url.endswith("/unpublish") and not failed_once:
            failed_once = True
            return 503, {"error": "unpublish refused"}
        return transport(method, url, headers, body)

    state = api.team_settings(publish_opt_in=False, transport=flaky_unpublish)
    assert state["ok"] is False
    assert state["publish_opt_in"] is False
    assert state["pending_unpublish"] is True
    assert state["error"] == "unpublish refused"

    blocked = api.team_publish(transport=transport)
    assert blocked["ok"] is False
    assert blocked["pending_unpublish"] is True
    assert "Sharing is disabled" in blocked["error"]

    # The next board read retries the remote retraction and clears the marker.
    board = api.team_leaderboard(transport=transport, refresh_profile=False)
    assert board["ok"] is True
    assert board["pending_unpublish"] is False
    assert board["leaderboard"][0]["has_published"] is False


def test_create_surfaces_initial_publish_failure(api, store):
    st, store_mod = store
    transport = _make_transport(st, store_mod)

    def publish_fails(method, url, headers, body):
        if url.endswith("/publish"):
            return 503, {"error": "publish refused"}
        return transport(method, url, headers, body)

    state = api.team_create(
        "http://relay.test", "Crew", "Channa", publish_opt_in=True, transport=publish_fails,
    )
    assert state["ok"] is False
    assert state["membership"]["team_name"] == "Crew"
    assert state["publish_opt_in"] is True
    assert state["publish_error"] == "publish refused"
    assert state["error"] == "publish refused"


def test_leave_clears_membership(api, store):
    st, store_mod = store
    transport = _make_transport(st, store_mod)
    api.team_create("http://relay.test", "Crew", "Channa", publish_opt_in=True, transport=transport)
    state = api.team_leave(transport=transport)
    assert state["membership"] is None
    assert state["publish_opt_in"] is False


def test_failed_remote_leave_is_retained_and_retried(api, store):
    st, store_mod = store
    transport = _make_transport(st, store_mod)
    api.team_create("http://relay.test", "Crew", "Channa", publish_opt_in=True, transport=transport)

    def leave_fails(method, url, headers, body):
        if url.endswith("/leave"):
            return 503, {"error": "leave refused"}
        return transport(method, url, headers, body)

    state = api.team_leave(transport=leave_fails)
    assert state["ok"] is False
    assert state["membership"] is None
    assert state["pending_leave_count"] == 1
    assert "Fabric will retry" in state["error"]
    persisted = json.loads(api.team_config_path().read_text(encoding="utf-8"))
    assert set(persisted["pending_leaves"][0]) == {
        "relay_url", "team_id", "member_id", "member_token",
    }
    assert stat.S_IMODE(api.team_config_path().stat().st_mode) == 0o600

    state = api.team_leaderboard(transport=transport, refresh_profile=False)
    assert state["ok"] is True
    assert state["pending_leave_count"] == 0


def test_relay_leave_is_idempotent_after_member_is_absent(store):
    st, _store_mod = store
    owner = st.create_team(name="Crew", display_name="Owner")
    member = st.join_team(
        team_id=owner["team_id"],
        join_secret=owner["join_secret"],
        display_name="Member",
    )
    assert st.leave(
        team_id=member["team_id"],
        member_id=member["member_id"],
        member_token=member["member_token"],
    ) == {"ok": True}
    assert st.leave(
        team_id=member["team_id"],
        member_id=member["member_id"],
        member_token=member["member_token"],
    ) == {"ok": True}


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


@pytest.mark.parametrize("operation", ["publish", "unpublish", "leave", "rotate", "kick"])
def test_mutations_require_explicit_relay_ack(api, operation):
    client = api.RelayClient("http://relay.test", transport=lambda *_args: (200, {}))
    calls = {
        "publish": lambda: client.publish("tm", "mb", "token", {}),
        "unpublish": lambda: client.unpublish("tm", "mb", "token"),
        "leave": lambda: client.leave("tm", "mb", "token"),
        "rotate": lambda: client.rotate("tm", "mb", "token"),
        "kick": lambda: client.kick("tm", "mb", "token", "target"),
    }
    with pytest.raises(api.RelayClientError, match="did not confirm"):
        calls[operation]()


def test_rotate_requires_new_invite_secret(api):
    client = api.RelayClient(
        "http://relay.test",
        transport=lambda *_args: (200, {"ok": True}),
    )
    with pytest.raises(api.RelayClientError, match="new invite secret"):
        client.rotate("tm", "mb", "token")


def test_generic_404_does_not_confirm_unpublish_or_leave(api, store):
    st, store_mod = store
    transport = _make_transport(st, store_mod)
    api.team_create(
        "http://relay.test", "Crew", "Channa", publish_opt_in=True,
        transport=transport,
    )

    def missing_route(method, url, headers, body):
        return 404, {"error": "route not found"}

    opt_out = api.team_settings(publish_opt_in=False, transport=missing_route)
    assert opt_out["ok"] is False
    assert opt_out["pending_unpublish"] is True
    assert opt_out["last_published_at"] is not None

    leave = api.team_leave(transport=missing_route)
    assert leave["ok"] is False
    assert leave["membership"] is None
    assert leave["pending_leave_count"] == 1

    retry = api.team_leaderboard(transport=missing_route, refresh_profile=False)
    assert retry["ok"] is False
    assert retry["pending_leave_count"] == 1


def test_create_and_join_reject_existing_membership_before_remote_call(api, store):
    st, store_mod = store
    base_transport = _make_transport(st, store_mod)
    calls = []

    def counting_transport(method, url, headers, body):
        calls.append((method, url))
        return base_transport(method, url, headers, body)

    current = api.team_create(
        "http://relay.test", "First", "Owner", publish_opt_in=True,
        transport=counting_transport,
    )
    invite = current["membership"]["invite_code"]
    calls.clear()

    created = api.team_create(
        "http://relay.test", "Second", "Owner", publish_opt_in=True,
        transport=counting_transport,
    )
    joined = api.team_join(invite, "Owner", transport=counting_transport)
    assert created["ok"] is False
    assert joined["ok"] is False
    assert created["membership"]["team_name"] == "First"
    assert joined["membership"]["team_name"] == "First"
    assert calls == []


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
    assert list(cfg_path.parent.glob(f".{cfg_path.name}.*.tmp")) == []
    assert stat.S_IMODE(cfg_path.stat().st_mode) == 0o600
    reloaded = api.load_team_config()
    assert reloaded["membership"]["team_id"] == "tm_x"
    assert reloaded["publish_opt_in"] is True


@pytest.mark.parametrize("pending_field", [{}, {"pending_unpublish": False}])
def test_old_failed_opt_out_migrates_to_pending_retraction(api, pending_field):
    cfg_path = api.team_config_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps({
        "membership": {
            "relay_url": "http://relay.test",
            "team_id": "tm_old",
            "member_id": "mb_old",
            "member_token": "token",
        },
        "publish_opt_in": False,
        "last_published_at": 123,
        "last_error": "relay unavailable",
        **pending_field,
    }), encoding="utf-8")

    loaded = api.load_team_config()
    persisted = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert loaded["pending_unpublish"] is True
    assert persisted["pending_unpublish"] is True
    assert stat.S_IMODE(cfg_path.stat().st_mode) == 0o600


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits only")
def test_load_hardens_unchanged_team_config_permissions(api):
    cfg_path = api.team_config_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps({
        "membership": {
            "relay_url": "http://relay.test",
            "team_id": "tm_old",
            "member_id": "mb_old",
            "member_token": "token",
            "join_secret": "secret",
        },
        "publish_opt_in": False,
        "pending_unpublish": False,
        "last_published_at": None,
    }), encoding="utf-8")
    cfg_path.parent.chmod(0o755)
    cfg_path.chmod(0o644)

    loaded = api.load_team_config()

    assert loaded["membership"]["member_token"] == "token"
    assert stat.S_IMODE(cfg_path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(cfg_path.stat().st_mode) == 0o600


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
    assert ts == {
        "installed": False,
        "running": False,
        "magicdns": None,
        "ipv4": None,
        "ipv6": None,
        "ips": [],
    }


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
    assert status["suggested_is_shareable"] is True  # tailnet URL itself answers
    assert status["shareable_relay"]["ok"] is True
    assert status["relay_live"] is True
    assert status["local_relay"]["ok"] is True
    assert status["tailscale"]["running"] is True
    assert status["tailscale_needs_setup"] is False
    assert "python -m relay" in status["run_command"]


def test_host_status_does_not_call_loopback_only_relay_shareable(api, monkeypatch):
    _use_tailscale(monkeypatch, api, status=_FakeTailscaleStatus(
        running=True, dns_name="my-box.tail1234.ts.net", ip="100.101.102.103"))

    def loopback_only(method, url, headers, body):
        if url.startswith("http://127.0.0.1:"):
            return 200, {"teams": 0, "members": 0, "schema_version": 1}
        raise api.RelayClientError("connection refused", status=0)

    status = api.host_status(9137, transport=loopback_only)
    assert status["local_relay"]["ok"] is True
    assert status["relay_live"] is True
    assert status["suggested_relay_url"] == "http://my-box.tail1234.ts.net:9137"
    assert status["suggested_is_shareable"] is False
    assert status["shareable_relay"]["ok"] is False


def test_host_status_detects_tailscale_only_relay(api, monkeypatch):
    _use_tailscale(monkeypatch, api, status=_FakeTailscaleStatus(
        running=True, dns_name="my-box.tail1234.ts.net", ip="100.101.102.103"))
    calls = []

    def tailnet_only(method, url, headers, body):
        calls.append(url)
        if url.startswith("http://my-box.tail1234.ts.net:"):
            return 200, {"teams": 0, "members": 0, "schema_version": 1}
        raise api.RelayClientError("connection refused", status=0)

    status = api.host_status(9137, transport=tailnet_only)
    assert status["local_relay"]["ok"] is False
    assert status["shareable_relay"]["ok"] is True
    assert status["suggested_is_shareable"] is True
    assert status["relay_live"] is True
    assert calls == [
        "http://127.0.0.1:9137/health",
        "http://my-box.tail1234.ts.net:9137/health",
    ]


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


def test_host_status_ignores_stale_tailscale_address_when_not_running(api, monkeypatch):
    # Tailscale can retain the node's last identity while logged out/stopped.
    # A stale MagicDNS name must not be advertised as currently shareable.
    _use_tailscale(monkeypatch, api, status=_FakeTailscaleStatus(
        running=False,
        backend_state="Stopped",
        dns_name="stale.tail1234.ts.net",
        ip="100.1.2.3",
    ))
    status = api.host_status(9137, transport=_healthy_relay_transport())
    assert status["suggested_relay_url"] == "http://127.0.0.1:9137"
    assert status["suggested_is_shareable"] is False
    assert status["tailscale_needs_setup"] is True


def test_host_status_brackets_ipv6_tailscale_suggestion(api, monkeypatch):
    _use_tailscale(
        monkeypatch,
        api,
        status=_FakeTailscaleStatus(
            running=True,
            dns_name=None,
            ip="fd7a:115c:a1e0::1234",
        ),
    )
    status = api.host_status(9137, transport=_healthy_relay_transport())
    assert status["tailscale"]["ipv4"] is None
    assert status["tailscale"]["ipv6"] == "fd7a:115c:a1e0::1234"
    assert status["suggested_relay_url"] == "http://[fd7a:115c:a1e0::1234]:9137"
    assert status["suggested_is_shareable"] is True


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
    monkeypatch.setattr(
        api,
        "_relay_process_identity",
        lambda p, start_time=None: "same" if p == pid and state["up"] else "gone",
    )
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


def test_start_local_relay_does_not_respawn_while_managed_relay_is_starting(api, monkeypatch):
    _no_tailscale(monkeypatch, api)
    monkeypatch.setattr(api, "RELAY_START_HEALTH_ATTEMPTS", 0)
    monkeypatch.setattr(api, "_process_start_time", lambda p: 999)
    monkeypatch.setattr(api, "_pid_is_alive", lambda p, start_time=None: bool(p))
    monkeypatch.setattr(api, "_relay_process_identity", lambda p, start_time=None: "same")
    spawned = []

    def spawn(argv, cwd, log):
        spawned.append(list(argv))
        return 424242

    def still_starting(method, url, headers, body):
        raise api.RelayClientError("refused", status=0)

    api.start_local_relay(9137, spawner=spawn, transport=still_starting)
    api.start_local_relay(9137, spawner=spawn, transport=still_starting)
    assert len(spawned) == 1


def test_start_local_relay_does_not_orphan_managed_relay_for_another_port(api, monkeypatch):
    state, spawned, spawn = _managed_relay_env(api, monkeypatch)
    transport = _stateful_transport(state)
    api.start_local_relay(9137, spawner=spawn, transport=transport)
    spawned.clear()

    result = api.start_local_relay(9999, spawner=spawn, transport=transport)
    assert spawned == {}
    assert result["default_port"] == 9137
    assert "already hosting a relay on port 9137" in (result.get("note") or "")
    assert api.load_relay_state()["port"] == 9137


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
    assert result["action_ok"] is False
    assert api.load_relay_state() == {}  # nothing recorded on failure


def test_start_local_relay_clears_state_when_child_exits_during_health_wait(api, monkeypatch):
    _no_tailscale(monkeypatch, api)
    monkeypatch.setattr(api, "_wait_relay_healthy", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(api, "_relay_process_identity", lambda *_args: "gone")

    def dead(method, url, headers, body):
        raise api.RelayClientError("refused", status=0)

    result = api.start_local_relay(
        9137,
        "127.0.0.1",
        spawner=lambda *_args: (424242, 999),
        transport=dead,
    )
    assert result["action_ok"] is False
    assert "exited right after starting" in result["error"]
    assert api.load_relay_state() == {}


def test_start_failure_cleanup_preserves_replacement_relay_state(api, monkeypatch):
    _no_tailscale(monkeypatch, api)

    def replace_during_health_wait(*_args, **_kwargs):
        replacement = api.load_relay_state()
        assert replacement["pid"] == 111
        replacement["pid"] = 222
        replacement["start_time"] = 2220
        api.save_relay_state(replacement)
        return False

    monkeypatch.setattr(api, "_wait_relay_healthy", replace_during_health_wait)
    monkeypatch.setattr(
        api,
        "_relay_process_identity",
        lambda pid, _start: "gone" if pid == 111 else "same",
    )

    def dead(method, url, headers, body):
        raise api.RelayClientError("refused", status=0)

    api.start_local_relay(
        9137,
        "127.0.0.1",
        spawner=lambda *_args: (111, 1110),
        transport=dead,
    )

    assert api.load_relay_state()["pid"] == 222


def test_start_local_relay_binds_loopback_by_default_without_tailscale(api, monkeypatch):
    state, spawned, spawn = _managed_relay_env(api, monkeypatch)
    api.start_local_relay(9137, None, spawner=spawn, transport=_stateful_transport(state))
    host_idx = spawned["argv"].index("--host") + 1
    assert spawned["argv"][host_idx] == "127.0.0.1"


def test_start_local_relay_binds_tailscale_ipv4_when_connected(api, monkeypatch):
    state, spawned, spawn = _managed_relay_env(api, monkeypatch)
    _use_tailscale(
        monkeypatch,
        api,
        status=_FakeTailscaleStatus(running=True, ip="100.64.0.8"),
    )
    api.start_local_relay(9137, None, spawner=spawn, transport=_stateful_transport(state))
    host_idx = spawned["argv"].index("--host") + 1
    assert spawned["argv"][host_idx] == "100.64.0.8"


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
    monkeypatch.setattr(api, "_terminate_relay_pid", lambda p, start: killed.setdefault("pid", p) or True)

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

    def term(p, start):
        terminated["pid"] = p
        terminated["start_time"] = start
        state["up"] = False
        return True  # terminate succeeded
    monkeypatch.setattr(api, "_terminate_relay_pid", term)
    result = api.stop_local_relay(transport=transport)
    assert terminated["pid"] == 424242
    assert terminated["start_time"] == 999
    assert api.relay_state_path().exists() is False
    assert result["managed_relay"]["managed"] is False


def test_stop_local_relay_keeps_state_when_terminate_fails(api, monkeypatch):
    # A failed terminate must KEEP the recorded state so Stop can be retried,
    # rather than forgetting a relay we couldn't kill.
    state, spawned, spawn = _managed_relay_env(api, monkeypatch)
    transport = _stateful_transport(state)
    api.start_local_relay(9137, "0.0.0.0", spawner=spawn, transport=transport)

    monkeypatch.setattr(api, "_terminate_relay_pid", lambda p, start: False)  # kill failed
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


def test_fresh_relay_record_remains_authoritative_during_startup_grace(api, monkeypatch):
    _no_tailscale(monkeypatch, api)
    api.save_relay_state({
        "pid": 555,
        "port": 9137,
        "host": "127.0.0.1",
        "start_time": 123,
        "started_at": int(api.time.time()),
        "log": "x.log",
    })
    monkeypatch.setattr(api, "_relay_process_identity", lambda *args: "gone")
    spawned = []

    def dead(method, url, headers, body):
        raise api.RelayClientError("refused", status=0)

    started = api.start_local_relay(
        9137,
        spawner=lambda *args: spawned.append(args) or (999, 456),
        transport=dead,
    )
    assert spawned == []
    assert started.get("action_ok") is not False
    assert started["managed_relay"]["managed"] is True
    assert started["managed_relay"]["starting"] is True

    stopped = api.stop_local_relay(transport=dead)
    assert stopped["action_ok"] is False
    assert api.load_relay_state()["pid"] == 555


def test_start_and_stop_fail_closed_when_pid_identity_is_unknown(api, monkeypatch):
    _no_tailscale(monkeypatch, api)
    api.save_relay_state({"pid": 555, "port": 9137, "start_time": None, "log": "x.log"})
    monkeypatch.setattr(api, "_pid_is_alive", lambda *args: False)
    monkeypatch.setattr(api, "_relay_process_identity", lambda *args: "unknown")
    spawned = []

    def dead(method, url, headers, body):
        raise api.RelayClientError("refused", status=0)

    started = api.start_local_relay(
        9137,
        spawner=lambda *args: spawned.append(args) or 999,
        transport=dead,
    )
    stopped = api.stop_local_relay(transport=dead)
    assert spawned == []
    assert started["action_ok"] is False
    assert stopped["action_ok"] is False
    assert api.load_relay_state()["pid"] == 555


def test_start_local_relay_respects_cross_process_lock(api, monkeypatch):
    _no_tailscale(monkeypatch, api)
    monkeypatch.setattr(api, "_acquire_relay_process_lock", lambda: (False, True))
    spawned = []

    def dead(method, url, headers, body):
        raise api.RelayClientError("refused", status=0)

    result = api.start_local_relay(
        9137,
        spawner=lambda *args: spawned.append(args) or 999,
        transport=dead,
    )
    assert spawned == []
    assert result["action_ok"] is False
    assert "Another dashboard process" in result["error"]


def test_terminate_relay_escalates_and_confirms_exit(api, monkeypatch):
    identities = iter(("same", "same", "same", "gone"))
    signals = []
    monkeypatch.setattr(api, "_relay_process_identity", lambda *args: next(identities))
    monkeypatch.setattr(api, "_signal_relay_pid", lambda pid, force: signals.append(force) or True)
    monkeypatch.setattr(api, "RELAY_STOP_TIMEOUT", 0)
    monkeypatch.setattr(api, "RELAY_FORCE_TIMEOUT", 0)
    assert api._terminate_relay_pid(123, 456) is True
    assert signals == [False, True]


def test_terminate_relay_never_signals_unknown_identity(api, monkeypatch):
    signals = []
    monkeypatch.setattr(api, "_relay_process_identity", lambda *args: "unknown")
    monkeypatch.setattr(api, "_signal_relay_pid", lambda pid, force: signals.append(force) or True)
    assert api._terminate_relay_pid(123, 456) is False
    assert signals == []


def test_default_spawner_retries_windows_without_breakaway(api, monkeypatch, tmp_path):
    import fabric_cli._subprocess_compat as compat

    monkeypatch.setattr(compat, "windows_detach_popen_kwargs", lambda: {"creationflags": 3})
    monkeypatch.setattr(compat, "windows_detach_flags_without_breakaway", lambda: 2)
    monkeypatch.setattr(api, "_capture_process_start_time", lambda pid: 777)
    calls = []

    class Proc:
        pid = 321

    def popen(argv, **kwargs):
        calls.append(kwargs["creationflags"])
        if len(calls) == 1:
            raise OSError("breakaway denied")
        return Proc()

    monkeypatch.setattr(api.subprocess, "Popen", popen)
    assert api._default_relay_spawner(
        ["python", "-m", "relay"], tmp_path, tmp_path / "relay.log"
    ) == (321, 777)
    assert calls == [3, 2]


@pytest.mark.live_system_guard_bypass
def test_relay_worker_record_failure_cleans_child(api, tmp_path):
    """A diagnostic-record failure must not leak the detached child."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]

    context = multiprocessing.get_context("spawn")
    gate = context.Event()
    ready = context.Queue()
    results = context.Queue()
    bad_spawn_log = tmp_path / "missing" / "relay-spawns.txt"
    fabric_home = str(api.relay_state_path().parents[2])
    worker = context.Process(
        target=_concurrent_relay_start_worker,
        args=(fabric_home, port, gate, ready, str(bad_spawn_log), results),
    )
    try:
        worker.start()
        assert ready.get(timeout=15) is True
        gate.set()
        worker.join(timeout=30)
        assert not worker.is_alive()
        assert worker.exitcode == 0
        response = results.get(timeout=5)
        assert response.get("action_ok") is False
        assert api.relay_state_path().exists() is False
        assert api._probe_relay_health(f"http://127.0.0.1:{port}")["ok"] is False
    finally:
        gate.set()
        if worker.is_alive():
            worker.terminate()
            worker.join(timeout=5)
        _cleanup_test_relays(api.relay_roster_path())
        api.clear_relay_state()


@pytest.mark.live_system_guard_bypass
def test_managed_relay_concurrent_processes_spawn_once(api, tmp_path):
    """Two dashboard workers must not orphan a bind-losing relay child."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]

    context = multiprocessing.get_context("spawn")
    gate = context.Event()
    ready = context.Queue()
    results = context.Queue()
    spawn_log = tmp_path / "relay-spawns.txt"
    fabric_home = str(api.relay_state_path().parents[2])
    workers = [
        context.Process(
            target=_concurrent_relay_start_worker,
            args=(fabric_home, port, gate, ready, str(spawn_log), results),
        )
        for _ in range(2)
    ]
    spawned_records = []
    responses = []
    try:
        for worker in workers:
            worker.start()
        for _ in workers:
            assert ready.get(timeout=15) is True
        gate.set()
        for worker in workers:
            worker.join(timeout=30)
        assert all(not worker.is_alive() for worker in workers)
        assert [worker.exitcode for worker in workers] == [0, 0]
        responses = [results.get(timeout=5) for _ in workers]
        assert all(response.get("action_ok") is not False for response in responses), responses

        spawned_records = [
            tuple(int(value) for value in line.split(",", 1))
            for line in spawn_log.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(spawned_records) == 1
        state = api.load_relay_state()
        assert state["pid"] == spawned_records[0][0]
        assert api._probe_relay_health(f"http://127.0.0.1:{port}")["ok"] is True

        stopped = api.stop_local_relay()
        assert stopped.get("action_ok") is not False, stopped.get("error")
    finally:
        gate.set()
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=5)
        if spawn_log.exists() and not spawned_records:
            spawned_records = [
                tuple(int(value) for value in line.split(",", 1))
                for line in spawn_log.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        for pid, start_time in spawned_records:
            if api._relay_process_identity(pid, start_time) == "same":
                api._terminate_relay_pid(pid, start_time)
        _cleanup_test_relays(api.relay_roster_path())
        api.clear_relay_state()

    assert api._probe_relay_health(f"http://127.0.0.1:{port}")["ok"] is False


def test_managed_relay_real_start_health_stop(api, monkeypatch):
    """Exercise the detached child, real HTTP health, state, and shutdown path."""
    _no_tailscale(monkeypatch, api)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]

    started = None
    try:
        started = api.start_local_relay(port=port, host="127.0.0.1")
        managed = started["managed_relay"]
        assert started.get("action_ok") is not False, started.get("error")
        assert started["local_relay"]["ok"] is True
        assert managed["managed"] is True
        assert managed["running"] is True
        assert managed["healthy"] is True
        assert managed["port"] == port
        assert api.relay_state_path().exists()
    finally:
        if started is not None or api.relay_state_path().exists():
            stopped = api.stop_local_relay()
            assert stopped.get("action_ok") is not False, stopped.get("error")

    assert api.relay_state_path().exists() is False
    assert api._probe_relay_health(f"http://127.0.0.1:{port}")["ok"] is False
