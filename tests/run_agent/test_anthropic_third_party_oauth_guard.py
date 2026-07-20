"""Tests for the retired native-Anthropic OAuth runtime flag.

The invariant: ``self._is_anthropic_oauth`` is always False for every
supported runtime credential. Native Anthropic OAuth is unsupported, while a
third-party endpoint may legitimately issue a JWT-shaped API key even when the
Fabric provider id remains ``anthropic``. Token shape must not reactivate the
legacy subscription-only 1M-context-beta retry (see NOTICE).

The tests cover the live construction and credential-transition paths:

1. ``AIAgent.__init__``
2. ``AIAgent.switch_model``
3. ``AIAgent._swap_credential``
4. ``AIAgent._try_activate_fallback``
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from run_agent import AIAgent


# A canonical Anthropic OAuth setup-token shape.
_OAUTH_LIKE_TOKEN = "sk-ant-oat01-example-1234567890abcdef"
_API_KEY_TOKEN = "sk-ant-api-abcdef1234567890"


@pytest.fixture
def agent():
    """Minimal AIAgent construction, skipping tool discovery."""
    with (
        patch("run_agent.get_tool_definitions", return_value=[]),
        patch("run_agent.check_toolset_requirements", return_value={}),
        patch("run_agent.OpenAI"),
    ):
        a = AIAgent(
            api_key="test-key-1234567890",
            base_url="https://openrouter.ai/api/v1",
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
        )
        a.client = MagicMock()
        return a


class TestOAuthFlagOnRefresh:
    """Site 3 — _try_refresh_anthropic_client_credentials."""

    def test_third_party_provider_refresh_is_noop(self, agent):
        """Refresh path returns False immediately when provider != anthropic — the
        OAuth flag can never be mutated for third-party providers. Double-defended
        by the per-assignment guard at line ~5393 so future refactors can't
        reintroduce the bug."""
        agent.api_mode = "anthropic_messages"
        agent.provider = "minimax"          # ← third-party
        agent._anthropic_api_key = "***"
        agent._anthropic_client = MagicMock()
        agent._is_anthropic_oauth = False

        with (
            patch("agent.anthropic_adapter.resolve_anthropic_token",
                  return_value=_OAUTH_LIKE_TOKEN),
            patch("agent.anthropic_adapter.build_anthropic_client",
                  return_value=MagicMock()),
        ):
            result = agent._try_refresh_anthropic_client_credentials()

        # The function short-circuits on non-anthropic providers.
        assert result is False
        # And the flag is untouched regardless.
        assert agent._is_anthropic_oauth is False

    def test_native_anthropic_oauth_refresh_path_is_removed(self, agent):
        agent.api_mode = "anthropic_messages"
        agent.provider = "anthropic"
        agent._anthropic_api_key = "***"
        agent._anthropic_client = MagicMock()
        agent._is_anthropic_oauth = False

        with (
            patch("agent.anthropic_adapter.resolve_anthropic_token",
                  return_value=_OAUTH_LIKE_TOKEN),
            patch("agent.anthropic_adapter.build_anthropic_client",
                  return_value=MagicMock()),
        ):
            result = agent._try_refresh_anthropic_client_credentials()

        assert result is False
        assert agent._is_anthropic_oauth is False


class TestOAuthFlagOnCredentialSwap:
    """Site 4 — _swap_credential (credential pool rotation)."""

    def test_pool_swap_on_third_party_never_flips_oauth(self, agent):
        agent.api_mode = "anthropic_messages"
        agent.provider = "glm"              # ← Zhipu GLM via /anthropic
        agent._anthropic_api_key = "old-key"
        agent._anthropic_base_url = "https://open.bigmodel.cn/api/anthropic"
        agent._anthropic_client = MagicMock()
        agent._is_anthropic_oauth = False

        entry = MagicMock()
        entry.runtime_api_key = _OAUTH_LIKE_TOKEN
        entry.runtime_base_url = "https://open.bigmodel.cn/api/anthropic"

        with patch("agent.anthropic_adapter.build_anthropic_client",
                   return_value=MagicMock()):
            agent._swap_credential(entry)

        assert agent._is_anthropic_oauth is False

    def test_proxy_jwt_swap_under_anthropic_provider_stays_non_oauth(self, agent):
        agent.api_mode = "anthropic_messages"
        agent.provider = "anthropic"
        agent.base_url = "https://gateway.example/anthropic"
        agent._anthropic_api_key = "old-proxy-key"
        agent._anthropic_base_url = agent.base_url
        agent._anthropic_client = MagicMock()
        agent._is_anthropic_oauth = True

        entry = MagicMock()
        entry.runtime_api_key = "eyJ.proxy.signature"
        entry.runtime_base_url = agent.base_url

        with patch(
            "agent.anthropic_adapter.build_anthropic_client",
            return_value=MagicMock(),
        ):
            agent._swap_credential(entry)

        assert agent._anthropic_api_key == "eyJ.proxy.signature"
        assert agent._is_anthropic_oauth is False


class TestOAuthFlagOnConstruction:
    """Site 1 — AIAgent.__init__ on a third-party anthropic_messages provider."""

    def test_minimax_init_does_not_flip_oauth(self):
        with (
            patch("run_agent.get_tool_definitions", return_value=[]),
            patch("run_agent.check_toolset_requirements", return_value={}),
            patch("agent.anthropic_adapter.build_anthropic_client",
                  return_value=MagicMock()),
            # Simulate a stale ANTHROPIC_TOKEN in the env — the init code
            # MUST NOT fall back to it when provider != anthropic.
            patch("agent.anthropic_adapter.resolve_anthropic_token",
                  return_value=_OAUTH_LIKE_TOKEN),
        ):
            agent = AIAgent(
                api_key="minimax-key-1234",
                base_url="https://api.minimax.io/anthropic",
                provider="minimax",
                api_mode="anthropic_messages",
                model="claude-sonnet-4-6",
                quiet_mode=True,
                skip_context_files=True,
                skip_memory=True,
            )

        # The effective key should be the explicit minimax-key, not the
        # stale Anthropic OAuth token, and the OAuth flag must be False.
        assert agent._anthropic_api_key == "minimax-key-1234"
        assert agent._is_anthropic_oauth is False

    def test_anthropic_provider_with_proxy_jwt_does_not_flip_oauth(self):
        with (
            patch("run_agent.get_tool_definitions", return_value=[]),
            patch("run_agent.check_toolset_requirements", return_value={}),
            patch(
                "agent.anthropic_adapter.build_anthropic_client",
                return_value=MagicMock(),
            ),
        ):
            agent = AIAgent(
                api_key="eyJ.proxy.signature",
                base_url="https://gateway.example/anthropic",
                provider="anthropic",
                api_mode="anthropic_messages",
                model="claude-sonnet-4-6",
                quiet_mode=True,
                skip_context_files=True,
                skip_memory=True,
            )

        assert agent._anthropic_api_key == "eyJ.proxy.signature"
        assert agent._is_anthropic_oauth is False


class TestOAuthFlagOnModelSwitch:
    def test_switch_to_anthropic_proxy_jwt_clears_stale_flag(self, agent):
        agent._is_anthropic_oauth = True
        with (
            patch(
                "agent.anthropic_adapter.build_anthropic_client",
                return_value=MagicMock(),
            ),
            patch("agent.credential_pool.load_pool", return_value=None),
            patch(
                "fabric_cli.timeouts.get_provider_request_timeout",
                return_value=None,
            ),
        ):
            agent.switch_model(
                new_model="claude-sonnet-4-6",
                new_provider="anthropic",
                api_key="eyJ.proxy.signature",
                base_url="https://gateway.example/anthropic",
                api_mode="anthropic_messages",
            )

        assert agent._anthropic_api_key == "eyJ.proxy.signature"
        assert agent._is_anthropic_oauth is False


class TestOAuthFlagOnFallbackActivation:
    """Live fallback activation targeting an Anthropic-format endpoint."""

    def test_fallback_to_third_party_does_not_flip_oauth(self, agent):
        agent._fallback_activated = False
        agent._fallback_model = {
            "provider": "anthropic",
            "model": "claude-sonnet-4-6",
            "base_url": "https://gateway.example/anthropic",
        }
        agent._fallback_chain = [agent._fallback_model]
        agent._fallback_index = 0
        agent._is_anthropic_oauth = True

        fallback_client = MagicMock()
        fallback_client.api_key = "eyJ.proxy.signature"
        fallback_client.base_url = "https://gateway.example/anthropic"
        with (
            patch(
                "agent.auxiliary_client.resolve_provider_client",
                return_value=(fallback_client, None),
            ),
            patch(
                "agent.anthropic_adapter.build_anthropic_client",
                return_value=MagicMock(),
            ),
        ):
            assert agent._try_activate_fallback() is True

        assert agent._anthropic_api_key == "eyJ.proxy.signature"
        assert agent._is_anthropic_oauth is False


class TestApiKeyTokensAlwaysSafe:
    """Regression: plain API-key shapes must always resolve to non-OAuth, any provider."""

    def test_native_anthropic_with_api_key_token(self):
        from agent.anthropic_adapter import _is_oauth_token
        assert _is_oauth_token(_API_KEY_TOKEN) is False

    def test_third_party_key_shape(self):
        from agent.anthropic_adapter import _is_oauth_token
        # Third-party key shapes (MiniMax 'mxp-...', GLM 'glm.sess.', etc.)
        # already return False from _is_oauth_token; the guard adds a second
        # defense line in case future token formats accidentally look OAuth-y.
        assert _is_oauth_token("mxp-abcdef123") is False
