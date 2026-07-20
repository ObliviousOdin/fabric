"""Regression tests for the machine-dashboard multi-profile unification.

The dashboard is ONE machine-level management surface: config, env, MCP,
model, and chat-PTY endpoints accept an optional ``profile`` so the global
profile switcher can target any profile's FABRIC_HOME. These tests pin:
reads/writes land in the REQUESTED profile, the dashboard's own profile
stays untouched, and the chat PTY env is scoped via FABRIC_HOME.
"""
import os

import pytest
import yaml


@pytest.fixture
def isolated_profiles(tmp_path, monkeypatch, _isolate_fabric_home):
    """Isolated default home + one named profile, each with config + .env."""
    from fabric_constants import get_fabric_home
    from fabric_cli import profiles

    default_home = get_fabric_home()
    profiles_root = default_home / "profiles"
    worker_home = profiles_root / "worker_beta"
    for home in (default_home, worker_home):
        home.mkdir(parents=True, exist_ok=True)
        (home / "config.yaml").write_text("{}\n", encoding="utf-8")
    (worker_home / ".env").write_text("", encoding="utf-8")

    monkeypatch.setattr(profiles, "_get_default_fabric_home", lambda: default_home)
    monkeypatch.setattr(profiles, "_get_profiles_root", lambda: profiles_root)
    return {"default": default_home, "worker_beta": worker_home}


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


def _cfg(home):
    return yaml.safe_load((home / "config.yaml").read_text()) or {}


class TestProfileScopedConfig:
    def test_config_put_lands_in_target_profile_only(self, client, isolated_profiles):
        resp = client.put(
            "/api/config",
            json={"config": {"timezone": "Mars/Olympus"}, "profile": "worker_beta"},
        )
        assert resp.status_code == 200
        assert _cfg(isolated_profiles["worker_beta"]).get("timezone") == "Mars/Olympus"
        assert _cfg(isolated_profiles["default"]).get("timezone") != "Mars/Olympus"

    def test_config_get_reads_target_profile(self, client, isolated_profiles):
        (isolated_profiles["worker_beta"] / "config.yaml").write_text(
            "timezone: Venus/Cloud\n", encoding="utf-8"
        )
        resp = client.get("/api/config", params={"profile": "worker_beta"})
        assert resp.status_code == 200
        assert resp.json().get("timezone") == "Venus/Cloud"
        # Unscoped read sees the dashboard's own config.
        resp = client.get("/api/config")
        assert resp.json().get("timezone") != "Venus/Cloud"

    def test_config_query_param_equivalent_to_body(self, client, isolated_profiles):
        """The SPA's fetchJSON injects ?profile= — must scope like body.profile."""
        resp = client.put(
            "/api/config?profile=worker_beta",
            json={"config": {"timezone": "Pluto/Far"}},
        )
        assert resp.status_code == 200
        assert _cfg(isolated_profiles["worker_beta"]).get("timezone") == "Pluto/Far"
        assert _cfg(isolated_profiles["default"]).get("timezone") != "Pluto/Far"

    def test_config_raw_round_trip_scoped(self, client, isolated_profiles):
        resp = client.put(
            "/api/config/raw",
            json={"yaml_text": "timezone: Io/Volcano\n", "profile": "worker_beta"},
        )
        assert resp.status_code == 200
        resp = client.get("/api/config/raw", params={"profile": "worker_beta"})
        assert "Io/Volcano" in resp.json()["yaml"]
        resp = client.get("/api/config/raw")
        assert "Io/Volcano" not in resp.json()["yaml"]

    def test_config_raw_path_reflects_requested_profile(self, client, isolated_profiles):
        """The Config page header shows /api/config/raw's ``path`` — it must
        point at the SWITCHED profile's config.yaml, not the dashboard's own
        (the stale-path bug reported after the profile unification launch)."""
        resp = client.get("/api/config/raw", params={"profile": "worker_beta"})
        assert resp.status_code == 200
        assert resp.json()["path"] == str(isolated_profiles["worker_beta"] / "config.yaml")
        resp = client.get("/api/config/raw")
        assert resp.json()["path"] == str(isolated_profiles["default"] / "config.yaml")

    def test_unknown_profile_404(self, client, isolated_profiles):
        resp = client.get("/api/config", params={"profile": "ghost"})
        assert resp.status_code == 404

    def test_current_profile_config_is_scoped_when_multiplexing(
        self, client, isolated_profiles, monkeypatch
    ):
        from agent.secret_scope import set_multiplex_active

        default_home = isolated_profiles["default"]
        (default_home / "config.yaml").write_text(
            "timezone: ${PROFILE_DISPLAY_ZONE}\n", encoding="utf-8"
        )
        (default_home / ".env").write_text(
            "PROFILE_DISPLAY_ZONE=Mars/Worker\n", encoding="utf-8"
        )
        monkeypatch.setenv("PROFILE_DISPLAY_ZONE", "Launch/Leak")

        set_multiplex_active(True)
        try:
            resp = client.get("/api/config")
        finally:
            set_multiplex_active(False)

        assert resp.status_code == 200
        assert resp.json()["timezone"] == "Mars/Worker"
        assert os.environ["PROFILE_DISPLAY_ZONE"] == "Launch/Leak"

    def test_managed_env_wins_inside_named_profile_scope(
        self, client, isolated_profiles, monkeypatch, tmp_path
    ):
        from fabric_cli import managed_scope

        worker_home = isolated_profiles["worker_beta"]
        (worker_home / "config.yaml").write_text(
            "timezone: ${PROFILE_DISPLAY_ZONE}\n", encoding="utf-8"
        )
        (worker_home / ".env").write_text(
            "PROFILE_DISPLAY_ZONE=Worker/User\n", encoding="utf-8"
        )
        managed_dir = tmp_path / "managed"
        managed_dir.mkdir()
        (managed_dir / ".env").write_text(
            "PROFILE_DISPLAY_ZONE=Admin/Managed\n", encoding="utf-8"
        )
        monkeypatch.setenv("FABRIC_MANAGED_DIR", str(managed_dir))
        monkeypatch.setenv("PROFILE_DISPLAY_ZONE", "Launch/Leak")
        managed_scope.invalidate_managed_cache()

        resp = client.get("/api/config", params={"profile": "worker_beta"})

        assert resp.status_code == 200
        assert resp.json()["timezone"] == "Admin/Managed"
        assert os.environ["PROFILE_DISPLAY_ZONE"] == "Launch/Leak"

    def test_config_scope_restores_nested_context_after_error(
        self, isolated_profiles
    ):
        from agent.secret_scope import (
            current_secret_scope,
            reset_secret_scope,
            set_secret_scope,
        )
        from fabric_cli.web_server import _config_profile_scope
        from fabric_constants import (
            get_fabric_home,
            reset_fabric_home_override,
            set_fabric_home_override,
        )

        outer_home = isolated_profiles["default"] / "outer"
        home_token = set_fabric_home_override(outer_home)
        secret_token = set_secret_scope({"OUTER_ONLY": "outer"})
        try:
            with pytest.raises(RuntimeError, match="boom"):
                with _config_profile_scope("worker_beta"):
                    assert get_fabric_home() == isolated_profiles["worker_beta"]
                    assert current_secret_scope() is not None
                    raise RuntimeError("boom")

            assert get_fabric_home() == outer_home
            assert current_secret_scope() == {"OUTER_ONLY": "outer"}
        finally:
            reset_secret_scope(secret_token)
            reset_fabric_home_override(home_token)

    @pytest.mark.asyncio
    async def test_config_scope_is_task_local_across_await(
        self, isolated_profiles, monkeypatch
    ):
        import asyncio

        from agent import secret_scope
        from fabric_cli.web_server import _config_profile_scope
        from fabric_constants import get_fabric_home

        monkeypatch.setattr(
            secret_scope,
            "build_profile_secret_scope",
            lambda home: {"PROFILE_HOME": str(home)},
        )
        entered = asyncio.Event()
        release = asyncio.Event()

        async def observe(profile):
            with _config_profile_scope(profile):
                entered.set()
                await release.wait()
                return (
                    get_fabric_home(),
                    dict(secret_scope.current_secret_scope() or {}),
                )

        worker_task = asyncio.create_task(observe("worker_beta"))
        await entered.wait()
        with _config_profile_scope(None):
            release.set()
            worker_home, worker_scope = await worker_task
            assert get_fabric_home() == isolated_profiles["default"]

        assert worker_home == isolated_profiles["worker_beta"]
        assert worker_scope == {
            "PROFILE_HOME": str(isolated_profiles["worker_beta"])
        }
        assert secret_scope.current_secret_scope() is None


class TestProfileScopedEnv:
    def test_env_set_lands_in_target_profile_only(
        self, client, isolated_profiles, monkeypatch
    ):
        monkeypatch.setenv("FAL_KEY", "launch-fal-value")
        resp = client.put(
            "/api/env",
            json={"key": "FAL_KEY", "value": "test-fal-123", "profile": "worker_beta"},
        )
        assert resp.status_code == 200
        worker_env = (isolated_profiles["worker_beta"] / ".env").read_text()
        assert "test-fal-123" in worker_env
        default_env_path = isolated_profiles["default"] / ".env"
        if default_env_path.exists():
            assert "test-fal-123" not in default_env_path.read_text()
        assert os.environ["FAL_KEY"] == "launch-fal-value"

    def test_anthropic_oauth_shaped_key_is_rejected_without_writes(
        self, client, isolated_profiles
    ):
        resp = client.put(
            "/api/env",
            json={
                "key": "ANTHROPIC_API_KEY",
                "value": "sk-ant-oat01-retired",
                "profile": "worker_beta",
            },
        )

        assert resp.status_code == 400
        worker_env = isolated_profiles["worker_beta"] / ".env"
        text = worker_env.read_text() if worker_env.exists() else ""
        assert "ANTHROPIC_API_KEY" not in text
        assert "ANTHROPIC_TOKEN" not in text

    def test_anthropic_api_key_write_clears_legacy_slot_in_target_profile(
        self, client, isolated_profiles, monkeypatch
    ):
        worker_env = isolated_profiles["worker_beta"] / ".env"
        worker_env.write_text(
            "ANTHROPIC_TOKEN=sk-ant-oat01-old\n"
            "ANTHROPIC_BASE_URL=https://gateway.example/anthropic\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("ANTHROPIC_API_KEY", "launch-key-must-survive")

        resp = client.put(
            "/api/env",
            json={
                "key": "ANTHROPIC_API_KEY",
                "value": "eyJ.worker.proxy",
                "profile": "worker_beta",
            },
        )

        assert resp.status_code == 200
        text = worker_env.read_text()
        assert "ANTHROPIC_API_KEY=eyJ.worker.proxy" in text
        assert "ANTHROPIC_BASE_URL=https://gateway.example/anthropic" in text
        assert "ANTHROPIC_TOKEN=sk-ant-oat01-old" not in text
        assert os.environ["ANTHROPIC_API_KEY"] == "launch-key-must-survive"

        default_env = isolated_profiles["default"] / ".env"
        default_text = default_env.read_text() if default_env.exists() else ""
        assert "eyJ.worker.proxy" not in default_text

    def test_env_list_reads_target_profile(self, client, isolated_profiles):
        (isolated_profiles["worker_beta"] / ".env").write_text(
            "FAL_KEY=worker-only-value\n", encoding="utf-8"
        )
        resp = client.get("/api/env", params={"profile": "worker_beta"})
        assert resp.status_code == 200
        assert resp.json()["FAL_KEY"]["is_set"] is True
        resp = client.get("/api/env")
        assert resp.json()["FAL_KEY"]["is_set"] is False

    def test_env_delete_scoped(self, client, isolated_profiles, monkeypatch):
        (isolated_profiles["worker_beta"] / ".env").write_text(
            "FAL_KEY=doomed\n", encoding="utf-8"
        )
        monkeypatch.setenv("FAL_KEY", "launch-must-survive")
        resp = client.request(
            "DELETE",
            "/api/env",
            json={"key": "FAL_KEY", "profile": "worker_beta"},
        )
        assert resp.status_code == 200
        assert "doomed" not in (isolated_profiles["worker_beta"] / ".env").read_text()
        assert os.environ["FAL_KEY"] == "launch-must-survive"

    def test_messaging_env_write_does_not_publish_target_secret(
        self, client, isolated_profiles, monkeypatch
    ):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "launch-telegram-token")

        resp = client.put(
            "/api/messaging/platforms/telegram",
            json={
                "profile": "worker_beta",
                "env": {"TELEGRAM_BOT_TOKEN": "worker-telegram-token"},
            },
        )

        assert resp.status_code == 200
        assert "worker-telegram-token" in (
            isolated_profiles["worker_beta"] / ".env"
        ).read_text(encoding="utf-8")
        assert os.environ["TELEGRAM_BOT_TOKEN"] == "launch-telegram-token"

    def test_toolset_status_does_not_inherit_launch_profile_key(
        self, client, isolated_profiles, monkeypatch
    ):
        monkeypatch.setenv("ELEVENLABS_API_KEY", "launch-elevenlabs-key")
        (isolated_profiles["worker_beta"] / ".env").write_text(
            "", encoding="utf-8"
        )

        resp = client.get(
            "/api/tools/toolsets/tts/config",
            params={"profile": "worker_beta"},
        )

        assert resp.status_code == 200
        env_rows = {
            row["key"]: row
            for provider in resp.json()["providers"]
            for row in provider.get("env_vars", [])
        }
        assert env_rows["ELEVENLABS_API_KEY"]["is_set"] is False

    def test_memory_setup_child_env_scrubs_launch_profile_secrets(
        self, isolated_profiles, monkeypatch
    ):
        from fabric_cli.web_server import (
            _config_profile_scope,
            _memory_provider_setup_env,
        )

        default_home = isolated_profiles["default"]
        (default_home / ".env").write_text(
            "DATABASE_URL=launch-db-secret\n", encoding="utf-8"
        )
        monkeypatch.setenv("DATABASE_URL", "launch-db-secret")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "launch-bot-secret")

        with _config_profile_scope("worker_beta"):
            child_env = _memory_provider_setup_env()

        assert "DATABASE_URL" not in child_env
        assert "TELEGRAM_BOT_TOKEN" not in child_env
        assert child_env["FABRIC_HOME"] == str(
            isolated_profiles["worker_beta"]
        )


class TestProfileScopedMcp:
    def test_mcp_add_and_list_scoped(self, client, isolated_profiles):
        resp = client.post(
            "/api/mcp/servers",
            json={"name": "scoped-srv", "url": "http://localhost:1234/sse",
                  "profile": "worker_beta"},
        )
        assert resp.status_code == 200

        worker_cfg = _cfg(isolated_profiles["worker_beta"])
        assert "scoped-srv" in worker_cfg.get("mcp_servers", {})
        assert "scoped-srv" not in _cfg(isolated_profiles["default"]).get("mcp_servers", {})

        listing = client.get("/api/mcp/servers", params={"profile": "worker_beta"}).json()
        assert any(s["name"] == "scoped-srv" for s in listing["servers"])
        listing = client.get("/api/mcp/servers").json()
        assert not any(s["name"] == "scoped-srv" for s in listing["servers"])

    def test_mcp_enabled_toggle_scoped(self, client, isolated_profiles):
        (isolated_profiles["worker_beta"] / "config.yaml").write_text(
            "mcp_servers:\n  srv1:\n    url: http://x/sse\n", encoding="utf-8"
        )
        resp = client.put(
            "/api/mcp/servers/srv1/enabled",
            json={"enabled": False, "profile": "worker_beta"},
        )
        assert resp.status_code == 200
        worker_cfg = _cfg(isolated_profiles["worker_beta"])
        assert worker_cfg["mcp_servers"]["srv1"]["enabled"] is False

    def test_mcp_probe_runs_inside_profile_scope(
        self, client, isolated_profiles, monkeypatch
    ):
        """The test-server probe must execute with the selected profile's
        scope active so env-placeholder expansion reads the profile's .env,
        matching the config the server was saved into."""
        import fabric_cli.mcp_config as mcp_config
        from fabric_constants import get_fabric_home

        (isolated_profiles["worker_beta"] / "config.yaml").write_text(
            "mcp_servers:\n"
            "  probe-srv:\n"
            "    url: http://x/sse\n"
            "    headers:\n"
            "      Authorization: Bearer ${MCP_PROFILE_TOKEN}\n",
            encoding="utf-8",
        )
        (isolated_profiles["worker_beta"] / ".env").write_text(
            "MCP_PROFILE_TOKEN=worker-token\n", encoding="utf-8"
        )
        monkeypatch.setenv("MCP_PROFILE_TOKEN", "launch-token")
        seen = {}

        def fake_probe(name, config, connect_timeout=30, details=None):
            from agent.secret_scope import current_secret_scope
            from fabric_cli.mcp_config import _resolve_mcp_server_config

            seen["home"] = str(get_fabric_home())
            seen["scope"] = dict(current_secret_scope() or {})
            seen["resolved"] = _resolve_mcp_server_config(config)
            seen["process_token"] = os.environ["MCP_PROFILE_TOKEN"]
            return [("tool-a", "desc")]

        monkeypatch.setattr(mcp_config, "_probe_single_server", fake_probe)
        resp = client.post(
            "/api/mcp/servers/probe-srv/test", params={"profile": "worker_beta"}
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert seen["home"] == str(isolated_profiles["worker_beta"])
        assert seen["scope"]["MCP_PROFILE_TOKEN"] == "worker-token"
        assert seen["resolved"]["headers"]["Authorization"] == (
            "Bearer worker-token"
        )
        assert seen["process_token"] == "launch-token"
        assert os.environ["MCP_PROFILE_TOKEN"] == "launch-token"

    def test_mcp_test_oauth_server_without_token_is_not_ok(
        self, client, isolated_profiles, monkeypatch
    ):
        """An `auth: oauth` server that serves tools/list anonymously must not
        false-green: a successful probe with no token on disk reports needs-auth."""
        import fabric_cli.mcp_config as mcp_config

        (isolated_profiles["worker_beta"] / "config.yaml").write_text(
            "mcp_servers:\n  oauth-srv:\n    url: http://x/sse\n    auth: oauth\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            mcp_config,
            "_probe_single_server",
            lambda name, config, connect_timeout=30, details=None: [("tool-a", "desc")],
        )
        monkeypatch.setattr(mcp_config, "_oauth_tokens_present", lambda name: False)

        resp = client.post(
            "/api/mcp/servers/oauth-srv/test", params={"profile": "worker_beta"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert "oauth" in body["error"].lower()

        # With a token present, the same probe is genuinely authenticated.
        monkeypatch.setattr(mcp_config, "_oauth_tokens_present", lambda name: True)
        resp = client.post(
            "/api/mcp/servers/oauth-srv/test", params={"profile": "worker_beta"}
        )
        assert resp.json()["ok"] is True

    def test_mcp_remove_scoped(self, client, isolated_profiles):
        (isolated_profiles["worker_beta"] / "config.yaml").write_text(
            "mcp_servers:\n  srv2:\n    url: http://x/sse\n", encoding="utf-8"
        )
        # Removing from the DASHBOARD's profile must 404 (srv2 lives in worker).
        resp = client.delete("/api/mcp/servers/srv2")
        assert resp.status_code == 404
        resp = client.delete("/api/mcp/servers/srv2", params={"profile": "worker_beta"})
        assert resp.status_code == 200
        assert "srv2" not in _cfg(isolated_profiles["worker_beta"]).get("mcp_servers", {})


class TestProfileScopedModel:
    def test_model_set_main_scoped(self, client, isolated_profiles):
        resp = client.post(
            "/api/model/set",
            json={
                "scope": "main",
                "provider": "openrouter",
                "model": "test/model-1",
                "confirm_expensive_model": True,
                "profile": "worker_beta",
            },
        )
        assert resp.status_code == 200
        worker_cfg = _cfg(isolated_profiles["worker_beta"])
        model_cfg = worker_cfg.get("model", {})
        assert isinstance(model_cfg, dict)
        assert model_cfg.get("provider") == "openrouter"
        default_model = _cfg(isolated_profiles["default"]).get("model", {})
        if isinstance(default_model, dict):
            assert default_model.get("default") != "test/model-1"

    def test_auxiliary_read_scoped_matches_write_target(
        self, client, isolated_profiles
    ):
        """Reads and writes must scope symmetrically: an aux pin written to
        the worker profile must show up ONLY in the worker-scoped read.
        (Regression: /api/model/auxiliary used to read unscoped while
        /api/model/set wrote scoped — the Models page displayed the
        dashboard profile's pins while editing the selected profile's.)"""
        (isolated_profiles["worker_beta"] / "config.yaml").write_text(
            "auxiliary:\n  vision:\n    provider: openrouter\n"
            "    model: worker/vision-pin\n",
            encoding="utf-8",
        )
        resp = client.get("/api/model/auxiliary", params={"profile": "worker_beta"})
        assert resp.status_code == 200
        vision = next(t for t in resp.json()["tasks"] if t["task"] == "vision")
        assert vision["model"] == "worker/vision-pin"

        # Unscoped read = the dashboard's own profile, which has no pin.
        resp = client.get("/api/model/auxiliary")
        assert resp.status_code == 200
        vision = next(t for t in resp.json()["tasks"] if t["task"] == "vision")
        assert vision["model"] != "worker/vision-pin"

    def test_auxiliary_unknown_profile_404(self, client, isolated_profiles):
        resp = client.get("/api/model/auxiliary", params={"profile": "ghost"})
        assert resp.status_code == 404

    def test_model_options_scoped_to_profile(self, client, isolated_profiles):
        """The Models picker must read the SAME profile model/set writes —
        current model/provider in the payload come from the scoped config."""
        (isolated_profiles["worker_beta"] / "config.yaml").write_text(
            "model:\n  provider: openrouter\n  default: worker/current-pin\n",
            encoding="utf-8",
        )
        resp = client.get("/api/model/options", params={"profile": "worker_beta"})
        assert resp.status_code == 200
        body = resp.json()
        # The payload carries the current selection somewhere stable; assert
        # the worker pin appears in the scoped response and not the unscoped.
        assert "worker/current-pin" in resp.text
        resp = client.get("/api/model/options")
        assert resp.status_code == 200
        assert "worker/current-pin" not in resp.text
        assert isinstance(body, dict)

    def test_model_options_unknown_profile_404(self, client, isolated_profiles):
        resp = client.get("/api/model/options", params={"profile": "ghost"})
        assert resp.status_code == 404

    def test_model_options_hides_unconfigured_providers_by_default(self, client, monkeypatch):
        calls = []

        monkeypatch.setattr(
            "fabric_cli.inventory.load_picker_context",
            lambda: object(),
        )

        def _fake_build_models_payload(_ctx, **kwargs):
            calls.append(kwargs)
            return {"providers": [], "model": "", "provider": ""}

        monkeypatch.setattr(
            "fabric_cli.inventory.build_models_payload",
            _fake_build_models_payload,
        )

        resp = client.get("/api/model/options")
        assert resp.status_code == 200
        assert calls[-1]["explicit_only"] is False
        assert calls[-1]["include_unconfigured"] is False

        resp = client.get("/api/model/options", params={"explicit_only": "1"})
        assert resp.status_code == 200
        assert calls[-1]["explicit_only"] is True

        resp = client.get("/api/model/options", params={"include_unconfigured": "1"})
        assert resp.status_code == 200
        assert calls[-1]["include_unconfigured"] is True

    def test_model_info_unknown_profile_404(self, client, isolated_profiles):
        """Regression: the broad except used to convert the 404 into a 200
        with empty model info ("no model set" — silently wrong)."""
        resp = client.get("/api/model/info", params={"profile": "ghost"})
        assert resp.status_code == 404

    def test_mcp_catalog_unknown_profile_404(self, client, isolated_profiles):
        resp = client.get("/api/mcp/catalog", params={"profile": "ghost"})
        assert resp.status_code == 404


class TestProfileScopedPostSetup:
    def test_post_setup_spawns_with_profile_flag(
        self, client, isolated_profiles, monkeypatch
    ):
        """Post-setup runs in a -p scoped subprocess so hooks that read
        config / write per-profile state see the same FABRIC_HOME the rest
        of the drawer's writes targeted."""
        import fabric_cli.web_server as web_server

        calls = []

        class _FakeProc:
            pid = 777

        monkeypatch.setattr(
            web_server,
            "_spawn_fabric_action",
            lambda subcommand, name: calls.append(list(subcommand)) or _FakeProc(),
        )
        monkeypatch.setattr(
            "fabric_cli.tools_config.valid_post_setup_keys",
            lambda: {"agent_browser"},
        )
        resp = client.post(
            "/api/tools/toolsets/browser/post-setup",
            json={"key": "agent_browser", "profile": "worker_beta"},
        )
        assert resp.status_code == 200
        assert calls == [
            ["-p", "worker_beta", "tools", "post-setup", "agent_browser"]
        ]

    def test_post_setup_without_profile_keeps_legacy_argv(
        self, client, isolated_profiles, monkeypatch
    ):
        import fabric_cli.web_server as web_server

        calls = []

        class _FakeProc:
            pid = 777

        monkeypatch.setattr(
            web_server,
            "_spawn_fabric_action",
            lambda subcommand, name: calls.append(list(subcommand)) or _FakeProc(),
        )
        monkeypatch.setattr(
            "fabric_cli.tools_config.valid_post_setup_keys",
            lambda: {"agent_browser"},
        )
        resp = client.post(
            "/api/tools/toolsets/browser/post-setup",
            json={"key": "agent_browser"},
        )
        assert resp.status_code == 200
        assert calls == [["tools", "post-setup", "agent_browser"]]


class TestProfileScopedGateway:
    def test_lifecycle_spawns_with_profile_flag(
        self, client, isolated_profiles, monkeypatch
    ):
        import fabric_cli.web_server as web_server

        calls = []

        class _FakeProc:
            pid = 888

        monkeypatch.setattr(
            web_server,
            "_spawn_fabric_action",
            lambda subcommand, name: calls.append((list(subcommand), name)) or _FakeProc(),
        )
        web_server._ACTION_PROCS.pop("gateway-restart", None)
        web_server._ACTION_COMMANDS.pop("gateway-restart", None)

        for verb in ("start", "stop", "restart"):
            resp = client.post(f"/api/gateway/{verb}", params={"profile": "worker_beta"})
            assert resp.status_code == 200

        assert calls == [
            (["-p", "worker_beta", "gateway", "start"], "gateway-start"),
            (["-p", "worker_beta", "gateway", "stop"], "gateway-stop"),
            (["-p", "worker_beta", "gateway", "restart"], "gateway-restart"),
        ]

    def test_status_reads_requested_profile_home(
        self, client, isolated_profiles, monkeypatch
    ):
        import fabric_cli.web_server as web_server
        from fabric_constants import get_fabric_home

        seen_homes = []

        def fake_get_running_pid():
            seen_homes.append(str(get_fabric_home()))
            return None

        monkeypatch.setattr(web_server, "check_config_version", lambda: (1, 1))
        # get_status probes via the TTL-cached wrapper (PR #53511 salvage);
        # patch the cached name so the fake still intercepts the probe.
        monkeypatch.setattr(web_server, "get_running_pid_cached", fake_get_running_pid)
        monkeypatch.setattr(
            web_server,
            "read_runtime_status",
            lambda: {"gateway_state": "startup_failed", "platforms": {}},
        )
        monkeypatch.setattr(web_server, "_GATEWAY_HEALTH_URL", None)

        resp = client.get("/api/status", params={"profile": "worker_beta"})

        assert resp.status_code == 200
        assert seen_homes[0] == str(isolated_profiles["worker_beta"])
        assert resp.json()["fabric_home"] == str(isolated_profiles["worker_beta"])

    def test_status_uses_runtime_pid_when_profile_pid_file_is_missing(
        self, client, isolated_profiles, monkeypatch
    ):
        import fabric_cli.web_server as web_server

        worker_home = isolated_profiles["worker_beta"]
        (worker_home / ".env").write_text(
            "TELEGRAM_BOT_TOKEN=worker-token\n", encoding="utf-8"
        )
        (worker_home / "config.yaml").write_text(
            yaml.safe_dump({"platforms": {"telegram": {"enabled": True}}}),
            encoding="utf-8",
        )
        runtime = {
            "pid": 4242,
            "gateway_state": "running",
            "platforms": {"telegram": {"state": "connected"}},
            "exit_reason": None,
            "updated_at": "2026-06-17T00:00:00+00:00",
        }
        monkeypatch.setattr(web_server, "check_config_version", lambda: (1, 1))
        monkeypatch.setattr(web_server, "get_running_pid_cached", lambda: None)
        monkeypatch.setattr(web_server, "read_runtime_status", lambda: runtime)
        monkeypatch.setattr(
            web_server, "get_runtime_status_running_pid", lambda payload: 4242
        )
        monkeypatch.setattr(web_server, "_GATEWAY_HEALTH_URL", None)
        from gateway.config import Platform

        class _FakeGatewayConfig:
            def get_connected_platforms(self):
                return [Platform.TELEGRAM]

        monkeypatch.setattr(
            "gateway.config.load_gateway_config", lambda: _FakeGatewayConfig()
        )

        resp = client.get("/api/status", params={"profile": "worker_beta"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["gateway_running"] is True
        assert data["gateway_pid"] == 4242
        assert data["gateway_state"] == "running"
        assert data["gateway_platforms"] == {"telegram": {"state": "connected"}}


class TestProfileScopedTelegramOnboarding:
    def test_apply_writes_target_profile_and_restarts_target(
        self, client, isolated_profiles, monkeypatch
    ):
        import time
        import fabric_cli.web_server as web_server

        with web_server._telegram_onboarding_lock:
            web_server._telegram_onboarding_pairings.clear()
            web_server._telegram_onboarding_pairings["pair-worker"] = (
                web_server._TelegramOnboardingPairing(
                    poll_token="poll-secret",
                    expires_at="2027-05-18T00:00:00.000Z",
                    expires_at_ts=time.time() + 600,
                    bot_token="123456:SECRET",
                    bot_username="worker_bot",
                    owner_user_id="123456789",
                )
            )

        calls = []

        class _FakeProc:
            pid = 889

        monkeypatch.setattr(
            web_server,
            "_spawn_fabric_action",
            lambda subcommand, name: calls.append((list(subcommand), name)) or _FakeProc(),
        )
        web_server._ACTION_PROCS.pop("gateway-restart", None)
        web_server._ACTION_COMMANDS.pop("gateway-restart", None)

        resp = client.post(
            "/api/messaging/telegram/onboarding/pair-worker/apply",
            params={"profile": "worker_beta"},
            json={"allowed_user_ids": ["123456789"]},
        )

        assert resp.status_code == 200
        assert resp.json()["restart_started"] is True
        assert calls == [
            (["-p", "worker_beta", "gateway", "restart"], "gateway-restart")
        ]

        worker_env = (isolated_profiles["worker_beta"] / ".env").read_text()
        assert "TELEGRAM_BOT_TOKEN=123456:SECRET" in worker_env
        assert "TELEGRAM_ALLOWED_USERS=123456789" in worker_env
        default_env_path = isolated_profiles["default"] / ".env"
        if default_env_path.exists():
            assert "TELEGRAM_BOT_TOKEN" not in default_env_path.read_text()

        worker_cfg = _cfg(isolated_profiles["worker_beta"])
        default_cfg = _cfg(isolated_profiles["default"])
        assert worker_cfg["platforms"]["telegram"]["enabled"] is True
        assert default_cfg.get("platforms", {}).get("telegram", {}).get("enabled") is not True


class TestProfileScopedChatPty:
    def test_chat_argv_scopes_fabric_home(self, isolated_profiles, monkeypatch):
        import fabric_cli.web_server as web_server

        monkeypatch.setattr(
            "fabric_cli.main._make_tui_argv",
            lambda root, tui_dev=False: (["cat"], None),
            raising=False,
        )
        argv, cwd, env = web_server._resolve_chat_argv(profile="worker_beta")
        from fabric_cli.tui_launch_context import consume_tui_launch_context

        index = argv.index("--launch-context")
        context = consume_tui_launch_context(argv[index + 1])
        assert env is not None
        assert env["FABRIC_HOME"] == str(isolated_profiles["worker_beta"])
        # Scoped chat must NOT attach to the dashboard's in-memory gateway.
        assert context.gateway_url == ""

    def test_chat_argv_unscoped_keeps_current_profile(self, isolated_profiles, monkeypatch):
        import fabric_cli.web_server as web_server

        monkeypatch.setattr(
            "fabric_cli.main._make_tui_argv",
            lambda root, tui_dev=False: (["cat"], None),
            raising=False,
        )
        argv, cwd, env = web_server._resolve_chat_argv()
        from fabric_cli.tui_launch_context import consume_tui_launch_context

        index = argv.index("--launch-context")
        consume_tui_launch_context(argv[index + 1])
        assert env is not None
        assert env.get("FABRIC_HOME") != str(isolated_profiles["worker_beta"])

    def test_chat_argv_unknown_profile_raises(self, isolated_profiles, monkeypatch):
        import fabric_cli.web_server as web_server

        monkeypatch.setattr(
            "fabric_cli.main._make_tui_argv",
            lambda root, tui_dev=False: (["cat"], None),
            raising=False,
        )
        # Reuse the HTTPException class web_server itself raises — avoids a
        # direct fastapi import (unresolvable in the ty lint environment).
        with pytest.raises(web_server.HTTPException) as exc:
            web_server._resolve_chat_argv(profile="ghost")
        assert exc.value.status_code == 404
