"""Fabric default capability catalog.

Setup surfaces start from a curated default set while the full adapter and
provider catalog remains available. Three levels of control are resolved at
call time so a container restart is enough to apply them:

- ``FABRIC_CAPABILITY_CATALOG=0`` exposes the full catalogs on every surface.
- Each catalog accepts a CSV override in the environment variable of the
  same name, e.g. ``FABRIC_MODEL_PROVIDERS="anthropic,openrouter,bedrock"``.
  Keys are matched case-insensitively against catalog slugs. The special
  value ``all`` (or ``*``) lifts filtering for that catalog only.
- Unset or empty override -> the curated default tuple below.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from typing import TypeVar

from utils import is_truthy_value

T = TypeVar("T")

FABRIC_GATEWAY_PLATFORMS = ("discord", "slack", "api_server")
# Curated multi-model default (canonical-catalog order): subscription/OAuth
# providers used by the setup wizard (openai-codex, xai-oauth), the major direct
# APIs, one aggregator (openrouter), and local/self-hosted options that fit
# edge devices (ollama, lmstudio, plus distinct ollama-cloud). The legacy Nous
# Portal remains opt-in, and everything else stays available via the CSV
# override or FABRIC_CAPABILITY_CATALOG=0.
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

# Each default tuple doubles as the lookup key for its override env var, so
# call sites keep passing the constant and never learn about the env layer.
# Two catalogs sharing an identical default tuple would silently shadow each
# other in this map; in that configuration mistake, disable env overrides and
# keep the curated defaults rather than crash existing call sites at
# import time. tests/fabric_cli/test_fabric_capabilities.py asserts the map
# is complete so the mistake cannot land silently.
_CATALOG_ENV_VARS: dict[tuple[str, ...], str] = {
    FABRIC_GATEWAY_PLATFORMS: "FABRIC_GATEWAY_PLATFORMS",
    FABRIC_MODEL_PROVIDERS: "FABRIC_MODEL_PROVIDERS",
    FABRIC_MEMORY_PROVIDERS: "FABRIC_MEMORY_PROVIDERS",
    FABRIC_TTS_PROVIDERS: "FABRIC_TTS_PROVIDERS",
    FABRIC_STT_PROVIDERS: "FABRIC_STT_PROVIDERS",
}
_ENV_OVERRIDES_ENABLED = len(_CATALOG_ENV_VARS) == 5

_ALL_SENTINELS = {"all", "*"}


def fabric_catalog_enabled() -> bool:
    # Present-but-empty must mean "default" (compose passthrough sets empty
    # strings for unset host vars), so strip before the truthy check.
    raw = (os.environ.get("FABRIC_CAPABILITY_CATALOG") or "").strip()
    if not raw:
        return True
    return is_truthy_value(raw, default=True)


def _normalize_key(value: object) -> str:
    return str(value or "").strip().lower()


def _split_csv(raw: str) -> list[str]:
    return [token.strip() for token in raw.split(",") if token.strip()]


def fabric_allowed_keys(allowed: Iterable[str]) -> list[str] | None:
    """Resolve the effective allow-list for a catalog.

    Returns ``None`` when filtering should be skipped entirely (the catalog is
    globally disabled, or the catalog's env override is ``all``/``*``).
    Otherwise returns the override CSV entries when set, or ``allowed`` as-is.
    """
    if not fabric_catalog_enabled():
        return None
    defaults = tuple(allowed)
    env_var = _CATALOG_ENV_VARS.get(defaults) if _ENV_OVERRIDES_ENABLED else None
    if env_var:
        raw = (os.environ.get(env_var) or "").strip()
        if raw:
            if raw.lower() in _ALL_SENTINELS:
                return None
            return _split_csv(raw)
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
    legacy model provider does not leave its subscription upsells elsewhere in
    the setup wizard. The full catalog remains available through the
    existing catalog opt-outs documented above.
    """
    effective = fabric_allowed_keys(FABRIC_MODEL_PROVIDERS)
    if effective is None:
        return True
    wanted = _normalize_key(slug)
    return wanted in {_normalize_key(item) for item in effective}
