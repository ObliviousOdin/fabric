"""Tests for the fabric-achievements team leaderboard client + backend helpers.

These exercise the invite codec, the points/profile model, the ``RelayClient``,
and the ``team_*`` backend helpers against an in-process relay store, plus one
real managed-relay lifecycle smoke test. ``FABRIC_HOME`` is isolated throughout.
"""
from __future__ import annotations

import asyncio
import base64
import importlib.util
import json
import multiprocessing
import os
import socket
import stat
import time
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


def test_invite_rejects_oversized_code_before_decoding(api):
    oversized = api.INVITE_PREFIX + ("A" * api.MAX_INVITE_CODE_LENGTH)

    with pytest.raises(ValueError, match="too large"):
        api.decode_invite(oversized)

    wrapped = ('"' * api.MAX_INVITE_CODE_LENGTH) + "fbl1_A"
    with pytest.raises(ValueError, match="too large"):
        api.decode_invite(wrapped)


def test_invite_rejects_decoded_payload_over_size_limit(api):
    payload = {
        "v": 1,
        "relay": "https://relay.example",
        "team_id": "tm_large",
        "team_name": "Crew",
        "secret": "s" * api.MAX_INVITE_PAYLOAD_LENGTH,
    }
    token = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")
    assert len(api.INVITE_PREFIX + token) < api.MAX_INVITE_CODE_LENGTH

    with pytest.raises(ValueError, match="Malformed invite code"):
        api.decode_invite(api.INVITE_PREFIX + token)


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"v": 1, "relay": "https://relay.example", "team_id": "tm", "secret": ""},
        {"v": 1, "relay": "https://user:password@relay.example", "team_id": "tm", "secret": "sek"},
    ],
)
def test_invite_rejects_invalid_or_credentialed_payloads(api, payload):
    token = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")

    with pytest.raises(ValueError):
        api.decode_invite(api.INVITE_PREFIX + token)


def test_invite_rejects_non_http_relay(api):
    with pytest.raises(ValueError):
        api._validate_relay_url("ftp://evil/relay")
    with pytest.raises(ValueError):
        api._validate_relay_url("")
    for url in ("http://relay.example:0", "https://relay.example:0"):
        with pytest.raises(ValueError, match="invalid port"):
            api._validate_relay_url(url)


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


def test_relay_keeps_committed_state_when_directory_fsync_fails(tmp_path, monkeypatch):
    store_mod = _load(STORE_PATH, f"lb_store_dir_fsync_{id(tmp_path)}")
    roster_path = tmp_path / "state" / "roster.json"
    relay = store_mod.LeaderboardStore(roster_path)
    original_fsync = store_mod.os.fsync
    calls = 0

    def fail_directory_fsync(fd):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("directory fsync unsupported")
        return original_fsync(fd)

    monkeypatch.setattr(store_mod.os, "fsync", fail_directory_fsync)
    owner = relay.create_team(name="Crew", display_name="Owner")

    assert calls == 2
    assert owner["team_id"] in relay._teams
    assert owner["team_id"] in store_mod.LeaderboardStore(roster_path)._teams


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


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits only")
def test_relay_roster_file_hardens_when_parent_chmod_fails(tmp_path, monkeypatch):
    store_mod = _load(STORE_PATH, f"lb_store_parent_modes_{id(tmp_path)}")
    roster_path = tmp_path / "state" / "roster.json"
    relay = store_mod.LeaderboardStore(roster_path)
    owner = relay.create_team(name="Crew", display_name="Owner")
    roster_path.chmod(0o644)
    original_chmod = Path.chmod

    def selective_chmod(path, mode):
        if path == roster_path.parent:
            raise PermissionError("parent owned elsewhere")
        return original_chmod(path, mode)

    monkeypatch.setattr(Path, "chmod", selective_chmod)
    hardened = store_mod.LeaderboardStore(roster_path)

    assert stat.S_IMODE(roster_path.stat().st_mode) == 0o600
    assert hardened.unpublish(
        team_id=owner["team_id"],
        member_id=owner["member_id"],
        member_token=owner["member_token"],
    ) == {"ok": True}


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
    assert state["error"] == "The relay could not complete the request."
    assert state["last_error"] == "A leaderboard action needs attention."
    assert "unpublish refused" not in json.dumps(state)

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
    assert state["publish_error"] == "The latest leaderboard publish failed."
    assert state["last_error"] == "A leaderboard action needs attention."
    assert state["error"] == "The relay could not complete the request."
    assert "publish refused" not in json.dumps(state)


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


def test_join_route_preserves_business_error_when_preflight_changes(api, monkeypatch):
    class Request:
        async def json(self):
            return {
                "invite_code": _diagnostic_invite(api, "https://relay.example"),
                "display_name": "Member",
                "publish_opt_in": True,
            }

    async def direct(fn, *args):
        return fn(*args)

    def full(*_args, **_kwargs):
        raise api.RelayClientError("team is full", status=409)

    monkeypatch.setattr(api, "_run", direct)
    monkeypatch.setattr(api, "team_join", full)
    monkeypatch.setattr(
        api,
        "team_preflight",
        lambda *_args, **_kwargs: {
            "state": "HOST_OFFLINE",
            "message": "A later diagnostic happened to fail.",
        },
    )

    result = asyncio.run(api.post_team_join(Request()))

    assert result == {"ok": False, "error": "team is full"}


def test_default_transport_rejects_oversized_response_body(api, monkeypatch):
    class OversizedResponse:
        remaining = api.MAX_RELAY_RESPONSE_BYTES + 1

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def getcode(self):
            return 200

        def read1(self, limit):
            amount = min(limit, self.remaining)
            self.remaining -= amount
            return b"x" * amount

    class Opener:
        def open(self, *_args, **_kwargs):
            return OversizedResponse()

    monkeypatch.setattr(api, "_relay_opener", lambda _url: Opener())

    with pytest.raises(api.RelayClientError) as exc:
        api._default_transport("GET", "https://relay.example/health", {}, None)

    assert exc.value.status == 502
    assert "size limit" in exc.value.message


def test_relay_opener_blocks_redirects_and_keeps_private_credentials_off_proxy(
    api, monkeypatch
):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:8080")
    monkeypatch.setenv("NO_PROXY", "")

    assert api._relay_opener("http://100.64.0.8:9137/path") is api._DIRECT_RELAY_OPENER
    assert api._relay_opener("https://node.tail1234.ts.net/path") is api._DIRECT_RELAY_OPENER

    funnel = api._proxy_aware_https_opener("https://node.tail1234.ts.net/path")
    funnel_proxy_handlers = [
        handler
        for handler in funnel.handlers
        if isinstance(handler, api.urllib.request.ProxyHandler)
    ]
    assert funnel_proxy_handlers
    assert any(
        "proxy.invalid" in value
        for value in funnel_proxy_handlers[0].proxies.values()
    )

    public = api._relay_opener("https://relay.example/path")
    proxy_handlers = [
        handler
        for handler in public.handlers
        if isinstance(handler, api.urllib.request.ProxyHandler)
    ]
    assert proxy_handlers
    assert any("proxy.invalid" in value for value in proxy_handlers[0].proxies.values())
    assert api._NoRelayRedirects().redirect_request(None, None, 302) is None


def test_default_transport_enforces_total_deadline_and_recovers_worker_slot(
    api, monkeypatch
):
    class SlowResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()
            return False

        def getcode(self):
            return 200

        def read1(self, _limit):
            time.sleep(0.03)
            return b"x"

        def close(self):
            return None

    class Opener:
        def open(self, *_args, **_kwargs):
            return SlowResponse()

    slots = api.threading.BoundedSemaphore(1)
    monkeypatch.setattr(api, "TEAM_HTTP_TIMEOUT", 0.1)
    monkeypatch.setattr(api, "_RELAY_REQUEST_SLOTS", slots)
    monkeypatch.setattr(api, "_relay_opener", lambda _url: Opener())

    started = time.monotonic()
    with pytest.raises(api.RelayClientError):
        api._default_transport("GET", "https://relay.example/health", {}, None)
    assert time.monotonic() - started < 0.4

    deadline = time.monotonic() + 0.5
    acquired = False
    while time.monotonic() < deadline:
        acquired = slots.acquire(blocking=False)
        if acquired:
            break
        time.sleep(0.01)
    assert acquired is True
    slots.release()


def test_dns_probe_has_bounded_wait_and_bounded_quarantine(api, monkeypatch):
    slots = api.threading.BoundedSemaphore(1)
    monkeypatch.setattr(api, "DNS_PROBE_TIMEOUT", 0.05)
    monkeypatch.setattr(api, "_NETWORK_PROBE_SLOTS", slots)
    monkeypatch.setattr(
        api.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: time.sleep(0.2) or [],
    )

    started = time.monotonic()
    assert api._resolve_host("slow.example", 443) is False
    assert time.monotonic() - started < 0.15
    # The only quarantine slot is still occupied, so a second call fails fast
    # instead of creating an unbounded resolver thread.
    started = time.monotonic()
    assert api._resolve_host("slow-again.example", 443) is False
    assert time.monotonic() - started < 0.05


def test_relay_unreachable_on_read_returns_error_payload(api, store):
    st, store_mod = store
    good = _make_transport(st, store_mod)
    api.team_create("http://relay.test", "Crew", "Channa", publish_opt_in=True, transport=good)
    membership = api.load_team_config()["membership"]
    raw_invite = api.encode_invite(
        membership["relay_url"],
        membership["team_id"],
        membership["team_name"],
        membership["join_secret"],
    )

    def dead(method, url, headers, body):
        raise api.RelayClientError(
            "transport included "
            f"{raw_invite} {membership['join_secret']} {membership['member_token']}",
            status=0,
        )

    # Reading the board with a dead relay is non-fatal — local membership
    # stays intact and the caller gets a structured, sanitized diagnostic.
    state = api.team_leaderboard(transport=dead)
    assert state["ok"] is False
    assert state["connection"]["state"] == "HOST_OFFLINE"
    assert state["error"] == "Could not reach the relay."
    displayed_errors = json.dumps({
        "error": state["error"],
        "publish_error": state["publish_error"],
        "last_error": state["last_error"],
        "connection": state["connection"],
    })
    for forbidden in [
        raw_invite,
        membership["join_secret"],
        membership["member_token"],
        "transport included",
    ]:
        assert forbidden not in displayed_errors
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


@pytest.mark.parametrize(
    "response",
    [
        {"ok": True},
        {"ok": True, "join_secret": ""},
        {"ok": True, "join_secret": "   "},
        {"ok": True, "join_secret": " padded "},
    ],
)
def test_rotate_requires_new_invite_secret(api, response):
    client = api.RelayClient(
        "http://relay.test",
        transport=lambda *_args: (200, response),
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


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits only")
def test_team_config_file_hardens_when_parent_chmod_fails(api, monkeypatch):
    cfg_path = api.team_config_path()
    api.save_team_config(api._default_team_config())
    cfg_path.chmod(0o644)
    original_chmod = Path.chmod

    def selective_chmod(path, mode):
        if path == cfg_path.parent:
            raise PermissionError("parent owned elsewhere")
        return original_chmod(path, mode)

    monkeypatch.setattr(Path, "chmod", selective_chmod)
    api.load_team_config()

    assert stat.S_IMODE(cfg_path.stat().st_mode) == 0o600


# ---- hosting detection (auto-fill the relay URL) -------------------------
def _healthy_relay_transport(schema_version=1, teams=2, members=5):
    """Transport that answers GET /health like a real relay's stats()."""
    def transport(method, url, headers, body):
        assert method == "GET" and url.endswith("/health"), (method, url)
        return 200, {"teams": teams, "members": members, "schema_version": schema_version}
    return transport


def _ts_status_json(
    dns="my-box.tail1234.ts.net.",
    ips=("100.101.102.103", "fd7a::1"),
    state="Running",
    tailnet_dns_suffix="tail1234.ts.net.",
):
    return json.dumps({
        "BackendState": state,
        "CurrentTailnet": {"MagicDNSSuffix": tailnet_dns_suffix},
        "Self": {"DNSName": dns, "TailscaleIPs": list(ips)},
    })


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
    assert result["error"] == "Could not reach the relay."
    assert "Connection refused" not in json.dumps(result)


def test_probe_relay_health_treats_nonzero_transport_status_as_reachable(api):
    def overloaded(method, url, headers, body):
        raise api.RelayClientError("sensitive upstream detail", status=503)

    result = api._probe_relay_health("https://relay.example", transport=overloaded)

    assert result == {
        "ok": False,
        "reachable": True,
        "error": "Relay returned HTTP 503.",
    }
    assert "sensitive" not in json.dumps(result)


def test_probe_relay_health_rejects_a_bad_url(api):
    result = api._probe_relay_health("not-a-url")
    assert result["ok"] is False
    assert "http(s) URL" in result["error"]


class _FakeTailscaleStatus:
    """Mirror of fabric_cli.tailscale_setup.TailscaleStatus for the reused seam."""

    def __init__(
        self,
        *,
        running,
        dns_name=None,
        ip=None,
        backend_state="Running",
        tailnet_dns_suffix=None,
    ):
        self.is_running = running
        self.dns_name = dns_name
        self.ip = ip
        self.backend_state = backend_state
        self.tailnet_dns_suffix = tailnet_dns_suffix


def _use_tailscale(monkeypatch, api, *, binary="/usr/bin/tailscale", status=None):
    """Point the reused ``fabric_cli.tailscale_setup`` seam at fakes.

    detect_tailscale prefers these helpers; setting both to non-None forces the
    reuse path (not the direct-probe fallback).
    """
    monkeypatch.setattr(api, "_ts_find_binary", lambda: binary)
    monkeypatch.setattr(api, "_ts_status", lambda b: status)


def _no_tailscale(monkeypatch, api):
    _use_tailscale(monkeypatch, api, binary=None)


# ---- layered relay diagnostics ------------------------------------------
def _preflight_transport(
    api,
    *,
    health_status=200,
    health_payload=None,
    leaderboard_status=200,
    leaderboard_payload=None,
    calls=None,
):
    """Deterministic transport for health + credential preflight requests."""
    health_payload = health_payload or {
        "schema_version": 1,
        "teams": 3,
        "members": 12,
    }
    leaderboard_payload = leaderboard_payload or {
        "team_name": "Crew",
        "member_count": 1,
        "leaderboard": [],
    }

    def transport(method, url, headers, body):
        path = urllib.parse.urlparse(url).path
        if calls is not None:
            calls.append({"method": method, "path": path, "headers": dict(headers)})
        if method == "GET" and path == "/health":
            return health_status, health_payload
        if method == "GET" and path.endswith("/leaderboard"):
            return leaderboard_status, leaderboard_payload
        raise AssertionError(f"unexpected diagnostic request: {method} {path}")

    return transport


def _tailnet_status(*, installed=True, running=True, suffix="tail1234.ts.net"):
    return {
        "installed": installed,
        "running": running,
        "backend_state": "Running" if running else "Stopped",
        "magicdns": "this-node.tail1234.ts.net" if running else None,
        "tailnet_dns_suffix": suffix,
        "ipv4": "100.64.0.8" if running else None,
        "ipv6": None,
        "ips": ["100.64.0.8"] if running else [],
    }


def _diagnostic_invite(api, relay="http://relay.tail1234.ts.net:9137"):
    return api.encode_invite(relay, "tm_diag", "Diagnostic Crew", "join-secret-46")


@pytest.mark.parametrize(
    ("tailscale", "expected_state"),
    [
        (_tailnet_status(installed=False, running=False), "TAILSCALE_MISSING"),
        (_tailnet_status(installed=True, running=False), "TAILSCALE_DISCONNECTED"),
    ],
)
def test_preflight_stops_at_tailscale_prerequisite(
    api, monkeypatch, tailscale, expected_state
):
    monkeypatch.setattr(api, "detect_tailscale", lambda: tailscale)

    result = api.team_preflight(
        _diagnostic_invite(api),
        transport=lambda *_args: pytest.fail("relay transport must not run"),
        dns_resolver=lambda *_args: pytest.fail("DNS must not run"),
        host_probe=lambda *_args: pytest.fail("host probe must not run"),
        tcp_probe=lambda *_args: pytest.fail("TCP must not run"),
    )

    assert result["state"] == expected_state
    assert result["actor"] == "member"
    assert result["can_join"] is False
    assert result["can_restart"] is False
    assert result["checks"][-1] == {"name": "tailscale", "status": "fail"}


def test_preflight_distinguishes_unverified_tailscale_status_from_disconnected(
    api, monkeypatch
):
    status = _tailnet_status(installed=True, running=False)
    status["status_verified"] = False
    monkeypatch.setattr(api, "detect_tailscale", lambda: status)

    result = api.team_preflight(
        _diagnostic_invite(api),
        transport=lambda *_args: pytest.fail("unverified status stops before HTTP"),
    )

    assert result["state"] == "TAILSCALE_UNAVAILABLE"
    assert result["checks"][-1] == {"name": "tailscale", "status": "unavailable"}
    assert "disconnected" not in result["message"].casefold()


def test_preflight_reports_wrong_tailnet_only_for_definitive_suffix_mismatch(
    api, monkeypatch
):
    monkeypatch.setattr(
        api,
        "detect_tailscale",
        lambda: _tailnet_status(suffix="different-tailnet.ts.net"),
    )

    result = api.team_preflight(
        _diagnostic_invite(api),
        transport=lambda *_args: pytest.fail("relay transport must not run"),
        dns_resolver=lambda *_args: pytest.fail("DNS must not run"),
        host_probe=lambda *_args: pytest.fail("host probe must not run"),
        tcp_probe=lambda *_args: pytest.fail("TCP must not run"),
    )

    assert result["state"] == "WRONG_TAILNET"
    assert result["checks"][-1] == {"name": "tailnet", "status": "fail"}

    # An absent suffix or a tailnet IP cannot prove a mismatch. Those targets
    # continue to the reachability layers instead of making a false claim.
    assert api._wrong_tailnet(
        "relay.tail1234.ts.net", _tailnet_status(suffix=None)
    ) is False
    assert api._wrong_tailnet(
        "100.64.0.44", _tailnet_status(suffix="different-tailnet.ts.net")
    ) is False


@pytest.mark.parametrize("failed_layer", ["dns", "host"])
def test_preflight_reports_host_offline_at_dns_or_tailnet_host_layer(
    api, monkeypatch, failed_layer
):
    monkeypatch.setattr(api, "detect_tailscale", _tailnet_status)
    calls = []

    def resolve(_host, _port):
        calls.append("dns")
        return failed_layer != "dns"

    def probe_host(_host):
        calls.append("host")
        return failed_layer != "host"

    result = api.team_preflight(
        _diagnostic_invite(api),
        transport=lambda *_args: pytest.fail("relay transport must not run"),
        dns_resolver=resolve,
        host_probe=probe_host,
        tcp_probe=lambda *_args: pytest.fail("TCP must not run"),
    )

    assert result["state"] == "HOST_OFFLINE"
    assert result["checks"][-1] == {"name": failed_layer, "status": "fail"}
    assert calls == (["dns"] if failed_layer == "dns" else ["dns", "host"])


@pytest.mark.parametrize(
    ("failing_probe", "expected_state", "failed_check"),
    [
        ("dns", "HOST_OFFLINE", "dns"),
        ("host", "HOST_PROBE_UNAVAILABLE", "tcp"),
        ("tcp", "HOST_REACHABLE_RELAY_DOWN", "tcp"),
    ],
)
def test_preflight_probe_exceptions_degrade_to_diagnostic_state(
    api, monkeypatch, failing_probe, expected_state, failed_check
):
    monkeypatch.setattr(api, "detect_tailscale", _tailnet_status)

    def probe(name):
        def run(*_args):
            if name == failing_probe:
                raise OSError(f"{name} probe exploded with join-secret-46")
            return True

        return run

    result = api.team_preflight(
        _diagnostic_invite(api),
        transport=lambda *_args: pytest.fail("HTTP must not run after probe failure"),
        dns_resolver=probe("dns"),
        host_probe=probe("host"),
        tcp_probe=(lambda *_args: False) if failing_probe == "host" else probe("tcp"),
    )

    assert result["state"] == expected_state
    assert result["checks"][-1] == {"name": failed_check, "status": "fail"}
    assert "probe exploded" not in json.dumps(result)
    assert "join-secret-46" not in json.dumps(result)


@pytest.mark.parametrize(
    ("probe_result", "tcp_result", "expected_state"),
    [
        ((False, "unreachable"), True, "HOST_OFFLINE"),
        ((False, "timeout"), False, "HOST_PROBE_UNAVAILABLE"),
        ((False, "unavailable"), False, "HOST_PROBE_UNAVAILABLE"),
        ((False, "invalid_target"), False, "HOST_PROBE_UNAVAILABLE"),
    ],
)
def test_preflight_preserves_tailscale_ping_outcomes(
    api, monkeypatch, probe_result, tcp_result, expected_state
):
    monkeypatch.setattr(api, "detect_tailscale", _tailnet_status)

    result = api.team_preflight(
        _diagnostic_invite(api),
        transport=lambda *_args: pytest.fail("failed host/TCP layer stops before HTTP"),
        dns_resolver=lambda *_args: True,
        host_probe=lambda *_args: probe_result,
        tcp_probe=lambda *_args: tcp_result,
    )

    assert result["state"] == expected_state


def test_tailnet_probe_fallback_does_not_call_cli_failure_host_offline(api, monkeypatch):
    monkeypatch.setattr(api, "_ts_find_binary", None)
    monkeypatch.setattr(api, "_ts_ping", None)
    monkeypatch.setattr(api, "_run_tailscale", lambda *_args, **_kwargs: (-1, ""))

    assert api._probe_tailnet_host("node.tail1234.ts.net") == (False, "unavailable")


def test_preflight_redacts_credentials_embedded_in_preview_fields(api):
    secret = "private-secret-46"
    invite = api.encode_invite(
        f"https://{secret}.relay.example",
        "tm_private_46",
        f"Crew — {secret} — HQ",
        secret,
    )

    result = api.team_preflight(
        invite,
        transport=_preflight_transport(api),
    )

    assert result["state"] == "CONNECTED"
    assert result["preview"]["team_name"] == "Team"
    assert result["preview"]["relay_host"] == "[redacted relay host]"
    assert secret not in json.dumps(result)


def test_preflight_distinguishes_reachable_tailscale_host_from_dead_relay_port(
    api, monkeypatch
):
    monkeypatch.setattr(api, "detect_tailscale", _tailnet_status)
    probes = []

    result = api.team_preflight(
        _diagnostic_invite(api),
        transport=lambda *_args: pytest.fail("HTTP must not run after TCP failure"),
        dns_resolver=lambda host, port: probes.append(("dns", host, port)) or True,
        host_probe=lambda host: probes.append(("host", host)) or True,
        tcp_probe=lambda host, port: probes.append(("tcp", host, port)) or False,
    )

    assert result["state"] == "HOST_REACHABLE_RELAY_DOWN"
    assert result["title"] == "Leaderboard relay is down"
    assert result["message"] == (
        "The relay host is online, but its Fabric leaderboard relay is not "
        "responding on port 9137. Your Tailscale connection is working. "
        "Ask the team owner to restart it."
    )
    assert result["checks"][-3:] == [
        {"name": "dns", "status": "pass"},
        {"name": "host", "status": "pass"},
        {"name": "tcp", "status": "fail"},
    ]
    assert probes == [
        ("dns", "relay.tail1234.ts.net", 9137),
        ("host", "relay.tail1234.ts.net"),
        ("tcp", "relay.tail1234.ts.net", 9137),
    ]


def test_preflight_reports_relay_down_when_tcp_connects_but_health_fails(
    api, monkeypatch
):
    monkeypatch.setattr(api, "detect_tailscale", _tailnet_status)
    transport = _preflight_transport(
        api,
        health_status=503,
        health_payload={"error": "join-secret-46 should never be echoed"},
    )

    result = api.team_preflight(
        _diagnostic_invite(api),
        transport=transport,
        dns_resolver=lambda *_args: True,
        host_probe=lambda *_args: True,
        tcp_probe=lambda *_args: True,
    )

    assert result["state"] == "HOST_REACHABLE_RELAY_DOWN"
    assert result["checks"][-1] == {"name": "health", "status": "fail"}
    assert "join-secret-46" not in json.dumps(result)


def test_preflight_reports_reachable_relay_with_rejected_credentials(
    api, monkeypatch
):
    monkeypatch.setattr(api, "detect_tailscale", _tailnet_status)
    calls = []
    transport = _preflight_transport(
        api,
        leaderboard_status=403,
        leaderboard_payload={"error": "bad credential join-secret-46"},
        calls=calls,
    )

    result = api.team_preflight(
        _diagnostic_invite(api),
        transport=transport,
        dns_resolver=lambda *_args: True,
        host_probe=lambda *_args: True,
        tcp_probe=lambda *_args: True,
    )

    assert result["state"] == "RELAY_REACHABLE_INVITE_INVALID"
    assert result["message"] == (
        "The relay is reachable, but these team credentials were rejected. "
        "Ask the team owner for a fresh invite."
    )
    assert result["checks"][-1] == {"name": "credentials", "status": "fail"}
    assert calls[-1]["headers"]["X-Join-Secret"] == "join-secret-46"
    assert "join-secret-46" not in json.dumps(result)


@pytest.mark.parametrize("status", [429, 500, 503])
def test_preflight_treats_transient_leaderboard_failures_as_relay_down(
    api, monkeypatch, status
):
    monkeypatch.setattr(api, "detect_tailscale", _tailnet_status)
    transport = _preflight_transport(
        api,
        leaderboard_status=status,
        leaderboard_payload={"error": "transient join-secret-46"},
    )

    result = api.team_preflight(
        _diagnostic_invite(api),
        transport=transport,
        dns_resolver=lambda *_args: True,
        host_probe=lambda *_args: True,
        tcp_probe=lambda *_args: True,
    )

    assert result["state"] == "HOST_REACHABLE_RELAY_DOWN"
    assert result["checks"][-1] == {"name": "credentials", "status": "fail"}
    assert "join-secret-46" not in json.dumps(result)


def test_preflight_connected_after_all_layers_pass(api, monkeypatch):
    monkeypatch.setattr(api, "detect_tailscale", _tailnet_status)

    result = api.team_preflight(
        _diagnostic_invite(api),
        transport=_preflight_transport(api),
        dns_resolver=lambda *_args: True,
        host_probe=lambda *_args: True,
        tcp_probe=lambda *_args: True,
    )

    assert result["state"] == "CONNECTED"
    assert result["can_join"] is True
    assert result["retryable"] is False
    assert result["can_restart"] is False
    assert result["checks"][-1] == {"name": "credentials", "status": "pass"}


def test_public_https_relay_bypasses_tailscale_and_host_probe(api, monkeypatch):
    monkeypatch.setattr(
        api,
        "detect_tailscale",
        lambda: pytest.fail("public relays must not require Tailscale"),
    )
    invite = _diagnostic_invite(api, "https://relay.example")
    calls = []

    result = api.team_preflight(
        invite,
        transport=_preflight_transport(api),
        dns_resolver=lambda host, port: calls.append(("dns", host, port)) or True,
        host_probe=lambda *_args: pytest.fail("public relays skip Tailscale ping"),
        tcp_probe=lambda host, port: calls.append(("tcp", host, port)) or True,
    )

    assert result["state"] == "CONNECTED"
    assert result["diagnostic"]["tailscale_required"] is False
    assert result["checks"][1:3] == [
        {"name": "tailscale", "status": "skipped"},
        {"name": "tailnet", "status": "skipped"},
    ]
    assert {"name": "host", "status": "skipped"} in result["checks"]
    assert calls == []


def test_https_ts_net_reports_tailscale_requirement_when_route_probes_fail(
    api, monkeypatch
):
    monkeypatch.setattr(
        api,
        "detect_tailscale",
        lambda: _tailnet_status(installed=False, running=False),
    )
    https_invite = _diagnostic_invite(api, "https://relay.tail1234.ts.net")
    calls = []

    def unavailable_direct_probe(method, url, headers, body):
        calls.append((method, urllib.parse.urlparse(url).path, dict(headers), body))
        raise api.RelayClientError("route unavailable", status=0)

    result = api.team_preflight(
        https_invite,
        transport=unavailable_direct_probe,
        dns_resolver=lambda *_args: pytest.fail("private target stops before DNS"),
        host_probe=lambda *_args: pytest.fail("private target stops before ping"),
        tcp_probe=lambda *_args: pytest.fail("private target stops before TCP"),
    )

    assert result["state"] == "TAILSCALE_MISSING"
    assert result["diagnostic"]["tailscale_required"] is True
    assert calls == [("GET", "/health", {"Accept": "application/json"}, None)]
    assert api._is_tailnet_target(
        "relay.tail1234.ts.net", "https://relay.tail1234.ts.net"
    ) is True
    assert api._is_tailnet_target(
        "relay.tail1234.ts.net", "https://relay.tail1234.ts.net:9137"
    ) is True


def test_https_ts_net_usable_route_works_without_connected_tailscale(
    api, monkeypatch
):
    monkeypatch.setattr(
        api,
        "detect_tailscale",
        lambda: _tailnet_status(installed=False, running=False),
    )
    calls = []
    invite = _diagnostic_invite(api, "https://relay.tail1234.ts.net")

    result = api.team_preflight(
        invite,
        transport=_preflight_transport(api, calls=calls),
        dns_resolver=lambda *_args: pytest.fail("usable HTTPS route skips private DNS"),
        host_probe=lambda *_args: pytest.fail("usable HTTPS route skips Tailscale ping"),
        tcp_probe=lambda *_args: pytest.fail("usable HTTPS route skips private TCP"),
    )

    assert result["state"] == "CONNECTED"
    assert result["diagnostic"]["tailscale_required"] is False
    assert [call["path"] for call in calls] == [
        "/health",
        "/api/teams/tm_diag/leaderboard",
    ]
    assert "X-Join-Secret" not in calls[0]["headers"]
    assert calls[1]["headers"]["X-Join-Secret"] == "join-secret-46"


def test_https_ts_net_usable_route_survives_unverified_tailscale_status(
    api, monkeypatch
):
    status = _tailnet_status()
    status["status_verified"] = False
    monkeypatch.setattr(api, "detect_tailscale", lambda: status)
    calls = []

    result = api.team_preflight(
        _diagnostic_invite(api, "https://relay.tail1234.ts.net"),
        transport=_preflight_transport(api, calls=calls),
        dns_resolver=lambda *_args: pytest.fail("usable route skips private DNS"),
        host_probe=lambda *_args: pytest.fail("usable route skips Tailscale ping"),
        tcp_probe=lambda *_args: pytest.fail("usable route skips private TCP"),
    )

    assert result["state"] == "CONNECTED"
    assert result["diagnostic"]["tailscale_required"] is False
    assert [call["path"] for call in calls] == [
        "/health",
        "/api/teams/tm_diag/leaderboard",
    ]


def test_https_ts_net_private_serve_keeps_connected_tailscale_diagnostics_direct(
    api, monkeypatch
):
    monkeypatch.setattr(api, "detect_tailscale", _tailnet_status)
    monkeypatch.setattr(
        api,
        "_proxy_aware_https_transport",
        lambda *_args: pytest.fail("connected private Serve must stay direct"),
    )
    calls = []

    result = api.team_preflight(
        _diagnostic_invite(api, "https://relay.tail1234.ts.net"),
        transport=_preflight_transport(api, calls=calls),
        dns_resolver=lambda *_args: True,
        host_probe=lambda *_args: (True, "reachable"),
        tcp_probe=lambda *_args: True,
    )

    assert result["state"] == "CONNECTED"
    assert result["diagnostic"]["tailscale_required"] is True
    assert result["checks"][1:5] == [
        {"name": "tailscale", "status": "pass"},
        {"name": "tailnet", "status": "pass"},
        {"name": "dns", "status": "pass"},
        {"name": "host", "status": "pass"},
    ]
    assert [call["path"] for call in calls] == [
        "/health",
        "/api/teams/tm_diag/leaderboard",
    ]


def test_relay_client_selects_proxy_only_after_direct_health_fails(
    api, monkeypatch
):
    calls = []

    def direct_transport(method, url, headers, body):
        calls.append(("direct", urllib.parse.urlparse(url).path, dict(headers)))
        raise api.RelayClientError("direct route unavailable", status=0)

    def proxy_transport(method, url, headers, body):
        calls.append(("proxy", urllib.parse.urlparse(url).path, dict(headers)))
        if url.endswith("/health"):
            return 200, {"schema_version": 1, "teams": 1, "members": 1}
        return 200, {"leaderboard": [], "member_count": 1}

    monkeypatch.setattr(api, "_default_transport", direct_transport)
    monkeypatch.setattr(api, "_proxy_aware_https_transport", proxy_transport)

    result = api.RelayClient(
        "https://relay.tail1234.ts.net"
    ).leaderboard("tm_diag", join_secret="join-secret-46")

    assert result["leaderboard"] == []
    assert calls[0] == ("direct", "/health", {"Accept": "application/json"})
    assert calls[1] == ("proxy", "/health", {"Accept": "application/json"})
    assert calls[2][0:2] == (
        "proxy",
        "/api/teams/tm_diag/leaderboard",
    )
    assert calls[2][2]["X-Join-Secret"] == "join-secret-46"


def test_proxy_route_keeps_its_budget_after_direct_route_times_out(
    api, monkeypatch
):
    clock = [100.0]
    monkeypatch.setattr(api.time, "monotonic", lambda: clock[0])

    def timed_out_direct(*_args):
        clock[0] += api.AMBIGUOUS_HTTPS_HEALTH_TIMEOUT
        raise api.RelayClientError("direct route timed out", status=0)

    def healthy_proxy(method, url, headers, body):
        assert api._remaining_network_timeout(api.TEAM_HTTP_TIMEOUT) > 0
        assert (method, urllib.parse.urlparse(url).path, headers, body) == (
            "GET",
            "/health",
            {"Accept": "application/json"},
            None,
        )
        return 200, {"schema_version": 1, "teams": 1, "members": 1}

    route, health = api._probe_ambiguous_https_route(
        "https://relay.tail1234.ts.net",
        direct_transport=timed_out_direct,
        proxy_transport=healthy_proxy,
    )

    assert route is healthy_proxy
    assert health["ok"] is True


def test_relay_client_prefers_direct_route_before_proxy_for_private_serve(
    api, monkeypatch
):
    proxy_calls = []
    direct_calls = []

    def proxy_transport(method, url, headers, body):
        proxy_calls.append((urllib.parse.urlparse(url).path, dict(headers), body))
        raise AssertionError("a healthy direct route must win")

    def direct_transport(method, url, headers, body):
        direct_calls.append((urllib.parse.urlparse(url).path, dict(headers)))
        if url.endswith("/health"):
            return 200, {"schema_version": 1, "teams": 1, "members": 1}
        return 200, {"leaderboard": [], "member_count": 1}

    monkeypatch.setattr(api, "_proxy_aware_https_transport", proxy_transport)
    monkeypatch.setattr(api, "_default_transport", direct_transport)

    api.RelayClient("https://relay.tail1234.ts.net").leaderboard(
        "tm_diag", join_secret="join-secret-46"
    )

    assert proxy_calls == []
    assert direct_calls[0] == ("/health", {"Accept": "application/json"})
    assert direct_calls[1][1]["X-Join-Secret"] == "join-secret-46"


def _save_diagnostic_membership(api, *, role="owner", relay_url="http://100.64.0.8:9137"):
    config = api._default_team_config()
    config["membership"] = {
        "relay_url": relay_url,
        "team_id": "tm_diag",
        "team_name": "Diagnostic Crew",
        "join_secret": "join-secret-46",
        "member_id": "mb_local",
        "member_token": "member-token-46",
        "role": role,
    }
    api.save_team_config(config)


def test_explicit_empty_invite_never_falls_back_to_saved_membership(api):
    _save_diagnostic_membership(api, role="owner")

    result = api.team_preflight(
        invite_code="",
        transport=lambda *_args: pytest.fail("invalid invite must not contact relay"),
    )

    assert result["state"] == "INVITE_INVALID"
    assert result["actor"] == "member"
    assert result["checks"] == [{"name": "invite", "status": "fail"}]


@pytest.mark.parametrize(
    ("role", "expected_actor", "expected_restart"),
    [("owner", "owner", True), ("member", "member", False)],
)
def test_current_membership_diagnostics_identify_actor_and_restart_capability(
    api, monkeypatch, role, expected_actor, expected_restart
):
    _save_diagnostic_membership(api, role=role)
    api.save_relay_state({
        "pid": 424242,
        "port": 9137,
        "host": "100.64.0.8",
        "start_time": 999,
        "started_at": 1_700_000_000,
    })
    monkeypatch.setattr(api, "detect_tailscale", _tailnet_status)
    monkeypatch.setattr(api, "_relay_state_identity", lambda _state: "same")

    result = api.team_preflight(
        transport=lambda *_args: pytest.fail("HTTP must not run after TCP failure"),
        dns_resolver=lambda *_args: True,
        host_probe=lambda *_args: True,
        tcp_probe=lambda *_args: False,
    )

    assert result["state"] == "HOST_REACHABLE_RELAY_DOWN"
    assert result["actor"] == expected_actor
    assert result["can_restart"] is expected_restart
    if expected_restart:
        assert result["message"].endswith("Restart the Fabric leaderboard relay below.")
    else:
        assert result["message"].endswith("Ask the team owner to restart it.")


def test_managed_restart_capability_is_not_exposed_for_wrong_tailnet(
    api, monkeypatch
):
    _save_diagnostic_membership(
        api,
        role="owner",
        relay_url="https://this-node.tail1234.ts.net",
    )
    api.save_relay_state({
        "pid": 424242,
        "port": 9137,
        "host": "100.64.0.8",
        "start_time": 999,
        "started_at": 1_700_000_000,
    })
    monkeypatch.setattr(
        api,
        "detect_tailscale",
        lambda: _tailnet_status(suffix="different-tailnet.ts.net"),
    )
    monkeypatch.setattr(api, "_relay_state_identity", lambda _state: "same")

    def unavailable_route(*_args):
        raise api.RelayClientError("route unavailable", status=0)

    result = api.team_preflight(transport=unavailable_route)

    assert result["state"] == "WRONG_TAILNET"
    assert result["actor"] == "owner"
    assert result["can_restart"] is False


@pytest.mark.parametrize(
    "relay_url",
    [
        "https://this-node.tail1234.ts.net",
        "https://this-node.tail1234.ts.net:443",
    ],
)
def test_managed_restart_accepts_exact_magicdns_https_facade_for_default_relay(
    api, monkeypatch, relay_url
):
    _save_diagnostic_membership(api, role="owner", relay_url=relay_url)
    state = {
        "pid": 424242,
        "port": 9137,
        "host": "100.64.0.8",
        "start_time": 999,
        "started_at": 1_700_000_000,
    }
    monkeypatch.setattr(api, "_relay_state_identity", lambda _state: "same")

    assert api._managed_relay_matches_membership(
        api.load_team_config()["membership"],
        _tailnet_status(),
        state=state,
    ) is True


@pytest.mark.parametrize(
    ("relay_url", "state_host", "state_port"),
    [
        ("https://other.tail1234.ts.net", "100.64.0.8", 9137),
        ("https://this-node.tail1234.ts.net/relay", "100.64.0.8", 9137),
        ("http://this-node.tail1234.ts.net:443", "100.64.0.8", 9137),
        ("https://this-node.tail1234.ts.net", "192.0.2.44", 9137),
        ("https://this-node.tail1234.ts.net", "100.64.0.8", 9000),
    ],
)
def test_managed_restart_rejects_arbitrary_https_facade_mappings(
    api, monkeypatch, relay_url, state_host, state_port
):
    _save_diagnostic_membership(api, role="owner", relay_url=relay_url)
    monkeypatch.setattr(api, "_relay_state_identity", lambda _state: "same")

    assert api._managed_relay_matches_membership(
        api.load_team_config()["membership"],
        _tailnet_status(),
        state={
            "pid": 424242,
            "port": state_port,
            "host": state_host,
            "start_time": 999,
        },
    ) is False


def test_detect_tailscale_absent(api, monkeypatch):
    _use_tailscale(monkeypatch, api, binary=None)
    ts = api.detect_tailscale()
    assert ts == {
        "installed": False,
        "running": False,
        "status_verified": True,
        "magicdns": None,
        "tailnet_dns_suffix": None,
        "ipv4": None,
        "ipv6": None,
        "ips": [],
    }


def test_detect_tailscale_running_reuses_canonical_helper(api, monkeypatch):
    _use_tailscale(monkeypatch, api, status=_FakeTailscaleStatus(
        running=True,
        dns_name="my-box.tail1234.ts.net",
        ip="100.101.102.103",
        tailnet_dns_suffix="tail1234.ts.net",
    ))
    ts = api.detect_tailscale()
    assert ts["installed"] is True and ts["running"] is True
    assert ts["magicdns"] == "my-box.tail1234.ts.net"
    assert ts["tailnet_dns_suffix"] == "tail1234.ts.net"
    assert ts["ipv4"] == "100.101.102.103"
    assert ts["ips"] == ["100.101.102.103"]


def test_detect_tailscale_installed_but_logged_out(api, monkeypatch):
    # A missing status snapshot is unverified, not proof the client logged out.
    _use_tailscale(monkeypatch, api, status=None)
    ts = api.detect_tailscale()
    assert ts["installed"] is True and ts["running"] is False
    assert ts["status_verified"] is False
    assert ts["magicdns"] is None and ts["ipv4"] is None

    _use_tailscale(
        monkeypatch,
        api,
        status=_FakeTailscaleStatus(running=False, backend_state="Stopped"),
    )
    stopped = api.detect_tailscale()
    assert stopped["running"] is False
    assert stopped["status_verified"] is True
    assert stopped["backend_state"] == "Stopped"


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
    assert ts["tailnet_dns_suffix"] == "tail1234.ts.net"
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


def test_stop_local_relay_refuses_process_that_changed_after_restart_check(
    api, monkeypatch
):
    _no_tailscale(monkeypatch, api)
    api.save_relay_state({
        "pid": 424243,
        "port": 9137,
        "host": "127.0.0.1",
        "start_time": 1000,
        "started_at": 1_700_000_001,
    })
    monkeypatch.setattr(api, "_relay_state_identity", lambda _state: "same")
    monkeypatch.setattr(
        api,
        "_terminate_relay_pid",
        lambda *_args: pytest.fail("changed process must not be terminated"),
    )

    def dead(*_args):
        raise api.RelayClientError("refused", status=0)

    result = api.stop_local_relay(
        transport=dead,
        expected_identity=(424242, 999),
    )

    assert result["action_ok"] is False
    assert "changed before restart" in result["error"]
    assert api.load_relay_state()["pid"] == 424243


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
    monkeypatch.setattr(api, "_relay_state_identity", lambda _state: "gone")

    def dead(method, url, headers, body):
        raise api.RelayClientError("refused", status=0)

    status = api.relay_process_status(transport=dead)
    assert status["managed"] is False and status["running"] is False
    assert api.relay_state_path().exists() is True  # read-only: not cleared here


def test_host_status_persists_uptime_bind_and_magicdns_health_telemetry(
    api, monkeypatch
):
    checked_at = 1_700_000_100
    _save_diagnostic_membership(api, role="owner")
    api.save_relay_state({
        "pid": 424242,
        "port": 9137,
        "host": "100.64.0.8",
        "start_time": 999,
        "started_at": checked_at - 100,
        "log": str(api.relay_log_path()),
    })
    monkeypatch.setattr(api, "detect_tailscale", _tailnet_status)
    monkeypatch.setattr(api, "_relay_state_identity", lambda _state: "same")
    monkeypatch.setattr(api.time, "time", lambda: checked_at)

    status = api.host_status(9137, transport=_healthy_relay_transport())

    managed = status["managed_relay"]
    assert managed["running"] is True
    assert managed["bind"] == "100.64.0.8"
    assert managed["uptime_seconds"] == 100
    assert managed["last_health_check_at"] == checked_at
    assert managed["last_successful_health_at"] == checked_at
    assert status["advertised_magicdns_probe"] == {
        "url": "http://this-node.tail1234.ts.net:9137",
        "ok": True,
        "checked_at": checked_at,
        "last_successful_at": checked_at,
    }

    persisted = json.loads(api.relay_health_state_path().read_text(encoding="utf-8"))
    assert persisted == {
        "last_health_check_at": checked_at,
        "last_magicdns_check_at": checked_at,
        "last_successful_health_at": checked_at,
        "last_successful_magicdns_at": checked_at,
        "process_pid": 424242,
        "process_start_time": 999,
    }
    assert not {
        "join_secret", "member_token", "invite_code", "transcript", "metrics"
    } & set(persisted)


def test_health_telemetry_drops_timestamps_from_an_old_process_generation(
    api, monkeypatch
):
    api.save_relay_state({"pid": 22, "start_time": 2200, "host": "127.0.0.1", "port": 9137})
    api.save_relay_health_state({
        "process_pid": 11,
        "process_start_time": 1100,
        "last_successful_health_at": 1_600_000_000,
        "last_successful_magicdns_at": 1_600_000_000,
    })
    monkeypatch.setattr(api.time, "time", lambda: 1_700_000_000)

    result = api._record_relay_health(
        healthy=False,
        magicdns_checked=False,
        magicdns_ok=False,
        expected_identity=(22, 2200),
    )

    assert result == {
        "last_health_check_at": 1_700_000_000,
        "process_pid": 22,
        "process_start_time": 2200,
    }


@pytest.mark.parametrize(
    ("role", "identity"),
    [("member", "same"), ("owner", "unknown"), ("owner", "other")],
)
def test_restart_rejects_unverified_or_non_owner_process(
    api, monkeypatch, role, identity
):
    _save_diagnostic_membership(api, role=role)
    api.save_relay_state({
        "pid": 424242,
        "port": 9137,
        "host": "100.64.0.8",
        "start_time": 999,
        "started_at": 1_700_000_000,
    })
    monkeypatch.setattr(api, "detect_tailscale", _tailnet_status)
    monkeypatch.setattr(api, "_relay_state_identity", lambda _state: identity)
    monkeypatch.setattr(
        api,
        "stop_local_relay",
        lambda **_kwargs: pytest.fail("unauthorized restart must not stop a process"),
    )
    monkeypatch.setattr(
        api,
        "start_local_relay",
        lambda **_kwargs: pytest.fail("unauthorized restart must not spawn a process"),
    )

    result = api.restart_local_relay()

    assert result["ok"] is False
    assert result["action_ok"] is False
    assert "exact managed local process" in result["error"]


def test_restart_preserves_verified_managed_relay_bind_and_port(api, monkeypatch):
    _save_diagnostic_membership(api, role="owner")
    api.save_relay_state({
        "pid": 424242,
        "port": 9137,
        "host": "100.64.0.8",
        "start_time": 999,
        "started_at": 1_700_000_000,
    })
    monkeypatch.setattr(api, "detect_tailscale", _tailnet_status)
    monkeypatch.setattr(api, "_relay_state_identity", lambda _state: "same")
    actions = []

    def stop(*, transport=None, expected_identity=None):
        actions.append(("stop", transport, expected_identity))
        return {"ok": True, "action_ok": True, "managed_relay": {"running": False}}

    def start(*, port, host, spawner=None, transport=None):
        actions.append(("start", port, host, spawner, transport))
        return {"ok": True, "action_ok": True, "managed_relay": {"running": True}}

    monkeypatch.setattr(api, "stop_local_relay", stop)
    monkeypatch.setattr(api, "start_local_relay", start)
    transport = object()
    spawner = object()

    result = api.restart_local_relay(transport=transport, spawner=spawner)

    assert result["restarted"] is True
    assert actions == [
        ("stop", transport, (424242, 999)),
        ("start", 9137, "100.64.0.8", spawner, transport),
    ]


def test_restart_maps_exact_magicdns_https_443_to_managed_default_port(
    api, monkeypatch
):
    _save_diagnostic_membership(
        api,
        role="owner",
        relay_url="https://this-node.tail1234.ts.net",
    )
    api.save_relay_state({
        "pid": 424242,
        "port": 9137,
        "host": "100.64.0.8",
        "start_time": 999,
        "started_at": 1_700_000_000,
    })
    monkeypatch.setattr(api, "detect_tailscale", _tailnet_status)
    monkeypatch.setattr(api, "_relay_state_identity", lambda _state: "same")
    actions = []
    monkeypatch.setattr(
        api,
        "stop_local_relay",
        lambda **kwargs: actions.append(("stop", kwargs["expected_identity"]))
        or {"ok": True, "action_ok": True, "managed_relay": {"running": False}},
    )
    monkeypatch.setattr(
        api,
        "start_local_relay",
        lambda **kwargs: actions.append(("start", kwargs["port"], kwargs["host"]))
        or {"ok": True, "action_ok": True, "managed_relay": {"running": True}},
    )

    result = api.restart_local_relay()

    assert result["restarted"] is True
    assert actions == [
        ("stop", (424242, 999)),
        ("start", 9137, "100.64.0.8"),
    ]


def test_restart_recovers_complete_owner_record_after_managed_process_crashes(
    api, monkeypatch
):
    _save_diagnostic_membership(api, role="owner")
    api.save_relay_state({
        "pid": 424242,
        "port": 9137,
        "host": "100.64.0.8",
        "start_time": 999,
        "started_at": 1_700_000_000,
    })
    monkeypatch.setattr(api, "detect_tailscale", _tailnet_status)
    monkeypatch.setattr(api, "_relay_state_identity", lambda _state: "gone")
    actions = []
    monkeypatch.setattr(
        api,
        "stop_local_relay",
        lambda **kwargs: actions.append(("stop", kwargs["expected_identity"]))
        or {"ok": True, "action_ok": True, "managed_relay": {"running": False}},
    )
    monkeypatch.setattr(
        api,
        "start_local_relay",
        lambda **kwargs: actions.append(("start", kwargs["port"], kwargs["host"]))
        or {"ok": True, "action_ok": True, "managed_relay": {"running": True}},
    )

    result = api.restart_local_relay()

    assert result["restarted"] is True
    assert actions == [("stop", (424242, 999)), ("start", 9137, "100.64.0.8")]


def test_relay_log_view_is_bounded_and_redacts_credentials(api):
    log_path = api.relay_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    noise = [f"noise-line-{index} " + ("x" * 80) for index in range(40)]
    sensitive = [
        "invite=fbl1_dGhpcy1pcy1zZWNyZXQ",
        "join_secret=join-secret-46",
        "member_token=member-token-46",
        "Authorization: Bearer auth-token-46",
        "token=session-token-46",
    ]
    log_path.write_text("\n".join([*noise, *sensitive]), encoding="utf-8")

    result = api.relay_logs(max_bytes=1_024, max_lines=10)

    assert result["ok"] is True
    assert result["truncated"] is True
    assert len(result["log"].splitlines()) <= 10
    assert "[redacted invite]" in result["log"]
    assert "[redacted]" in result["log"]
    for forbidden in [
        "fbl1_dGhpcy1pcy1zZWNyZXQ",
        "join-secret-46",
        "member-token-46",
        "auth-token-46",
        "session-token-46",
    ]:
        assert forbidden not in result["log"]


@pytest.mark.skipif(os.name == "nt", reason="symlink setup differs on Windows")
def test_relay_log_view_rejects_fixed_path_redirected_outside_logs(api, tmp_path):
    log_path = api.relay_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    other_log = log_path.parent / "agent.log"
    other_log.write_text("member_token=must-not-be-read", encoding="utf-8")
    log_path.symlink_to(other_log)

    result = api.relay_logs()

    assert result == {
        "ok": False,
        "error": "The relay log path could not be verified.",
        "log": "",
    }


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO requires POSIX")
def test_relay_log_view_rejects_fifo_without_blocking(api):
    log_path = api.relay_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    os.mkfifo(log_path)

    started = time.monotonic()
    result = api.relay_logs()

    assert time.monotonic() - started < 0.5
    assert result["ok"] is False
    assert result["log"] == ""


def test_relay_log_tail_drops_unredactable_partial_first_line(api):
    log_path = api.relay_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("member_token=" + ("secret-suffix-" * 300), encoding="utf-8")

    result = api.relay_logs(max_bytes=1_024)

    assert result["ok"] is True
    assert result["truncated"] is True
    assert result["log"] == ""


@pytest.mark.skipif(os.name == "nt", reason="link setup differs on Windows")
def test_secure_log_writer_rejects_links_and_hardens_existing_mode(api):
    log_path = api.relay_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    target = log_path.parent / "agent.log"
    target.write_text("private", encoding="utf-8")
    log_path.symlink_to(target)
    with pytest.raises(OSError):
        api._open_secure_log_file(log_path, append=True)

    log_path.unlink()
    log_path.write_text("relay", encoding="utf-8")
    log_path.chmod(0o644)
    with api._open_secure_log_file(log_path, append=True) as handle:
        handle.write(b" ok")
    assert stat.S_IMODE(log_path.stat().st_mode) == 0o600

    hardlink = log_path.parent / "relay-hardlink.log"
    os.link(log_path, hardlink)
    with pytest.raises(OSError):
        api._open_secure_log_file(log_path, append=True)


def test_secure_log_windows_fallback_rejects_parent_identity_swap(
    api, monkeypatch, tmp_path
):
    log_path = api.relay_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    other_parent = tmp_path / "replacement-logs"
    other_parent.mkdir()
    snapshots = iter((os.lstat(log_path.parent), os.lstat(other_parent)))

    monkeypatch.setattr(api.os, "supports_dir_fd", set())
    monkeypatch.setattr(
        api,
        "_secure_log_parent_metadata",
        lambda _parent: next(snapshots),
    )

    with pytest.raises(OSError, match="identity changed"):
        api._open_secure_log_file(log_path, append=True)


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
    monkeypatch.setattr(api, "_signal_relay_pid", lambda pid, force, **_kwargs: signals.append(force) or True)
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


def test_terminate_treats_process_exit_during_signal_race_as_success(
    api, monkeypatch
):
    identities = iter(("same", "gone"))
    monkeypatch.setattr(api, "_relay_process_identity", lambda *_args: next(identities))
    monkeypatch.setattr(api, "_signal_relay_pid", lambda *_args, **_kwargs: False)

    assert api._terminate_relay_pid(123, 456) is True


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
