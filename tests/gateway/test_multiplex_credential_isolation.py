"""End-to-end credential isolation proof for multiplex mode (Workstream A).

These exercise the REAL resolution path (runtime_provider, secret scope, MCP
interpolation) rather than mocking it, proving the property that matters: two
profiles with different keys never see each other's, and an unscoped read in
multiplex mode fails closed instead of leaking.
"""
import asyncio
import json
import threading
from types import SimpleNamespace

import pytest

from pathlib import Path

from agent import secret_scope as ss


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    ss.set_multiplex_active(False)
    yield
    ss.set_multiplex_active(False)


class TestRuntimeProviderUsesScope:
    """fabric_cli.runtime_provider._getenv resolves through the secret scope."""

    def test_getenv_reads_scope_under_multiplex(self, monkeypatch):
        from fabric_cli.runtime_provider import _getenv
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-global-leak")
        ss.set_multiplex_active(True)
        tok = ss.set_secret_scope({"ANTHROPIC_API_KEY": "sk-profileA"})
        try:
            assert _getenv("ANTHROPIC_API_KEY") == "sk-profileA"
        finally:
            ss.reset_secret_scope(tok)

    def test_getenv_two_profiles_isolated(self, monkeypatch):
        from fabric_cli.runtime_provider import _getenv
        ss.set_multiplex_active(True)

        tok_a = ss.set_secret_scope({"OPENAI_API_KEY": "sk-A"})
        try:
            assert _getenv("OPENAI_API_KEY") == "sk-A"
        finally:
            ss.reset_secret_scope(tok_a)

        tok_b = ss.set_secret_scope({"OPENAI_API_KEY": "sk-B"})
        try:
            assert _getenv("OPENAI_API_KEY") == "sk-B"
        finally:
            ss.reset_secret_scope(tok_b)

    def test_getenv_fails_closed_unscoped(self, monkeypatch):
        from fabric_cli.runtime_provider import _getenv
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-leak")
        ss.set_multiplex_active(True)
        with pytest.raises(ss.UnscopedSecretError):
            _getenv("OPENROUTER_API_KEY")

    def test_getenv_global_var_still_reads_environ(self, monkeypatch):
        from fabric_cli.runtime_provider import _getenv
        monkeypatch.setenv("HERMES_MAX_ITERATIONS", "42")
        ss.set_multiplex_active(True)
        # global var: no scope needed, no raise
        assert _getenv("HERMES_MAX_ITERATIONS") == "42"


class TestMcpInterpolationUsesScope:
    """MCP config ${VAR} interpolation resolves through the secret scope."""

    def test_interpolation_reads_scope(self, monkeypatch):
        from tools.mcp_tool import _interpolate_env_vars
        monkeypatch.setenv("MY_MCP_TOKEN", "global-token")
        ss.set_multiplex_active(True)
        tok = ss.set_secret_scope({"MY_MCP_TOKEN": "profile-token"})
        try:
            cfg = {"env": {"TOKEN": "${MY_MCP_TOKEN}"}}
            assert _interpolate_env_vars(cfg) == {"env": {"TOKEN": "profile-token"}}
        finally:
            ss.reset_secret_scope(tok)

    def test_interpolation_unset_keeps_placeholder(self, monkeypatch):
        from tools.mcp_tool import _interpolate_env_vars
        monkeypatch.delenv("UNSET_MCP_VAR", raising=False)
        # multiplex off: unset var keeps literal placeholder (legacy behavior)
        assert _interpolate_env_vars("${UNSET_MCP_VAR}") == "${UNSET_MCP_VAR}"

    def test_interpolation_off_reads_environ(self, monkeypatch):
        from tools.mcp_tool import _interpolate_env_vars
        monkeypatch.setenv("MY_MCP_TOKEN", "env-token")
        # multiplex off: legacy os.environ resolution
        assert _interpolate_env_vars("${MY_MCP_TOKEN}") == "env-token"


class TestProfilePathResolutionUnderMultiplexScope:
    """Profile-scoped paths must follow the per-turn _profile_runtime_scope.

    The multiplexed gateway (gateway.multiplex_profiles) serves every profile
    from ONE process, scoping each inbound turn with _profile_runtime_scope —
    the same in-process-many-profiles topology as the desktop tui_gateway. The
    profile-isolation fixes (per-call path resolution + thread context
    propagation) must therefore hold under THIS scope too, not just desktop.
    This is the regression guard proving reachability is not desktop-only.
    """

    def _profiles(self, tmp_path):
        prof_a = tmp_path / "profA"
        prof_b = tmp_path / "profB"
        for p in (prof_a, prof_b):
            (p / "skills").mkdir(parents=True, exist_ok=True)
            (p / "state").mkdir(parents=True, exist_ok=True)
        return prof_a, prof_b

    def test_skills_dir_follows_multiplex_scope(self, tmp_path):
        from gateway.run import _profile_runtime_scope
        import tools.skills_hub as sh

        prof_a, prof_b = self._profiles(tmp_path)
        with _profile_runtime_scope(prof_a):
            a_seen = Path(sh.SKILLS_DIR)
        with _profile_runtime_scope(prof_b):
            b_seen = Path(sh.SKILLS_DIR)

        assert a_seen == prof_a / "skills"
        assert b_seen == prof_b / "skills"

    def test_cache_dir_follows_multiplex_scope(self, tmp_path):
        from gateway.run import _profile_runtime_scope
        import gateway.platforms.base as gb

        _prof_a, prof_b = self._profiles(tmp_path)
        with _profile_runtime_scope(prof_b):
            seen = gb.get_image_cache_dir()
        assert str(seen).startswith(str(prof_b))

    def test_worker_thread_inherits_multiplex_scope(self, tmp_path):
        """A wrapped worker spawned inside the scope must see the right profile.

        The _profile_runtime_scope docstring relies on copy_context() carrying
        the override into the agent worker thread; this proves the M2 fix
        primitive delivers that under the multiplexer's scope.
        """
        import threading

        from gateway.run import _profile_runtime_scope
        from fabric_constants import get_fabric_home
        from tools.thread_context import propagate_context_to_thread

        _prof_a, prof_b = self._profiles(tmp_path)
        seen = {}

        def worker():
            seen["home"] = str(get_fabric_home())

        with _profile_runtime_scope(prof_b):
            t = threading.Thread(target=propagate_context_to_thread(worker))
            t.start()
            t.join()

        assert seen["home"] == str(prof_b)

    def test_prebuilt_external_secrets_reach_profile_scope(self, tmp_path):
        from gateway.run import _profile_runtime_scope

        _prof_a, prof_b = self._profiles(tmp_path)
        with _profile_runtime_scope(
            prof_b,
            secrets={"HONCHO_API_KEY": "vault-profile-b"},
        ):
            assert ss.current_secret_scope() == {
                "HONCHO_API_KEY": "vault-profile-b"
            }


@pytest.mark.asyncio
async def test_message_profile_secret_resolution_does_not_block_event_loop(
    tmp_path,
    monkeypatch,
):
    """A cold vault lookup runs off-loop before the message scope is entered."""
    from gateway.run import GatewayRunner

    home = tmp_path / "profiles" / "worker"
    home.mkdir(parents=True)
    started = threading.Event()
    release = threading.Event()

    def blocking_build(profile_home):
        assert Path(profile_home) == home
        started.set()
        assert release.wait(timeout=2)
        return {"HONCHO_API_KEY": "worker-vault-key"}

    monkeypatch.setattr(ss, "build_profile_secret_scope", blocking_build)

    runner = object.__new__(GatewayRunner)
    runner.config = SimpleNamespace(multiplex_profiles=True)
    runner._resolve_profile_home_for_source = lambda _source: home

    async def run_off_loop(func, *args):
        return await asyncio.to_thread(func, *args)

    observed = {}

    async def inner(_event):
        observed["scope"] = dict(ss.current_secret_scope() or {})
        return "ok"

    runner._run_in_executor_with_context = run_off_loop
    runner._handle_message_in_profile = inner
    event = SimpleNamespace(source=SimpleNamespace(profile="worker"))

    task = asyncio.create_task(runner._handle_message(event))
    assert await asyncio.to_thread(started.wait, 1)
    # This coroutine can still run while the secret resolver is blocked.
    await asyncio.wait_for(asyncio.sleep(0), timeout=0.1)
    release.set()

    assert await task == "ok"
    assert observed["scope"] == {"HONCHO_API_KEY": "worker-vault-key"}


@pytest.mark.asyncio
async def test_concurrent_profiles_keep_prompt_routing_auth_and_fallback_local(
    tmp_path,
    monkeypatch,
):
    """Two live profile scopes never exchange turn policy or credentials."""
    from gateway.config import GatewayConfig, Platform
    from gateway.run import (
        GatewayRunner,
        _load_gateway_runtime_config,
        _profile_runtime_scope,
        _resolve_gateway_model,
    )
    from gateway.session import SessionSource

    monkeypatch.setenv("DISCORD_ALLOWED_USERS", "launch-user")
    monkeypatch.setenv("PROMPT_TOKEN", "launch-prompt")
    ss.set_multiplex_active(True)

    homes = {}
    for name, marker in (("alpha", "A"), ("beta", "B")):
        home = tmp_path / "profiles" / name
        home.mkdir(parents=True)
        homes[name] = home
        (home / ".env").write_text(
            f"DISCORD_ALLOWED_USERS=admin-{name}\n"
            f"PROMPT_TOKEN={marker}\n"
            f"PROVIDER_KEY=provider-key-{marker}\n",
            encoding="utf-8",
        )
        (home / "prefill.json").write_text(
            json.dumps([{"role": "system", "content": f"prefill-{marker}"}]),
            encoding="utf-8",
        )
        (home / "config.yaml").write_text(
            "model:\n"
            f"  default: model-{marker}\n"
            f"  provider: provider-{marker}\n"
            "  api_key: ${PROVIDER_KEY}\n"
            f"  base_url: https://provider-{marker}.example/v1\n"
            "agent:\n"
            "  system_prompt: profile-${PROMPT_TOKEN}\n"
            "  prefill_messages_file: prefill.json\n"
            "  service_tier: fast\n"
            "provider_routing:\n"
            f"  order: [route-{marker}]\n"
            "fallback_providers:\n"
            f"  - provider: fallback-{marker}\n"
            f"    model: fallback-model-{marker}\n"
            "discord:\n"
            f"  allow_admin_from: [admin-{name}]\n"
            "  user_allowed_commands: [help]\n",
            encoding="utf-8",
        )

    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(multiplex_profiles=True)
    runner.adapters = {}
    runner._profile_adapters = {"alpha": {}, "beta": {}}
    runner.pairing_stores = {}
    runner.pairing_store = SimpleNamespace(
        is_approved=lambda *_args, **_kwargs: False
    )
    runner._session_model_overrides = {}
    runner._last_resolved_model = {}
    runner.session_store = None

    def fake_resolve_runtime_provider(
        *,
        requested=None,
        explicit_base_url=None,
        explicit_api_key=None,
        **_kwargs,
    ):
        return {
            "provider": requested,
            "base_url": explicit_base_url,
            "api_key": explicit_api_key,
            "api_mode": "chat_completions",
        }

    monkeypatch.setattr(
        "fabric_cli.runtime_provider.resolve_runtime_provider",
        fake_resolve_runtime_provider,
    )
    barrier = threading.Barrier(2)

    def resolve(name):
        home = homes[name]
        other_name = "beta" if name == "alpha" else "alpha"
        source = SessionSource(
            platform=Platform.DISCORD,
            chat_id=f"chat-{name}",
            chat_type="dm",
            user_id=f"admin-{name}",
            profile=name,
        )
        foreign_source = SessionSource(
            platform=Platform.DISCORD,
            chat_id=f"chat-{name}",
            chat_type="dm",
            user_id=f"admin-{other_name}",
            profile=name,
        )
        with _profile_runtime_scope(home):
            barrier.wait(timeout=2)
            config = _load_gateway_runtime_config()
            gateway_config = runner._authorization_gateway_config()
            prompt = runner._load_ephemeral_system_prompt(
                config,
                allow_process_env=False,
            )
            prefill = runner._load_prefill_messages(
                config,
                config_home=home,
                allow_process_env=False,
            )
            runtime_model, runtime = runner._resolve_session_agent_runtime(
                source=source,
                session_key=f"session-{name}",
                user_config=config,
                gateway_config=gateway_config,
            )
            return {
                "model": _resolve_gateway_model(config),
                "runtime_model": runtime_model,
                "provider": runtime["provider"],
                "api_key": runtime["api_key"],
                "base_url": runtime["base_url"],
                "prompt": prompt,
                "prefill": prefill[0]["content"],
                "route": runner._load_provider_routing(config)["order"][0],
                "fallback": runner._refresh_fallback_model(config)[0]["model"],
                "authorized": runner._is_user_authorized(source),
                "slash_denial": runner._check_slash_access(source, "update"),
                "foreign_slash_denied": runner._check_slash_access(
                    foreign_source,
                    "update",
                )
                is not None,
                "config_admin": gateway_config.platforms[
                    Platform.DISCORD
                ].extra["allow_admin_from"][0],
            }

    alpha, beta = await asyncio.gather(
        asyncio.to_thread(resolve, "alpha"),
        asyncio.to_thread(resolve, "beta"),
    )

    assert alpha == {
        "model": "model-A",
        "runtime_model": "model-A",
        "provider": "provider-A",
        "api_key": "provider-key-A",
        "base_url": "https://provider-A.example/v1",
        "prompt": "profile-A",
        "prefill": "prefill-A",
        "route": "route-A",
        "fallback": "fallback-model-A",
        "authorized": True,
        "slash_denial": None,
        "foreign_slash_denied": True,
        "config_admin": "admin-alpha",
    }
    assert beta == {
        "model": "model-B",
        "runtime_model": "model-B",
        "provider": "provider-B",
        "api_key": "provider-key-B",
        "base_url": "https://provider-B.example/v1",
        "prompt": "profile-B",
        "prefill": "prefill-B",
        "route": "route-B",
        "fallback": "fallback-model-B",
        "authorized": True,
        "slash_denial": None,
        "foreign_slash_denied": True,
        "config_admin": "admin-beta",
    }


def test_adapter_auth_callback_binds_profile_home_and_secrets(tmp_path):
    """External-context auth runs with the adapter's owning profile bound."""
    from fabric_constants import get_fabric_home
    from gateway.config import GatewayConfig, Platform
    from gateway.run import GatewayRunner

    profile_home = tmp_path / "profiles" / "beta"
    profile_home.mkdir(parents=True)
    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(multiplex_profiles=True)
    observed = {}

    def authorize(source):
        observed.update(
            profile=source.profile,
            home=get_fabric_home(),
            secret=ss.get_secret("DISCORD_ALLOWED_USERS"),
        )
        return source.user_id == "beta-user"

    runner._is_user_authorized = authorize
    check = runner._make_adapter_auth_check(
        Platform.DISCORD,
        profile_name="beta",
        profile_home=profile_home,
        profile_secrets={"DISCORD_ALLOWED_USERS": "beta-user"},
    )

    assert check("beta-user", "group", "beta-chat") is True
    assert observed == {
        "profile": "beta",
        "home": profile_home,
        "secret": "beta-user",
    }
    assert ss.current_secret_scope() is None


def test_last_good_model_fallback_is_profile_scoped(monkeypatch):
    """A transient empty config cannot recover another profile's model."""
    from gateway.config import GatewayConfig, Platform
    from gateway.run import GatewayRunner
    from gateway.session import SessionSource

    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(multiplex_profiles=True)
    runner._session_model_overrides = {}
    runner._last_resolved_model = {
        "profile:alpha": "model-A",
        "profile:beta": "model-B",
        "*": "launch-model",
    }
    runner._rehydrate_session_model_override = lambda _key: None
    runner._active_profile_name = lambda: "default"
    monkeypatch.setattr(
        "gateway.run._resolve_scoped_runtime_agent_kwargs",
        lambda _config: {
            "provider": None,
            "api_key": None,
            "base_url": None,
            "api_mode": None,
        },
    )

    def resolve(profile):
        source = SessionSource(
            platform=Platform.DISCORD,
            chat_id=f"chat-{profile}",
            user_id=f"user-{profile}",
            profile=profile,
        )
        model, _runtime = runner._resolve_session_agent_runtime(
            source=source,
            session_key=f"session-{profile}",
            user_config={},
            gateway_config=GatewayConfig(),
        )
        return model

    assert resolve("alpha") == "model-A"
    assert resolve("beta") == "model-B"
    assert resolve("unknown") == ""


def test_cached_agent_provider_routing_is_refreshed_from_turn_snapshot():
    """Cached agents cannot retain another/older turn's routing policy."""
    from gateway.run import GatewayRunner

    agent = SimpleNamespace(
        providers_allowed=["stale"],
        providers_ignored=["stale"],
        providers_order=["stale"],
        provider_sort="stale",
        provider_require_parameters=False,
        provider_data_collection="stale",
    )
    routing = {
        "only": ["profile-provider"],
        "ignore": ["blocked-provider"],
        "order": ["preferred-provider"],
        "sort": "throughput",
        "require_parameters": True,
        "data_collection": "deny",
    }

    GatewayRunner._apply_turn_provider_routing(agent, routing)

    assert agent.providers_allowed == ["profile-provider"]
    assert agent.providers_ignored == ["blocked-provider"]
    assert agent.providers_order == ["preferred-provider"]
    assert agent.provider_sort == "throughput"
    assert agent.provider_require_parameters is True
    assert agent.provider_data_collection == "deny"
    assert agent.providers_allowed is not routing["only"]


@pytest.mark.asyncio
async def test_hygiene_agent_constructor_runs_off_event_loop(tmp_path):
    """A blocking provider constructor cannot stop the gateway ticker."""
    from fabric_constants import get_fabric_home
    from gateway.run import GatewayRunner, _profile_runtime_scope

    started = threading.Event()
    release = threading.Event()
    constructor_thread = []

    class BlockingAgent:
        def __init__(self, **kwargs):
            constructor_thread.append(threading.get_ident())
            assert get_fabric_home() == tmp_path
            assert ss.get_secret("PROFILE_KEY") == "scoped-key"
            self.session_id = kwargs["session_id"]
            self.context_compressor = SimpleNamespace(bind_session_state=lambda *_: None)
            started.set()
            assert release.wait(timeout=2)

        def _compress_context(self, messages, *_args, **_kwargs):
            return list(messages), ""

    runner = object.__new__(GatewayRunner)
    main_thread = threading.get_ident()
    ticks = []

    async def ticker():
        assert await asyncio.to_thread(started.wait, 1)
        for _ in range(3):
            ticks.append("tick")
            await asyncio.sleep(0)
        release.set()

    with _profile_runtime_scope(
        tmp_path,
        secrets={"PROFILE_KEY": "scoped-key"},
    ):
        compression = runner._construct_and_compress_hygiene_agent(
            BlockingAgent,
            runtime={"api_key": "scoped-key"},
            model="model-A",
            session_id="session-A",
            session_db=None,
            messages=[{"role": "user", "content": "hello"}],
            approx_tokens=1,
        )
        (agent, compressed), _ = await asyncio.wait_for(
            asyncio.gather(compression, ticker()),
            timeout=2,
        )

    assert len(constructor_thread) == 1
    assert constructor_thread[0] != main_thread
    assert ticks == ["tick", "tick", "tick"]
    assert agent.session_id == "session-A"
    assert compressed == [{"role": "user", "content": "hello"}]
    runner._shutdown_executor()


def test_secondary_profile_fails_closed_against_global_mcp_registry():
    """Launch-profile MCP schemas and bridges never enter a secondary turn."""
    from gateway.config import GatewayConfig, Platform
    from gateway.run import GatewayRunner
    from gateway.session import SessionSource
    from tools.registry import registry

    tool_name = "mcp__launch_only__read_secret"
    registry.register(
        name=tool_name,
        toolset="mcp-launch-only",
        schema={
            "name": tool_name,
            "description": "launch profile only",
            "parameters": {"type": "object", "properties": {}},
        },
        handler=lambda **_kwargs: "should-not-run",
    )
    try:
        runner = object.__new__(GatewayRunner)
        runner.config = GatewayConfig(multiplex_profiles=True)
        runner._active_profile_name = lambda: "default"
        source = SessionSource(
            platform=Platform.DISCORD,
            chat_id="secondary-chat",
            user_id="secondary-user",
            profile="secondary",
        )
        assert runner._is_secondary_profile_source(source) is True
        primary_source = SessionSource(
            platform=Platform.DISCORD,
            chat_id="primary-chat",
            user_id="primary-user",
            profile="default",
        )
        assert runner._is_secondary_profile_source(primary_source) is False
        assert "mcp-launch-only" in runner._disable_registered_mcp_toolsets(
            ["browser"]
        )

        agent = SimpleNamespace(
            tools=[
                {"type": "function", "function": {"name": tool_name}},
                {"type": "function", "function": {"name": "tool_search"}},
                {"type": "function", "function": {"name": "tool_describe"}},
                {"type": "function", "function": {"name": "tool_call"}},
                {"type": "function", "function": {"name": "read_file"}},
            ],
            valid_tool_names={
                tool_name,
                "tool_search",
                "tool_describe",
                "tool_call",
                "read_file",
            },
            enabled_toolsets=["file", "mcp-launch-only"],
            disabled_toolsets=["browser"],
            _skip_mcp_refresh=False,
        )
        runner._apply_secondary_profile_mcp_gate(agent)

        assert [tool["function"]["name"] for tool in agent.tools] == [
            "read_file"
        ]
        assert agent.valid_tool_names == {"read_file"}
        assert not any(
            toolset.startswith("mcp-")
            for toolset in agent.enabled_toolsets
        )
        assert "mcp-launch-only" in agent.disabled_toolsets
        assert agent._skip_mcp_refresh is True
    finally:
        registry.deregister(tool_name)
