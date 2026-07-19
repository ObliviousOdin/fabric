"""Regression tests for dashboard profile-scoped skills/toolsets management.

"Set as active" on the Profiles page only flips the sticky ``active_profile``
file (future CLI/gateway runs) — it never retargets the running dashboard
process. Before the ``profile`` parameter existed, toggling a skill after
"activating" a profile silently wrote into the dashboard's own config.
These tests pin the new behavior: reads and writes land in the REQUESTED
profile's FABRIC_HOME, and the dashboard's own profile stays untouched.
"""
import pytest
import yaml


def _write_skill(skills_dir, name, description="test skill"):
    d = skills_dir / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n",
        encoding="utf-8",
    )


@pytest.fixture
def isolated_profiles(tmp_path, monkeypatch, _isolate_fabric_home):
    """Isolated default home + one named profile, each with its own skills."""
    from fabric_constants import get_fabric_home
    from fabric_cli import profiles

    default_home = get_fabric_home()
    profiles_root = default_home / "profiles"
    worker_home = profiles_root / "worker_alpha"
    worker_beta_home = profiles_root / "worker_beta"
    for home in (default_home, worker_home, worker_beta_home):
        (home / "skills").mkdir(parents=True, exist_ok=True)
        (home / "config.yaml").write_text("{}\n", encoding="utf-8")

    _write_skill(default_home / "skills", "dashboard-skill")
    _write_skill(worker_home / "skills", "worker-skill")
    _write_skill(worker_beta_home / "skills", "worker-beta-skill")

    monkeypatch.setattr(profiles, "_get_default_fabric_home", lambda: default_home)
    monkeypatch.setattr(profiles, "_get_profiles_root", lambda: profiles_root)
    return {
        "default": default_home,
        "worker_alpha": worker_home,
        "worker_beta": worker_beta_home,
    }


@pytest.fixture
def client(monkeypatch, isolated_profiles):
    try:
        from starlette.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi/starlette not installed")

    import fabric_state
    from fabric_constants import get_fabric_home
    from fabric_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN

    monkeypatch.setattr(fabric_state, "DEFAULT_DB_PATH", get_fabric_home() / "state.db")
    c = TestClient(app)
    c.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN
    return c


def _load_cfg(home):
    return yaml.safe_load((home / "config.yaml").read_text()) or {}


class TestProfileScopedSkills:
    def test_skills_list_scopes_to_requested_profile(self, client, isolated_profiles):
        resp = client.get("/api/skills", params={"profile": "worker_alpha"})
        assert resp.status_code == 200
        names = {s["name"] for s in resp.json()}
        assert "worker-skill" in names
        assert "dashboard-skill" not in names

    def test_skills_list_without_profile_uses_dashboard_home(
        self, client, isolated_profiles
    ):
        resp = client.get("/api/skills")
        assert resp.status_code == 200
        names = {s["name"] for s in resp.json()}
        assert "dashboard-skill" in names
        assert "worker-skill" not in names

    def test_toggle_writes_into_target_profile_only(self, client, isolated_profiles):
        resp = client.put(
            "/api/skills/toggle",
            json={"name": "worker-skill", "enabled": False, "profile": "worker_alpha"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "name": "worker-skill", "enabled": False}

        worker_cfg = _load_cfg(isolated_profiles["worker_alpha"])
        assert "worker-skill" in worker_cfg.get("skills", {}).get("disabled", [])
        # The dashboard's own config must stay untouched — this was the bug.
        default_cfg = _load_cfg(isolated_profiles["default"])
        assert "worker-skill" not in default_cfg.get("skills", {}).get("disabled", [])

    def test_toggle_reenable_round_trip(self, client, isolated_profiles):
        for enabled in (False, True):
            client.put(
                "/api/skills/toggle",
                json={
                    "name": "worker-skill",
                    "enabled": enabled,
                    "profile": "worker_alpha",
                },
            )
        worker_cfg = _load_cfg(isolated_profiles["worker_alpha"])
        assert "worker-skill" not in worker_cfg.get("skills", {}).get("disabled", [])

    def test_unknown_profile_returns_404(self, client, isolated_profiles):
        resp = client.get("/api/skills", params={"profile": "no_such_profile"})
        assert resp.status_code == 404

    def test_invalid_profile_name_returns_400(self, client, isolated_profiles):
        resp = client.get("/api/skills", params={"profile": "Bad Name!"})
        assert resp.status_code == 400

    def test_scope_does_not_create_module_path_globals(self, client, isolated_profiles):
        """Profile scoping stays task-local and never mutates module paths."""
        import tools.skills_tool as skills_tool

        assert not hasattr(skills_tool, "SKILLS_DIR")
        assert not hasattr(skills_tool, "FABRIC_HOME")
        client.get("/api/skills", params={"profile": "worker_alpha"})
        assert not hasattr(skills_tool, "SKILLS_DIR")
        assert not hasattr(skills_tool, "FABRIC_HOME")


class TestProfileScopedMemory:
    def test_status_endpoint_does_not_execute_user_provider_module(
        self, client, isolated_profiles
    ):
        worker_home = isolated_profiles["worker_alpha"]
        plugin_dir = worker_home / "plugins" / "unsafe-status-provider"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "__init__.py").write_text(
            "# MemoryProvider marker for static discovery\n"
            "raise AssertionError('status imported user provider')\n",
            encoding="utf-8",
        )
        (plugin_dir / "plugin.yaml").write_text(
            "description: Static status provider\n",
            encoding="utf-8",
        )

        response = client.get(
            "/api/memory",
            params={"profile": "worker_alpha"},
        )

        assert response.status_code == 200
        row = next(
            provider
            for provider in response.json()["providers"]
            if provider["name"] == "unsafe-status-provider"
        )
        assert row["source"] == "user"
        assert row["lifecycle"]["load"] == "not_inspected"

    def test_provider_config_does_not_inherit_another_profiles_process_secret(
        self, client, isolated_profiles, monkeypatch
    ):
        default_home = isolated_profiles["default"]
        worker_home = isolated_profiles["worker_alpha"]
        (default_home / ".env").write_text(
            "HONCHO_API_KEY=default-secret\n", encoding="utf-8"
        )
        (worker_home / ".env").write_text("", encoding="utf-8")
        monkeypatch.setenv("HONCHO_API_KEY", "default-secret")

        worker = client.get(
            "/api/memory/providers/honcho/config",
            params={"profile": "worker_alpha"},
        )
        default = client.get("/api/memory/providers/honcho/config")

        assert worker.status_code == 200
        assert default.status_code == 200
        worker_key = next(
            field for field in worker.json()["fields"] if field["key"] == "api_key"
        )
        default_key = next(
            field for field in default.json()["fields"] if field["key"] == "api_key"
        )
        assert worker_key["is_set"] is False
        assert default_key["is_set"] is True
        assert "default-secret" not in worker.text
        assert "default-secret" not in default.text

    def test_profile_env_can_select_provider_without_process_env_alias(
        self, client, isolated_profiles, monkeypatch
    ):
        worker_home = isolated_profiles["worker_alpha"]
        (worker_home / ".env").write_text(
            "RETAINDB_API_KEY=worker-secret\n",
            encoding="utf-8",
        )
        (worker_home / "config.yaml").write_text(
            "memory:\n  provider: retaindb\n",
            encoding="utf-8",
        )
        monkeypatch.delenv("RETAINDB_API_KEY", raising=False)

        status = client.get(
            "/api/memory",
            params={"profile": "worker_alpha"},
        )
        row = next(
            provider
            for provider in status.json()["providers"]
            if provider["name"] == "retaindb"
        )
        assert row["available"] is False
        assert row["status"] == "readiness_unknown"
        assert status.json()["selection"]["state"] == "readiness_unknown"

        select = client.put(
            "/api/memory/provider",
            params={"profile": "worker_alpha"},
            json={"provider": "retaindb"},
        )

        assert select.status_code == 200
        assert _load_cfg(worker_home)["memory"]["provider"] == "retaindb"

        from fabric_constants import (
            reset_fabric_home_override,
            set_fabric_home_override,
        )
        from plugins.memory import load_memory_provider

        token = set_fabric_home_override(worker_home)
        try:
            provider = load_memory_provider("retaindb")
            assert provider is not None and provider.is_available()
            provider.initialize("worker-runtime", fabric_home=str(worker_home))
            assert provider.get_runtime_state().value == "ready"
            assert provider._client.api_key == "worker-secret"
            provider.shutdown()
        finally:
            reset_fabric_home_override(token)

    def test_status_reads_requested_profile_tiers_and_files(
        self, client, isolated_profiles
    ):
        default_home = isolated_profiles["default"]
        worker_home = isolated_profiles["worker_alpha"]
        (default_home / "config.yaml").write_text(
            "memory:\n  memory_enabled: true\n  user_profile_enabled: false\n",
            encoding="utf-8",
        )
        (worker_home / "config.yaml").write_text(
            "memory:\n  memory_enabled: false\n  user_profile_enabled: true\n",
            encoding="utf-8",
        )
        (default_home / "memories").mkdir(exist_ok=True)
        (worker_home / "memories").mkdir(exist_ok=True)
        (default_home / "memories" / "MEMORY.md").write_text(
            "default", encoding="utf-8"
        )
        (worker_home / "memories" / "MEMORY.md").write_text(
            "worker-memory", encoding="utf-8"
        )

        worker = client.get("/api/memory", params={"profile": "worker_alpha"})
        default = client.get("/api/memory")

        assert worker.status_code == 200
        assert worker.json()["tiers"]["memory"] == {
            "enabled": False,
            "bytes": 13,
        }
        assert worker.json()["tiers"]["user"]["enabled"] is True
        assert default.json()["tiers"]["memory"] == {
            "enabled": True,
            "bytes": 7,
        }

    def test_provider_selection_and_reset_mutate_only_requested_profile(
        self, client, isolated_profiles
    ):
        default_home = isolated_profiles["default"]
        worker_home = isolated_profiles["worker_alpha"]
        (default_home / "config.yaml").write_text(
            "memory:\n  provider: keep-default\n", encoding="utf-8"
        )
        (worker_home / "config.yaml").write_text(
            "memory:\n  provider: clear-worker\n  external_write_consent: true\n",
            encoding="utf-8",
        )
        (default_home / "memories").mkdir(exist_ok=True)
        (worker_home / "memories").mkdir(exist_ok=True)
        (default_home / "memories" / "MEMORY.md").write_text(
            "default", encoding="utf-8"
        )
        (worker_home / "memories" / "MEMORY.md").write_text(
            "worker", encoding="utf-8"
        )

        select = client.put(
            "/api/memory/provider",
            params={"profile": "worker_alpha"},
            json={"provider": "built-in"},
        )
        reset = client.post(
            "/api/memory/reset",
            params={"profile": "worker_alpha"},
            json={"target": "memory"},
        )

        assert select.status_code == 200
        assert reset.status_code == 200
        assert _load_cfg(worker_home)["memory"]["provider"] == ""
        assert (
            _load_cfg(worker_home)["memory"]["external_write_consent"] is False
        )
        assert _load_cfg(default_home)["memory"]["provider"] == "keep-default"
        assert not (worker_home / "memories" / "MEMORY.md").exists()
        assert (default_home / "memories" / "MEMORY.md").exists()

class TestProfileScopedToolsets:
    def test_toolset_toggle_scopes_to_profile(self, client, isolated_profiles):
        resp = client.put(
            "/api/tools/toolsets/x_search",
            json={"enabled": True, "profile": "worker_alpha"},
        )
        assert resp.status_code == 200

        worker_cfg = _load_cfg(isolated_profiles["worker_alpha"])
        assert "x_search" in worker_cfg.get("platform_toolsets", {}).get("cli", [])
        default_cfg = _load_cfg(isolated_profiles["default"])
        assert "x_search" not in default_cfg.get("platform_toolsets", {}).get("cli", [])

        listing = client.get(
            "/api/tools/toolsets", params={"profile": "worker_alpha"}
        ).json()
        assert {t["name"]: t for t in listing}["x_search"]["enabled"] is True
        # Unscoped listing reflects the dashboard's own (untouched) config.
        listing = client.get("/api/tools/toolsets").json()
        assert {t["name"]: t for t in listing}["x_search"]["enabled"] is False

    def test_toolset_toggle_unknown_profile_404(self, client, isolated_profiles):
        resp = client.put(
            "/api/tools/toolsets/x_search",
            json={"enabled": True, "profile": "ghost"},
        )
        assert resp.status_code == 404


class TestProfileScopedHubActions:
    def test_explicit_default_profile_stays_explicit(self, isolated_profiles):
        """Default is a target profile, while current means inherit the host."""
        from fabric_cli.web_server import _profile_cli_args

        assert _profile_cli_args(" Default ") == ["-p", "default"]
        assert _profile_cli_args("current") == []

    def test_hub_install_spawns_with_profile_flag(
        self, client, isolated_profiles, monkeypatch
    ):
        """Hub installs must go through a fresh ``fabric -p <profile>``
        subprocess — the in-process scope can't reach skills_hub's
        import-time SKILLS_DIR binding."""
        import fabric_cli.web_server as web_server

        calls = []

        class _FakeProc:
            pid = 4242

        def _fake_spawn(subcommand, name):
            calls.append((list(subcommand), name))
            return _FakeProc()

        monkeypatch.setattr(web_server, "_spawn_fabric_action", _fake_spawn)
        resp = client.post(
            "/api/skills/hub/install",
            json={"identifier": "official/demo", "profile": "worker_alpha"},
        )
        assert resp.status_code == 200
        assert calls == [
            (
                ["-p", "worker_alpha", "skills", "install", "official/demo", "--yes"],
                web_server._hub_action_name("install", "official/demo"),
            )
        ]

    def test_hub_install_without_profile_keeps_legacy_argv(
        self, client, isolated_profiles, monkeypatch
    ):
        import fabric_cli.web_server as web_server

        calls = []

        class _FakeProc:
            pid = 4242

        monkeypatch.setattr(
            web_server,
            "_spawn_fabric_action",
            lambda subcommand, name: calls.append(list(subcommand)) or _FakeProc(),
        )
        resp = client.post(
            "/api/skills/hub/install", json={"identifier": "official/demo"}
        )
        assert resp.status_code == 200
        assert calls == [["skills", "install", "official/demo", "--yes"]]

    def test_hub_install_unknown_profile_404(self, client, isolated_profiles):
        resp = client.post(
            "/api/skills/hub/install",
            json={"identifier": "official/demo", "profile": "ghost"},
        )
        assert resp.status_code == 404

    def test_hub_update_uses_distinct_action_names_per_profile(
        self, client, isolated_profiles, monkeypatch
    ):
        import fabric_cli.web_server as web_server

        calls = []

        class _FakeProc:
            def __init__(self, pid):
                self.pid = pid

            def poll(self):
                return None

        monkeypatch.setattr(web_server, "_ACTION_PROCS", {})
        monkeypatch.setattr(web_server, "_ACTION_COMMANDS", {})
        monkeypatch.setattr(web_server, "_ACTION_RESULTS", {})
        monkeypatch.setattr(web_server, "_ACTION_LOG_FILES", dict(web_server._ACTION_LOG_FILES))

        def _fake_spawn(subcommand, name):
            proc = _FakeProc(5000 + len(calls))
            calls.append((list(subcommand), name))
            web_server._ACTION_PROCS[name] = proc
            web_server._ACTION_COMMANDS[name] = tuple(subcommand)
            return proc

        monkeypatch.setattr(web_server, "_spawn_fabric_action", _fake_spawn)

        alpha = client.post(
            "/api/skills/hub/update", json={"profile": "worker_alpha"}
        ).json()
        beta = client.post(
            "/api/skills/hub/update", json={"profile": "worker_beta"}
        ).json()

        assert calls[0][0] == ["-p", "worker_alpha", "skills", "update"]
        assert calls[1][0] == ["-p", "worker_beta", "skills", "update"]
        assert alpha["name"] == calls[0][1]
        assert beta["name"] == calls[1][1]
        assert alpha["name"] != beta["name"]
        assert (
            web_server._ACTION_LOG_FILES[alpha["name"]]
            != web_server._ACTION_LOG_FILES[beta["name"]]
        )
        assert client.get(f"/api/actions/{alpha['name']}/status").json()["pid"] == 5000
        assert client.get(f"/api/actions/{beta['name']}/status").json()["pid"] == 5001

    def test_hub_update_unscoped_action_uses_current_home_identity(
        self, client, isolated_profiles, monkeypatch
    ):
        import fabric_cli.web_server as web_server

        names = []

        class _FakeProc:
            pid = 6000

            def poll(self):
                return 0

        monkeypatch.setattr(web_server, "_ACTION_PROCS", {})
        monkeypatch.setattr(web_server, "_ACTION_LOG_FILES", dict(web_server._ACTION_LOG_FILES))
        monkeypatch.setattr(
            web_server,
            "_spawn_fabric_action",
            lambda subcommand, name: names.append(name) or _FakeProc(),
        )

        first = client.post("/api/skills/hub/update", json={}).json()
        second = client.post("/api/skills/hub/update", json={}).json()

        assert first["name"] == second["name"] == names[0] == names[1]
        assert first["name"].startswith("skills-update-home-")
        assert "default" not in first["name"]

    def test_hub_update_same_profile_joins_running_action(
        self, client, isolated_profiles, monkeypatch
    ):
        import fabric_cli.web_server as web_server

        calls = []

        class _FakeProc:
            pid = 7000

            def poll(self):
                return None

        proc = _FakeProc()
        monkeypatch.setattr(web_server, "_ACTION_PROCS", {})
        monkeypatch.setattr(web_server, "_ACTION_COMMANDS", {})
        monkeypatch.setattr(web_server, "_ACTION_RESULTS", {})
        monkeypatch.setattr(web_server, "_ACTION_LOG_FILES", dict(web_server._ACTION_LOG_FILES))

        def _fake_spawn(subcommand, name):
            calls.append((list(subcommand), name))
            web_server._ACTION_PROCS[name] = proc
            return proc

        monkeypatch.setattr(web_server, "_spawn_fabric_action", _fake_spawn)

        first = client.post(
            "/api/skills/hub/update", json={"profile": "worker_alpha"}
        ).json()
        second = client.post(
            "/api/skills/hub/update", json={"profile": "worker_alpha"}
        ).json()

        assert first == second
        assert len(calls) == 1
