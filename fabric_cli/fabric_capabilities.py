"""Fabric default capability catalog.

Setup surfaces start from a curated default set while the full adapter and
provider catalog remains available. User overrides live under
``capabilities`` in config.yaml: ``enabled: false`` exposes every catalog,
and each ``*_providers`` / ``gateway_platforms`` list can replace its curated
default. A null list exposes that catalog in full.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TypeVar

T = TypeVar("T")

FABRIC_GATEWAY_PLATFORMS = ("discord", "slack", "api_server")
# Curated multi-model default (canonical-catalog order): subscription/OAuth
# providers used by the setup wizard (openai-codex, xai-oauth), the major direct
# APIs, one aggregator (openrouter), and local/self-hosted options that fit
# edge devices (ollama, lmstudio, plus distinct ollama-cloud). Nous Portal
# remains opt-in, and everything else stays available through config.yaml.
FABRIC_MODEL_PROVIDERS = (
    "openrouter",
    "ollama",
    "lmstudio",
    "anthropic",
    "openai-codex",
    "openai-api",
    "xai-oauth",
    "gemini",
    "deepseek",
    "xai",
    "ollama-cloud",
)
FABRIC_MEMORY_PROVIDERS = ("honcho", "holographic", "hindsight")
FABRIC_TTS_PROVIDERS = ("openai", "piper", "command")
FABRIC_STT_PROVIDERS = ("local", "openai", "command")

# Each default tuple doubles as the lookup key for its config field, so call
# sites keep passing the constant and never learn about config structure.
_CATALOG_CONFIG_KEYS: dict[tuple[str, ...], str] = {
    FABRIC_GATEWAY_PLATFORMS: "gateway_platforms",
    FABRIC_MODEL_PROVIDERS: "model_providers",
    FABRIC_MEMORY_PROVIDERS: "memory_providers",
    FABRIC_TTS_PROVIDERS: "tts_providers",
    FABRIC_STT_PROVIDERS: "stt_providers",
}


def _load_capabilities_config() -> dict:
    """Load the canonical catalog config without creating an import cycle."""
    try:
        from fabric_cli.config import load_config

        section = load_config().get("capabilities") or {}
        return section if isinstance(section, dict) else {}
    except Exception:
        return {}


def fabric_catalog_enabled() -> bool:
    return _load_capabilities_config().get("enabled", True) is not False


def _normalize_key(value: object) -> str:
    return str(value or "").strip().lower()


def fabric_allowed_keys(allowed: Iterable[str]) -> list[str] | None:
    """Resolve the effective allow-list for a catalog.

    Returns ``None`` when filtering should be skipped entirely (the catalog is
    globally disabled or the catalog's config value is null). Otherwise
    returns the configured list or ``allowed`` as-is.
    """
    section = _load_capabilities_config()
    if section.get("enabled", True) is False:
        return None
    defaults = tuple(allowed)
    config_key = _CATALOG_CONFIG_KEYS.get(defaults)
    if config_key:
        if config_key in section:
            configured = section[config_key]
            if configured is None:
                return None
            if isinstance(configured, (list, tuple)):
                return [
                    str(item).strip()
                    for item in configured
                    if str(item).strip()
                ]
    return list(defaults)


def filter_fabric_keys(
    values: Iterable[T],
    allowed: Iterable[str],
    *,
    key: Callable[[T], object] = lambda item: item,
) -> list[T]:
    items = list(values)
    effective = fabric_allowed_keys(allowed)
    if effective is None:
        return items
    allowed_set = {_normalize_key(item) for item in effective}
    return [item for item in items if _normalize_key(key(item)) in allowed_set]


def filter_fabric_model_rows(rows: Iterable[dict]) -> list[dict]:
    """Apply the curated model-provider catalog without erasing user state.

    The allow-list controls which *unconfigured* canonical providers are
    advertised. A current or user-defined row is already part of the user's
    desired state and must remain visible even when its slug is generic (for
    example local Ollama appears as ``custom`` or ``custom:<name>``).
    """
    items = list(rows)
    effective = fabric_allowed_keys(FABRIC_MODEL_PROVIDERS)
    if effective is None:
        return items
    allowed_set = {_normalize_key(item) for item in effective}
    return [
        row
        for row in items
        if _normalize_key(row.get("slug", "")) in allowed_set
        or bool(row.get("is_current"))
        or bool(row.get("is_user_defined"))
    ]


def fabric_model_provider_visible(slug: str) -> bool:
    """Return whether a model-provider integration belongs on Fabric setup UI.

    This gate is also used for provider-owned auxiliary tool rows, so hiding a
    opt-in model provider does not leave its subscription upsells elsewhere in
    the setup wizard. The full catalog remains available through the
    existing config controls documented above.
    """
    effective = fabric_allowed_keys(FABRIC_MODEL_PROVIDERS)
    if effective is None:
        return True
    wanted = _normalize_key(slug)
    return wanted in {_normalize_key(item) for item in effective}
