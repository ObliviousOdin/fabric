"""Shared model-switching logic for CLI and gateway /model commands.

Both the CLI (cli.py) and gateway (gateway/run.py) /model handlers
share the same core pipeline:

  parse flags -> alias resolution -> provider resolution ->
  credential resolution -> normalize model name ->
  metadata lookup -> build result

This module ties together the foundation layers:

- ``agent.models_dev``            -- models.dev catalog, ModelInfo, ProviderInfo
- ``fabric_cli.providers``        -- canonical provider identity + overlays
- ``fabric_cli.model_normalize``  -- per-provider name formatting

Provider switching uses the ``--provider`` flag exclusively.
No colon-based ``provider:model`` syntax — colons are reserved for
OpenRouter variant suffixes (``:free``, ``:extended``, ``:fast``).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, List, NamedTuple, Optional

from agent.egress_policy import (
    AuthorizedInferenceRoute,
    EgressMode,
    EgressPolicy,
    EgressPolicyConfigurationError,
    EgressPolicyError,
    EgressPolicyViolation,
    InferencePurpose,
    authorize_inference_route,
    policy_from_config,
    require_policy_available,
)

from fabric_cli.providers import (
    ProviderDef,
    custom_provider_slug,
    determine_api_mode,
    get_label,
    is_aggregator,
    resolve_provider_full,
)
from fabric_cli.model_normalize import (
    normalize_model_for_provider,
)
from agent.models_dev import (
    ModelCapabilities,
    ModelInfo,
    get_model_capabilities,
    get_model_info,
    list_provider_models,
)

# Providers whose picker model list should NOT be capped by max_models.
# OpenCode Zen / Go are aggregators whose full catalogs (70+ models each) must
# be visible so users can pick any model they have access to.
_UNCAPPED_PICKER_PROVIDERS: frozenset[str] = frozenset({"opencode-zen", "opencode-go"})

logger = logging.getLogger(__name__)


def _load_model_switch_policy() -> tuple[EgressPolicy, dict[str, Any]]:
    """Return one uncached snapshot of the active profile's route policy.

    The egress-policy config loader deliberately leaves ``${SECRET}``
    references unexpanded.  Model switching calls this once per attempt and
    never stores the result at module scope, so multiplexed gateway profiles
    cannot inherit a prior profile's policy.
    """

    from fabric_cli.config import load_egress_policy_config

    config = load_egress_policy_config()
    policy = policy_from_config(config)
    require_policy_available(policy, surface=InferencePurpose.PRIMARY.value)
    return policy, config


def _policy_failure_result(
    error: EgressPolicyError | EgressPolicyConfigurationError,
    *,
    is_global: bool,
    target_provider: str = "",
    provider_label: str = "",
) -> "ModelSwitchResult":
    """Build a stable, secret-free switch failure for a policy rejection."""

    if isinstance(error, EgressPolicyError):
        # The exception has already normalized the identity.  Do not copy a
        # raw config label or requested provider into a failure payload.
        target_provider = error.provider
        provider_label = error.provider
    else:
        target_provider = ""
        provider_label = ""
    return ModelSwitchResult(
        success=False,
        target_provider=target_provider,
        provider_label=provider_label,
        is_global=is_global,
        error_message=str(error),
    )


def _nested_policy_failure(
    error: BaseException,
) -> Optional[EgressPolicyError | EgressPolicyConfigurationError]:
    """Find a policy failure wrapped by a provider/resolver exception."""

    current: Optional[BaseException] = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (EgressPolicyError, EgressPolicyConfigurationError)):
            return current
        current = current.__cause__ or current.__context__
    return None


def _authorize_model_switch_route(
    policy: EgressPolicy,
    *,
    provider: str,
    base_url: Any,
) -> Optional[AuthorizedInferenceRoute]:
    """Authorize one candidate route for the model-switch primary client."""

    return authorize_inference_route(
        policy,
        purpose=InferencePurpose.PRIMARY,
        provider=provider,
        base_url=base_url,
    )


def _reauthorize_restricted_route(
    policy: EgressPolicy,
    *,
    provider: str,
    base_url: Any,
    expected_base_url: str,
) -> str:
    """Reject resolver/alias substitutions and return the canonical route."""

    authorized = _authorize_model_switch_route(
        policy,
        provider=provider,
        base_url=base_url,
    )
    if not isinstance(authorized, AuthorizedInferenceRoute):  # pragma: no cover
        raise RuntimeError("local_ai route authorization did not return a route")
    if authorized.base_url != expected_base_url:
        raise EgressPolicyViolation(
            "remote_ai_forbidden",
            mode=policy.mode,
            purpose=InferencePurpose.PRIMARY.value,
            provider=provider,
            origin_digest=authorized.origin_digest,
        )
    return authorized.base_url


def _declared_model_ids(value: Any) -> list[str]:
    """Return configured model IDs from supported config shapes.

    Accepts:
    - ``{"model-id": {...}}``
    - ``["model-a", "model-b"]``
    - ``[{"id": "model-a"}, {"name": "model-b"}]``
    - ``"model-a"``
    """
    ids: list[str] = []
    seen: set[str] = set()

    def _add(candidate: Any) -> None:
        if not isinstance(candidate, str):
            return
        model_id = candidate.strip()
        if not model_id:
            return
        lowered = model_id.lower()
        if lowered in seen:
            return
        seen.add(lowered)
        ids.append(model_id)

    if isinstance(value, str):
        _add(value)
        return ids

    if isinstance(value, dict):
        for model_id in value:
            _add(model_id)
        return ids

    if isinstance(value, (list, tuple)):
        for item in value:
            if isinstance(item, str):
                _add(item)
                continue
            if isinstance(item, dict):
                model_id = item.get("id")
                if not isinstance(model_id, str) or not model_id.strip():
                    model_id = item.get("name")
                _add(model_id)
        return ids

    return ids


def _bare_custom_provider_def(current_base_url: str) -> Optional[ProviderDef]:
    """ProviderDef for a direct ``model.provider: custom`` endpoint."""
    base_url = str(current_base_url or "").strip()
    if not base_url:
        return None
    return ProviderDef(
        id="custom",
        name="Custom endpoint",
        transport="openai_chat",
        api_key_env_vars=(),
        base_url=base_url,
        is_aggregator=False,
        auth_type="api_key",
        source="model-config",
    )


# ---------------------------------------------------------------------------
# Non-agentic model warning
# ---------------------------------------------------------------------------

_FABRIC_MODEL_WARNING = (
    "Nous Research Hermes 3 & 4 models are NOT agentic and are not designed "
    "for use with Fabric. They lack the tool-calling capabilities "
    "required for agent workflows. Consider using an agentic model instead "
    "(Claude, GPT, Gemini, DeepSeek, etc.)."
)

# Match only the real Nous Research Hermes 3 / Hermes 4 chat families.
# The previous substring check (`"hermes" in name.lower()`) false-positived on
# unrelated local Modelfiles like ``fabric-brain:qwen3-14b-ctx16k`` that just
# happen to carry "hermes" in their tag but are fully tool-capable.
#
# Positive examples the regex must match:
#   NousResearch/Hermes-3-Llama-3.1-70B, hermes-4-405b, openrouter/hermes3:70b
# Negative examples it must NOT match:
#   fabric-brain:qwen3-14b-ctx16k, qwen3:14b, claude-opus-4-6
_NOUS_FABRIC_NON_AGENTIC_RE = re.compile(
    r"(?:^|[/:])fabric[-_ ]?[34](?:[-_.:]|$)",
    re.IGNORECASE,
)


def is_nous_fabric_non_agentic(model_name: str) -> bool:
    """Return True if *model_name* is a real Nous Hermes 3/4 chat model.

    Used to decide whether to surface the non-agentic warning at startup.
    Callers in :mod:`cli.py` and here should go through this single helper
    so the two sites don't drift.
    """
    if not model_name:
        return False
    return bool(_NOUS_FABRIC_NON_AGENTIC_RE.search(model_name))


def _check_fabric_model_warning(model_name: str) -> str:
    """Return a warning string if *model_name* is a Nous Hermes 3/4 chat model."""
    if is_nous_fabric_non_agentic(model_name):
        return _FABRIC_MODEL_WARNING
    return ""


# ---------------------------------------------------------------------------
# Model aliases -- short names -> (vendor, family) with NO version numbers.
# Resolved dynamically against the live models.dev catalog.
# ---------------------------------------------------------------------------

class ModelIdentity(NamedTuple):
    """Vendor slug and family prefix used for catalog resolution."""
    vendor: str
    family: str


MODEL_ALIASES: dict[str, ModelIdentity] = {
    # Anthropic
    "sonnet":    ModelIdentity("anthropic", "claude-sonnet"),
    "opus":      ModelIdentity("anthropic", "claude-opus"),
    "haiku":     ModelIdentity("anthropic", "claude-haiku"),
    "claude":    ModelIdentity("anthropic", "claude"),

    # OpenAI
    "gpt5":      ModelIdentity("openai", "gpt-5"),
    "gpt":       ModelIdentity("openai", "gpt"),
    "codex":     ModelIdentity("openai", "codex"),
    "o3":        ModelIdentity("openai", "o3"),
    "o4":        ModelIdentity("openai", "o4"),

    # Google
    "gemini":    ModelIdentity("google", "gemini"),

    # DeepSeek
    "deepseek":  ModelIdentity("deepseek", "deepseek-chat"),

    # X.AI
    "grok":      ModelIdentity("x-ai", "grok"),

    # Meta
    "llama":     ModelIdentity("meta-llama", "llama"),

    # Qwen / Alibaba
    "qwen":      ModelIdentity("qwen", "qwen"),

    # MiniMax
    "minimax":   ModelIdentity("minimax", "minimax"),

    # Nvidia
    "nemotron":  ModelIdentity("nvidia", "nemotron"),

    # Moonshot / Kimi
    "kimi":      ModelIdentity("moonshotai", "kimi"),

    # Z.AI / GLM
    "glm":       ModelIdentity("z-ai", "glm"),

    # Step Plan (StepFun)
    "step":      ModelIdentity("stepfun", "step"),

    # Xiaomi
    "mimo":      ModelIdentity("xiaomi", "mimo"),

    # Arcee
    "trinity":   ModelIdentity("arcee-ai", "trinity"),
}


# ---------------------------------------------------------------------------
# Direct aliases — exact model+provider+base_url for endpoints that aren't
# in the models.dev catalog (e.g. Ollama Cloud, local servers).
# Checked BEFORE catalog resolution.  Format:
#   alias -> (model_id, provider, base_url)
# These can also be loaded from config.yaml ``model_aliases:`` section.
# ---------------------------------------------------------------------------

class DirectAlias(NamedTuple):
    """Exact model mapping that bypasses catalog resolution."""
    model: str
    provider: str
    base_url: str


# Built-in direct aliases (can be extended via config.yaml model_aliases:)
_BUILTIN_DIRECT_ALIASES: dict[str, DirectAlias] = {}

# Merged dict (builtins + user config); populated by _load_direct_aliases()
DIRECT_ALIASES: dict[str, DirectAlias] = {}


def _load_direct_aliases() -> dict[str, DirectAlias]:
    """Load direct aliases from config.yaml ``model_aliases:`` section.

    Config format::

        model_aliases:
          qwen:
            model: "qwen3.5:397b"
            provider: custom
            base_url: "https://ollama.com/v1"
          minimax:
            model: "minimax-m2.7"
            provider: custom
            base_url: "https://ollama.com/v1"

    Also reads ``model.aliases`` (set by ``Fabric config set model.aliases.xxx``)
    and converts simple string entries (``ds-flash: deepseek/deepseek-v4-flash``)
    into DirectAlias objects.  The provider is parsed from the ``provider/``
    prefix in the value; if no slash, the current provider is used.
    """
    merged = dict(_BUILTIN_DIRECT_ALIASES)
    try:
        from fabric_cli.config import load_config
        cfg = load_config()

        # --- model_aliases (dict-based format) ---
        user_aliases = cfg.get("model_aliases")
        if isinstance(user_aliases, dict):
            for name, entry in user_aliases.items():
                if not isinstance(entry, dict):
                    continue
                model = entry.get("model", "")
                provider = entry.get("provider", "custom")
                base_url = entry.get("base_url", "")
                if model:
                    merged[name.strip().lower()] = DirectAlias(
                        model=model, provider=provider, base_url=base_url,
                    )

        # --- model.aliases (string-based format, from config set) ---
        model_section = cfg.get("model", {})
        if isinstance(model_section, dict):
            simple_aliases = model_section.get("aliases")
            if isinstance(simple_aliases, dict):
                current_provider = model_section.get("provider", "")
                for name, value in simple_aliases.items():
                    if not isinstance(value, str) or not value.strip():
                        continue
                    key = name.strip().lower()
                    if key in merged:
                        continue  # don't override explicit model_aliases entries
                    val = value.strip()
                    if "/" in val:
                        provider, model = val.split("/", 1)
                    else:
                        provider = current_provider
                        model = val
                    merged[key] = DirectAlias(
                        model=model.strip(),
                        provider=provider.strip() or current_provider,
                        base_url="",
                    )
    except Exception:
        pass
    return merged


def _ensure_direct_aliases() -> None:
    """Lazy-load direct aliases on first use.

    Mutates the existing DIRECT_ALIASES dict in place rather than rebinding
    the module attribute. This keeps `from fabric_cli.model_switch import
    DIRECT_ALIASES` references valid in callers — rebinding would leave them
    pointing at a stale empty dict.
    """
    if not DIRECT_ALIASES:
        DIRECT_ALIASES.update(_load_direct_aliases())


def _load_unexpanded_direct_aliases(
    current_provider: str,
) -> dict[str, DirectAlias]:
    """Load this profile's aliases without expanding credential references.

    ``DIRECT_ALIASES`` is a legacy process-global cache.  Reusing it in a
    multiplexed ``local_ai`` host would let one profile's endpoint selection
    bleed into another profile and its loader calls ``load_config()``, which
    expands every environment reference.  The restricted lane therefore
    builds a fresh, raw snapshot for each switch attempt.
    """

    merged = dict(_BUILTIN_DIRECT_ALIASES)
    try:
        from fabric_cli.config import read_raw_config

        raw = read_raw_config()
    except Exception:
        raw = {}

    configs: list[dict[str, Any]] = [raw] if isinstance(raw, dict) else []
    try:
        from fabric_cli import managed_scope

        managed = managed_scope.load_managed_config()
        if isinstance(managed, dict):
            configs.append(managed)
    except Exception:
        pass

    effective_provider = str(current_provider or "").strip()
    for config in configs:
        root_aliases = config.get("model_aliases")
        if isinstance(root_aliases, dict):
            for name, entry in root_aliases.items():
                if not isinstance(name, str) or not isinstance(entry, dict):
                    continue
                model = entry.get("model")
                if not isinstance(model, str) or not model.strip():
                    continue
                provider = entry.get("provider", "custom")
                base_url = entry.get("base_url", "")
                merged[name.strip().lower()] = DirectAlias(
                    model=model.strip(),
                    provider=str(provider or "custom").strip() or "custom",
                    base_url=str(base_url or "").strip(),
                )

        model_section = config.get("model")
        if not isinstance(model_section, dict):
            continue
        configured_provider = model_section.get("provider")
        if isinstance(configured_provider, str) and configured_provider.strip():
            effective_provider = configured_provider.strip()
        simple_aliases = model_section.get("aliases")
        if not isinstance(simple_aliases, dict):
            continue
        for name, value in simple_aliases.items():
            if not isinstance(name, str) or not isinstance(value, str) or not value.strip():
                continue
            key = name.strip().lower()
            if key in merged:
                continue
            raw_value = value.strip()
            if "/" in raw_value:
                provider, model = raw_value.split("/", 1)
            else:
                provider, model = effective_provider, raw_value
            merged[key] = DirectAlias(
                model=model.strip(),
                provider=provider.strip() or effective_provider,
                base_url="",
            )
    return merged


def _resolve_restricted_alias(
    raw_input: str,
    aliases: dict[str, DirectAlias],
) -> Optional[tuple[str, str, str]]:
    """Resolve only explicit direct aliases without catalog/network access."""

    key = raw_input.strip().lower()
    direct = aliases.get(key)
    if direct is not None:
        return direct.provider, direct.model, key
    for alias_name, direct_alias in aliases.items():
        if direct_alias.model.lower() == key:
            return direct_alias.provider, direct_alias.model, alias_name
    return None


def _resolve_restricted_provider(
    name: str,
    user_providers: Optional[dict],
    custom_providers: Optional[list],
    *,
    current_provider: str = "",
    current_base_url: str = "",
) -> Optional[ProviderDef]:
    """Resolve a provider from static/config data only.

    The ordinary resolver consults models.dev before returning even known
    providers.  That is correct online, but is an unauthorized metadata HTTP
    path when a restricted switch has not yet approved its target route.
    """

    from fabric_cli.providers import (
        FABRIC_OVERLAYS,
        normalize_provider,
        resolve_custom_provider,
        resolve_user_provider,
    )

    raw = str(name or "").strip().lower()
    if not raw:
        return None
    if isinstance(user_providers, dict):
        user_provider = resolve_user_provider(raw, user_providers)
        if user_provider is not None:
            return user_provider

    canonical = normalize_provider(raw)
    if isinstance(user_providers, dict):
        user_provider = resolve_user_provider(canonical, user_providers)
        if user_provider is not None:
            return user_provider

    custom_provider = resolve_custom_provider(raw, custom_providers)
    if custom_provider is not None:
        return custom_provider

    overlay = FABRIC_OVERLAYS.get(canonical)
    if overlay is not None:
        return ProviderDef(
            id=canonical,
            name=canonical,
            transport=overlay.transport,
            api_key_env_vars=overlay.extra_env_vars,
            base_url=overlay.base_url_override,
            base_url_env_var=overlay.base_url_env_var,
            is_aggregator=overlay.is_aggregator,
            auth_type=overlay.auth_type,
            source="hermes",
        )

    if canonical == str(current_provider or "").strip().lower() and current_base_url:
        return ProviderDef(
            id=canonical,
            name=canonical,
            transport="openai_chat",
            api_key_env_vars=(),
            base_url=current_base_url,
            source="live-runtime",
        )
    return None


def _restricted_route_hint(
    *,
    target_provider: str,
    current_provider: str,
    current_base_url: str,
    policy_config: dict[str, Any],
    user_providers: Optional[dict],
    custom_providers: Optional[list],
    provider_def: Optional[ProviderDef],
    direct_alias: Optional[DirectAlias],
) -> str:
    """Find a route candidate using only already-loaded, non-secret data."""

    if direct_alias is not None and direct_alias.base_url:
        return direct_alias.base_url
    if provider_def is not None and provider_def.id == target_provider and provider_def.base_url:
        return provider_def.base_url
    if target_provider == current_provider and current_base_url:
        return current_base_url

    configured = _resolve_restricted_provider(
        target_provider,
        user_providers,
        custom_providers,
        current_provider=current_provider,
        current_base_url=current_base_url,
    )
    if configured is not None and configured.base_url:
        return configured.base_url

    model_config = policy_config.get("model")
    if isinstance(model_config, dict):
        configured_provider = str(model_config.get("provider") or "").strip()
        configured_url = str(model_config.get("base_url") or "").strip()
        if configured_url and configured_provider in {"", target_provider}:
            return configured_url
    return ""


def _restricted_api_mode(
    provider: str,
    base_url: str,
    provider_def: Optional[ProviderDef],
) -> str:
    """Resolve wire mode from static/config data without provider metadata."""

    from fabric_cli.providers import TRANSPORT_TO_API_MODE

    if provider_def is not None:
        configured = TRANSPORT_TO_API_MODE.get(provider_def.transport)
        if configured:
            return configured
    lowered = str(base_url or "").rstrip("/").lower()
    if lowered.endswith("/anthropic") or "/coding" in lowered:
        return "anthropic_messages"
    return "chat_completions"


def _restricted_validation(
    model: str,
    *,
    api_key: str,
    base_url: str,
    api_mode: str,
) -> dict[str, Any]:
    """Validate a local-policy model through a proxy-disabled local probe.

    The legacy validators use ``urllib``/``requests`` with environment proxy
    inheritance.  Even a literal loopback URL could therefore be sent to a
    configured remote proxy.  This small OpenAI-compatible probe deliberately
    installs an empty proxy handler, refuses redirects, and caps the body.
    """

    requested = str(model or "").strip()
    if not requested:
        return {
            "accepted": False,
            "persist": False,
            "recognized": False,
            "message": "Model name cannot be empty.",
        }
    if any(character.isspace() for character in requested):
        return {
            "accepted": False,
            "persist": False,
            "recognized": False,
            "message": "Model names cannot contain spaces.",
        }

    import json
    import urllib.request

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    normalized = base_url.rstrip("/")
    candidates = [normalized]
    alternate = normalized[:-3].rstrip("/") if normalized.endswith("/v1") else normalized + "/v1"
    if alternate and alternate not in candidates:
        candidates.append(alternate)

    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "identity",
        "User-Agent": "Fabric/model-switch",
    }
    if api_key:
        if api_mode == "anthropic_messages":
            headers["x-api-key"] = api_key
            headers["anthropic-version"] = "2023-06-01"
        else:
            headers["Authorization"] = f"Bearer {api_key}"

    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _NoRedirect(),
    )
    model_ids: Optional[list[str]] = None
    for candidate in candidates:
        request = urllib.request.Request(candidate + "/models", headers=headers)
        try:
            with opener.open(request, timeout=5.0) as response:
                if str(response.headers.get("Content-Encoding") or "identity").lower() not in {
                    "",
                    "identity",
                }:
                    continue
                body = response.read(1024 * 1024 + 1)
                if len(body) > 1024 * 1024:
                    continue
                payload = json.loads(body.decode("utf-8"))
                items = payload.get("data") if isinstance(payload, dict) else None
                if not isinstance(items, list):
                    continue
                model_ids = [
                    str(item.get("id") or "").strip()
                    for item in items
                    if isinstance(item, dict) and str(item.get("id") or "").strip()
                ]
                break
        except Exception:
            continue

    if model_ids is None:
        return {
            "accepted": api_mode == "anthropic_messages",
            "persist": True,
            "recognized": False,
            "message": "The authorized local endpoint did not expose a usable model listing.",
        }
    if requested in model_ids:
        return {
            "accepted": True,
            "persist": True,
            "recognized": True,
            "message": None,
        }
    return {
        "accepted": False,
        "persist": False,
        "recognized": False,
        "message": "The model was not found in the authorized local endpoint's listing.",
    }


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ModelSwitchResult:
    """Result of a model switch attempt."""

    success: bool
    new_model: str = ""
    target_provider: str = ""
    provider_changed: bool = False
    api_key: str = ""
    base_url: str = ""
    api_mode: str = ""
    error_message: str = ""
    warning_message: str = ""
    provider_label: str = ""
    resolved_via_alias: str = ""
    capabilities: Optional[ModelCapabilities] = None
    model_info: Optional[ModelInfo] = None
    is_global: bool = False
# ---------------------------------------------------------------------------
# Flag parsing
# ---------------------------------------------------------------------------

def parse_model_flags(raw_args: str) -> tuple[str, str, bool, bool, bool]:
    """Parse --provider, --global, --session, and --refresh flags from /model command args.

    Returns ``(model_input, explicit_provider, is_global, force_refresh, is_session)``.

    ``is_global`` and ``is_session`` are independent flag presences; the
    *effective* persistence decision is resolved by
    :func:`resolve_persist_behavior` so the config-gated default
    (``model.persist_switch_by_default``) is applied in one place.

    Examples::

        "sonnet"                         -> ("sonnet", "", False, False, False)
        "sonnet --global"                -> ("sonnet", "", True, False, False)
        "sonnet --session"               -> ("sonnet", "", False, False, True)
        "sonnet --provider anthropic"    -> ("sonnet", "anthropic", False, False, False)
        "--provider my-ollama"           -> ("", "my-ollama", False, False, False)
        "--refresh"                      -> ("", "", False, True, False)
        "sonnet --provider anthropic --global" -> ("sonnet", "anthropic", True, False, False)
    """
    is_global = False
    explicit_provider = ""
    force_refresh = False
    is_session = False

    # Normalize Unicode dashes (Telegram/iOS auto-converts -- to em/en dash)
    # A single Unicode dash before a flag keyword becomes "--"
    import re as _re
    raw_args = _re.sub(r'[\u2012\u2013\u2014\u2015](provider|global|session|refresh)', r'--\1', raw_args)

    # Extract --global
    if "--global" in raw_args:
        is_global = True
        raw_args = raw_args.replace("--global", "").strip()

    # Extract --session (explicit session-only; overrides the persist default)
    if "--session" in raw_args:
        is_session = True
        raw_args = raw_args.replace("--session", "").strip()

    # Extract --refresh (bust the model picker disk cache before listing)
    if "--refresh" in raw_args:
        force_refresh = True
        raw_args = raw_args.replace("--refresh", "").strip()

    # Extract --provider <name>
    parts = raw_args.split()
    i = 0
    filtered: list[str] = []
    while i < len(parts):
        if parts[i] == "--provider" and i + 1 < len(parts):
            explicit_provider = parts[i + 1]
            i += 2
        else:
            filtered.append(parts[i])
            i += 1

    model_input = " ".join(filtered).strip()
    return (model_input, explicit_provider, is_global, force_refresh, is_session)


def resolve_persist_behavior(
    is_global: bool,
    is_session: bool,
    *,
    model_config: Optional[dict] = None,
) -> bool:
    """Decide whether a ``/model`` switch should persist to ``config.yaml``.

    Resolution order:

    1. ``--session`` explicitly opts out → ``False`` (this session only).
    2. ``--global`` explicitly opts in → ``True``.
    3. Otherwise defer to ``model.persist_switch_by_default`` in
       ``config.yaml`` (defaults to ``True``, so a plain ``/model <name>``
       survives across sessions — the behavior users expect).

    The config read is defensive: on a fresh install ``model`` may be a
    flat string rather than a dict, in which case the built-in default
    (``True``) applies.
    """
    if is_session:
        return False
    if is_global:
        return True
    try:
        if model_config is None:
            # The shared picker context chooses strict raw config before any
            # secret expansion in restricted modes and preserves the legacy
            # expanded loader online. Persistence preference is part of that
            # same model-config read and must not bypass its policy boundary.
            from fabric_cli.inventory import load_picker_context

            model_cfg = load_picker_context().model_config
        else:
            model_cfg = model_config
        if isinstance(model_cfg, dict):
            return bool(model_cfg.get("persist_switch_by_default", True))
    except Exception:
        pass
    return True


# ---------------------------------------------------------------------------
# Alias resolution
# ---------------------------------------------------------------------------

def _model_sort_key(model_id: str, prefix: str) -> tuple:
    """Sort key for model version preference.

    Extracts version numbers after the family prefix and returns a sort key
    that prefers higher versions.  Suffix tokens (``pro``, ``omni``, etc.)
    are used as tiebreakers, with common quality indicators ranked.

    Examples (with prefix ``"mimo"``)::

        mimo-v2.5-pro   → (-2.5, 0, 'pro')     # highest version wins
        mimo-v2.5       → (-2.5, 1, '')          # no suffix = lower than pro
        mimo-v2-pro     → (-2.0, 0, 'pro')
        mimo-v2-omni    → (-2.0, 1, 'omni')
        mimo-v2-flash   → (-2.0, 1, 'flash')
    """
    # Strip the prefix (and optional "/" separator for aggregator slugs)
    rest = model_id[len(prefix):]
    if rest.startswith("/"):
        rest = rest[1:]
    rest = rest.lstrip("-").strip()

    # Parse version and suffix from the remainder.
    # "v2.5-pro" → version [2.5], suffix "pro"
    # "-omni"    → version [],    suffix "omni"
    # State machine: start → in_version → between → in_suffix
    nums: list[float] = []
    suffix_buf = ""
    state = "start"
    num_buf = ""

    for ch in rest:
        if state == "start":
            if ch in "vV":
                state = "in_version"
            elif ch.isdigit():
                state = "in_version"
                num_buf += ch
            elif ch in "-_.":
                pass  # skip separators before any content
            else:
                state = "in_suffix"
                suffix_buf += ch
        elif state == "in_version":
            if ch.isdigit():
                num_buf += ch
            elif ch == ".":
                if "." in num_buf:
                    # Second dot — flush current number, start new component
                    try:
                        nums.append(float(num_buf.rstrip(".")))
                    except ValueError:
                        pass
                    num_buf = ""
                else:
                    num_buf += ch
            elif ch in "-_.":
                if num_buf:
                    try:
                        nums.append(float(num_buf.rstrip(".")))
                    except ValueError:
                        pass
                    num_buf = ""
                state = "between"
            else:
                if num_buf:
                    try:
                        nums.append(float(num_buf.rstrip(".")))
                    except ValueError:
                        pass
                    num_buf = ""
                state = "in_suffix"
                suffix_buf += ch
        elif state == "between":
            if ch.isdigit():
                state = "in_version"
                num_buf = ch
            elif ch in "vV":
                state = "in_version"
            elif ch in "-_.":
                pass
            else:
                state = "in_suffix"
                suffix_buf += ch
        elif state == "in_suffix":
            suffix_buf += ch

    # Flush remaining buffer (strip trailing dots — "5.4." → "5.4")
    if num_buf and state == "in_version":
        try:
            nums.append(float(num_buf.rstrip(".")))
        except ValueError:
            pass

    suffix = suffix_buf.lower().strip("-_.")
    suffix = suffix.strip()

    # Negate versions so higher → sorts first
    version_key = tuple(-n for n in nums)

    # Suffix quality ranking: pro/max > (no suffix) > omni/flash/mini/lite
    # Lower number = preferred
    _SUFFIX_RANK = {"pro": 0, "max": 0, "plus": 0, "turbo": 0}
    suffix_rank = _SUFFIX_RANK.get(suffix, 1)

    return version_key + (suffix_rank, suffix)


def resolve_alias(
    raw_input: str,
    current_provider: str,
) -> Optional[tuple[str, str, str]]:
    """Resolve a short alias against the current provider's catalog.

    Looks up *raw_input* in :data:`MODEL_ALIASES`, then searches the
    current provider's models.dev catalog for the model whose ID starts
    with ``vendor/family`` (or just ``family`` for non-aggregator
    providers) and has the **highest version**.

    Returns:
        ``(provider, resolved_model_id, alias_name)`` if a match is
        found on the current provider, or ``None`` if the alias doesn't
        exist or no matching model is available.
    """
    key = raw_input.strip().lower()

    # Check direct aliases first (exact model+provider+base_url mappings)
    _ensure_direct_aliases()
    direct = DIRECT_ALIASES.get(key)
    if direct is not None:
        return (direct.provider, direct.model, key)

    # Reverse lookup: match by model ID so full names (e.g. "kimi-k2.5",
    # "glm-4.7") route through direct aliases instead of falling through
    # to the catalog/OpenRouter.
    for alias_name, da in DIRECT_ALIASES.items():
        if da.model.lower() == key:
            return (da.provider, da.model, alias_name)

    identity = MODEL_ALIASES.get(key)
    if identity is None:
        return None

    vendor, family = identity

    # Build catalog from models.dev, then merge in static _PROVIDER_MODELS
    # entries that models.dev may be missing (e.g. newly added models not
    # yet synced to the registry).
    catalog = list_provider_models(current_provider)
    try:
        from fabric_cli.models import _PROVIDER_MODELS
        static = _PROVIDER_MODELS.get(current_provider, [])
        if static:
            seen = {m.lower() for m in catalog}
            for m in static:
                if m.lower() not in seen:
                    catalog.append(m)
    except Exception:
        pass

    # For aggregators, models are vendor/model-name format
    aggregator = is_aggregator(current_provider)

    if aggregator:
        prefix = f"{vendor}/{family}".lower()
        matches = [
            mid for mid in catalog
            if mid.lower().startswith(prefix)
        ]
    else:
        family_lower = family.lower()
        matches = [
            mid for mid in catalog
            if mid.lower().startswith(family_lower)
        ]

    if not matches:
        return None

    # Sort by version descending — prefer the latest/highest version
    prefix_for_sort = f"{vendor}/{family}" if aggregator else family
    matches.sort(key=lambda m: _model_sort_key(m, prefix_for_sort))
    return (current_provider, matches[0], key)


def get_authenticated_provider_slugs(
    current_provider: str = "",
    user_providers: dict = None,
    custom_providers: list | None = None,
) -> list[str]:
    """Return slugs of providers that have credentials.

    Uses ``list_authenticated_providers()`` which is backed by the models.dev
    in-memory cache (1 hr TTL) — no extra network cost.
    """
    try:
        providers = list_authenticated_providers(
            current_provider=current_provider,
            user_providers=user_providers,
            custom_providers=custom_providers,
            max_models=0,
        )
        return [p["slug"] for p in providers]
    except Exception:
        return []


def _resolve_alias_fallback(
    raw_input: str,
    authenticated_providers: list[str] = (),
) -> Optional[tuple[str, str, str]]:
    """Try to resolve an alias on the user's authenticated providers.

    Falls back to ``("openrouter", "nous")`` only when no authenticated
    providers are supplied (backwards compat for non-interactive callers).
    """
    providers = authenticated_providers or ("openrouter", "nous")
    for provider in providers:
        result = resolve_alias(raw_input, provider)
        if result is not None:
            return result
    return None


def resolve_display_context_length(
    model: str,
    provider: str,
    base_url: str = "",
    api_key: str = "",
    model_info: Optional[ModelInfo] = None,
    custom_providers: list | None = None,
    config_context_length: int | None = None,
) -> Optional[int]:
    """Resolve the context length to show in /model output.

    models.dev reports per-vendor context (e.g. gpt-5.5 = 1.05M on openai)
    but provider-enforced limits can be lower (e.g. Codex OAuth caps the
    same slug at 272k). The authoritative source is
    ``agent.model_metadata.get_model_context_length`` which already knows
    about Codex OAuth, Copilot, Nous, and falls back to models.dev for the
    rest.

    When ``custom_providers`` is provided, per-model ``context_length``
    overrides from ``custom_providers[].models.<id>.context_length`` are
    honored — this closes #15779 where ``/model`` switch ignored user-set
    overrides.

    Prefer the provider-aware value; fall back to ``model_info.context_window``
    only if the resolver returns nothing.
    """
    try:
        from agent.model_metadata import get_model_context_length
        ctx = get_model_context_length(
            model,
            base_url=base_url or "",
            api_key=api_key or "",
            provider=provider or None,
            custom_providers=custom_providers,
            config_context_length=config_context_length,
        )
        if ctx:
            return int(ctx)
    except Exception:
        pass
    if model_info is not None and model_info.context_window:
        return int(model_info.context_window)
    return None


# ---------------------------------------------------------------------------
# Configured-provider detection for typed model names
# ---------------------------------------------------------------------------


def _configured_provider_matches(
    model_name: str,
    user_providers: Optional[dict],
    custom_providers: Optional[list],
) -> dict[str, str]:
    """Return ``{provider_slug: canonical_model_id}`` for every configured
    provider whose declared models contain an exact (case-insensitive) match
    for ``model_name``.

    Used by :func:`switch_model` to route a *typed* model name to the provider
    that actually declares it in user/custom provider config, instead of
    leaving it on the current provider.  Without this, a model declared under
    ``providers.<slug>`` / ``custom_providers`` but typed while the current
    provider is ``openai-codex`` stays on Codex and is soft-accepted as an
    unknown hidden Codex model (#45006).

    Matching is exact (case-insensitive); the configured spelling is returned
    so the downstream validation/override path sees the canonical id.  Only the
    explicitly-declared model collections are scanned (``models``, the singular
    ``model``, and ``default_model``) — never fuzzy/family matching.
    """
    if not model_name or not model_name.strip():
        return {}
    target = model_name.strip().lower()

    def _match(value) -> Optional[str]:
        """Canonical id if ``value`` (a model collection or scalar) declares
        ``target``, else None."""
        for model_id in _declared_model_ids(value):
            if model_id.lower() == target:
                return model_id
        return None

    matches: dict[str, str] = {}

    if isinstance(user_providers, dict):
        for slug, cfg in user_providers.items():
            if not isinstance(slug, str) or not isinstance(cfg, dict):
                continue
            for key in ("models", "model", "default_model"):
                hit = _match(cfg.get(key))
                if hit:
                    matches[slug] = hit
                    break

    if isinstance(custom_providers, list):
        for entry in custom_providers:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            slug = f"custom:{name}"
            if slug in matches:
                continue
            for key in ("models", "model", "default_model"):
                hit = _match(entry.get(key))
                if hit:
                    matches[slug] = hit
                    break

    return matches


# ---------------------------------------------------------------------------
# Core model-switching pipeline
# ---------------------------------------------------------------------------

def switch_model(
    raw_input: str,
    current_provider: str,
    current_model: str,
    current_base_url: str = "",
    current_api_key: str = "",
    is_global: bool = False,
    explicit_provider: str = "",
    user_providers: dict = None,
    custom_providers: list | None = None,
    preflight_local_runtime: bool = False,
) -> ModelSwitchResult:
    """Core model-switching pipeline shared between CLI and gateway.

    Resolution chain:

      If --provider given:
        a. Resolve provider via resolve_provider_full()
        b. Resolve credentials
        c. If model given, resolve alias on target provider or use as-is
        d. If no model, auto-detect from endpoint

      If no --provider:
        a. Try alias resolution on current provider
        b. If alias exists but not on current provider -> fallback
        c. On aggregator, try vendor/model slug conversion
        d. Aggregator catalog search
        e. detect_provider_for_model() as last resort
        f. Resolve credentials
        g. Normalize model name for target provider

      Finally:
        h. Get full model metadata from models.dev
        i. Build result

    Args:
        raw_input: The model name (after flag parsing).
        current_provider: The currently active provider.
        current_model: The currently active model name.
        current_base_url: The currently active base URL.
        current_api_key: The currently active API key.
        is_global: Whether to persist the switch.
        explicit_provider: From --provider flag (empty = no explicit provider).
        user_providers: The ``providers:`` dict from config.yaml (for user endpoints).
        custom_providers: The ``custom_providers:`` list from config.yaml.
        preflight_local_runtime: Run a bounded Ollama readiness check for an
            explicit user-facing switch. Normal picker inventory remains
            probe-free; callers opt in only after the user selects a model.

    Returns:
        ModelSwitchResult with all information the caller needs.
    """
    try:
        egress_policy, policy_config = _load_model_switch_policy()
    except (EgressPolicyError, EgressPolicyConfigurationError) as error:
        return _policy_failure_result(error, is_global=is_global)

    restricted_egress = egress_policy.mode is EgressMode.LOCAL_AI
    restricted_aliases = (
        _load_unexpanded_direct_aliases(current_provider)
        if restricted_egress
        else {}
    )

    from fabric_cli.models import (
        copilot_model_api_mode,
        detect_provider_for_model,
        detect_static_provider_for_model,
        validate_requested_model,
        opencode_model_api_mode,
    )
    from fabric_cli.runtime_provider import resolve_runtime_provider

    resolved_alias = ""
    new_model = raw_input.strip()
    target_provider = current_provider
    resolved_moa_preset = False
    selected_provider_def: Optional[ProviderDef] = None

    # =================================================================
    # PATH A: Explicit --provider given
    # =================================================================
    if explicit_provider:
        # Resolve the provider
        if restricted_egress:
            pdef = _resolve_restricted_provider(
                explicit_provider,
                user_providers,
                custom_providers,
                current_provider=current_provider,
                current_base_url=current_base_url,
            )
        else:
            pdef = resolve_provider_full(
                explicit_provider,
                user_providers,
                custom_providers,
            )
        if pdef is None and explicit_provider.strip().lower() == "custom":
            pdef = _bare_custom_provider_def(current_base_url)
        if pdef is None:
            if restricted_egress:
                _switch_err = (
                    "The requested provider has no static local_ai route. "
                    "Define a literal local endpoint under 'providers:' or "
                    "'custom_providers:'."
                )
            else:
                _switch_err = (
                    f"Unknown provider '{explicit_provider}'. "
                    f"Check 'fabric model' for available providers, or define it "
                    f"in config.yaml under 'providers:'."
                )
            # Check for common config issues that cause provider resolution failures
            if not restricted_egress:
                try:
                    from fabric_cli.config import validate_config_structure
                    _cfg_issues = validate_config_structure()
                    if _cfg_issues:
                        _switch_err += "\n\nRun 'fabric doctor' — config issues detected:"
                        for _ci in _cfg_issues[:3]:
                            _switch_err += f"\n  • {_ci.message}"
                except Exception:
                    pass
            return ModelSwitchResult(
                success=False,
                is_global=is_global,
                error_message=_switch_err,
            )

        selected_provider_def = pdef
        target_provider = pdef.id

        # The explicit provider route is already knowable here.  In the
        # restricted lane it must be authorized before the aggregator auth
        # lookup, OAuth-backed provider discovery, or endpoint auto-detection
        # below can run.
        if restricted_egress:
            route_hint = _restricted_route_hint(
                target_provider=target_provider,
                current_provider=current_provider,
                current_base_url=current_base_url,
                policy_config=policy_config,
                user_providers=user_providers,
                custom_providers=custom_providers,
                provider_def=pdef,
                direct_alias=None,
            )
            try:
                authorized = _authorize_model_switch_route(
                    egress_policy,
                    provider=target_provider,
                    base_url=route_hint,
                )
            except (EgressPolicyError, EgressPolicyConfigurationError) as error:
                return _policy_failure_result(
                    error,
                    is_global=is_global,
                    target_provider=target_provider,
                    provider_label=pdef.name,
                )
            if authorized is not None:
                pdef.base_url = authorized.base_url

        if target_provider == "moa" and not new_model:
            try:
                from fabric_cli.config import load_config
                from fabric_cli.moa_config import normalize_moa_config

                new_model = normalize_moa_config(load_config().get("moa") or {})["default_preset"]
            except Exception:
                new_model = "default"

        # Guard against silent aggregator hops. A vendor name like bare
        # "openai" is an alias that resolves to an aggregator ("openrouter").
        # If the user explicitly asked for that vendor but the aggregator it
        # routes to has no credentials, do NOT silently switch them onto an
        # unauthed endpoint (the classic HTTP 401 "Missing Authentication
        # header"). Point them at the real direct provider instead.
        from fabric_cli.models import _AGGREGATOR_PROVIDERS as _AGG_PROVIDERS
        from fabric_cli.providers import ALIASES as _PROVIDER_ALIAS_TABLE
        _explicit_norm = explicit_provider.strip().lower()
        _alias_target = _PROVIDER_ALIAS_TABLE.get(_explicit_norm)
        if (
            _alias_target
            and _alias_target == target_provider
            and target_provider != _explicit_norm
            and target_provider in _AGG_PROVIDERS
        ):
            _authed = get_authenticated_provider_slugs(
                current_provider=current_provider,
                user_providers=user_providers,
                custom_providers=custom_providers,
            )
            if target_provider not in _authed:
                _suggestions = [
                    s for s in _authed
                    if s.startswith(_explicit_norm) and s != _explicit_norm
                ]
                _hint = (
                    f" Did you mean: {', '.join(_suggestions)}?"
                    if _suggestions else ""
                )
                return ModelSwitchResult(
                    success=False,
                    target_provider=target_provider,
                    provider_label=pdef.name,
                    is_global=is_global,
                    error_message=(
                        f"Provider '{_explicit_norm}' is an alias that routes "
                        f"through {get_label(target_provider)}, which "
                        f"has no credentials configured.{_hint}"
                    ),
                )

        # If no model specified, try auto-detect from endpoint
        if not new_model:
            if pdef.base_url:
                if restricted_egress:
                    return ModelSwitchResult(
                        success=False,
                        target_provider=target_provider,
                        provider_label=pdef.name,
                        is_global=is_global,
                        error_message=(
                            "Automatic model discovery is disabled by local_ai. "
                            "Specify the model explicitly."
                        ),
                    )
                from fabric_cli.runtime_provider import _auto_detect_local_model
                detected = _auto_detect_local_model(pdef.base_url)
                if detected:
                    new_model = detected
                else:
                    return ModelSwitchResult(
                        success=False,
                        target_provider=target_provider,
                        provider_label=pdef.name,
                        is_global=is_global,
                        error_message=(
                            f"No model detected on {pdef.name} ({pdef.base_url}). "
                            f"Specify the model explicitly: /model <model-name> --provider {explicit_provider}"
                        ),
                    )
            else:
                return ModelSwitchResult(
                    success=False,
                    target_provider=target_provider,
                    provider_label=pdef.name,
                    is_global=is_global,
                    error_message=(
                        f"Provider '{pdef.name}' has no base URL configured. "
                        f"Specify a model: /model <model-name> --provider {explicit_provider}"
                    ),
                )

        # Resolve alias on the TARGET provider
        alias_result = (
            _resolve_restricted_alias(new_model, restricted_aliases)
            if restricted_egress
            else resolve_alias(new_model, target_provider)
        )
        if alias_result is not None:
            _, new_model, resolved_alias = alias_result

    # =================================================================
    # PATH B: No explicit provider — resolve from model input
    # =================================================================
    else:
        if restricted_egress:
            # MoA's full config loader expands credential references.  Slot
            # selection is handled by the separately gated MoA pipeline; this
            # primary switch lane resolves direct aliases only until a literal
            # endpoint has been authorized.
            alias_result = _resolve_restricted_alias(raw_input, restricted_aliases)
        else:
            try:
                from fabric_cli.config import load_config
                from fabric_cli.moa_config import exact_moa_preset_name, normalize_moa_config

                _moa_cfg = normalize_moa_config(load_config().get("moa") or {})
                _moa_match = exact_moa_preset_name(_moa_cfg, raw_input)
                if _moa_match:
                    target_provider = "moa"
                    new_model = _moa_match
                    resolved_alias = ""
                    resolved_moa_preset = True
                    alias_result = None
                else:
                    alias_result = resolve_alias(raw_input, current_provider)
            except Exception:
                alias_result = resolve_alias(raw_input, current_provider)

        # --- Step a: Try alias resolution on current provider ---

        if resolved_moa_preset:
            pass
        elif alias_result is not None:
            target_provider, new_model, resolved_alias = alias_result
            logger.debug(
                "Alias '%s' resolved to %s on %s",
                resolved_alias, new_model, target_provider,
            )
        else:
            # --- Step b: Alias exists but not on current provider -> fallback ---
            key = raw_input.strip().lower()
            if key in MODEL_ALIASES:
                if restricted_egress:
                    identity = MODEL_ALIASES[key]
                    return ModelSwitchResult(
                        success=False,
                        is_global=is_global,
                        error_message=(
                            f"Alias '{key}' maps to {identity.vendor}/{identity.family}, "
                            "but local_ai does not perform credential-backed provider "
                            "or remote catalog discovery. Use a direct local alias or "
                            "the full local model name."
                        ),
                    )
                authed = get_authenticated_provider_slugs(
                    current_provider=current_provider,
                    user_providers=user_providers,
                    custom_providers=custom_providers,
                )
                fallback_result = _resolve_alias_fallback(raw_input, authed)
                if fallback_result is not None:
                    target_provider, new_model, resolved_alias = fallback_result
                    logger.debug(
                        "Alias '%s' resolved via fallback to %s on %s",
                        resolved_alias, new_model, target_provider,
                    )
                else:
                    identity = MODEL_ALIASES[key]
                    return ModelSwitchResult(
                        success=False,
                        is_global=is_global,
                        error_message=(
                            f"Alias '{key}' maps to {identity.vendor}/{identity.family} "
                            f"but no matching model was found in any provider catalog. "
                            f"Try specifying the full model name."
                        ),
                    )
            elif not resolved_moa_preset:
                # --- Step c: On aggregator, convert vendor:model to vendor/model ---
                # Only convert when there's no slash — a slash means the name
                # is already in vendor/model format and the colon is a variant
                # tag (:free, :extended, :fast) that must be preserved.
                colon_pos = raw_input.find(":")
                if (
                    not restricted_egress
                    and colon_pos > 0
                    and "/" not in raw_input
                    and is_aggregator(current_provider)
                ):
                    left = raw_input[:colon_pos].strip().lower()
                    right = raw_input[colon_pos + 1:].strip()
                    if left and right:
                        # Colons become slashes for aggregator slugs
                        new_model = f"{left}/{right}"
                        logger.debug(
                            "Converted vendor:model '%s' to aggregator slug '%s'",
                            raw_input, new_model,
                        )

        # --- Step d: Aggregator catalog search ---
        # Track whether the live catalog of the CURRENT provider resolved the
        # model — if so, step e must not second-guess and switch providers.
        # Critical for flat-namespace resellers like opencode-go / opencode-zen
        # whose live /v1/models returns bare IDs (e.g. "deepseek-v4-flash") that
        # coincidentally match entries in native providers' static catalogs.
        resolved_in_current_catalog = False
        if (
            not restricted_egress
            and is_aggregator(target_provider)
            and not resolved_alias
        ):
            catalog = list_provider_models(target_provider)
            if catalog:
                new_model_lower = new_model.lower()
                for mid in catalog:
                    if mid.lower() == new_model_lower:
                        new_model = mid
                        resolved_in_current_catalog = True
                        break
                else:
                    for mid in catalog:
                        if "/" in mid:
                            _, bare = mid.split("/", 1)
                            if bare.lower() == new_model_lower:
                                new_model = mid
                                resolved_in_current_catalog = True
                                break

        # --- Step d.5: configured-provider exact-match detection (#45006) ---
        # If the typed model is declared in user/custom provider config, route
        # to that provider BEFORE detect_provider_for_model() guesses from
        # static catalogs and BEFORE the common-path validation can let a
        # soft-accepting current provider (e.g. openai-codex) swallow the name
        # as an unknown hidden model.  Configured matches beat static-catalog
        # detection.  Unlike step e this is deliberately NOT gated on
        # ``not is_custom`` — switching from a local/custom provider A to a
        # configured provider B that declares the typed model is the point.
        config_routed = False
        if (
            not resolved_alias
            and not resolved_in_current_catalog
            and target_provider == current_provider
        ):
            cfg_matches = _configured_provider_matches(
                new_model, user_providers, custom_providers
            )
            if cfg_matches:
                if current_provider in cfg_matches:
                    # The current provider itself declares it — keep current.
                    new_model = cfg_matches[current_provider]
                    config_routed = True
                else:
                    match_slugs = sorted(cfg_matches)
                    if len(match_slugs) > 1:
                        return ModelSwitchResult(
                            success=False,
                            is_global=is_global,
                            error_message=(
                                f"'{new_model}' is declared by multiple configured "
                                f"providers ({', '.join(match_slugs)}). Re-run with "
                                f"--provider <slug> to choose which one to use."
                            ),
                        )
                    target_provider = match_slugs[0]
                    new_model = cfg_matches[target_provider]
                    config_routed = True
                    logger.debug(
                        "Configured-provider detection routed '%s' to %s",
                        new_model, target_provider,
                    )
                    # User-config providers (providers.<slug>) are resolved in
                    # the credential block via resolve_user_provider(), which is
                    # gated on explicit_provider.  Mirror the picker so the
                    # rerouted user provider's base_url/key load from the passed
                    # config rather than a from-scratch runtime re-resolve that
                    # doesn't know user-config slugs.  custom:* slugs resolve via
                    # resolve_runtime_provider() directly and need no hint.
                    if isinstance(user_providers, dict) and target_provider in user_providers:
                        explicit_provider = target_provider

        # --- Step e: detect_provider_for_model() as last resort ---
        _base = current_base_url or ""
        is_custom = (
            current_provider in {"custom", "local"}
            or current_provider.startswith("custom:")
            or ("localhost" in _base or "127.0.0.1" in _base)
        )

        if (
            target_provider == current_provider
            and not is_custom
            and not resolved_alias
            and not resolved_in_current_catalog
            and not config_routed
        ):
            detected = (
                detect_static_provider_for_model(new_model, current_provider)
                if restricted_egress
                else detect_provider_for_model(new_model, current_provider)
            )
            if detected:
                target_provider, new_model = detected

    # =================================================================
    # COMMON PATH: Resolve credentials, normalize, get metadata
    # =================================================================

    provider_changed = target_provider != current_provider
    if restricted_egress:
        label_def = selected_provider_def or _resolve_restricted_provider(
            target_provider,
            user_providers,
            custom_providers,
            current_provider=current_provider,
            current_base_url=current_base_url,
        )
        provider_label = label_def.name if label_def is not None else target_provider
    else:
        provider_label = get_label(target_provider)
    if target_provider == "custom" and current_base_url:
        provider_label = "Custom endpoint"
    if target_provider.startswith("custom:"):
        custom_pdef = (
            _resolve_restricted_provider(
                target_provider,
                user_providers,
                custom_providers,
                current_provider=current_provider,
                current_base_url=current_base_url,
            )
            if restricted_egress
            else resolve_provider_full(
                target_provider,
                user_providers,
                custom_providers,
            )
        )
        if custom_pdef is not None:
            provider_label = custom_pdef.name

    # --- Resolve credentials ---
    api_key = current_api_key
    base_url = current_base_url
    api_mode = ""

    # The final provider is now known.  In local_ai authorize its raw route
    # before reading key references, invoking OAuth/runtime resolution, or
    # issuing a live validation probe.  Every later resolver must return this
    # exact normalized literal route.
    authorized_base_url = ""
    if restricted_egress:
        restricted_direct_alias = (
            restricted_aliases.get(resolved_alias) if resolved_alias else None
        )
        route_hint = _restricted_route_hint(
            target_provider=target_provider,
            current_provider=current_provider,
            current_base_url=current_base_url,
            policy_config=policy_config,
            user_providers=user_providers,
            custom_providers=custom_providers,
            provider_def=selected_provider_def,
            direct_alias=restricted_direct_alias,
        )
        try:
            authorized = _authorize_model_switch_route(
                egress_policy,
                provider=target_provider,
                base_url=route_hint,
            )
        except EgressPolicyError as error:
            return _policy_failure_result(
                error,
                is_global=is_global,
                target_provider=target_provider,
                provider_label=provider_label,
            )
        if not isinstance(authorized, AuthorizedInferenceRoute):  # pragma: no cover
            raise RuntimeError("local_ai route authorization did not return a route")
        authorized_base_url = authorized.base_url
        base_url = authorized_base_url

    if provider_changed or explicit_provider:
        import os
        # User-config providers (providers.<name> in config.yaml) carry their
        # own base_url + transport + key reference. resolve_runtime_provider()
        # resolves by provider NAME and doesn't know user-config slugs (e.g. a
        # block named "openai"), so it would re-resolve from scratch and fail
        # or hop to an aggregator. Use the pdef's endpoint directly instead.
        _user_pdef = None
        if explicit_provider and user_providers:
            from fabric_cli.providers import resolve_user_provider as _ruser
            _user_pdef = _ruser(explicit_provider.strip().lower(), user_providers)
            if _user_pdef is None:
                _user_pdef = _ruser(target_provider, user_providers)
        if _user_pdef is not None and _user_pdef.base_url:
            _ucfg = (user_providers or {}).get(explicit_provider.strip().lower()) \
                or (user_providers or {}).get(target_provider) or {}
            try:
                _ukey = str(_ucfg.get("api_key", "") or "").strip()
                if _ukey.startswith("${") and _ukey.endswith("}"):
                    env_name = _ukey[2:-1]
                    if restricted_egress:
                        from fabric_cli.config import get_env_value

                        _ukey = str(get_env_value(env_name) or "").strip()
                    else:
                        _ukey = os.environ.get(env_name, "").strip()
                if not _ukey:
                    _kenv = str(_ucfg.get("key_env", "") or "").strip()
                    if _kenv:
                        if restricted_egress:
                            from fabric_cli.config import get_env_value

                            _ukey = str(get_env_value(_kenv) or "").strip()
                        else:
                            _ukey = os.environ.get(_kenv, "").strip()
            except Exception:
                if not restricted_egress:
                    raise
                return ModelSwitchResult(
                    success=False,
                    is_global=is_global,
                    error_message=(
                        "Could not resolve profile-scoped credentials for the "
                        "authorized local provider."
                    ),
                )
            try:
                runtime = resolve_runtime_provider(
                    requested=target_provider,
                    explicit_api_key=_ukey or None,
                    explicit_base_url=(
                        authorized_base_url
                        if restricted_egress
                        else _user_pdef.base_url
                    ),
                    target_model=new_model,
                )
                api_key = runtime.get("api_key", "") or _ukey
                base_url = runtime.get("base_url", "") or (
                    authorized_base_url
                    if restricted_egress
                    else _user_pdef.base_url
                )
                api_mode = runtime.get("api_mode", "")
            except (EgressPolicyError, EgressPolicyConfigurationError) as error:
                return _policy_failure_result(
                    error,
                    is_global=is_global,
                    target_provider=target_provider,
                    provider_label=provider_label,
                )
            except Exception as error:
                nested_policy_error = _nested_policy_failure(error)
                if nested_policy_error is not None:
                    return _policy_failure_result(
                        nested_policy_error,
                        is_global=is_global,
                        target_provider=target_provider,
                        provider_label=provider_label,
                    )
                api_key = _ukey
                base_url = (
                    authorized_base_url
                    if restricted_egress
                    else _user_pdef.base_url
                )
                api_mode = ""
        elif target_provider == "custom" and current_base_url:
            api_key = current_api_key
            base_url = current_base_url
            api_mode = (
                _restricted_api_mode(target_provider, base_url, selected_provider_def)
                if restricted_egress
                else determine_api_mode(target_provider, base_url)
            )
        else:
            try:
                if restricted_egress:
                    runtime = resolve_runtime_provider(
                        requested=target_provider,
                        explicit_base_url=authorized_base_url,
                        target_model=new_model,
                    )
                else:
                    runtime = resolve_runtime_provider(
                        requested=target_provider,
                        target_model=new_model,
                    )
                api_key = runtime.get("api_key", "")
                base_url = runtime.get("base_url", "")
                api_mode = runtime.get("api_mode", "")
            except (EgressPolicyError, EgressPolicyConfigurationError) as error:
                return _policy_failure_result(
                    error,
                    is_global=is_global,
                    target_provider=target_provider,
                    provider_label=provider_label,
                )
            except Exception as e:
                nested_policy_error = _nested_policy_failure(e)
                if nested_policy_error is not None:
                    return _policy_failure_result(
                        nested_policy_error,
                        is_global=is_global,
                        target_provider=target_provider,
                        provider_label=provider_label,
                    )
                if restricted_egress:
                    return ModelSwitchResult(
                        success=False,
                        is_global=is_global,
                        error_message=(
                            "Could not resolve credentials for the authorized "
                            "local provider."
                        ),
                    )
                return ModelSwitchResult(
                    success=False,
                    target_provider=target_provider,
                    provider_label=provider_label,
                    is_global=is_global,
                    error_message=(
                        f"Could not resolve credentials for provider "
                        f"'{provider_label}': {e}"
                    ),
                )
    else:
        try:
            if restricted_egress:
                runtime = resolve_runtime_provider(
                    requested=current_provider,
                    explicit_base_url=authorized_base_url,
                    target_model=new_model,
                )
            else:
                runtime = resolve_runtime_provider(
                    requested=current_provider,
                    target_model=new_model,
                )
            # If resolution fell through to "custom" (e.g. named custom provider like
            # "ollama-launch" that resolve_runtime_provider doesn't know), keep existing
            # credentials. Otherwise use the resolved values (picks up credential rotation,
            # base_url adjustments for OpenCode, etc.).
            api_key = runtime.get("api_key", "")
            base_url = runtime.get("base_url", "")
            api_mode = runtime.get("api_mode", "")
        except (EgressPolicyError, EgressPolicyConfigurationError) as error:
            return _policy_failure_result(
                error,
                is_global=is_global,
                target_provider=target_provider,
                provider_label=provider_label,
            )
        except Exception as error:
            nested_policy_error = _nested_policy_failure(error)
            if nested_policy_error is not None:
                return _policy_failure_result(
                    nested_policy_error,
                    is_global=is_global,
                    target_provider=target_provider,
                    provider_label=provider_label,
                )
            pass

    if restricted_egress:
        try:
            base_url = _reauthorize_restricted_route(
                egress_policy,
                provider=target_provider,
                base_url=base_url,
                expected_base_url=authorized_base_url,
            )
        except EgressPolicyError as error:
            return _policy_failure_result(
                error,
                is_global=is_global,
                target_provider=target_provider,
                provider_label=provider_label,
            )

    # --- Direct alias override: use exact base_url from the alias if set ---
    if resolved_alias:
        if restricted_egress:
            _da = restricted_aliases.get(resolved_alias)
        else:
            _ensure_direct_aliases()
            _da = DIRECT_ALIASES.get(resolved_alias)
        if _da is not None and _da.base_url:
            base_url = _da.base_url
            api_mode = ""  # clear so determine_api_mode re-detects from URL
            if not api_key:
                api_key = "no-key-required"

    if restricted_egress:
        try:
            base_url = _reauthorize_restricted_route(
                egress_policy,
                provider=target_provider,
                base_url=base_url,
                expected_base_url=authorized_base_url,
            )
        except EgressPolicyError as error:
            return _policy_failure_result(
                error,
                is_global=is_global,
                target_provider=target_provider,
                provider_label=provider_label,
            )

    # --- Normalize model name for target provider ---
    new_model = normalize_model_for_provider(new_model, target_provider)

    # --- Validate ---
    try:
        if restricted_egress:
            validation = _restricted_validation(
                new_model,
                api_key=api_key,
                base_url=base_url,
                api_mode=api_mode,
            )
        else:
            validation = validate_requested_model(
                new_model,
                target_provider,
                api_key=api_key,
                base_url=base_url,
                api_mode=api_mode or None,
            )
    except Exception as e:
        validation = {
            "accepted": False,
            "persist": False,
            "recognized": False,
            "message": (
                "Could not validate the requested model."
                if restricted_egress
                else f"Could not validate `{new_model}`: {e}"
            ),
        }

    # Override rejection if model is in the user's saved provider config.
    # API /v1/models may not list cloud/aliased models even though the server supports them.
    if not validation.get("accepted"):
        override = False
        if user_providers:
            # user_providers is a dict: {provider_slug: config_dict}
            for slug, cfg in user_providers.items():
                if slug == target_provider:
                    if new_model in _declared_model_ids(cfg.get("models", {})):
                        override = True
                        break
        # Also check custom_providers list — models declared there should be accepted
        # even if the remote /v1/models endpoint doesn't list them.
        if not override and custom_providers and isinstance(custom_providers, list):
            for entry in custom_providers:
                if not isinstance(entry, dict):
                    continue
                # Match by provider slug (custom:<name>) or by base_url
                entry_name = entry.get("name", "")
                entry_slug = (
                    custom_provider_slug(str(entry_name))
                    if restricted_egress and entry_name
                    else f"custom:{entry_name}" if entry_name else ""
                )
                entry_url = entry.get("base_url", "")
                entry_url_matches = entry_url == base_url
                if restricted_egress and entry_url and not entry_url_matches:
                    try:
                        entry_route = _authorize_model_switch_route(
                            egress_policy,
                            provider=target_provider,
                            base_url=entry_url,
                        )
                        entry_url_matches = bool(
                            entry_route is not None
                            and entry_route.base_url == base_url
                        )
                    except EgressPolicyError:
                        entry_url_matches = False
                if entry_slug == target_provider or entry_url_matches:
                    # Check if the requested model matches the entry's model
                    entry_model = entry.get("model", "")
                    entry_models = entry.get("models", {})
                    if new_model == entry_model:
                        override = True
                        break
                    if new_model in _declared_model_ids(entry_models):
                        override = True
                        break
        if override:
            validation = {"accepted": True, "persist": True, "recognized": False, "message": validation.get("message", "")}
        else:
            msg = validation.get("message", "Invalid model")
            return ModelSwitchResult(
                success=False,
                new_model=new_model,
                target_provider=target_provider,
                provider_label=provider_label,
                is_global=is_global,
                error_message=msg,
            )

    # Apply auto-correction if validation found a closer match
    if validation.get("corrected_model"):
        new_model = validation["corrected_model"]

    # --- Copilot api_mode override ---
    if not restricted_egress and target_provider in {"copilot", "github-copilot"}:
        api_mode = copilot_model_api_mode(new_model, api_key=api_key)

    # --- OpenCode api_mode override ---
    if not restricted_egress and target_provider in {"opencode-zen", "opencode-go", "opencode"}:
        api_mode = opencode_model_api_mode(target_provider, new_model)

    # --- Determine api_mode if not already set ---
    if not api_mode:
        api_mode = (
            _restricted_api_mode(target_provider, base_url, selected_provider_def)
            if restricted_egress
            else determine_api_mode(target_provider, base_url)
        )

    # OpenCode base URLs end with /v1 for OpenAI-compatible models, but the
    # Anthropic SDK prepends its own /v1/messages to the base_url.  Normalize
    # symmetrically (strip /v1 for anthropic_messages, re-append it for
    # chat_completions / codex_responses).  Mirrors the same logic in
    # fabric_cli.runtime_provider.resolve_runtime_provider; without the strip,
    # /model switches into an anthropic_messages-routed OpenCode model
    # (e.g. `/model minimax-m2.7` on opencode-go, `/model claude-sonnet-4-6`
    # on opencode-zen) hit a double /v1 and returned OpenCode's website 404
    # page — and without the re-append, a stripped URL persisted to
    # model.base_url broke every later chat_completions model (glm, deepseek,
    # kimi) the same way.
    if (
        not restricted_egress
        and target_provider in {"opencode-zen", "opencode-go"}
        and isinstance(base_url, str)
    ):
        from fabric_cli.models import normalize_opencode_base_url
        base_url = normalize_opencode_base_url(target_provider, api_mode, base_url)

    if restricted_egress:
        try:
            base_url = _reauthorize_restricted_route(
                egress_policy,
                provider=target_provider,
                base_url=base_url,
                expected_base_url=authorized_base_url,
            )
        except EgressPolicyError as error:
            return _policy_failure_result(
                error,
                is_global=is_global,
                target_provider=target_provider,
                provider_label=provider_label,
            )

    # models.dev is an optional remote metadata source.  It is unrelated to
    # inference, but consulting it here would make a successful local_ai
    # switch perform a second, non-local HTTP request after the authorized
    # model-list probe.  Keep restricted switches local-only; online retains
    # the exact legacy metadata calls.
    if restricted_egress:
        capabilities = None
        model_info = None
    else:
        # --- Get capabilities (legacy) ---
        capabilities = get_model_capabilities(target_provider, new_model)

        # --- Get full model info from models.dev ---
        model_info = get_model_info(target_provider, new_model)

    # --- Collect warnings ---
    warnings: list[str] = []
    if validation.get("message"):
        warnings.append(validation["message"])
    fabric_warn = _check_fabric_model_warning(new_model)
    if fabric_warn:
        warnings.append(fabric_warn)
    if preflight_local_runtime:
        preflight_error, preflight_warning = _preflight_ollama_selection(
            provider=target_provider,
            model=new_model,
            base_url=base_url,
            api_key=api_key,
            config=policy_config,
        )
        if preflight_error:
            return ModelSwitchResult(
                success=False,
                new_model=new_model,
                target_provider=target_provider,
                provider_label=provider_label,
                is_global=is_global,
                error_message=preflight_error,
            )
        if preflight_warning:
            warnings.append(preflight_warning)

    # --- Build result ---
    return ModelSwitchResult(
        success=True,
        new_model=new_model,
        target_provider=target_provider,
        provider_changed=provider_changed,
        api_key=api_key,
        base_url=base_url,
        api_mode=api_mode,
        warning_message=" | ".join(warnings) if warnings else "",
        provider_label=provider_label,
        resolved_via_alias=resolved_alias,
        capabilities=capabilities,
        model_info=model_info,
        is_global=is_global,
    )


def _preflight_ollama_selection(
    *,
    provider: str,
    model: str,
    base_url: str,
    api_key: Any,
    config: dict[str, Any],
) -> tuple[str | None, str | None]:
    """Return ``(blocking_error, nonblocking_warning)`` for one selection.

    The readiness snapshot is already bounded and secret-free. This adapter
    deliberately emits only fixed messages and numeric capability facts; raw
    endpoints, credentials, response bodies, and exceptions never cross into
    a model-switch result.
    """

    from fabric_cli.ollama_runtime import (
        build_ollama_readiness_snapshot,
        is_ollama_runtime_target,
    )

    if not is_ollama_runtime_target(provider, base_url):
        return None, None

    probe_config = dict(config) if isinstance(config, dict) else {}
    raw_model_config = probe_config.get("model")
    model_config = (
        dict(raw_model_config) if isinstance(raw_model_config, dict) else {}
    )
    model_config.update({
        "provider": provider,
        "default": model,
        "base_url": base_url,
    })
    probe_config["model"] = model_config
    explicit_key = api_key if isinstance(api_key, str) else ""
    if explicit_key == "no-key-required":
        explicit_key = ""
    try:
        snapshot = build_ollama_readiness_snapshot(
            config=probe_config,
            model=model,
            base_url=base_url,
            api_key=explicit_key,
            include_resources=False,
            timeout=4.0,
        )
    except Exception:
        return (
            None,
            "Ollama readiness could not be verified. The selection was not "
            "rejected, but the next agent start may fail; run `fabric status "
            "--deep` before relying on it.",
        )

    if not snapshot.applicable:
        return None, None

    if snapshot.context_state == "too_small":
        from agent.model_metadata import MINIMUM_CONTEXT_LENGTH

        detected = snapshot.effective_context_length
        detected_text = (
            f"{detected:,} tokens" if isinstance(detected, int) else "too little context"
        )
        return (
            "The selected Ollama model reports "
            f"{detected_text}, below Fabric's {MINIMUM_CONTEXT_LENGTH:,}-token "
            "agent minimum. Choose or pull a compatible model; do not claim a "
            "larger context than the runtime reports.",
            None,
        )
    if snapshot.tools_state == "unsupported":
        return (
            "The selected Ollama model reports no tool support, so Fabric "
            "cannot use it for agent actions. Choose a tool-capable model.",
            None,
        )
    if snapshot.state == "model_missing":
        return (
            "The selected Ollama model is not installed. Pull it with `fabric "
            "ollama pull <model>` or choose an installed model.",
            None,
        )
    if snapshot.state in {"auth_failed", "blocked", "incompatible", "invalid_endpoint"}:
        return (
            "The selected Ollama runtime failed its capability preflight. Run "
            "`fabric status --deep` and fix the reported local-model issue "
            "before switching.",
            None,
        )
    if snapshot.state in {"access_unavailable", "not_configured", "unreachable"}:
        return (
            None,
            "Ollama readiness could not be verified. The selection was not "
            "rejected, but the next agent start may fail; run `fabric status "
            "--deep` before relying on it.",
        )
    if snapshot.state == "degraded":
        return (
            None,
            "Ollama is reachable, but context or tool capability is still "
            "unverified. Run `fabric status --deep` and a reversible tool "
            "smoke test before relying on this model.",
        )
    return None, None


# ---------------------------------------------------------------------------
# Authenticated providers listing (for /model no-args display)
# ---------------------------------------------------------------------------

# Process-level guard so the picker prewarm thread is spawned at most once per
# process — mirrors run_agent's _openrouter_prewarm_done. Without a guard a
# long-lived process (or repeated triggers) would leak one OS thread per call.
import threading as _threading  # noqa: E402

_picker_prewarm_done = _threading.Event()


def _extra_headers_from_config(entry: Any) -> dict[str, str]:
    if not isinstance(entry, dict):
        return {}
    from fabric_cli.config import normalize_extra_headers

    return normalize_extra_headers(entry.get("extra_headers"))


def _restricted_picker_rows(
    *,
    current_provider: str,
    current_base_url: str,
    current_model: str,
    max_models: Optional[int],
) -> Optional[List[dict]]:
    """Return config-only picker rows under local_ai, else ``None``.

    The online picker intentionally performs credential discovery and live
    catalog probes.  Those actions happen before a user has selected a target
    route, so they cannot run in local_ai.  Restricted pickers show only
    profile-declared endpoints whose literal route passes the same policy;
    they never read keys or probe ``/models``.
    """

    try:
        policy, config = _load_model_switch_policy()
    except (EgressPolicyError, EgressPolicyConfigurationError):
        return []
    if policy.mode is EgressMode.ONLINE:
        return None

    rows: dict[str, dict] = {}

    def _add_row(
        *,
        slug: str,
        name: str,
        base_url: Any,
        models: list[str],
        source: str,
    ) -> None:
        safe_slug = str(slug or "").strip()
        if not safe_slug:
            return
        try:
            route = _authorize_model_switch_route(
                policy,
                provider=safe_slug,
                base_url=base_url,
            )
        except EgressPolicyError:
            return
        if not isinstance(route, AuthorizedInferenceRoute):  # pragma: no cover
            return
        existing = rows.get(safe_slug.lower())
        if existing is None:
            unique_models = list(dict.fromkeys(model for model in models if model))
            rows[safe_slug.lower()] = {
                "slug": safe_slug,
                "name": str(name or safe_slug),
                "is_current": safe_slug.lower()
                == str(current_provider or "").strip().lower(),
                "is_user_defined": True,
                "models": unique_models,
                "total_models": len(unique_models),
                "source": source,
                "api_url": route.base_url,
            }
            return
        for model in models:
            if model and model not in existing["models"]:
                existing["models"].append(model)
        existing["total_models"] = len(existing["models"])
        existing["is_current"] = bool(
            existing["is_current"]
            or safe_slug.lower() == str(current_provider or "").strip().lower()
        )

    configured_providers = config.get("providers")
    if isinstance(configured_providers, dict):
        for slug, entry in configured_providers.items():
            if not isinstance(slug, str) or not isinstance(entry, dict):
                continue
            endpoint = (
                entry.get("base_url")
                or entry.get("url")
                or entry.get("api")
                or ""
            )
            models: list[str] = []
            for key in ("models", "model", "default_model"):
                models.extend(_declared_model_ids(entry.get(key)))
            _add_row(
                slug=slug,
                name=str(entry.get("name") or slug),
                base_url=endpoint,
                models=models,
                source="user-config",
            )

    configured_custom = config.get("custom_providers")
    if isinstance(configured_custom, list):
        for entry in configured_custom:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip()
            endpoint = (
                entry.get("base_url")
                or entry.get("url")
                or entry.get("api")
                or ""
            )
            models = []
            for key in ("models", "model", "default_model"):
                models.extend(_declared_model_ids(entry.get(key)))
            _add_row(
                slug=custom_provider_slug(name) if name else "",
                name=name,
                base_url=endpoint,
                models=models,
                source="user-config",
            )

    current_url = str(current_base_url or "").strip()
    if not current_url:
        model_config = config.get("model")
        if isinstance(model_config, dict):
            current_url = str(model_config.get("base_url") or "").strip()
    if current_provider and current_url:
        _add_row(
            slug=current_provider,
            name=(
                "Custom endpoint"
                if current_provider == "custom"
                else "Ollama (Local)"
                if current_provider in {"ollama", "ollama-local"}
                else current_provider
            ),
            base_url=current_url,
            models=[current_model] if current_model else [],
            source="model-config",
        )

    result = list(rows.values())
    if current_model:
        for row in result:
            if row["is_current"] and current_model not in row["models"]:
                row["models"].insert(0, current_model)
                row["total_models"] = len(row["models"])
                break
    for row in result:
        if max_models is not None:
            row["models"] = row["models"][:max_models]
    result.sort(key=lambda row: (not row["is_current"], -row["total_models"]))
    return result


def prewarm_picker_cache_async() -> Optional["_threading.Thread"]:
    """Warm the provider-models disk cache in a background daemon thread.

    The no-args ``/model`` picker calls ``list_authenticated_providers()``,
    which fetches each authenticated provider's live ``/v1/models`` list on a
    cold/stale cache. Those fetches are independent HTTP round-trips but run
    serially, so the first ``/model`` open in a session (or any open after the
    1h cache TTL expires) blocks ~1-2s on the user's critical path.

    This pre-warms that exact path off-thread during idle session time: it
    runs ``list_authenticated_providers()`` once, which populates
    ``provider_models_cache.json`` for every authed provider. By the time the
    user types ``/model``, the picker hits the warm disk cache and renders in
    ~100ms.

    Fire-and-forget. Process-level Event guard ensures it runs at most once.
    Fully exception-isolated — a slow or offline provider can never affect the
    session. Returns the spawned thread (for tests) or None if already warmed.
    """
    if _picker_prewarm_done.is_set():
        return None
    _picker_prewarm_done.set()

    def _warm() -> None:
        try:
            from fabric_cli.inventory import load_picker_context

            ctx = load_picker_context()
            if ctx.restricted_egress:
                return
            # Calling this is what populates cached_provider_model_ids() ->
            # provider_models_cache.json for each authed provider. We discard
            # the result; the side effect (warm disk cache) is the point.
            list_authenticated_providers(
                current_provider=ctx.current_provider,
                current_base_url=ctx.current_base_url,
                current_model=ctx.current_model,
                user_providers=ctx.user_providers,
                custom_providers=ctx.custom_providers,
            )
        except Exception:
            # Best-effort warmup — never surface errors into the session.
            logger.debug("picker cache prewarm failed", exc_info=True)

    t = _threading.Thread(target=_warm, daemon=True, name="picker-cache-prewarm")
    t.start()
    return t


def list_authenticated_providers(
    current_provider: str = "",
    current_base_url: str = "",
    user_providers: dict = None,
    custom_providers: list | None = None,
    *,
    force_fresh_nous_tier: bool = False,
    max_models: int | None = None,
    current_model: str = "",
    refresh: bool = False,
    probe_custom_providers: bool = True,
    probe_current_custom_provider: bool = False,
) -> List[dict]:
    """Detect which providers have credentials and list their curated models.

    Uses the curated model lists from fabric_cli/models.py (OPENROUTER_MODELS,
    _PROVIDER_MODELS) — NOT the full models.dev catalog.  These are hand-picked
    agentic models that work well as agent backends.

    Returns a list of dicts, each with:
      - slug: str — the --provider value to use
      - name: str — display name
      - is_current: bool
      - is_user_defined: bool
      - models: list[str] — curated model IDs (up to max_models)
      - total_models: int — total curated count
      - source: str — "built-in", "models.dev", "user-config"

    Only includes providers that have API keys set or are user-defined endpoints.
    ``force_fresh_nous_tier`` bypasses the short Nous tier cache for explicit
    account-sensitive flows. UI picker opens should leave it false so they do
    not block on fresh Portal/account checks every time.

    ``refresh`` busts the per-provider model-id disk cache
    (``provider_models_cache.json``) up front so every row re-fetches its
    live catalog. Use for an explicit user-triggered "refresh models" action
    (e.g. the desktop picker's refresh control); leave false for normal picker
    opens so they stay snappy on the 1h cache.

    ``probe_custom_providers`` controls live ``/models`` discovery for saved
    custom OpenAI-compatible endpoints. Keep the default true for CLI parity;
    GUI picker opens can pass false to show configured models immediately
    without waiting on offline local endpoints.

    ``probe_current_custom_provider`` is the middle ground for GUI picker
    opens: probe only the currently-selected custom endpoint so its model list
    matches the active provider without blocking on every saved/offline custom
    endpoint.
    """
    restricted_rows = _restricted_picker_rows(
        current_provider=current_provider,
        current_base_url=current_base_url,
        current_model=current_model,
        max_models=max_models,
    )
    if restricted_rows is not None:
        return restricted_rows

    import os
    from agent.models_dev import (
        PROVIDER_TO_MODELS_DEV,
        fetch_models_dev,
        get_provider_info as _mdev_pinfo,
    )
    from fabric_cli.auth import PROVIDER_REGISTRY
    from fabric_cli.models import (
        OPENROUTER_MODELS, _PROVIDER_MODELS,
        _MODELS_DEV_PREFERRED, _merge_with_models_dev, cached_provider_model_ids,
        clear_provider_models_cache, get_curated_nous_model_ids,
    )

    # Explicit refresh: drop every provider's cached model-id list so the
    # cached_provider_model_ids() calls below all re-fetch live. Without this
    # a stale 1h cache can fall back to the curated static list when its live
    # fetch later fails, silently dropping live-only models (e.g. OpenCode
    # Zen's free tier) the user had seen before.
    if refresh:
        try:
            clear_provider_models_cache()
        except Exception:
            pass


    results: List[dict] = []
    seen_slugs: set = set()  # lowercase-normalized to catch case variants (#9545)
    seen_mdev_ids: set = set()  # prevent duplicate entries for aliases (e.g. kimi-coding + kimi-coding-cn)
    _current_provider_norm = str(current_provider or "").strip().lower()
    _current_base_url_norm = str(current_base_url or "").strip().rstrip("/").lower()

    def _can_probe_custom_provider(*, row_is_current: bool) -> bool:
        return bool(probe_custom_providers or (probe_current_custom_provider and row_is_current))

    # Effective base URLs of every built-in row we emit (normalized lower+rstrip).
    # Section 4 uses this to hide ``custom_providers`` entries that point at the
    # same endpoint as a built-in (e.g. a user-defined "my-dashscope" on
    # https://coding-intl.dashscope.aliyuncs.com/v1 collides with the built-in
    # alibaba-coding-plan row when DASHSCOPE_API_KEY is present). Fixes #16970.
    _builtin_endpoints: set = set()

    def _norm_url(url: str) -> str:
        return str(url or "").strip().rstrip("/").lower()

    def _record_builtin_endpoint(slug: str) -> None:
        """Record the effective base URL for a built-in provider row.

        Prefers the live env-override (e.g. DASHSCOPE_BASE_URL) over the
        static inference_base_url so the dedup matches what a user typing
        that URL into custom_providers would actually hit."""
        try:
            from fabric_cli.auth import PROVIDER_REGISTRY as _reg
        except Exception:
            return
        pcfg = _reg.get(slug)
        if not pcfg:
            return
        url = ""
        if getattr(pcfg, "base_url_env_var", ""):
            url = os.environ.get(pcfg.base_url_env_var, "") or ""
        if not url:
            url = getattr(pcfg, "inference_base_url", "") or ""
        normed = _norm_url(url)
        if normed:
            _builtin_endpoints.add(normed)

    def _has_fast_aws_sdk_signal() -> bool:
        """Return True when explicit AWS auth config is present.

        This intentionally avoids botocore's full credential chain. Provider
        picker/model-switch discovery can run for non-Bedrock providers, and
        botocore may otherwise probe EC2 IMDS (169.254.169.254) on local
        machines before returning no credentials.
        """
        if os.environ.get("AWS_BEARER_TOKEN_BEDROCK", "").strip():
            return True
        if (
            os.environ.get("AWS_ACCESS_KEY_ID", "").strip()
            and os.environ.get("AWS_SECRET_ACCESS_KEY", "").strip()
        ):
            return True
        return any(
            os.environ.get(name, "").strip()
            for name in (
                "AWS_PROFILE",
                "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
                "AWS_CONTAINER_CREDENTIALS_FULL_URI",
                "AWS_WEB_IDENTITY_TOKEN_FILE",
            )
        )

    def _has_aws_sdk_creds_for_listing(slug: str) -> bool:
        """Credential check for AWS SDK providers in non-runtime discovery."""
        slug_norm = str(slug or "").strip().lower()
        current_norm = str(current_provider or "").strip().lower()
        if _has_fast_aws_sdk_signal():
            return True
        if slug_norm != current_norm:
            return False
        try:
            from agent.bedrock_adapter import has_aws_credentials
            return bool(has_aws_credentials())
        except Exception:
            return False

    data = fetch_models_dev()

    # Build curated model lists keyed by fabric provider ID
    curated: dict[str, list[str]] = dict(_PROVIDER_MODELS)
    curated["openrouter"] = [mid for mid, _ in OPENROUTER_MODELS]
    # "nous" pulls from the remote model-catalog manifest published at
    # https://obliviousodin.github.io/fabric/api/model-catalog.json so
    # newly added Portal models surface in the /model picker without
    # requiring a Fabric release. Falls back to the in-repo
    # _PROVIDER_MODELS["nous"] snapshot when the manifest is unreachable.
    curated["nous"] = get_curated_nous_model_ids()
    # Ollama Cloud uses dynamic discovery (no static curated list)
    if "ollama-cloud" not in curated:
        from fabric_cli.models import fetch_ollama_cloud_models
        curated["ollama-cloud"] = fetch_ollama_cloud_models()
    # LM Studio has no static catalog — probe its native /api/v1/models
    # endpoint live so the picker reflects whatever the user has loaded.
    # Base URL precedence: LM_BASE_URL env var > active config's base_url
    # (when current provider is lmstudio) > 127.0.0.1 default.
    # On auth rejection or unreachable server, fall back to the caller-supplied
    # current model so the picker still shows something when offline / mis-keyed.
    if "lmstudio" not in curated and (
        os.environ.get("LM_API_KEY") or os.environ.get("LM_BASE_URL") or current_provider.strip().lower() == "lmstudio"
    ):
        from fabric_cli.models import fetch_lmstudio_models
        from fabric_cli.auth import AuthError
        is_current_lmstudio = current_provider.strip().lower() == "lmstudio"
        lm_base = (
            os.environ.get("LM_BASE_URL")
            or (current_base_url if is_current_lmstudio and current_base_url else None)
            or "http://127.0.0.1:1234/v1"
        )
        try:
            live = fetch_lmstudio_models(
                api_key=os.environ.get("LM_API_KEY", ""),
                base_url=lm_base,
                timeout=1.5, # Smaller timeout for picker
            )
        except AuthError:
            live = []
        if not live and is_current_lmstudio and current_model:
            live = [current_model]
        curated["lmstudio"] = live

    # --- 1. Check Fabric-mapped providers ---
    from fabric_cli.models import _AGGREGATOR_PROVIDERS as _AGG_PROVIDERS
    from fabric_cli.providers import ALIASES as _PROVIDER_ALIAS_TABLE
    for fabric_id, mdev_id in PROVIDER_TO_MODELS_DEV.items():
        # Skip vendor names that are merely aliases routing through an
        # aggregator (e.g. bare "openai" → "openrouter"). These are NOT
        # directly-routable providers: emitting them as their own picker
        # row produces a phantom entry that, when selected, resolves via
        # resolve_provider_full() to the aggregator (OpenRouter) — silently
        # switching a user off their real provider onto an endpoint they
        # may have no key for (HTTP 401). The user's real provider (e.g.
        # openai-api, or a providers.openai config row) covers this vendor.
        _alias_target = _PROVIDER_ALIAS_TABLE.get(fabric_id)
        if (
            _alias_target
            and _alias_target != fabric_id
            and _alias_target in _AGG_PROVIDERS
        ):
            continue
        # Skip aliases that map to the same models.dev provider (e.g.
        # kimi-coding and kimi-coding-cn both → kimi-for-coding).
        # The first one with valid credentials wins (#10526).
        if mdev_id in seen_mdev_ids:
            continue
        pdata = data.get(mdev_id)
        if not isinstance(pdata, dict):
            continue

        # Prefer auth.py PROVIDER_REGISTRY for env var names — it's our
        # source of truth.  models.dev can have wrong mappings (e.g.
        # minimax-cn → MINIMAX_API_KEY instead of MINIMAX_CN_API_KEY).
        pconfig = PROVIDER_REGISTRY.get(fabric_id)
        # Skip non-API-key auth providers here — they are handled in
        # section 2 (FABRIC_OVERLAYS) with proper auth store checking.
        if pconfig and pconfig.auth_type != "api_key":
            continue
        if pconfig and pconfig.api_key_env_vars:
            env_vars = list(pconfig.api_key_env_vars)
        else:
            env_vars = pdata.get("env", [])
            if not isinstance(env_vars, list):
                continue

        # Check if any env var is set
        has_creds = any(os.environ.get(ev) for ev in env_vars)
        if not has_creds:
            try:
                from fabric_cli.auth import _load_auth_store
                store = _load_auth_store()
                if store and store.get("credential_pool", {}).get(fabric_id):
                    has_creds = True
            except Exception:
                pass
        if not has_creds:
            continue

        # Unified pathway: route through cached_provider_model_ids() so the
        # /model picker sees the SAME list `fabric model` would build, with
        # disk caching to keep the picker open snappy. Falls back to the
        # curated static list when the live fetcher returns nothing.
        model_ids = cached_provider_model_ids(fabric_id)
        if not model_ids:
            model_ids = curated.get(fabric_id, [])
            if fabric_id in _MODELS_DEV_PREFERRED:
                model_ids = _merge_with_models_dev(fabric_id, model_ids)
        total = len(model_ids)
        if fabric_id in _UNCAPPED_PICKER_PROVIDERS:
            top = model_ids  # Aggregator: show full catalog regardless of max_models
        else:
            top = model_ids[:max_models] if max_models is not None else model_ids

        slug = fabric_id
        pinfo = _mdev_pinfo(mdev_id)
        display_name = pinfo.name if pinfo else mdev_id

        results.append({
            "slug": slug,
            "name": display_name,
            "is_current": slug == current_provider or mdev_id == current_provider,
            "is_user_defined": False,
            "models": top,
            "total_models": total,
            "source": "built-in",
        })
        seen_slugs.add(slug.lower())
        seen_mdev_ids.add(mdev_id)
        _record_builtin_endpoint(slug)

    # --- 2. Check Fabric-only providers (nous, openai-codex, copilot, opencode-go) ---
    from fabric_cli.providers import FABRIC_OVERLAYS
    from fabric_cli.auth import PROVIDER_REGISTRY as _auth_registry

    # Build reverse mapping: models.dev ID → Fabric provider ID.
    # FABRIC_OVERLAYS keys may be models.dev IDs (e.g. "github-copilot")
    # while _PROVIDER_MODELS and config.yaml use Fabric IDs ("copilot").
    _mdev_to_fabric = {v: k for k, v in PROVIDER_TO_MODELS_DEV.items()}

    for pid, overlay in FABRIC_OVERLAYS.items():
        if pid.lower() in seen_slugs:
            continue

        # Resolve Fabric slug — e.g. "github-copilot" → "copilot"
        fabric_slug = _mdev_to_fabric.get(pid, pid)
        if fabric_slug.lower() in seen_slugs:
            continue

        # Check if credentials exist
        has_creds = False
        if fabric_slug == "ollama":
            # Local Ollama is no-auth. Treat it as configured only after the
            # profile selected it; the provider setup menu remains the entry
            # point for a first connection.
            has_creds = _current_provider_norm in {"ollama", "ollama-local"}
        elif overlay.auth_type == "aws_sdk":
            has_creds = _has_aws_sdk_creds_for_listing(fabric_slug)
        elif overlay.extra_env_vars:
            has_creds = any(os.environ.get(ev) for ev in overlay.extra_env_vars)
        # Also check api_key_env_vars from PROVIDER_REGISTRY for api_key auth_type
        if not has_creds and overlay.auth_type == "api_key":
            for _key in (pid, fabric_slug):
                pcfg = _auth_registry.get(_key)
                if pcfg and pcfg.api_key_env_vars:
                    if any(os.environ.get(ev) for ev in pcfg.api_key_env_vars):
                        has_creds = True
                        break
        # Check auth store and credential pool for non-env-var credentials.
        # This applies to OAuth providers AND api_key providers that also
        # support OAuth (e.g. anthropic supports both API key and Claude Code
        # OAuth via external credential files).
        if not has_creds:
            try:
                from fabric_cli.auth import _load_auth_store
                store = _load_auth_store()
                providers_store = store.get("providers", {})
                if store and (pid in providers_store or fabric_slug in providers_store):
                    has_creds = True
            except Exception as exc:
                logger.debug("Auth store check failed for %s: %s", pid, exc)
        # Fallback: check the credential pool after its provider-specific
        # seeding and routing rules run. This catches pool entries that are not
        # represented by the singleton provider block above. In particular,
        # Codex CLI refresh credentials are not silently imported: users must
        # explicitly import them or authenticate through Fabric to avoid two
        # processes racing a single-use refresh token.
        if not has_creds:
            try:
                from agent.credential_pool import load_pool
                pool = load_pool(fabric_slug)
                if pool.has_credentials():
                    has_creds = True
            except Exception as exc:
                logger.debug("Credential pool check failed for %s: %s", fabric_slug, exc)
        # Fallback: check external credential files directly.
        # The credential pool gates anthropic behind
        # is_provider_explicitly_configured() to prevent auxiliary tasks
        # from silently consuming Claude Code tokens (PR #4210).
        # But the /model picker is discovery-oriented — we WANT to show
        # providers the user can switch to, even if they aren't currently
        # configured.
        if not has_creds and fabric_slug == "anthropic":
            try:
                from agent.anthropic_adapter import (
                    read_claude_code_credentials,
                    read_fabric_oauth_credentials,
                )
                fabric_creds = read_fabric_oauth_credentials()
                cc_creds = read_claude_code_credentials()
                if (fabric_creds and fabric_creds.get("accessToken")) or \
                   (cc_creds and cc_creds.get("accessToken")):
                    has_creds = True
            except Exception as exc:
                logger.debug("Anthropic external creds check failed: %s", exc)
        if not has_creds:
            continue

        if fabric_slug == "ollama":
            model_ids = []
            if refresh:
                try:
                    from agent.ollama_native_adapter import (
                        DEFAULT_OLLAMA_NATIVE_BASE_URL,
                    )
                    from fabric_cli.ollama_runtime import discover_ollama_models

                    discovery = discover_ollama_models(
                        current_base_url or DEFAULT_OLLAMA_NATIVE_BASE_URL,
                        timeout=1.5,
                    )
                    if discovery.state == "reachable":
                        model_ids = list(discovery.models)
                except Exception:
                    model_ids = []
            if not model_ids and current_model:
                model_ids = [current_model]
        elif fabric_slug in {"openai-codex", "copilot", "copilot-acp"}:
            # Use live OAuth-backed discovery so the gateway /model picker
            # matches what the user's authenticated Codex/Copilot backend
            # actually serves — including ChatGPT-Pro-only Codex slugs
            # (e.g. gpt-5.3-codex-spark) that aren't in the static curated
            # catalog. ``cached_provider_model_ids()`` falls back to the
            # curated list when the live endpoint is unreachable, so this
            # is safe for unauthenticated and offline cases too.
            model_ids = cached_provider_model_ids(fabric_slug)
        # For aws_sdk providers (bedrock), use live discovery so the list
        # reflects the active region (eu.*, ap.*) not the static us.* list.
        elif overlay.auth_type == "aws_sdk":
            try:
                _ids = cached_provider_model_ids(fabric_slug)
                model_ids = _ids if _ids else (curated.get(fabric_slug, []) or curated.get(pid, []))
            except Exception:
                model_ids = curated.get(fabric_slug, []) or curated.get(pid, [])
        elif fabric_slug == "nous":
            # Nous serves a large live /v1/models catalog (vendor-prefixed
            # models from many providers, returned alphabetically). The
            # `fabric model` picker deliberately shows ONLY the curated agentic
            # list — augmented with the Portal's free/paid recommendations so
            # newly-launched models surface without a CLI release — in curated
            # order. Mirror that exactly (see _model_flow_nous in main.py) so
            # the GUI picker matches the CLI. Was: falling through to
            # cached_provider_model_ids, which dumped the full alphabetical
            # catalog; then: curated-only, which dropped the 4 Portal
            # recommendations (e.g. stepfun/step-3.7-flash:free).
            model_ids = curated.get("nous", [])
            try:
                from fabric_cli.models import (
                    get_pricing_for_provider as _nous_pricing,
                    check_nous_free_tier as _nous_free,
                    union_with_portal_free_recommendations as _union_free,
                    union_with_portal_paid_recommendations as _union_paid,
                )
                from fabric_cli.auth import get_provider_auth_state as _nous_state

                _pricing = _nous_pricing("nous") or {}
                _portal = ""
                try:
                    _st = _nous_state("nous") or {}
                    _portal = _st.get("portal_base_url", "") or ""
                except Exception:
                    _portal = ""
                if _nous_free(force_fresh=force_fresh_nous_tier):
                    model_ids, _ = _union_free(model_ids, _pricing, _portal)
                else:
                    model_ids, _ = _union_paid(model_ids, _pricing, _portal)
            except Exception:
                # Portal recommendation fetch failed — fall back to the
                # curated list alone (still correct, just may lag newly
                # launched models, exactly like an offline CLI run).
                pass
        else:
            # Unified pathway — see Section 1 rationale. Fall back to the
            # curated dict (with models.dev merge for preferred providers)
            # when the live fetcher comes up empty.
            model_ids = cached_provider_model_ids(fabric_slug)
            if not model_ids:
                model_ids = curated.get(fabric_slug, []) or curated.get(pid, [])
                if fabric_slug in _MODELS_DEV_PREFERRED:
                    model_ids = _merge_with_models_dev(fabric_slug, model_ids)
        total = len(model_ids)
        if fabric_slug in _UNCAPPED_PICKER_PROVIDERS:
            top = model_ids  # Aggregator: show full catalog regardless of max_models
        else:
            top = model_ids[:max_models] if max_models is not None else model_ids

        results.append({
            "slug": fabric_slug,
            "name": get_label(fabric_slug),
            "is_current": fabric_slug == current_provider or pid == current_provider,
            "is_user_defined": False,
            "models": top,
            "total_models": total,
            "source": "hermes",
        })
        seen_slugs.add(pid.lower())
        seen_slugs.add(fabric_slug.lower())
        _record_builtin_endpoint(fabric_slug)

    # --- 2b. Cross-check canonical provider list ---
    # Catches providers that are in CANONICAL_PROVIDERS but weren't found
    # in PROVIDER_TO_MODELS_DEV or FABRIC_OVERLAYS (keeps /model in sync
    # with `fabric model`).
    try:
        from fabric_cli.models import CANONICAL_PROVIDERS as _canon_provs
    except ImportError:
        _canon_provs = []

    for _cp in _canon_provs:
        if _cp.slug.lower() in seen_slugs:
            continue

        # Check credentials via PROVIDER_REGISTRY (auth.py)
        _cp_config = _auth_registry.get(_cp.slug)
        _cp_has_creds = False
        if _cp_config and _cp_config.api_key_env_vars:
            _cp_has_creds = any(os.environ.get(ev) for ev in _cp_config.api_key_env_vars)
        # Also check auth store and credential pool
        if not _cp_has_creds:
            try:
                from fabric_cli.auth import _load_auth_store
                _cp_store = _load_auth_store()
                _cp_providers_store = _cp_store.get("providers", {})
                if _cp_store and _cp.slug in _cp_providers_store:
                    _cp_has_creds = True
            except Exception:
                pass
        if not _cp_has_creds:
            try:
                from agent.credential_pool import load_pool
                _cp_pool = load_pool(_cp.slug)
                if _cp_pool.has_credentials():
                    _cp_has_creds = True
            except Exception:
                pass

        # Special case: aws_sdk auth (bedrock) — no API key env vars,
        # credentials come from the boto3 credential chain (env vars,
        # ~/.aws/credentials, instance roles, etc.)
        if not _cp_has_creds and _cp_config and getattr(_cp_config, "auth_type", "") == "aws_sdk":
            _cp_has_creds = _has_aws_sdk_creds_for_listing(_cp.slug)

        if not _cp_has_creds:
            continue

        # For bedrock, use live discovery so the list reflects the active
        # region (eu.*, us.*, ap.*) instead of the hardcoded us.* static list.
        if _cp_config and getattr(_cp_config, "auth_type", "") == "aws_sdk":
            try:
                _ids = cached_provider_model_ids(_cp.slug)
                _cp_model_ids = _ids if _ids else curated.get(_cp.slug, [])
            except Exception:
                _cp_model_ids = curated.get(_cp.slug, [])
        else:
            # Unified pathway — same as sections 1 and 2.
            _cp_model_ids = cached_provider_model_ids(_cp.slug)
            if not _cp_model_ids:
                _cp_model_ids = curated.get(_cp.slug, [])
        _cp_total = len(_cp_model_ids)
        _cp_top = _cp_model_ids[:max_models] if max_models is not None else _cp_model_ids

        results.append({
            "slug": _cp.slug,
            "name": _cp.label,
            "is_current": _cp.slug == current_provider,
            "is_user_defined": False,
            "models": _cp_top,
            "total_models": _cp_total,
            "source": "canonical",
        })
        seen_slugs.add(_cp.slug.lower())
        _record_builtin_endpoint(_cp.slug)

    # --- 3. User-defined endpoints from config ---
    # Track (name, base_url) of what section 3 emits so section 4 can skip
    # any overlapping ``custom_providers:`` entries.  Callers typically pass
    # both (gateway/CLI invoke ``get_compatible_custom_providers()`` which
    # merges ``providers:`` into the list) — without this, the same endpoint
    # produces two picker rows: one bare-slug ("openrouter") from section 3
    # and one "custom:openrouter" from section 4, both labelled identically.
    _section3_emitted_pairs: set = set()
    if user_providers and isinstance(user_providers, dict):
        for ep_name, ep_cfg in user_providers.items():
            if not isinstance(ep_cfg, dict):
                continue
            # Skip if this slug was already emitted (e.g. canonical provider
            # with the same name) or will be picked up by section 4.
            if ep_name.lower() in seen_slugs:
                continue
            display_name = ep_cfg.get("name", "") or ep_name
            # ``base_url`` is Fabric's canonical write key (matches
            # custom_providers and _save_custom_provider); ``api`` / ``url``
            # remain as fallbacks for hand-edited / legacy configs.
            api_url = (
                ep_cfg.get("base_url", "")
                or ep_cfg.get("api", "")
                or ep_cfg.get("url", "")
                or ""
            )
            # ``default_model`` is the legacy key; ``model`` matches what
            # custom_providers entries use, so accept either.
            default_model = ep_cfg.get("default_model", "") or ep_cfg.get("model", "")

            # Build models list from both default_model and full models array
            models_list = []
            if default_model:
                models_list.append(default_model)
            # Also include the full models list from config.
            # Fabric writes ``models:`` as a dict keyed by model id, but older
            # or hand-edited configs may use strings or ``[{id: ...}]`` rows.
            for model_id in _declared_model_ids(ep_cfg.get("models", [])):
                if model_id not in models_list:
                    models_list.append(model_id)

            # Official OpenAI API rows in providers: often have base_url but no
            # explicit models: dict — avoid a misleading zero count in /model.
            if not models_list:
                url_lower = str(api_url).strip().lower()
                if "api.openai.com" in url_lower:
                    fb = curated.get("openai") or []
                    if fb:
                        models_list = list(fb)

            # Prefer the endpoint's live /models list when discoverable,
            # unless the provider explicitly opts out via discover_models: false.
            # Policy mirrors Section 4's should_probe logic:
            # - With an api_key: always probe (user opted into the endpoint).
            # - Without an api_key but with explicit models: skip — the user
            #   is narrowing a public endpoint to a specific subset.
            # - Without an api_key AND no explicit models: probe anyway so
            #   bare-endpoint providers (local llama.cpp / Ollama servers)
            #   still show their full model catalog.
            api_key = str(ep_cfg.get("api_key", "") or "").strip()
            if not api_key:
                key_env = str(ep_cfg.get("key_env", "") or "").strip()
                api_key = os.environ.get(key_env, "").strip() if key_env else ""
            discover = ep_cfg.get("discover_models", True)
            if isinstance(discover, str):
                discover = discover.lower() not in {"false", "no", "0"}
            has_explicit_models = bool(models_list)
            _ep_url_norm = str(api_url).strip().rstrip("/").lower()
            _ep_slug_norm = str(ep_name).strip().lower()
            _ep_custom_slug_norm = custom_provider_slug(display_name).lower()
            _ep_is_current = (
                _ep_slug_norm == _current_provider_norm
                or _ep_custom_slug_norm == _current_provider_norm
                or (
                    _current_provider_norm == "custom"
                    and bool(_current_base_url_norm)
                    and _ep_url_norm == _current_base_url_norm
                )
            )
            should_probe = _can_probe_custom_provider(row_is_current=_ep_is_current) and bool(api_url) and discover and (
                bool(api_key) or not has_explicit_models
            )
            if should_probe:
                try:
                    from fabric_cli.models import fetch_api_models
                    live_models = fetch_api_models(
                        api_key,
                        api_url,
                        headers=_extra_headers_from_config(ep_cfg) or None,
                    )
                    if live_models:
                        models_list = live_models
                except Exception:
                    pass

            results.append({
                "slug": ep_name,
                "name": display_name,
                "is_current": _ep_is_current,
                "is_user_defined": True,
                "models": models_list,
                "total_models": len(models_list) if models_list else 0,
                "source": "user-config",
                "api_url": api_url,
            })
            seen_slugs.add(ep_name.lower())
            seen_slugs.add(custom_provider_slug(display_name).lower())
            _pair = (
                str(display_name).strip().lower(),
                str(api_url).strip().rstrip("/").lower(),
            )
            if _pair[0] and _pair[1]:
                _section3_emitted_pairs.add(_pair)

    # --- 3b. Active bare custom endpoint from model config ---
    # A config can still use the direct one-off form:
    #   model.provider: custom
    #   model.base_url: https://some-openai-compatible/v1
    # In that shape there is no named providers:/custom_providers row for the
    # picker to render, but the gateway only passes this current model slice to
    # list_authenticated_providers(). Surface the active endpoint explicitly so
    # /model does not look like it ignored config.yaml.
    if (
        _current_provider_norm == "custom"
        and current_base_url
        and "custom" not in seen_slugs
        and not any(
            isinstance(_cp, dict)
            and str(
                _cp.get("base_url", "")
                or _cp.get("url", "")
                or _cp.get("api", "")
            ).strip().rstrip("/").lower()
            == str(current_base_url).strip().rstrip("/").lower()
            for _cp in (custom_providers or [])
        )
    ):
        _models = [current_model] if current_model else []
        if refresh or probe_current_custom_provider:
            try:
                from fabric_cli.models import fetch_api_models

                _live_models = fetch_api_models("", str(current_base_url).strip().rstrip("/"))
                if _live_models:
                    _models = _live_models
            except Exception:
                pass
        results.append({
            "slug": "custom",
            "name": "Custom endpoint",
            "is_current": True,
            "is_user_defined": True,
            "models": _models[:max_models] if max_models is not None else _models,
            "total_models": len(_models),
            "source": "model-config",
            "api_url": str(current_base_url).strip().rstrip("/"),
        })
        seen_slugs.add("custom")

    # --- 4. Saved custom providers from config ---
    # Each ``custom_providers`` entry represents one model under a named
    # provider. Entries sharing the same endpoint, credential identity, and
    # wire protocol are grouped into a single picker row, so e.g. four Ollama
    # entries pointing at ``http://localhost:11434/v1`` with per-model display
    # names ("Ollama — GLM 5.1", "Ollama — Qwen3-coder", ...) appear as one
    # "Ollama" row with four models inside instead of four near-duplicates
    # that differ only by suffix. Same-host entries with different ``key_env``
    # or ``api_mode`` remain distinct providers.
    if custom_providers and isinstance(custom_providers, list):
        from collections import OrderedDict

        # Key by endpoint + credential identity + wire protocol instead of
        # slug: names frequently differ per model ("Ollama — X") while the
        # endpoint stays the same.  Keep same-host providers with distinct
        # env-backed credentials or API protocols separate so picker selection
        # cannot route through the wrong credential/mode pair.
        groups: "OrderedDict[tuple, dict]" = OrderedDict()
        for entry in custom_providers:
            if not isinstance(entry, dict):
                continue

            raw_name = (entry.get("name") or "").strip()
            api_url = (
                entry.get("base_url", "")
                or entry.get("url", "")
                or entry.get("api", "")
                or ""
            ).strip().rstrip("/")
            if not raw_name or not api_url:
                continue
            inline_api_key = (entry.get("api_key") or "").strip()
            key_env = (entry.get("key_env") or "").strip()
            api_key = inline_api_key or (
                os.environ.get(key_env, "").strip() if key_env else ""
            )
            api_mode = str(
                entry.get("api_mode")
                or entry.get("transport")
                or ""
            ).strip().lower()
            credential_identity = (
                inline_api_key
                if inline_api_key
                else (f"env:{key_env}" if key_env else "")
            )

            # Read discover_models from the entry (same semantics as
            # section 3: true by default, set false to keep the explicit
            # ``models:`` list instead of replacing it with live /models).
            discover = entry.get("discover_models", True)
            if isinstance(discover, str):
                discover = discover.lower() not in {"false", "no", "0"}

            # Per-provider extra_headers participate in the group identity:
            # two entries sharing (api_url, credential, api_mode) but declaring
            # different headers are distinct endpoints (e.g. different tenants
            # behind one proxy URL, routed by header) and must probe /models
            # with their own headers rather than collapsing into one row and
            # silently adopting whichever header set was seen first.
            entry_extra_headers = _extra_headers_from_config(entry)
            headers_identity = tuple(sorted(entry_extra_headers.items()))

            group_key = (api_url, credential_identity, api_mode, headers_identity)
            if group_key not in groups:
                # Strip per-model suffix so "Ollama — GLM 5.1" becomes
                # "Ollama" for the grouped row. Em dash is the convention
                # Fabric's own writer uses; a hyphen variant is accepted
                # for hand-edited configs.
                display_name = raw_name
                for sep in ("—", " - "):
                    if sep in display_name:
                        display_name = display_name.split(sep)[0].strip()
                        break
                if not display_name:
                    display_name = raw_name
                slug = custom_provider_slug(display_name)
                groups[group_key] = {
                    "slug": slug,
                    "name": display_name,
                    "api_url": api_url,
                    "api_key": api_key,
                    "models": [],
                    "discover_models": discover,
                    "extra_headers": entry_extra_headers,
                }
            else:
                if api_key and not groups[group_key].get("api_key"):
                    groups[group_key]["api_key"] = api_key
                # extra_headers is part of group_key, so every entry in this
                # group already carries identical headers — nothing to merge.
                # If any entry in this group opts out of discovery,
                # honour that for the whole grouped row.
                if not discover:
                    groups[group_key]["discover_models"] = False

            # The singular ``model:`` field only holds the currently
            # active model. Fabric's own writer (main.py::_save_custom_provider)
            # stores every configured model as a dict under ``models:``;
            # downstream readers (agent/models_dev.py, gateway/run.py,
            # run_agent.py, fabric_cli/config.py) already consume that dict.
            default_model = (entry.get("model") or "").strip()
            if default_model and default_model not in groups[group_key]["models"]:
                groups[group_key]["models"].append(default_model)

            for model_id in _declared_model_ids(entry.get("models", {})):
                if model_id not in groups[group_key]["models"]:
                    groups[group_key]["models"].append(model_id)

        _section4_emitted_slugs: set = set()
        _current_base_url_group_count = sum(
            1
            for _grp in groups.values()
            if _current_base_url_norm
            and str(_grp["api_url"]).strip().rstrip("/").lower() == _current_base_url_norm
        )
        for grp in groups.values():
            api_url = grp["api_url"]
            api_key = grp.get("api_key", "")
            slug = grp["slug"]
            # If the slug is already claimed by a built-in / overlay /
            # user-provider row (sections 1-3), skip this custom group
            # to avoid shadowing a real provider.
            if slug.lower() in seen_slugs and slug.lower() not in _section4_emitted_slugs:
                continue
            # If a prior section-4 group already used this slug (two custom
            # endpoints with the same cleaned name — e.g. two OpenAI-
            # compatible gateways named identically with different keys),
            # append a counter so both rows stay visible in the picker.
            if slug.lower() in _section4_emitted_slugs:
                base_slug = slug
                n = 2
                while f"{base_slug}-{n}".lower() in seen_slugs:
                    n += 1
                slug = f"{base_slug}-{n}"
                grp["slug"] = slug
            # Skip if section 3 already emitted this endpoint under its
            # ``providers:`` dict key — matches on (display_name, base_url).
            # Prevents two picker rows labelled identically when callers
            # pass both ``user_providers`` and a compatibility-merged
            # ``custom_providers`` list.
            _pair_key = (
                str(grp["name"]).strip().lower(),
                str(grp["api_url"]).strip().rstrip("/").lower(),
            )
            if _pair_key[0] and _pair_key[1] and _pair_key in _section3_emitted_pairs:
                continue
            # Skip if a built-in row (sections 1/2/2b) already represents this
            # endpoint. Fixes #16970: a user-defined "my-dashscope" pointing at
            # https://coding-intl.dashscope.aliyuncs.com/v1 duplicates the
            # built-in alibaba-coding-plan row whenever DASHSCOPE_API_KEY is
            # set. The built-in row carries the curated model list, correct
            # auth wiring, and canonical slug — keep it and hide the shadow.
            _grp_url_norm = _pair_key[1]
            if _grp_url_norm and _grp_url_norm in _builtin_endpoints:
                continue
            # Live model discovery from custom provider endpoints (matches
            # Section 3 behavior for user ``providers:`` entries).
            # Also probes when no api_key is set (e.g. local llama.cpp /
            # Ollama servers) — the /models endpoint often works without
            # auth.  The CLI's _model_flow_named_custom always probes, so
            # the Telegram/Discord picker should do the same for parity.
            # Live-discovery policy:
            # - With an api_key, the user has explicitly opted into the
            #   endpoint and live /models is the source of truth — replace
            #   the (possibly partial) ``models:`` subset configured for
            #   context-length overrides with the full live catalog.
            #   This is the Bifrost / aggregator-gateway case.
            # - Without an api_key but with an explicit ``models:`` list
            #   (or top-level ``model:``), the user is narrowing a public
            #   endpoint to a specific subset (e.g. ollama.com /v1/models
            #   returns 35 models but the user only wants 4). Preserve the
            #   explicit list and skip live discovery.
            # - Without an api_key AND no explicit models, fall through to
            #   live discovery so bare-endpoint custom providers (local
            #   llama.cpp / Ollama servers) still appear populated.
            # - When discover_models: false is set, skip live discovery and
            #   keep the explicit ``models:`` list regardless of whether an
            #   api_key is present. This supports endpoints that expose a
            #   full aggregator catalog via /models but only serve a subset
            #   (parity with section 3's user ``providers:`` behaviour).
            _grp_is_current = slug.lower() == _current_provider_norm or (
                _current_provider_norm == "custom"
                and bool(_current_base_url_norm)
                and _grp_url_norm == _current_base_url_norm
                and _current_base_url_group_count == 1
            )
            should_probe = (
                _can_probe_custom_provider(row_is_current=_grp_is_current)
                and bool(api_url)
                and (bool(api_key) or not grp["models"])
                and grp.get("discover_models", True)
            )
            if should_probe:
                try:
                    from fabric_cli.models import fetch_api_models

                    live_models = fetch_api_models(
                        api_key,
                        api_url,
                        headers=grp.get("extra_headers") or None,
                    )
                    if live_models:
                        grp["models"] = live_models
                        grp["total_models"] = len(live_models)
                except Exception:
                    pass
            results.append({
                "slug": slug,
                "name": grp["name"],
                "is_current": _grp_is_current,
                "is_user_defined": True,
                "models": grp["models"],
                "total_models": len(grp["models"]),
                "source": "user-config",
                "api_url": grp["api_url"],
            })
            seen_slugs.add(slug.lower())
            _section4_emitted_slugs.add(slug.lower())

    # Surface a custom / uncurated model the user selected via the CLI.
    # Each row's model list is its curated/live catalog, so a model the user set
    # with `/model <provider>/<uncurated-name>` would otherwise be invisible in
    # every picker — the main model picker AND the MoA reference/aggregator slot
    # pickers, which read these same rows. Inject it at the front of the current
    # provider's row (matched by slug) so it is selectable and shown. Done as a
    # post-pass so it covers every provider section uniformly, regardless of
    # which branch emitted the row.
    if current_model:
        for _row in results:
            if not _row.get("is_current"):
                continue
            _models = _row.get("models") or []
            if current_model not in _models:
                _row["models"] = [current_model, *_models]
                _row["total_models"] = _row.get("total_models", len(_models)) + 1
            break

    # Sort: current provider first, then by model count descending
    results.sort(key=lambda r: (not r["is_current"], -r["total_models"]))

    return results


def _prepend_moa_picker_provider(providers: List[dict], current_provider: str = "") -> List[dict]:
    """Add the virtual MoA provider row used by interactive model pickers.

    ``list_authenticated_providers()`` only returns real/auth-backed providers.
    The CLI model inventory adds MoA separately so named presets appear next to
    normal providers; gateway pickers call ``list_picker_providers()`` directly,
    so they need the same virtual row here. Reuse the inventory's single row
    builder so the row shape stays defined in one place.
    """
    try:
        from fabric_cli.inventory import _moa_provider_row

        moa_row = _moa_provider_row(current_provider)
        if moa_row is None:
            return providers
        return [moa_row] + [p for p in providers if str(p.get("slug", "")).lower() != "moa"]
    except Exception:
        return providers


def list_picker_providers(
    current_provider: str = "",
    current_base_url: str = "",
    user_providers: dict = None,
    custom_providers: list | None = None,
    max_models: int | None = None,
    current_model: str = "",
    include_moa: bool = False,
) -> List[dict]:
    """Interactive-picker variant of :func:`list_authenticated_providers`.

    Post-processes the base list so the ``/model`` picker (Telegram/Discord
    inline keyboards) only surfaces models that are actually callable in the
    current install:

    - OpenRouter's model list is replaced with the output of
      :func:`fabric_cli.models.fetch_openrouter_models`, which filters the
      curated ``OPENROUTER_MODELS`` snapshot against the live OpenRouter
      catalog.  IDs the live catalog no longer carries drop out, so the
      picker never offers a model the user can't call.
    - Provider rows whose model list ends up empty are dropped, except
      custom endpoints (``is_user_defined=True`` with an ``api_url``) where
      the user may supply their own model set through config.

    All other providers and metadata fields are passed through unchanged.
    The typed ``/model <name>`` path is unaffected -- only the interactive
    picker payload is narrowed.
    """
    from fabric_cli.models import fetch_openrouter_models

    providers = list_authenticated_providers(
        current_provider=current_provider,
        current_base_url=current_base_url,
        user_providers=user_providers,
        custom_providers=custom_providers,
        max_models=max_models,
        current_model=current_model,
    )
    if include_moa:
        providers = _prepend_moa_picker_provider(providers, current_provider=current_provider)

    filtered: List[dict] = []
    for p in providers:
        slug = str(p.get("slug", "")).lower()
        if slug == "openrouter":
            try:
                live = fetch_openrouter_models()
                live_ids = [mid for mid, _ in live]
            except Exception:
                live_ids = list(p.get("models", []))
            p = dict(p)
            p["models"] = live_ids[:max_models] if max_models is not None else live_ids
            p["total_models"] = len(live_ids)

        has_models = bool(p.get("models"))
        is_custom_endpoint = bool(p.get("is_user_defined")) and bool(p.get("api_url"))
        if not has_models and not is_custom_endpoint:
            continue
        filtered.append(p)

    return filtered
