"""
Status command for the Fabric CLI.

Shows the status of all Fabric components.
"""

import os
import sys
import subprocess  # noqa: F401 — re-exported for tests that monkeypatch status.subprocess to guard against regressions
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()

from fabric_cli.colors import Colors, color
from fabric_cli.config import get_env_path, get_env_value, get_fabric_home, load_config
from fabric_cli.fabric_capabilities import (
    FABRIC_GATEWAY_PLATFORMS,
    fabric_model_provider_visible,
    filter_fabric_keys,
)
from fabric_cli.egress_status import build_egress_status_snapshot
from fabric_constants import OPENROUTER_MODELS_URL


# Lazy compatibility seams: status tests and embedders historically patch
# these module attributes. Keeping small forwarding functions preserves that
# surface without importing provider, OAuth, account, or tool-gateway modules
# before the egress mode has selected the online-only branch.
def resolve_requested_provider(*args, **kwargs):
    from fabric_cli.runtime_provider import resolve_requested_provider as _impl

    return _impl(*args, **kwargs)


def resolve_provider(*args, **kwargs):
    from fabric_cli.auth import resolve_provider as _impl

    return _impl(*args, **kwargs)


def provider_label(*args, **kwargs):
    from fabric_cli.models import provider_label as _impl

    return _impl(*args, **kwargs)


def get_nous_portal_account_info(*args, **kwargs):
    from fabric_cli.nous_account import get_nous_portal_account_info as _impl

    return _impl(*args, **kwargs)


def format_nous_portal_entitlement_message(*args, **kwargs):
    from fabric_cli.nous_account import (
        format_nous_portal_entitlement_message as _impl,
    )

    return _impl(*args, **kwargs)


def get_nous_subscription_features(*args, **kwargs):
    from fabric_cli.nous_subscription import get_nous_subscription_features as _impl

    return _impl(*args, **kwargs)


def managed_nous_tools_enabled(*args, **kwargs):
    from tools.tool_backend_helpers import managed_nous_tools_enabled as _impl

    return _impl(*args, **kwargs)


def check_mark(ok: bool) -> str:
    if ok:
        return color("✓", Colors.GREEN)
    return color("✗", Colors.RED)

def redact_key(key: str) -> str:
    """Redact an API key for display.

    Thin wrapper over :func:`agent.redact.mask_secret`. Preserves the
    "(not set)" placeholder in dim color to match ``fabric config``'s
    output (previously this variant was missing the DIM color —
    consolidated via PR that also introduced ``mask_secret``).
    """
    from agent.redact import mask_secret
    return mask_secret(key, empty=color("(not set)", Colors.DIM))


def _format_iso_timestamp(value) -> str:
    """Format ISO timestamps for status output, converting to local timezone."""
    if not value or not isinstance(value, str):
        return "(unknown)"
    from datetime import datetime, timezone
    text = value.strip()
    if not text:
        return "(unknown)"
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return value
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def _configured_model_label(config: dict, *, apply_catalog: bool = True) -> str:
    """Return the configured default model from config.yaml."""
    model_cfg = config.get("model")
    if isinstance(model_cfg, dict):
        provider = str(model_cfg.get("provider") or "").strip()
        model = (model_cfg.get("default") or model_cfg.get("name") or "").strip()
    elif isinstance(model_cfg, str):
        model = model_cfg.strip()
    else:
        model = ""
    return model or "(not set)"


_PROVIDER_VISIBILITY_ALIASES = {
    "openai": "openai-api",
    "codex": "openai-codex",
    "grok": "xai",
    "xai-api": "xai",
    "qwen": "qwen-oauth",
}


def _known_provider_slugs() -> set[str]:
    """Load canonical provider ids only on the unrestricted online path."""
    from fabric_cli.models import CANONICAL_PROVIDERS

    return {entry.slug for entry in CANONICAL_PROVIDERS}


def _provider_visible_for_status(slug: str) -> bool:
    """Hide known off-catalog providers while preserving custom endpoints."""
    normalized = str(slug or "").strip().lower()
    normalized = _PROVIDER_VISIBILITY_ALIASES.get(normalized, normalized)
    if not normalized or normalized in {"auto", "custom"} or normalized.startswith("custom:"):
        return True
    if normalized not in _known_provider_slugs():
        return True
    return fabric_model_provider_visible(normalized)


def _configured_provider_id(config: dict) -> str:
    """Return the unexpanded provider id without auth/runtime resolution."""

    model_cfg = config.get("model") if isinstance(config, dict) else None
    if isinstance(model_cfg, dict):
        provider = model_cfg.get("provider")
        if isinstance(provider, str) and provider.strip():
            return provider.strip()
    return "(not set)"


def _effective_provider_label() -> str:
    """Return the provider label matching current CLI runtime resolution."""

    # Keep provider/auth imports off the restricted status import path. This
    # helper is called only for online mode; local_ai and unavailable policy
    # render directly from the unexpanded route-policy snapshot.
    from fabric_cli.auth import AuthError

    requested = resolve_requested_provider()
    try:
        effective = resolve_provider(requested)
    except AuthError:
        effective = requested or "auto"

    if effective == "openrouter":
        # A custom endpoint may be configured either in config.yaml
        # (model.base_url — the canonical location; the runtime treats
        # config.yaml as the single source of truth) or via the legacy
        # OPENAI_BASE_URL env var. Either way, labeling it "OpenRouter"
        # is misleading (#3296).
        config_base_url = ""
        try:
            model_cfg = load_config().get("model")
            if isinstance(model_cfg, dict):
                config_base_url = (model_cfg.get("base_url") or "").strip()
        except Exception:
            pass
        if config_base_url or get_env_value("OPENAI_BASE_URL"):
            effective = "custom"

    if not _provider_visible_for_status(effective):
        return "Configured provider (not in catalog)"
    return provider_label(effective)


from fabric_constants import is_termux as _is_termux


def _show_ollama_deep_status(config: dict) -> None:
    """Render one sanitized Ollama readiness snapshot for explicit deep status."""

    try:
        from fabric_cli.ollama_runtime import (
            build_ollama_readiness_snapshot,
            is_ollama_readiness_candidate,
        )

        if not is_ollama_readiness_candidate(config):
            return
        snapshot = build_ollama_readiness_snapshot(
            config=config,
            include_resources=True,
        )
    except Exception:
        # Deep diagnostics are advisory and must never break the rest of
        # ``fabric status`` or print a raw exception that could include a URL,
        # credential, response body, or internal host detail.
        print(f"  Ollama:      {check_mark(False)} readiness check failed safely")
        return

    data = snapshot.to_dict()
    if not data.get("applicable"):
        # A local custom endpoint can be LM Studio/vLLM/llama.cpp. Do not label
        # it as a broken Ollama installation when protocol evidence says no.
        return

    state = str(data.get("state") or "unknown")
    if state == "ready":
        marker = check_mark(True)
    elif state == "degraded":
        marker = color("!", Colors.YELLOW)
    else:
        marker = check_mark(False)
    print(f"  Ollama:      {marker} {state.replace('_', ' ')}")

    model = str(data.get("model") or "")
    if model:
        print(f"    Model:      {model}")
    context = data.get("effective_context_length")
    if isinstance(context, int) and not isinstance(context, bool):
        print(
            f"    Context:    {context:,} tokens "
            f"({data.get('context_state', 'unknown')}, {data.get('context_source', 'unknown')})"
        )
    else:
        print(f"    Context:    {data.get('context_state', 'unknown')}")
    print(f"    Tools:      {data.get('tools_state', 'unknown')}")
    print(f"    Vision:     {data.get('vision_state', 'unknown')}")

    resource_state = str(data.get("resource_state") or "unknown")
    if resource_state != "unknown":
        resource = resource_state.replace("_", " ")
        vram = data.get("loaded_vram_bytes")
        if isinstance(vram, int) and not isinstance(vram, bool):
            resource += f" ({vram:,} bytes in VRAM)"
        print(f"    Resources:  {resource}")

    for issue in data.get("issues") or []:
        if isinstance(issue, dict) and issue.get("message"):
            print(f"    {str(issue.get('severity') or 'info').title()}: {issue['message']}")


def _show_deep_checks(config: dict) -> None:
    """Run opt-in network/service diagnostics for the active profile."""

    print()
    print(color("◆ Deep Checks", Colors.CYAN, Colors.BOLD))
    _show_ollama_deep_status(config)

    # Check OpenRouter connectivity only when the active profile owns a key.
    openrouter_key = get_env_value("OPENROUTER_API_KEY") or ""
    if openrouter_key:
        try:
            import httpx

            response = httpx.get(
                OPENROUTER_MODELS_URL,
                headers={"Authorization": f"Bearer {openrouter_key}"},
                timeout=10,
            )
            ok = response.status_code == 200
            detail = "reachable" if ok else f"error ({response.status_code})"
            print(f"  OpenRouter:   {check_mark(ok)} {detail}")
        except Exception:
            # Never print a raw exception: transports can echo request URLs,
            # proxy credentials, certificate paths, or response bodies.
            print(f"  OpenRouter:   {check_mark(False)} unreachable")

    # Check the local gateway port. This is informational: an available port
    # is not itself an error when the gateway is intentionally stopped.
    try:
        import socket

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(("127.0.0.1", 18789))
        sock.close()
        print(f"  Port 18789:   {'in use' if result == 0 else 'available'}")
    except OSError:
        pass


def _maybe_show_deep_checks(args, config: dict) -> None:
    """Keep ordinary ``fabric status`` free of deep live probes."""

    if getattr(args, "deep", False):
        _show_deep_checks(config)


def show_status(args):
    """Show status of all Fabric components."""

    print()
    print(color("┌─────────────────────────────────────────────────────────┐", Colors.CYAN))
    try:
        from fabric_cli.fabric_brand import status_header

        _hdr = status_header()
    except Exception:
        _hdr = f"│{'Fabric Status':^57}│"
    print(color(_hdr, Colors.CYAN))
    print(color("└─────────────────────────────────────────────────────────┘", Colors.CYAN))

    # =========================================================================
    # Environment
    # =========================================================================
    print()
    print(color("◆ Environment", Colors.CYAN, Colors.BOLD))
    print(f"  Project:      {PROJECT_ROOT}")
    print(f"  Python:       {sys.version.split()[0]}")

    env_path = get_env_path()
    print(f"  .env file:    {check_mark(env_path.exists())} {'exists' if env_path.exists() else 'not found'}")

    egress = build_egress_status_snapshot()
    runtime_blocked = not bool(egress.get("available"))
    local_ai_status = egress.get("mode") == "local_ai"

    if runtime_blocked:
        # Do not expand provider config, read credentials, refresh OAuth, load
        # plugins, or run a live probe while the process-wide contract is
        # unavailable or malformed. This is the intentionally safe repair view.
        config = {}
        print("  Model:        (not inspected while runtime is blocked)")
        print("  Provider:     (not inspected while runtime is blocked)")
    elif local_ai_status:
        # The ordinary config loader expands ${...} and the provider label
        # resolver may refresh OAuth. Restricted status uses only the strict,
        # unexpanded route-policy view and leaves all remote auth untouched.
        try:
            from fabric_cli.config import load_egress_policy_config

            config = load_egress_policy_config()
        except Exception:
            config = {}
        print(f"  Model:        {_configured_model_label(config, apply_catalog=False)}")
        print(f"  Provider:     {_configured_provider_id(config)}")
    else:
        try:
            config = load_config()
        except Exception:
            config = {}

        print(f"  Model:        {_configured_model_label(config)}")
        print(f"  Provider:     {_effective_provider_label()}")

    print()
    print(color("◆ Network & AI Egress", Colors.CYAN, Colors.BOLD))
    mode = str(egress.get("mode") or "unknown")
    state = str(egress.get("status") or "unavailable")
    print(f"  Mode:         {mode}")
    print(f"  Enforcement:  {check_mark(bool(egress.get('available')))} {state}")
    print(f"  Scope:        {egress.get('scope') or 'unknown'}")
    allowed_count = egress.get("allowed_private_cidr_count")
    if mode == "local_ai" and isinstance(allowed_count, int):
        print(f"  Private CIDRs:{allowed_count:>3} explicitly approved")
    if egress.get("reason"):
        print(f"  Reason:       {egress['reason']}")

    if runtime_blocked:
        print()
        print(color("◆ Repair", Colors.CYAN, Colors.BOLD))
        print("  Runtime/network checks were skipped before credentials or plugins loaded.")
        print("  Inspect config: fabric config")
        print("  Diagnose:      fabric doctor")
        print("  Choose a currently available mode: online or local_ai")
        return

    if local_ai_status:
        print()
        print(color("◆ Local AI Diagnostics", Colors.CYAN, Colors.BOLD))
        print("  Remote credential, OAuth, provider-catalog, account, and plugin probes were skipped.")
        if getattr(args, "deep", False):
            _show_ollama_deep_status(config)
        else:
            print("  Run `fabric status --deep` for a bounded probe of the authorized local endpoint.")
        return

    # =========================================================================
    # API Keys
    # =========================================================================
    print()
    print(color("◆ API Keys", Colors.CYAN, Colors.BOLD))

    # Values may be a single env var name (str) or a tuple of alternates (first found wins).
    keys: list[tuple[str, str | tuple[str, ...], str | None]] = [
        ("OpenRouter", "OPENROUTER_API_KEY", "openrouter"),
        ("OpenAI", "OPENAI_API_KEY", "openai-api"),
        ("Anthropic", "ANTHROPIC_API_KEY", "anthropic"),
        ("Google / Gemini", ("GOOGLE_API_KEY", "GEMINI_API_KEY"), "gemini"),
        ("DeepSeek", "DEEPSEEK_API_KEY", "deepseek"),
        ("xAI / Grok", "XAI_API_KEY", "xai"),
        ("NVIDIA NIM", "NVIDIA_API_KEY", "nvidia"),
        ("Z.AI / GLM", "GLM_API_KEY", "zai"),
        ("Kimi", "KIMI_API_KEY", "kimi-coding"),
        ("StepFun Step Plan", "STEPFUN_API_KEY", "stepfun"),
        ("MiniMax", "MINIMAX_API_KEY", "minimax"),
        ("MiniMax-CN", "MINIMAX_CN_API_KEY", "minimax-cn"),
        ("Firecrawl", "FIRECRAWL_API_KEY", None),
        ("Tavily", "TAVILY_API_KEY", None),
        ("Browser Use", "BROWSER_USE_API_KEY", None),
        ("Browserbase", "BROWSERBASE_API_KEY", None),
        ("FAL", "FAL_KEY", None),
        ("ElevenLabs", "ELEVENLABS_API_KEY", None),
        ("GitHub", "GITHUB_TOKEN", None),
    ]

    def _resolve_env(env_ref) -> str:
        """Return first non-empty env var value from a str or tuple of names."""
        if isinstance(env_ref, tuple):
            for candidate in env_ref:
                v = get_env_value(candidate) or ""
                if v:
                    return v
            return ""
        return get_env_value(env_ref) or ""

    for name, env_ref, provider_slug in keys:
        if provider_slug and not fabric_model_provider_visible(provider_slug):
            continue
        # Anthropic already has a dedicated lookup below; keep that as the
        # single source of truth (it also resolves pooled API keys), skip here
        # so we don't print two "Anthropic" rows.
        if name == "Anthropic":
            continue
        value = _resolve_env(env_ref)
        has_key = bool(value)
        display = redact_key(value)
        print(f"  {name:<12}  {check_mark(has_key)} {display}")

    if fabric_model_provider_visible("anthropic"):
        from fabric_cli.auth import get_anthropic_key
        anthropic_value = get_anthropic_key()
        anthropic_display = redact_key(anthropic_value)
        print(f"  {'Anthropic':<12}  {check_mark(bool(anthropic_value))} {anthropic_display}")

    # =========================================================================
    # Auth Providers (OAuth)
    # =========================================================================
    print()
    print(color("◆ Auth Providers", Colors.CYAN, Colors.BOLD))

    def _visible_auth_status(provider_slug: str, getter_name: str) -> dict:
        """Call an auth probe only when its provider is customer-visible."""
        if not fabric_model_provider_visible(provider_slug):
            return {}
        try:
            from fabric_cli import auth as auth_module

            return getattr(auth_module, getter_name)() or {}
        except Exception:
            return {}

    show_nous = fabric_model_provider_visible("nous")
    show_codex = fabric_model_provider_visible("openai-codex")
    show_qwen = fabric_model_provider_visible("qwen-oauth")
    show_minimax = fabric_model_provider_visible("minimax-oauth")
    show_xai_oauth = fabric_model_provider_visible("xai-oauth")

    nous_status = _visible_auth_status("nous", "get_nous_auth_status")
    codex_status = _visible_auth_status("openai-codex", "get_codex_auth_status")
    qwen_status = _visible_auth_status("qwen-oauth", "get_qwen_auth_status")
    minimax_status = _visible_auth_status("minimax-oauth", "get_minimax_oauth_auth_status")

    nous_account_info = None
    if show_nous and (
        nous_status.get("logged_in")
        or nous_status.get("access_token")
        or nous_status.get("portal_base_url")
        or nous_status.get("inference_credential_present")
        or nous_status.get("error_code")
    ):
        try:
            nous_account_info = get_nous_portal_account_info()
        except Exception:
            nous_account_info = None

    nous_logged_in = bool(
        nous_status.get("logged_in")
        or (nous_account_info and nous_account_info.logged_in)
    )
    nous_inference_present = bool(
        nous_status.get("inference_credential_present")
        or (nous_account_info and nous_account_info.inference_credential_present)
    )
    nous_error = nous_status.get("error")
    if show_nous:
        if nous_logged_in:
            nous_label = "logged in"
        elif nous_inference_present:
            nous_label = "not logged in (Nous inference key configured)"
        else:
            nous_label = (
                "not logged in (run: fabric portal "
                "--client-id <registered-client-id>)"
            )
        print(
            f"  {'Nous Portal':<12}  {check_mark(nous_logged_in)} "
            f"{nous_label}"
        )
        portal_url = nous_status.get("portal_base_url") or "(unknown)"
        inference_url = (
            nous_status.get("inference_base_url")
            or (nous_account_info.inference_base_url if nous_account_info else None)
        )
        access_exp = _format_iso_timestamp(nous_status.get("access_expires_at"))
        key_exp = _format_iso_timestamp(nous_status.get("agent_key_expires_at"))
        refresh_label = "yes" if nous_status.get("has_refresh_token") else "no"
        if nous_logged_in or portal_url != "(unknown)" or nous_error:
            print(f"    Portal URL: {portal_url}")
        if nous_inference_present and inference_url:
            print(f"    Inference:  {inference_url}")
        if nous_logged_in or nous_status.get("access_expires_at"):
            print(f"    Access exp: {access_exp}")
        if nous_logged_in or nous_inference_present or nous_status.get("agent_key_expires_at"):
            print(f"    Key exp:    {key_exp}")
        if nous_logged_in or nous_status.get("has_refresh_token"):
            print(f"    Refresh:    {refresh_label}")
        if nous_error:
            print(f"    Error:      {nous_error}")

    codex_logged_in = bool(codex_status.get("logged_in"))
    if show_codex:
        print(
            f"  {'OpenAI Codex':<12}  {check_mark(codex_logged_in)} "
            f"{'logged in' if codex_logged_in else 'not logged in (run: fabric model)'}"
        )
        codex_auth_file = codex_status.get("auth_store")
        if codex_auth_file:
            print(f"    Auth file:  {codex_auth_file}")
        codex_last_refresh = _format_iso_timestamp(codex_status.get("last_refresh"))
        if codex_status.get("last_refresh"):
            print(f"    Refreshed:  {codex_last_refresh}")
        if codex_status.get("error") and not codex_logged_in:
            print(f"    Error:      {codex_status.get('error')}")

    qwen_logged_in = bool(qwen_status.get("logged_in"))
    if show_qwen:
        print(
            f"  {'Qwen OAuth':<12}  {check_mark(qwen_logged_in)} "
            f"{'logged in' if qwen_logged_in else 'not logged in (run: qwen auth qwen-oauth)'}"
        )
        qwen_auth_file = qwen_status.get("auth_file")
        if qwen_auth_file:
            print(f"    Auth file:  {qwen_auth_file}")
        qwen_exp = qwen_status.get("expires_at_ms")
        if qwen_exp:
            from datetime import datetime, timezone
            print(f"    Access exp: {datetime.fromtimestamp(int(qwen_exp) / 1000, tz=timezone.utc).isoformat()}")
        if qwen_status.get("error") and not qwen_logged_in:
            print(f"    Error:      {qwen_status.get('error')}")

    minimax_logged_in = bool(minimax_status.get("logged_in"))
    if show_minimax:
        print(
            f"  {'MiniMax OAuth':<12}  {check_mark(minimax_logged_in)} "
            f"{'logged in' if minimax_logged_in else 'not logged in (run: fabric auth add minimax-oauth)'}"
        )
        minimax_region = minimax_status.get("region")
        if minimax_logged_in and minimax_region:
            print(f"    Region:     {minimax_region}")
        minimax_exp = minimax_status.get("expires_at")
        if minimax_exp:
            print(f"    Access exp: {minimax_exp}")
        if minimax_status.get("error") and not minimax_logged_in:
            print(f"    Error:      {minimax_status.get('error')}")

    # xAI OAuth — separate try/except so an import failure here cannot
    # disrupt the already-printed Nous/Codex/Qwen/MiniMax rows above.
    xai_oauth_status = _visible_auth_status("xai-oauth", "get_xai_oauth_auth_status")

    xai_oauth_logged_in = bool(xai_oauth_status.get("logged_in"))
    if show_xai_oauth:
        print(
            f"  {'xAI OAuth':<12}  {check_mark(xai_oauth_logged_in)} "
            f"{'logged in' if xai_oauth_logged_in else 'not logged in (run: fabric auth add xai-oauth)'}"
        )
        xai_auth_file = xai_oauth_status.get("auth_store")
        if xai_auth_file:
            print(f"    Auth file:  {xai_auth_file}")
        if xai_oauth_status.get("last_refresh"):
            print(f"    Refreshed:  {_format_iso_timestamp(xai_oauth_status.get('last_refresh'))}")
        if xai_oauth_status.get("error") and not xai_oauth_logged_in:
            print(f"    Error:      {xai_oauth_status.get('error')}")

    # =========================================================================
    # Nous Subscription Features
    # =========================================================================
    if show_nous and managed_nous_tools_enabled():
        features = get_nous_subscription_features(config)
        print()
        print(color("◆ Nous Tool Gateway", Colors.CYAN, Colors.BOLD))
        if not features.nous_auth_present:
            print("  Nous Portal   ✗ not logged in")
        else:
            print("  Nous Portal   ✓ managed tools available")
        for feature in features.items():
            if feature.managed_by_nous:
                state = "active via Nous subscription"
            elif feature.active:
                current = feature.current_provider or "configured provider"
                state = f"active via {current}"
            elif feature.included_by_default and features.nous_auth_present:
                state = "included by subscription, not currently selected"
            elif feature.key == "modal" and features.nous_auth_present:
                state = "available via subscription (optional)"
            else:
                state = "not configured"
            print(f"  {feature.label:<15} {check_mark(feature.available or feature.active or feature.managed_by_nous)} {state}")
    elif show_nous and (nous_logged_in or nous_inference_present):
        # Nous OAuth without entitlement, or an opaque inference key without
        # Portal account information, cannot enable the Tool Gateway.
        print()
        print(color("◆ Nous Tool Gateway", Colors.CYAN, Colors.BOLD))
        message = format_nous_portal_entitlement_message(
            nous_account_info,
            capability="managed web, image, TTS, STT, browser, and Modal tools",
        )
        if message:
            for line in message.splitlines():
                print(f"  {line}")

    # =========================================================================
    # API-Key Providers
    # =========================================================================
    apikey_providers = [
        ("zai", "Z.AI / GLM", ("GLM_API_KEY", "ZAI_API_KEY", "Z_AI_API_KEY")),
        ("kimi-coding", "Kimi / Moonshot", ("KIMI_API_KEY",)),
        ("stepfun", "StepFun Step Plan", ("STEPFUN_API_KEY",)),
        ("minimax", "MiniMax", ("MINIMAX_API_KEY",)),
        ("minimax-cn", "MiniMax (China)", ("MINIMAX_CN_API_KEY",)),
    ]
    visible_apikey_providers = [
        row for row in apikey_providers if fabric_model_provider_visible(row[0])
    ]
    if visible_apikey_providers:
        print()
        print(color("◆ API-Key Providers", Colors.CYAN, Colors.BOLD))
    for provider_slug, pname, env_vars in visible_apikey_providers:
        key_val = ""
        for ev in env_vars:
            key_val = get_env_value(ev) or ""
            if key_val:
                break
        configured = bool(key_val)
        label = "configured" if configured else "not configured (run: fabric model)"
        print(f"  {pname:<16} {check_mark(configured)} {label}")

    # LM Studio reachability — only probe when it's the active provider so
    # users with foreign configs don't see noise. Auth rejection vs. silent
    # empty list is the most common LM Studio support case.
    if _effective_provider_label() == "LM Studio":
        from fabric_cli.auth import AuthError
        from fabric_cli.models import probe_lmstudio_models
        model_cfg = config.get("model")
        base = (model_cfg.get("base_url") if isinstance(model_cfg, dict) else None) or get_env_value("LM_BASE_URL") or "http://127.0.0.1:1234/v1"
        try:
            models = probe_lmstudio_models(api_key=get_env_value("LM_API_KEY") or "", base_url=base, timeout=1.5)
            if models is None:
                ok, msg = False, f"unreachable at {base}"
            else:
                ok, msg = True, f"reachable ({len(models)} model(s)) at {base}"
        except AuthError:
            ok, msg = False, "auth rejected — set LM_API_KEY"
        print(f"  {'LM Studio':<16} {check_mark(ok)} {msg}")

    # =========================================================================
    # Terminal Configuration
    # =========================================================================
    print()
    print(color("◆ Terminal Backend", Colors.CYAN, Colors.BOLD))

    terminal_cfg = config.get("terminal", {}) if isinstance(config.get("terminal"), dict) else {}
    terminal_env = os.getenv("TERMINAL_ENV", "")
    if not terminal_env:
        terminal_env = terminal_cfg.get("backend", "local")
    print(f"  Backend:      {terminal_env}")

    if terminal_env == "ssh":
        ssh_host = os.getenv("TERMINAL_SSH_HOST", "")
        ssh_user = os.getenv("TERMINAL_SSH_USER", "")
        print(f"  SSH Host:     {ssh_host or '(not set)'}")
        print(f"  SSH User:     {ssh_user or '(not set)'}")
    elif terminal_env == "docker":
        docker_image = os.getenv("TERMINAL_DOCKER_IMAGE", "python:3.11-slim")
        print(f"  Docker Image: {docker_image}")
    elif terminal_env == "daytona":
        daytona_image = os.getenv("TERMINAL_DAYTONA_IMAGE", "nikolaik/python-nodejs:python3.11-nodejs20")
        print(f"  Daytona Image: {daytona_image}")

    sudo_password = os.getenv("SUDO_PASSWORD", "")
    print(f"  Sudo:         {check_mark(bool(sudo_password))} {'enabled' if sudo_password else 'disabled'}")

    # =========================================================================
    # Messaging Platforms
    # =========================================================================
    print()
    print(color("◆ Messaging Platforms", Colors.CYAN, Colors.BOLD))

    platforms = [
        ("telegram", "Telegram", ("TELEGRAM_BOT_TOKEN", "TELEGRAM_HOME_CHANNEL")),
        ("discord", "Discord", ("DISCORD_BOT_TOKEN", "DISCORD_HOME_CHANNEL")),
        ("whatsapp", "WhatsApp", ("WHATSAPP_ENABLED", None)),
        ("signal", "Signal", ("SIGNAL_HTTP_URL", "SIGNAL_HOME_CHANNEL")),
        ("slack", "Slack", ("SLACK_BOT_TOKEN", None)),
        ("email", "Email", ("EMAIL_ADDRESS", "EMAIL_HOME_ADDRESS")),
        ("sms", "SMS", ("TWILIO_ACCOUNT_SID", "SMS_HOME_CHANNEL")),
        ("dingtalk", "DingTalk", ("DINGTALK_CLIENT_ID", None)),
        ("feishu", "Feishu", ("FEISHU_APP_ID", "FEISHU_HOME_CHANNEL")),
        ("wecom", "WeCom", ("WECOM_BOT_ID", "WECOM_HOME_CHANNEL")),
        ("wecom_callback", "WeCom Callback", ("WECOM_CALLBACK_CORP_ID", None)),
        ("weixin", "Weixin", ("WEIXIN_ACCOUNT_ID", "WEIXIN_HOME_CHANNEL")),
        ("bluebubbles", "BlueBubbles", ("BLUEBUBBLES_SERVER_URL", "BLUEBUBBLES_HOME_CHANNEL")),
        ("qqbot", "QQBot", ("QQ_APP_ID", "QQ_HOME_CHANNEL")),
        ("yuanbao", "Yuanbao", ("YUANBAO_APP_ID", "YUANBAO_HOME_CHANNEL")),
    ]

    visible_platforms = filter_fabric_keys(
        platforms,
        FABRIC_GATEWAY_PLATFORMS,
        key=lambda item: item[0],
    )
    for _platform_slug, name, (token_var, home_var) in visible_platforms:
        token = os.getenv(token_var, "")
        has_token = bool(token)
        
        home_channel = ""
        if home_var:
            home_channel = os.getenv(home_var, "")
        # Back-compat: QQBot home channel was renamed from QQ_HOME_CHANNEL to QQBOT_HOME_CHANNEL
        if not home_channel and home_var == "QQBOT_HOME_CHANNEL":
            home_channel = os.getenv("QQ_HOME_CHANNEL", "")
        
        status = "configured" if has_token else "not configured"
        if home_channel:
            status += f" (home: {home_channel})"
        
        print(f"  {name:<12}  {check_mark(has_token)} {status}")

    # Plugin-registered platforms
    try:
        from gateway.platform_registry import platform_registry
        visible_plugin_entries = filter_fabric_keys(
            platform_registry.plugin_entries(),
            FABRIC_GATEWAY_PLATFORMS,
            key=lambda entry: entry.name,
        )
        for entry in visible_plugin_entries:
            configured = entry.check_fn()
            status_str = "configured" if configured else "not configured"
            label = entry.label
            print(f"  {label:<12}  {check_mark(configured)} {status_str} (plugin)")
    except Exception:
        pass

    # =========================================================================
    # Gateway Status
    # =========================================================================
    print()
    print(color("◆ Gateway Service", Colors.CYAN, Colors.BOLD))

    try:
        from fabric_cli.gateway import get_gateway_runtime_snapshot, _format_gateway_pids

        snapshot = get_gateway_runtime_snapshot()
        is_running = snapshot.running
        print(f"  Status:       {check_mark(is_running)} {'running' if is_running else 'stopped'}")
        print(f"  Manager:      {snapshot.manager}")
        if snapshot.gateway_pids:
            print(f"  PID(s):       {_format_gateway_pids(snapshot.gateway_pids)}")
        if snapshot.has_process_service_mismatch:
            print("  Service:      installed but not managing the current running gateway")
        elif _is_termux() and not snapshot.gateway_pids:
            print("  Start with:   fabric gateway")
            print("  Note:         Android may stop background jobs when Termux is suspended")
        elif snapshot.service_installed and not snapshot.service_running:
            print("  Service:      installed but stopped")
    except Exception:
        if _is_termux():
            print(f"  Status:       {color('unknown', Colors.DIM)}")
            print("  Manager:      Termux / manual process")
        elif sys.platform.startswith('linux'):
            print(f"  Status:       {color('unknown', Colors.DIM)}")
            print("  Manager:      systemd/manual")
        elif sys.platform == 'darwin':
            print(f"  Status:       {color('unknown', Colors.DIM)}")
            print("  Manager:      launchd")
        else:
            print(f"  Status:       {color('N/A', Colors.DIM)}")
            print("  Manager:      (not supported on this platform)")

    # =========================================================================
    # Cron Jobs
    # =========================================================================
    print()
    print(color("◆ Scheduled Jobs", Colors.CYAN, Colors.BOLD))

    jobs_file = get_fabric_home() / "cron" / "jobs.json"
    if jobs_file.exists():
        import json
        try:
            with open(jobs_file, encoding="utf-8") as f:
                data = json.load(f)
                jobs = data.get("jobs", [])
                enabled_jobs = [j for j in jobs if j.get("enabled", True)]
                print(f"  Jobs:         {len(enabled_jobs)} active, {len(jobs)} total")
        except Exception:
            print("  Jobs:         (error reading jobs file)")
    else:
        print("  Jobs:         0")

    # =========================================================================
    # Sessions
    # =========================================================================
    print()
    print(color("◆ Sessions", Colors.CYAN, Colors.BOLD))

    # Gateway session count: state.db is the source of truth (#9006);
    # fall back to sessions.json for pre-migration installs.
    _session_count = None
    try:
        from fabric_state import SessionDB
        _db = SessionDB()
        try:
            _lister = getattr(_db, "list_gateway_sessions", None)
            if callable(_lister):
                _session_count = len(_lister(active_only=True))
        finally:
            _db.close()
    except Exception:
        _session_count = None

    if _session_count is not None and _session_count > 0:
        print(f"  Active:       {_session_count} session(s)")
    else:
        sessions_file = get_fabric_home() / "sessions" / "sessions.json"
        if sessions_file.exists():
            import json
            try:
                with open(sessions_file, encoding="utf-8") as f:
                    data = json.load(f)
                    _entries = {
                        k: v for k, v in data.items()
                        if not str(k).startswith("_")
                    } if isinstance(data, dict) else {}
                    print(f"  Active:       {len(_entries)} session(s)")
            except Exception:
                print("  Active:       (error reading sessions file)")
        else:
            print(f"  Active:       {_session_count if _session_count is not None else 0}")

    # =========================================================================
    # Deep checks
    # =========================================================================
    _maybe_show_deep_checks(args, config)

    print()
    print(color("─" * 60, Colors.DIM))
    print(color("  Run 'fabric doctor' for detailed diagnostics", Colors.DIM))
    print(color("  Run 'fabric setup' to configure", Colors.DIM))
    print()
