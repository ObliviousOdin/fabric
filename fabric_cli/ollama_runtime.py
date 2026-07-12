"""Passive, profile-scoped readiness inspection for configured Ollama runtimes.

The inspector is deliberately not a model tool and performs no work at import
time.  Callers opt into a bounded live probe (currently ``fabric status
--deep``); normal model pickers and public metadata endpoints must remain
network-free until a profile-keyed cache exists.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import ipaddress
import json
from pathlib import Path
from queue import SimpleQueue
import re
from threading import Thread
import time
from typing import Any, Mapping
from urllib.parse import urlparse


OLLAMA_READINESS_SCHEMA_VERSION = 1
_MAX_PROBE_SECONDS = 10.0
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_OLLAMA_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_OLLAMA_CLOUD_PROVIDERS = frozenset({"ollama-cloud", "ollama_cloud"})


@dataclass(frozen=True)
class OllamaReadinessIssue:
    """One stable, non-secret readiness finding."""

    code: str
    severity: str
    message: str


@dataclass(frozen=True)
class OllamaReadinessSnapshot:
    """Immutable and JSON-safe description of one configured runtime."""

    schema_version: int
    applicable: bool
    state: str
    profile_scope_id: str
    endpoint_kind: str
    endpoint_fingerprint: str
    server_type: str | None
    transport_state: str
    model: str
    model_state: str
    model_digest: str | None
    model_size_bytes: int | None
    effective_context_length: int | None
    context_state: str
    context_source: str
    tools_state: str
    vision_state: str
    resource_state: str
    loaded: bool | None
    loaded_size_bytes: int | None
    loaded_vram_bytes: int | None
    issues: tuple[OllamaReadinessIssue, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a materialized JSON-safe mapping."""

        payload = asdict(self)
        payload["issues"] = [asdict(issue) for issue in self.issues]
        return payload


@dataclass(frozen=True)
class OllamaModelDiscovery:
    """Sanitized result of one explicit native model-catalog probe."""

    state: str
    models: tuple[str, ...] = ()
    issue_code: str | None = None


def _clean_text(value: Any, *, limit: int = 240) -> str:
    text = _CONTROL_CHARS.sub(" ", str(value or "")).strip()
    return text[:limit]


def _profile_scope_id(home: Path) -> str:
    try:
        canonical = str(home.expanduser().resolve())
    except OSError:
        canonical = str(home.expanduser().absolute())
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _canonical_endpoint_material(base_url: str) -> str:
    """Canonical endpoint material without userinfo, query, or fragment."""

    parsed = urlparse(base_url)
    host = (parsed.hostname or "").lower().rstrip(".")
    try:
        port = parsed.port
    except ValueError:
        port = None
    path = (parsed.path or "").rstrip("/")
    if path.endswith("/v1"):
        path = path[:-3]
    return f"{parsed.scheme.lower()}://{host}:{port or ''}{path}"


def _endpoint_fingerprint(base_url: str) -> str:
    material = _canonical_endpoint_material(base_url)
    if not material or material == "://:":
        return ""
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _endpoint_kind(base_url: str) -> str:
    parsed = urlparse(base_url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        return "unknown"
    if host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
        return "loopback"
    if host.endswith((".docker.internal", ".podman.internal", ".lima.internal")):
        return "container-host"
    if "." not in host:
        return "local-service"
    try:
        address = ipaddress.ip_address(host)
        if address.is_private or address.is_link_local or address.is_loopback:
            return "private-network"
        if isinstance(address, ipaddress.IPv4Address) and address in ipaddress.IPv4Network("100.64.0.0/10"):
            return "private-network"
    except ValueError:
        pass
    return "remote"


def _server_root(base_url: str) -> str:
    root = base_url.strip().rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3]
    return root


def _bare_model(model: str) -> str:
    # Reuse Fabric's provider-prefix contract so Ollama ``model:tag`` names are
    # preserved while values such as ``custom:my-model`` are normalized.
    from agent.model_metadata import _strip_provider_prefix

    return _clean_text(_strip_provider_prefix(model), limit=256)


def _matches_model(candidate: str, configured: str) -> bool:
    candidate = candidate.strip()
    configured = configured.strip()
    if not candidate or not configured:
        return False
    if candidate == configured:
        return True
    return candidate == f"{configured}:latest" or configured == f"{candidate}:latest"


def _runtime_context_config(
    value: Any,
    *,
    zero_falls_back: bool,
) -> tuple[int | None, bool]:
    """Mirror agent-init context parsing and identify unsafe values.

    Conversion failures fall back to runtime discovery in ``agent_init``.
    Non-positive ``ollama_num_ctx`` values do not, while a negative or boolean
    ``context_length`` can also poison the later Ollama cap.  The boolean return
    marks only values that could otherwise make this snapshot falsely ready.
    """

    if value is None:
        return None, False
    if isinstance(value, bool):
        if value is False and zero_falls_back:
            return None, False
        return None, True
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None, False
    if result > 0:
        return result, False
    if result == 0 and zero_falls_back:
        return None, False
    return None, True


def _reasonable_nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def _extract_capability(show: Mapping[str, Any], name: str) -> bool | None:
    from agent.model_metadata import ollama_tools_from_show, ollama_vision_from_show

    if name == "tools":
        return ollama_tools_from_show(dict(show))
    if name == "vision":
        return ollama_vision_from_show(dict(show))
    raise ValueError(f"Unsupported Ollama capability: {name}")


def _state_word(value: bool | None) -> str:
    if value is True:
        return "supported"
    if value is False:
        return "unsupported"
    return "unknown"


def _configured_values(
    config: Mapping[str, Any],
) -> tuple[str, str, str, int | None, int | None, tuple[str, ...]]:
    invalid_context_fields: list[str] = []
    model_cfg = config.get("model")
    if isinstance(model_cfg, Mapping):
        model = _clean_text(model_cfg.get("default") or model_cfg.get("name"), limit=256)
        provider = _clean_text(model_cfg.get("provider"), limit=128).lower()
        base_url = str(model_cfg.get("base_url") or "").strip()
        configured_context, context_invalid = _runtime_context_config(
            model_cfg.get("context_length"),
            zero_falls_back=True,
        )
        ollama_context, ollama_context_invalid = _runtime_context_config(
            model_cfg.get("ollama_num_ctx"),
            zero_falls_back=False,
        )
        if context_invalid:
            invalid_context_fields.append("model.context_length")
        if ollama_context_invalid:
            invalid_context_fields.append("model.ollama_num_ctx")
    else:
        model = _clean_text(model_cfg, limit=256)
        provider = ""
        base_url = ""
        configured_context = None
        ollama_context = None

    if not base_url and provider:
        providers = config.get("providers")
        provider_name = provider.removeprefix("custom:")
        entry = None
        if isinstance(providers, Mapping):
            entry = providers.get(provider) or providers.get(provider_name)
        if isinstance(entry, Mapping):
            base_url = str(
                entry.get("base_url")
                or entry.get("api_url")
                or entry.get("api")
                or entry.get("url")
                or ""
            ).strip()
            if not model:
                model = _clean_text(
                    entry.get("model") or entry.get("default_model"),
                    limit=256,
                )

        if not base_url:
            try:
                from fabric_cli.config import get_compatible_custom_providers

                compatible = get_compatible_custom_providers(dict(config))
            except Exception:
                compatible = []
            requested = provider_name.strip().lower().replace(" ", "-")
            for candidate in compatible:
                if not isinstance(candidate, Mapping):
                    continue
                names = {
                    str(candidate.get("name") or "")
                    .strip()
                    .lower()
                    .replace(" ", "-"),
                    str(candidate.get("provider_key") or "")
                    .strip()
                    .lower()
                    .replace(" ", "-"),
                }
                if requested not in names:
                    continue
                base_url = str(candidate.get("base_url") or "").strip()
                if not model:
                    model = _clean_text(candidate.get("model"), limit=256)
                break
    return (
        model,
        provider,
        base_url,
        configured_context,
        ollama_context,
        tuple(invalid_context_fields),
    )


def is_ollama_readiness_candidate(config: Mapping[str, Any]) -> bool:
    """Return whether an explicit deep check should try Ollama discovery.

    This intentionally excludes ordinary cloud providers. A configured local
    custom endpoint may turn out to be LM Studio/vLLM/llama.cpp; the snapshot
    will classify that protocol without displaying a false Ollama failure.
    """

    model, provider, base_url, _, _, _ = _configured_values(config)
    if not model or not base_url:
        return False
    if provider in _OLLAMA_CLOUD_PROVIDERS:
        return False
    if "ollama" in provider:
        return True
    try:
        from agent.model_metadata import is_local_endpoint

        local = is_local_endpoint(base_url)
    except Exception:
        local = False
    if not local:
        return False
    if provider in {"", "auto", "custom", "local"}:
        return True
    if provider.startswith("custom:"):
        return True
    providers = config.get("providers")
    return isinstance(providers, Mapping) and (
        provider in providers or provider.removeprefix("custom:") in providers
    )


def _empty_snapshot(
    *,
    home: Path,
    state: str,
    applicable: bool,
    endpoint_kind: str = "unknown",
    endpoint_fingerprint: str = "",
    transport_state: str = "not_configured",
    model: str = "",
    issues: tuple[OllamaReadinessIssue, ...] = (),
) -> OllamaReadinessSnapshot:
    return OllamaReadinessSnapshot(
        schema_version=OLLAMA_READINESS_SCHEMA_VERSION,
        applicable=applicable,
        state=state,
        profile_scope_id=_profile_scope_id(home),
        endpoint_kind=endpoint_kind,
        endpoint_fingerprint=endpoint_fingerprint,
        server_type=None,
        transport_state=transport_state,
        model=model,
        model_state="unknown",
        model_digest=None,
        model_size_bytes=None,
        effective_context_length=None,
        context_state="unknown",
        context_source="unknown",
        tools_state="unknown",
        vision_state="unknown",
        resource_state="unknown",
        loaded=None,
        loaded_size_bytes=None,
        loaded_vram_bytes=None,
        issues=issues,
    )


def _expected_ollama(provider: str, base_url: str) -> bool:
    if provider in _OLLAMA_CLOUD_PROVIDERS:
        return False
    if "ollama" in provider:
        return True
    try:
        return urlparse(base_url).port == 11434
    except ValueError:
        return False


def is_ollama_runtime_target(provider: str, base_url: str) -> bool:
    """Return whether an explicit model action targets an Ollama runtime.

    This is intentionally narrower than :func:`is_ollama_readiness_candidate`,
    which may inspect an unknown local custom endpoint to classify its server.
    Model-selection preflight must not add an Ollama-specific request to every
    LM Studio, vLLM, or llama.cpp switch merely because it is local.
    """

    return _expected_ollama(
        _clean_text(provider, limit=128).lower(),
        str(base_url or "").strip(),
    )


def discover_ollama_models(
    base_url: str,
    *,
    api_key: str = "",
    timeout: float = 5.0,
    transport: Any | None = None,
) -> OllamaModelDiscovery:
    """Read an Ollama ``/api/tags`` catalog after an explicit setup action.

    The result never includes the endpoint, credential, response body, or raw
    exception.  Redirects and environment proxies are disabled so a local URL
    cannot silently become a remote request.
    """

    try:
        from agent.ollama_native_adapter import normalize_ollama_native_base_url

        root = normalize_ollama_native_base_url(base_url)
    except (TypeError, ValueError):
        return OllamaModelDiscovery("invalid", issue_code="ollama_endpoint_invalid")

    import httpx

    bounded_timeout = max(0.2, min(float(timeout), _MAX_PROBE_SECONDS))
    deadline = time.monotonic() + bounded_timeout
    headers = {"Accept-Encoding": "identity"}
    key = str(api_key or "").strip()
    if key.lower() not in {"", "no-key-required", "ollama", "ollama-local"}:
        headers["Authorization"] = f"Bearer {key}"
    try:
        with httpx.Client(
            headers=headers,
            follow_redirects=False,
            trust_env=False,
            timeout=bounded_timeout,
            transport=transport,
        ) as client:
            status, payload = _request_json(
                client,
                "GET",
                f"{root}/api/tags",
                deadline=deadline,
            )
    except Exception:
        return OllamaModelDiscovery(
            "unreachable", issue_code="ollama_unreachable"
        )

    if status in {401, 403}:
        return OllamaModelDiscovery("auth_failed", issue_code="ollama_auth_failed")
    if status != 200 or not isinstance(payload, Mapping):
        return OllamaModelDiscovery(
            "incompatible", issue_code="ollama_protocol_mismatch"
        )
    raw_models = payload.get("models")
    if not isinstance(raw_models, list):
        return OllamaModelDiscovery(
            "incompatible", issue_code="ollama_protocol_mismatch"
        )

    models: list[str] = []
    seen: set[str] = set()
    for entry in raw_models:
        if not isinstance(entry, Mapping):
            continue
        model = _clean_text(entry.get("name") or entry.get("model"), limit=256)
        if not model or model.lower() in seen:
            continue
        seen.add(model.lower())
        models.append(model)
    return OllamaModelDiscovery("reachable", tuple(models))


def _request_json(
    client: Any,
    method: str,
    url: str,
    *,
    deadline: float,
    json_body: Mapping[str, Any] | None = None,
) -> tuple[int, Any]:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Ollama readiness deadline exceeded")

    # httpx's read timeout is an inactivity timeout, not a wall-clock bound: a
    # peer can trickle one byte before each read timeout and hold a synchronous
    # diagnostic forever. Run the complete request + JSON decode in a daemon
    # worker so the shared readiness deadline remains an actual total bound.
    outcome: SimpleQueue[tuple[bool, Any]] = SimpleQueue()

    def _run_request() -> None:
        try:
            with client.stream(
                method,
                url,
                json=dict(json_body) if json_body is not None else None,
                timeout=remaining,
            ) as response:
                content_encoding = response.headers.get("content-encoding", "").strip().lower()
                if content_encoding and content_encoding != "identity":
                    raise ValueError("Ollama readiness response used unsupported compression")
                content_length = response.headers.get("content-length")
                try:
                    declared_size = int(content_length) if content_length else None
                except ValueError:
                    declared_size = None
                if declared_size is not None and declared_size > _MAX_RESPONSE_BYTES:
                    raise ValueError("Ollama readiness response exceeded the safe size limit")

                body = bytearray()
                chunks = (
                    (response.content,)
                    if response.is_stream_consumed
                    else response.iter_raw()
                )
                for chunk in chunks:
                    body.extend(chunk)
                    if len(body) > _MAX_RESPONSE_BYTES:
                        raise ValueError("Ollama readiness response exceeded the safe size limit")
                try:
                    payload = json.loads(body) if body else None
                except Exception:
                    payload = None
                outcome.put((True, (int(response.status_code), payload)))
        except Exception as exc:
            outcome.put((False, exc))

    worker = Thread(target=_run_request, daemon=True, name="ollama-readiness-http")
    worker.start()
    worker.join(remaining)
    if worker.is_alive():
        try:
            client.close()
        except Exception:
            pass
        raise TimeoutError("Ollama readiness deadline exceeded")

    succeeded, value = outcome.get()
    if not succeeded:
        raise value
    return value


def _resolve_runtime_access(
    provider: str,
    base_url: str,
    model: str,
) -> tuple[str, str, dict[str, str], bool]:
    """Resolve the configured runtime endpoint/key without serializing either."""

    try:
        from fabric_cli.runtime_provider import resolve_runtime_provider

        runtime = resolve_runtime_provider(
            requested=provider or None,
            explicit_base_url=base_url or None,
            target_model=model or None,
        )
    except Exception:
        return base_url, "", {}, False
    resolved_url = str(runtime.get("base_url") or base_url or "").strip()
    resolved_key = str(runtime.get("api_key") or "").strip()
    if resolved_key == "no-key-required":
        resolved_key = ""
    raw_headers = runtime.get("extra_headers")
    resolved_headers = {
        str(key): str(value)
        for key, value in raw_headers.items()
        if str(key).strip() and value is not None
    } if isinstance(raw_headers, Mapping) else {}
    return resolved_url, resolved_key, resolved_headers, True


def _resolve_readiness_verify(config: Mapping[str, Any], base_url: str) -> Any:
    """Mirror the configured runtime's TLS verification policy."""

    try:
        from agent.ssl_verify import resolve_httpx_verify
        from fabric_cli.config import get_custom_provider_tls_settings

        tls = get_custom_provider_tls_settings(base_url, config=dict(config))
        return resolve_httpx_verify(
            ca_bundle=tls.get("ssl_ca_cert"),
            ssl_verify=tls.get("ssl_verify"),
            base_url=base_url,
        )
    except Exception:
        return True


def _build_snapshot_impl(
    *,
    config: Mapping[str, Any] | None,
    home: Path,
    model: str | None,
    base_url: str | None,
    api_key: str | None,
    include_resources: bool,
    timeout: float,
    transport: Any | None,
) -> OllamaReadinessSnapshot:
    from fabric_cli.config import load_config

    cfg = config if config is not None else load_config()
    (
        cfg_model,
        provider,
        cfg_url,
        configured_context,
        configured_ollama_context,
        invalid_context_fields,
    ) = _configured_values(cfg)
    selected_model = _clean_text(model if model is not None else cfg_model, limit=256)
    endpoint = str(base_url if base_url is not None else cfg_url).strip()

    if not endpoint or not selected_model:
        return _empty_snapshot(
            home=home,
            state="not_configured",
            applicable=_expected_ollama(provider, endpoint),
            endpoint_kind=_endpoint_kind(endpoint),
            endpoint_fingerprint=_endpoint_fingerprint(endpoint),
            model=selected_model,
            issues=(
                OllamaReadinessIssue(
                    "ollama_config_incomplete",
                    "info",
                    "Configure an Ollama endpoint and select an installed model.",
                ),
            ),
        )

    if api_key is None:
        endpoint, resolved_key, resolved_headers, access_resolved = _resolve_runtime_access(
            provider,
            endpoint,
            selected_model,
        )
    else:
        resolved_key = str(api_key)
        resolved_headers = {}
        access_resolved = True

    kind = _endpoint_kind(endpoint)
    fingerprint = _endpoint_fingerprint(endpoint)
    expected = _expected_ollama(provider, endpoint)
    if not access_resolved:
        return _empty_snapshot(
            home=home,
            state="access_unavailable",
            applicable=expected,
            endpoint_kind=kind,
            endpoint_fingerprint=fingerprint,
            transport_state="not_checked",
            model=selected_model,
            issues=(
                OllamaReadinessIssue(
                    "ollama_access_resolution_failed",
                    "error",
                    "Fabric could not resolve this profile's stored endpoint credential safely.",
                ),
            ),
        )
    parsed = urlparse(endpoint)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or bool(parsed.query)
        or bool(parsed.fragment)
    ):
        return _empty_snapshot(
            home=home,
            state="invalid_endpoint",
            applicable=expected,
            endpoint_kind=kind,
            endpoint_fingerprint=fingerprint,
            transport_state="invalid",
            model=selected_model,
            issues=(
                OllamaReadinessIssue(
                    "ollama_endpoint_invalid",
                    "error",
                    "Use an HTTP or HTTPS endpoint with a host and store credentials separately from the URL.",
                ),
            ),
        )

    import httpx

    bounded_timeout = max(0.2, min(float(timeout), _MAX_PROBE_SECONDS))
    deadline = time.monotonic() + bounded_timeout
    headers = dict(resolved_headers)
    if resolved_key and not any(key.lower() == "authorization" for key in headers):
        headers["Authorization"] = f"Bearer {resolved_key}"
    for key in tuple(headers):
        if key.lower() == "accept-encoding":
            headers.pop(key)
    headers["Accept-Encoding"] = "identity"
    root = _server_root(endpoint)
    verify = _resolve_readiness_verify(cfg, endpoint)

    try:
        with httpx.Client(
            headers=headers,
            follow_redirects=False,
            # A proxy can turn a literal loopback/private URL into remote
            # traffic. Readiness is an endpoint-local diagnostic and never
            # inherits HTTP(S)_PROXY, ALL_PROXY, or netrc settings.
            trust_env=False,
            timeout=bounded_timeout,
            transport=transport,
            verify=verify,
        ) as client:
            tags_status, tags_payload = _request_json(
                client,
                "GET",
                f"{root}/api/tags",
                deadline=deadline,
            )

            if tags_status in {401, 403}:
                return _empty_snapshot(
                    home=home,
                    state="auth_failed",
                    applicable=expected,
                    endpoint_kind=kind,
                    endpoint_fingerprint=fingerprint,
                    transport_state="auth_failed",
                    model=selected_model,
                    issues=(
                        OllamaReadinessIssue(
                            "ollama_auth_failed",
                            "error",
                            "The configured endpoint rejected its stored credential.",
                        ),
                    ),
                )
            if tags_status != 200 or not isinstance(tags_payload, Mapping) or not isinstance(tags_payload.get("models"), list):
                return _empty_snapshot(
                    home=home,
                    state="incompatible",
                    applicable=expected,
                    endpoint_kind=kind,
                    endpoint_fingerprint=fingerprint,
                    transport_state="incompatible",
                    model=selected_model,
                    issues=(
                        OllamaReadinessIssue(
                            "ollama_protocol_mismatch",
                            "error" if expected else "info",
                            "The endpoint did not return an Ollama model catalog.",
                        ),
                    ),
                )

            bare_model = _bare_model(selected_model)
            installed_entry: Mapping[str, Any] | None = None
            for entry in tags_payload.get("models", []):
                if not isinstance(entry, Mapping):
                    continue
                candidate = str(entry.get("name") or entry.get("model") or "")
                if _matches_model(candidate, bare_model):
                    installed_entry = entry
                    break

            if installed_entry is None:
                return OllamaReadinessSnapshot(
                    schema_version=OLLAMA_READINESS_SCHEMA_VERSION,
                    applicable=True,
                    state="model_missing",
                    profile_scope_id=_profile_scope_id(home),
                    endpoint_kind=kind,
                    endpoint_fingerprint=fingerprint,
                    server_type="ollama",
                    transport_state="reachable",
                    model=selected_model,
                    model_state="missing",
                    model_digest=None,
                    model_size_bytes=None,
                    effective_context_length=None,
                    context_state="unknown",
                    context_source="unknown",
                    tools_state="unknown",
                    vision_state="unknown",
                    resource_state="unknown",
                    loaded=None,
                    loaded_size_bytes=None,
                    loaded_vram_bytes=None,
                    issues=(
                        OllamaReadinessIssue(
                            "ollama_model_missing",
                            "error",
                            "Pull the selected model in Ollama or choose an installed model.",
                        ),
                    ),
                )

            show_status, show_payload = _request_json(
                client,
                "POST",
                f"{root}/api/show",
                deadline=deadline,
                json_body={"name": bare_model},
            )
            show = show_payload if show_status == 200 and isinstance(show_payload, Mapping) else {}
            from agent.model_metadata import (
                ollama_model_context_from_show,
                ollama_num_ctx_from_show,
            )

            detected_context = ollama_num_ctx_from_show(dict(show))
            model_context_max = ollama_model_context_from_show(dict(show))
            if invalid_context_fields:
                effective_context = None
                context_source = "invalid_config"
            elif configured_ollama_context:
                effective_context = configured_ollama_context
                context_source = "config_ollama_num_ctx"
                if configured_context and configured_context < effective_context:
                    effective_context = configured_context
                    context_source = "config_cap"
            elif detected_context:
                if configured_context and configured_context < detected_context:
                    effective_context = configured_context
                    context_source = "config_cap"
                else:
                    effective_context = detected_context
                    context_source = "ollama_show"
            else:
                # ``model.context_length`` alone is budgeting metadata and is
                # not proof that Ollama allocated that window.
                effective_context = None
                context_source = "unknown"
            context_exceeds_model = bool(
                configured_ollama_context
                and model_context_max
                and configured_ollama_context > model_context_max
            )
            context_override_unverified = bool(
                configured_ollama_context
                and not model_context_max
                and (
                    not detected_context
                    or configured_ollama_context > detected_context
                )
            )
            supports_tools = _extract_capability(show, "tools")
            supports_vision = _extract_capability(show, "vision")

            loaded: bool | None = None
            loaded_size: int | None = None
            loaded_vram: int | None = None
            resource_state = "unknown"
            if include_resources:
                try:
                    ps_status, ps_payload = _request_json(
                        client,
                        "GET",
                        f"{root}/api/ps",
                        deadline=deadline,
                    )
                    if ps_status == 200 and isinstance(ps_payload, Mapping) and isinstance(ps_payload.get("models"), list):
                        loaded = False
                        resource_state = "not_loaded"
                        for entry in ps_payload.get("models", []):
                            if not isinstance(entry, Mapping):
                                continue
                            candidate = str(entry.get("name") or entry.get("model") or "")
                            if not _matches_model(candidate, bare_model):
                                continue
                            loaded = True
                            resource_state = "loaded"
                            loaded_size = _reasonable_nonnegative_int(entry.get("size"))
                            loaded_vram = _reasonable_nonnegative_int(entry.get("size_vram"))
                            break
                except Exception:
                    # Resource evidence is optional and never invalidates a
                    # successful daemon/model probe.
                    pass
    except Exception:
        return _empty_snapshot(
            home=home,
            state="unreachable",
            applicable=expected,
            endpoint_kind=kind,
            endpoint_fingerprint=fingerprint,
            transport_state="unreachable",
            model=selected_model,
            issues=(
                OllamaReadinessIssue(
                    "ollama_unreachable",
                    "error",
                    "Start Ollama and verify that the configured endpoint is reachable from this process.",
                ),
            ),
        )

    from agent.model_metadata import MINIMUM_CONTEXT_LENGTH

    issues: list[OllamaReadinessIssue] = []
    if invalid_context_fields:
        context_state = "invalid_config"
        fields = " and ".join(invalid_context_fields)
        issues.append(
            OllamaReadinessIssue(
                "ollama_context_config_invalid",
                "error",
                f"Set {fields} to positive integer token counts or remove the invalid override.",
            )
        )
    elif context_exceeds_model:
        context_state = "exceeds_model"
        issues.append(
            OllamaReadinessIssue(
                "ollama_context_exceeds_model",
                "error",
                "The configured Ollama context exceeds the model/runtime value reported by the daemon.",
            )
        )
    elif context_override_unverified:
        context_state = "override_unverified"
        issues.append(
            OllamaReadinessIssue(
                "ollama_context_override_unverified",
                "warning",
                "Ollama did not report the model maximum, so the larger configured context allocation could not be validated.",
            )
        )
    elif effective_context is None:
        context_state = "unknown"
        issues.append(
            OllamaReadinessIssue(
                "ollama_context_unknown",
                "warning",
                "Ollama did not report an effective context window; verify it before agentic work.",
            )
        )
    elif effective_context < MINIMUM_CONTEXT_LENGTH:
        context_state = "too_small"
        issues.append(
            OllamaReadinessIssue(
                "ollama_context_too_small",
                "error",
                f"Increase the effective context window to at least {MINIMUM_CONTEXT_LENGTH:,} tokens.",
            )
        )
    else:
        context_state = "ready"

    if supports_tools is False:
        issues.append(
            OllamaReadinessIssue(
                "ollama_tools_unsupported",
                "error",
                "The selected model/runtime reports no tool capability; choose a tool-capable model for agent actions.",
            )
        )
    elif supports_tools is None:
        issues.append(
            OllamaReadinessIssue(
                "ollama_tools_unknown",
                "warning",
                "Tool capability is unknown; verify it with a small reversible tool request.",
            )
        )

    if context_state in {"invalid_config", "too_small", "exceeds_model"} or supports_tools is False:
        state = "blocked"
    elif context_state == "ready" and supports_tools is True:
        state = "ready"
    else:
        state = "degraded"

    raw_digest = _clean_text(installed_entry.get("digest"), limit=128).lower()
    digest = raw_digest if _OLLAMA_DIGEST.fullmatch(raw_digest) else None
    model_size = _reasonable_nonnegative_int(installed_entry.get("size"))
    return OllamaReadinessSnapshot(
        schema_version=OLLAMA_READINESS_SCHEMA_VERSION,
        applicable=True,
        state=state,
        profile_scope_id=_profile_scope_id(home),
        endpoint_kind=kind,
        endpoint_fingerprint=fingerprint,
        server_type="ollama",
        transport_state="reachable",
        model=selected_model,
        model_state="installed",
        model_digest=digest,
        model_size_bytes=model_size,
        effective_context_length=effective_context,
        context_state=context_state,
        context_source=context_source,
        tools_state=_state_word(supports_tools),
        vision_state=_state_word(supports_vision),
        resource_state=resource_state,
        loaded=loaded,
        loaded_size_bytes=loaded_size,
        loaded_vram_bytes=loaded_vram,
        issues=tuple(issues),
    )


def build_ollama_readiness_snapshot(
    *,
    config: Mapping[str, Any] | None = None,
    home: Path | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    include_resources: bool = False,
    timeout: float = 4.0,
    transport: Any | None = None,
) -> OllamaReadinessSnapshot:
    """Build one passive readiness snapshot for a stored/configured runtime.

    ``home`` and caller-supplied values make the function usable by profile-
    aware adapters without mutating process-global environment state.  The
    optional ``transport`` is a test seam for ``httpx.MockTransport``.
    """

    from agent.secret_scope import (
        build_profile_secret_scope,
        current_secret_scope,
        is_multiplex_active,
        reset_secret_scope,
        set_secret_scope,
    )
    from fabric_constants import (
        get_fabric_home,
        reset_fabric_home_override,
        set_fabric_home_override,
    )

    explicit_home = home is not None
    effective_home = Path(home) if explicit_home else Path(get_fabric_home())
    home_token = None
    try:
        already_scoped = effective_home.resolve() == Path(get_fabric_home()).resolve()
    except OSError:
        already_scoped = effective_home == Path(get_fabric_home())
    if not already_scoped:
        home_token = set_fabric_home_override(effective_home)

    secret_token = None
    try:
        # Preserve legacy/current-profile shell exports for ordinary CLI use.
        # Explicit cross-profile reads and unscoped multiplexed reads must
        # instead install a home-owned fail-closed mapping. A pre-existing
        # context scope is authoritative when no explicit home was requested.
        outer_scope = current_secret_scope()
        if explicit_home or (outer_scope is None and is_multiplex_active()):
            secret_token = set_secret_scope(build_profile_secret_scope(effective_home))
        return _build_snapshot_impl(
            config=config,
            home=effective_home,
            model=model,
            base_url=base_url,
            api_key=api_key,
            include_resources=include_resources,
            timeout=timeout,
            transport=transport,
        )
    finally:
        try:
            if secret_token is not None:
                reset_secret_scope(secret_token)
        finally:
            if home_token is not None:
                reset_fabric_home_override(home_token)
