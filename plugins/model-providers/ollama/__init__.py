"""First-class local Ollama provider profile."""

from __future__ import annotations

from typing import Any

from providers import register_provider
from providers.base import ProviderProfile


class OllamaLocalProfile(ProviderProfile):
    """Request controls for the native Ollama edge adapter."""

    def build_api_kwargs_extras(
        self,
        *,
        reasoning_config: dict | None = None,
        ollama_num_ctx: int | None = None,
        **_context: Any,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        extra_body: dict[str, Any] = {}
        top_level: dict[str, Any] = {}
        if ollama_num_ctx:
            extra_body["options"] = {"num_ctx": ollama_num_ctx}
        if isinstance(reasoning_config, dict):
            effort = str(reasoning_config.get("effort") or "").strip().lower()
            if reasoning_config.get("enabled") is False or effort == "none":
                extra_body["think"] = False
            elif effort:
                top_level["reasoning_effort"] = effort
        return extra_body, top_level


ollama = OllamaLocalProfile(
    name="ollama",
    aliases=("ollama-local",),
    display_name="Ollama (Local)",
    description="Local models through Ollama's native /api/chat protocol",
    base_url="http://127.0.0.1:11434",
    models_url="http://127.0.0.1:11434/api/tags",
    env_vars=(),
    auth_type="local",
    # Avoid Ollama's small default num_predict truncating agent responses.
    default_max_tokens=65536,
    supports_vision=True,
)

register_provider(ollama)
