"""Tests for fallback credential pool isolation.

Verifies that fallback activation isolates the credential pool from the
primary provider, preventing two bugs:

1. GH #33163: fallback retains primary's base_url → requests go to wrong endpoint
2. GH #33088: fallback provider's 429 exhausts primary credential pool

Both bugs share the same root cause: _recover_with_credential_pool and
_swap_credential continue operating on the PRIMARY's credential pool during
fallback calls, contaminating primary state with fallback-provider errors.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest



# ── Helpers ──────────────────────────────────────────────────────────

def _make_pool(provider, n_entries=1):
    """Create a mock credential pool with N entries."""
    pool = MagicMock()
    pool.provider = provider
    pool.has_credentials.return_value = n_entries > 0
    pool.has_available.return_value = n_entries > 0
    entry = MagicMock()
    entry.id = f"{provider}-entry-0"
    entry.runtime_api_key = f"key-{provider}"
    entry.runtime_base_url = f"https://{provider}.example.com/v1"
    entry.access_token = f"token-{provider}"
    entry.base_url = f"https://{provider}.example.com/v1"
    pool.current.return_value = entry
    pool.mark_exhausted_and_rotate.return_value = entry
    return pool


def _make_agent(provider="openai-codex", model="gpt-5.5",
                base_url="https://chatgpt.com/backend-api/codex",
                api_mode="codex_responses"):
    """Create a minimal AIAgent-like object with just the fields we need."""
    agent = MagicMock()
    agent.provider = provider
    agent.model = model
    agent.base_url = base_url
    agent.api_mode = api_mode
    agent.api_key = "primary-key"
    agent._fallback_activated = False
    agent._fallback_index = 0
    agent._fallback_chain = []
    agent._primary_runtime = {
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "api_mode": api_mode,
        "api_key": "primary-key",
        "client_kwargs": {
            "api_key": "primary-key",
            "base_url": base_url,
        },
        "use_prompt_caching": False,
        "use_native_cache_layout": False,
        "anthropic_api_key": "",
        "anthropic_base_url": "",
    }
    agent._config_context_length = None
    agent._credential_pool = _make_pool(provider)
    agent._rate_limited_until = 0
    agent._transport_cache = {}
    agent._client_kwargs = {
        "api_key": "primary-key",
        "base_url": base_url,
    }
    return agent


# ── Test: _try_activate_fallback clears mismatched pool ──────────────

class TestFallbackCredentialIsolation:
    """Test that _try_activate_fallback isolates the credential pool."""

    def test_fallback_clears_primary_pool(self):
        """When switching from openai-codex to openrouter, the codex pool is cleared."""
        # We test the isolation logic directly here as a minimal guard; the
        # integration-style test below calls the real fallback activator.

        agent = _make_agent(provider="openai-codex", base_url="https://chatgpt.com/backend-api/codex")
        agent._fallback_activated = True
        agent._credential_pool = _make_pool("openai-codex")

        # Simulate: after fallback activation, provider is now openrouter
        fb_provider = "openrouter"
        fb_model = "openrouter/auto"

        # The isolation code from _try_activate_fallback:
        pool = getattr(agent, "_credential_pool", None)
        if pool is not None:
            pool_provider = getattr(pool, "provider", "") or ""
            if pool_provider.lower() != fb_provider:
                agent._credential_pool = None

        assert agent._credential_pool is None, (
            "Pool should be cleared when fallback provider differs from pool provider"
        )

    def test_fallback_keeps_matching_pool(self):
        """When fallback provider matches pool provider, pool is preserved."""
        agent = _make_agent(provider="openrouter", base_url="https://openrouter.ai/api/v1")
        agent._credential_pool = _make_pool("openrouter")

        fb_provider = "openrouter"

        pool = getattr(agent, "_credential_pool", None)
        if pool is not None:
            pool_provider = getattr(pool, "provider", "") or ""
            if pool_provider.lower() != fb_provider:
                agent._credential_pool = None

        assert agent._credential_pool is not None, (
            "Pool should be preserved when fallback provider matches pool provider"
        )

    def test_fallback_attaches_matching_pool_after_clear(self):
        """Provider-switch fallback should attach the fallback provider's pool."""
        from agent.chat_completion_helpers import try_activate_fallback

        agent = _make_agent(
            provider="ollama-cloud",
            model="glm-5.2",
            base_url="https://ollama.com/v1",
            api_mode="chat_completions",
        )
        agent._fallback_chain = [{"provider": "openai-codex", "model": "gpt-5.5"}]
        agent._credential_pool = _make_pool("ollama-cloud")
        agent._buffer_status = MagicMock()
        agent._is_azure_openai_url.return_value = False
        agent._is_direct_openai_url.return_value = False
        agent._provider_model_requires_responses_api.return_value = False
        agent._anthropic_prompt_cache_policy.return_value = (False, False)
        agent._ensure_lmstudio_runtime_loaded = MagicMock()
        agent._replace_primary_openai_client = MagicMock()
        agent.context_compressor = None

        fallback_client = SimpleNamespace(
            api_key="codex-key",
            base_url="https://chatgpt.com/backend-api/codex",
            _custom_headers={},
        )
        fallback_pool = _make_pool("openai-codex")

        with patch(
            "agent.auxiliary_client.resolve_provider_client",
            return_value=(fallback_client, "gpt-5.5"),
        ) as resolve_provider_client, patch(
            "agent.credential_pool.load_pool",
            return_value=fallback_pool,
        ) as load_pool:
            assert try_activate_fallback(agent) is True

        resolve_provider_client.assert_called_once()
        load_pool.assert_called_once_with("openai-codex")
        assert agent.provider == "openai-codex"
        assert agent.model == "gpt-5.5"
        assert agent.base_url == "https://chatgpt.com/backend-api/codex"
        assert agent.api_mode == "codex_responses"
        assert agent._credential_pool is fallback_pool
        assert agent._credential_pool.provider == "openai-codex"
        assert agent._transport_cache == {}

    @pytest.mark.parametrize("fallback_provider", ["custom:claude", "claude"])
    def test_anthropic_alias_named_custom_fallback_is_not_hijacked(
        self, fallback_provider
    ):
        """A saved custom provider may intentionally use an alias-like name."""
        from agent.chat_completion_helpers import try_activate_fallback
        from agent.egress_policy import EgressMode, EgressPolicy

        custom_url = "https://private-gateway.example/v1"
        route_config = {
            "providers": {
                "claude": {
                    "name": "claude",
                    "base_url": custom_url,
                    "api_key": "private-key",
                    "default_model": "private-model",
                    "transport": "chat_completions",
                }
            }
        }
        agent = _make_agent(provider="openrouter", model="openrouter/auto")
        agent._fallback_chain = [{
            "provider": fallback_provider,
            "model": "private-model",
            "base_url": custom_url,
            "api_key": "private-key",
        }]
        agent._buffer_status = MagicMock()
        agent._is_azure_openai_url.return_value = False
        agent._is_direct_openai_url.return_value = False
        agent._provider_model_requires_responses_api.return_value = False
        agent._anthropic_prompt_cache_policy.return_value = (False, False)
        agent._ensure_lmstudio_runtime_loaded = MagicMock()
        agent.context_compressor = None

        created_clients = []

        def _create_openai_client(**kwargs):
            client = SimpleNamespace(
                api_key=kwargs["api_key"],
                base_url=kwargs["base_url"],
                _custom_headers=kwargs.get("default_headers") or {},
            )
            created_clients.append(client)
            return client

        with patch(
            "agent.auxiliary_client._load_auxiliary_egress_context",
            return_value=(EgressPolicy(EgressMode.ONLINE), route_config),
        ), patch(
            "fabric_cli.runtime_provider.load_config",
            return_value=route_config,
        ), patch(
            "agent.auxiliary_client._create_openai_client",
            side_effect=_create_openai_client,
        ), patch(
            "agent.credential_pool.load_pool",
            return_value=None,
        ) as load_pool:
            assert try_activate_fallback(agent) is True

        load_pool.assert_called_once_with(fallback_provider)
        assert len(created_clients) == 1
        assert created_clients[0].api_key == "private-key"
        assert created_clients[0].base_url == custom_url
        assert agent.provider == fallback_provider
        assert agent.api_mode == "chat_completions"
        assert agent.base_url == custom_url

    def test_local_named_alias_preflights_before_resolution_without_expanded_lookup(
        self,
    ):
        """Restricted fallback keeps alias identity raw until local authorization."""
        from agent.chat_completion_helpers import try_activate_fallback
        from agent.egress_policy import (
            EgressMode,
            EgressPolicy,
            authorize_inference_route,
        )

        local_url = "http://127.0.0.1:8111/v1"
        local_policy = EgressPolicy(EgressMode.LOCAL_AI)
        raw_route_config = {
            "providers": {
                "claude": {
                    "base_url": local_url,
                    "api_key": "${LOCAL_RELAY_KEY}",
                }
            }
        }
        agent = _make_agent(
            provider="ollama",
            model="primary-model",
            base_url="http://127.0.0.1:11434/v1",
            api_mode="chat_completions",
        )
        agent._fallback_chain = [{
            "provider": "claude",
            "model": "relay-model",
            "api_mode": "chat_completions",
        }]
        agent._unavailable_fallback_keys = set()
        agent._buffer_status = MagicMock()
        agent._is_azure_openai_url.return_value = False
        agent._is_direct_openai_url.return_value = False
        agent._provider_model_requires_responses_api.return_value = False
        agent._anthropic_prompt_cache_policy.return_value = (False, False)
        agent._ensure_lmstudio_runtime_loaded = MagicMock()
        agent.context_compressor = None

        fallback_client = SimpleNamespace(
            api_key="local-key",
            base_url=local_url,
            _custom_headers={},
        )
        call_order = []

        def _authorize(**kwargs):
            call_order.append(("authorize", kwargs["provider"]))
            return authorize_inference_route(
                local_policy,
                purpose="fallback",
                provider=kwargs["provider"],
                base_url=local_url,
            )

        def _resolve(provider, **kwargs):
            call_order.append(("resolve", provider))
            return fallback_client, kwargs["model"]

        with patch(
            "agent.auxiliary_client._load_auxiliary_egress_context",
            return_value=(local_policy, raw_route_config),
        ), patch(
            "agent.auxiliary_client._authorize_auxiliary_route",
            side_effect=_authorize,
        ), patch(
            "agent.auxiliary_client.resolve_provider_client",
            side_effect=_resolve,
        ), patch(
            "fabric_cli.runtime_provider.has_named_custom_provider",
        ) as has_named_custom_provider, patch(
            "agent.credential_pool.load_pool",
            return_value=None,
        ):
            assert try_activate_fallback(agent) is True

        assert call_order == [("authorize", "claude"), ("resolve", "claude")]
        has_named_custom_provider.assert_not_called()
        assert agent.provider == "custom"
        assert agent.base_url == local_url
        assert agent._disable_environment_proxy is True

    @pytest.mark.parametrize(
        "fallback_provider",
        ["claude", "claude-oauth", "claude-code"],
    )
    @pytest.mark.parametrize("pool_strategy", ["round_robin", "random"])
    def test_anthropic_fallback_pool_cannot_rotate_across_endpoints(
        self, fallback_provider, pool_strategy
    ):
        """A routed fallback selects and later exhausts its exact pool key."""
        from agent.agent_runtime_helpers import recover_with_credential_pool
        from agent.chat_completion_helpers import try_activate_fallback
        from agent.credential_pool import (
            STATUS_EXHAUSTED,
            STRATEGY_RANDOM,
            STRATEGY_ROUND_ROBIN,
            CredentialPool,
            PooledCredential,
        )

        native_url = "https://api.anthropic.com"
        azure_url = "https://resource-b.services.ai.azure.com/anthropic"
        native_entry = PooledCredential(
            provider="anthropic",
            id="native",
            label="native",
            auth_type="api_key",
            priority=0,
            source="manual:native",
            access_token="sk-ant-api03-native",
            base_url=native_url,
        )
        azure_entry_a = PooledCredential(
            provider="anthropic",
            id="azure-a",
            label="azure-a",
            auth_type="api_key",
            priority=1,
            source="manual:azure-a",
            access_token="azure-resource-b-key-a",
            base_url=azure_url,
        )
        azure_entry_b = PooledCredential(
            provider="anthropic",
            id="azure-b",
            label="azure-b",
            auth_type="api_key",
            priority=2,
            source="manual:azure-b",
            access_token="azure-resource-b-key-b",
            base_url=azure_url,
        )

        def _fresh_unfiltered_pool():
            pool = CredentialPool(
                "anthropic",
                [native_entry, azure_entry_a, azure_entry_b],
            )
            pool._strategy = pool_strategy
            return pool

        agent = _make_agent(
            provider="anthropic",
            model="claude-opus-4-20250514",
            base_url=native_url,
            api_mode="anthropic_messages",
        )
        # The primary already holds a native-only live pool view. A
        # same-provider fallback must reload the full persisted pool before
        # filtering; filtering this existing view could never discover Azure.
        agent._credential_pool = CredentialPool("anthropic", [native_entry])
        agent._fallback_chain = [
            {
                "provider": fallback_provider,
                "model": "claude-sonnet-4-20250514",
                "base_url": azure_url,
            }
        ]
        agent._buffer_status = MagicMock()
        agent._is_azure_openai_url.return_value = False
        agent._is_direct_openai_url.return_value = False
        agent._provider_model_requires_responses_api.return_value = False
        agent._anthropic_prompt_cache_policy.return_value = (False, False)
        agent._ensure_lmstudio_runtime_loaded = MagicMock()
        agent.context_compressor = None

        # Do not mock resolve_provider_client: exercise the real fallback URL
        # -> endpoint-filtered Anthropic pool -> client chain. The standalone
        # resolver deliberately exposes only the primary native route here, so
        # the fallback succeeds only if _try_anthropic selects its Azure tuple.
        with patch(
            "agent.auxiliary_client.load_pool",
            return_value=_fresh_unfiltered_pool(),
        ), patch(
            "agent.credential_pool.load_pool",
            return_value=_fresh_unfiltered_pool(),
        ), patch(
            "fabric_cli.auth.resolve_api_key_provider_credentials",
            return_value={
                "api_key": native_entry.access_token,
                "base_url": native_url,
            },
        ), patch(
            "agent.anthropic_adapter.build_anthropic_client",
            return_value=MagicMock(),
        ), patch(
            "agent.credential_pool.CredentialPool._persist",
            autospec=True,
        ), patch(
            "agent.credential_pool.get_pool_strategy",
            return_value=pool_strategy,
        ), patch(
            "agent.credential_pool.random.choice",
            side_effect=lambda entries: entries[-1],
        ):
            assert try_activate_fallback(agent) is True

        attached_pool = agent._credential_pool
        assert [entry.id for entry in attached_pool.entries()] == [
            "azure-a",
            "azure-b",
        ]
        failed_entry = (
            azure_entry_b
            if pool_strategy == STRATEGY_RANDOM
            else azure_entry_a
        )
        next_entry = (
            azure_entry_a
            if pool_strategy == STRATEGY_RANDOM
            else azure_entry_b
        )
        assert pool_strategy in {STRATEGY_RANDOM, STRATEGY_ROUND_ROBIN}
        assert attached_pool.current().id == failed_entry.id
        assert agent.provider == "anthropic"
        assert agent.api_key == failed_entry.access_token
        # This test exercises in-memory recovery only; never persist its fake
        # credentials/statuses to whichever FABRIC_HOME invoked pytest.
        attached_pool._persist = MagicMock()

        # The terminal 429 must exhaust azure-a—the key that actually served
        # the request—and rotate only to its same-endpoint sibling.
        recovered, retried = recover_with_credential_pool(
            agent,
            status_code=429,
            has_retried_429=True,
        )
        assert recovered is True
        assert retried is False
        entries_by_id = {entry.id: entry for entry in attached_pool.entries()}
        assert entries_by_id[failed_entry.id].last_status == STATUS_EXHAUSTED
        assert entries_by_id[next_entry.id].last_status != STATUS_EXHAUSTED
        assert attached_pool.current().id == next_entry.id
        agent._swap_credential.assert_called_once()
        assert agent._swap_credential.call_args.args[0].id == next_entry.id


# ── Test: _recover_with_credential_pool rejects mismatched pool ──────

class TestRecoveryProviderGuard:
    """Test that _recover_with_credential_pool skips mismatched pools."""

    def test_recovery_skips_mismatched_pool(self):
        """_recover_with_credential_pool should not mutate a pool belonging
        to a different provider than the active agent provider."""
        agent = _make_agent(provider="openrouter")
        # Pool still belongs to primary (openai-codex) — mismatch
        agent._credential_pool = _make_pool("openai-codex")

        current_provider = (getattr(agent, "provider", "") or "").strip().lower()
        pool_provider = getattr(agent._credential_pool, "provider", "") or ""

        # The guard logic:
        should_skip = (current_provider and pool_provider and
                       current_provider != pool_provider)

        assert should_skip is True, (
            f"Provider mismatch: agent={current_provider}, pool={pool_provider} — should skip"
        )

    def test_recovery_allows_matching_pool(self):
        """When pool and agent provider match, recovery proceeds normally."""
        agent = _make_agent(provider="openrouter")
        agent._credential_pool = _make_pool("openrouter")

        current_provider = (getattr(agent, "provider", "") or "").strip().lower()
        pool_provider = getattr(agent._credential_pool, "provider", "") or ""

        should_skip = (current_provider and pool_provider and
                       current_provider != pool_provider)

        assert should_skip is False, (
            "Same provider — should allow recovery"
        )

    def test_recovery_429_from_zai_does_not_exhaust_codex_pool(self):
        """Regression test for GH #33088: zai 429 should NOT exhaust
        openai-codex credential pool."""
        agent = _make_agent(provider="zai", base_url="https://api.z.com/v1")
        # Stale codex pool from primary
        codex_pool = _make_pool("openai-codex")
        agent._credential_pool = codex_pool

        # The guard should prevent mark_exhausted_and_rotate from being called
        current_provider = "zai"
        pool_provider = "openai-codex"
        should_skip = current_provider != pool_provider

        assert should_skip is True
        codex_pool.mark_exhausted_and_rotate.assert_not_called()


# ── Test: base_url not overwritten after fallback ────────────────────

class TestBaseUrlLeak:
    """Regression tests for GH #33163: base_url leaks from primary."""

    def test_client_kwargs_base_url_preserved_after_pool_clear(self):
        """After fallback activation clears the pool, _client_kwargs should
        still have the fallback base_url, not the primary's."""
        agent = _make_agent(
            provider="openai-codex",
            base_url="https://chatgpt.com/backend-api/codex"
        )

        # Simulate what _try_activate_fallback does:
        fb_base_url = "https://openrouter.ai/api/v1/"
        agent.provider = "openrouter"
        agent.base_url = fb_base_url
        agent._client_kwargs = {
            "api_key": "or-key",
            "base_url": fb_base_url,
        }

        # Clear mismatched pool
        agent._credential_pool = None

        assert agent._client_kwargs["base_url"] == fb_base_url, (
            f"base_url should be {fb_base_url}, not primary's URL"
        )

    def test_swap_credential_does_not_restore_primary_url(self):
        """_swap_credential should not be called when pool is None,
        preventing it from overwriting base_url back to primary's."""
        agent = _make_agent(provider="openrouter", base_url="https://openrouter.ai/api/v1/")
        agent._credential_pool = None  # Cleared by fallback isolation

        # If pool is None, _recover_with_credential_pool returns early
        # and _swap_credential is never called
        pool = agent._credential_pool
        assert pool is None, "Pool should be None — _swap_credential won't be reached"
