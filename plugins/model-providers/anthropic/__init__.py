"""Native Anthropic provider profile."""

import json
import logging
import urllib.request

from providers import register_provider
from providers.base import ProviderProfile

logger = logging.getLogger(__name__)


class AnthropicProfile(ProviderProfile):
    """Native Anthropic — uses x-api-key header, not Bearer."""

    def fetch_models(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 8.0,
    ) -> list[str] | None:
        """Anthropic uses x-api-key header and anthropic-version."""
        if not api_key:
            return None
        endpoint = str(base_url or self.base_url or "").strip().rstrip("/")
        if not endpoint:
            return None
        try:
            from agent.anthropic_adapter import (
                _anthropic_static_auth_headers,
                _with_anthropic_api_version,
            )

            headers = _anthropic_static_auth_headers(api_key, endpoint)
        except ImportError:
            return None
        except ValueError:
            return None
        models_url = (
            f"{endpoint}/models"
            if endpoint.endswith("/v1")
            else f"{endpoint}/v1/models"
        )
        models_url = _with_anthropic_api_version(models_url, endpoint)
        try:
            req = urllib.request.Request(models_url, headers=headers)
            req.add_header("Accept", "application/json")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode())
            return [
                m["id"]
                for m in data.get("data", [])
                if isinstance(m, dict) and "id" in m
            ]
        except Exception as exc:
            logger.debug("fetch_models(anthropic): %s", exc)
            return None


anthropic = AnthropicProfile(
    name="anthropic",
    aliases=("claude", "claude-oauth", "claude-code"),
    api_mode="anthropic_messages",
    env_vars=("ANTHROPIC_API_KEY",),
    base_url="https://api.anthropic.com",
    auth_type="api_key",
    default_aux_model="claude-haiku-4-5-20251001",
)

register_provider(anthropic)
