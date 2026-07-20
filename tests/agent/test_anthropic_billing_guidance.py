"""Tests for the Anthropic API billing branch of
``agent.conversation_loop._billing_or_entitlement_message``.

Native Anthropic credentials in Fabric are API keys. Billing failures must
point to Anthropic Console credits/spend limits, never Claude subscription
settings.
"""
from __future__ import annotations

from agent.conversation_loop import _billing_or_entitlement_message


def test_anthropic_api_billing_guidance():
    msg = _billing_or_entitlement_message(
        capability="model access",
        provider="anthropic",
        base_url="https://api.anthropic.com",
        model="claude-opus-4-7",
    )
    assert "claude.ai/settings/usage" not in msg
    assert "Anthropic Console" in msg
    assert "credits" in msg
    assert "subscription" not in msg.lower()
    # Must still offer the provider-switch escape hatch.
    assert "/model" in msg
    # Model name should be interpolated.
    assert "claude-opus-4-7" in msg


def test_non_anthropic_billing_guidance_unaffected():
    """A non-Anthropic provider keeps the generic billing guidance and does
    NOT get the Anthropic-specific claude.ai settings link."""
    msg = _billing_or_entitlement_message(
        capability="model access",
        provider="openrouter",
        base_url="https://openrouter.ai/api/v1",
        model="anthropic/claude-opus-4.7",
    )
    assert "claude.ai/settings/usage" not in msg
    # Generic path still surfaces the OpenRouter credits link.
    assert "openrouter.ai/settings/credits" in msg
