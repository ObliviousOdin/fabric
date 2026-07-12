"""Contract tests for the passive Ollama readiness snapshot."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time

import httpx

from fabric_cli.ollama_runtime import (
    _resolve_readiness_verify,
    build_ollama_readiness_snapshot,
    discover_ollama_models,
    is_ollama_readiness_candidate,
)


MODEL = "qwen-test:latest"
URL = "http://127.0.0.1:11434/v1"


def _config(**model_overrides):
    model = {
        "provider": "custom",
        "default": MODEL,
        "base_url": URL,
    }
    model.update(model_overrides)
    return {"model": model}


def _transport(
    *,
    tags=None,
    show=None,
    ps=None,
    tags_status: int = 200,
    show_status: int = 200,
    ps_status: int = 200,
    seen: list[httpx.Request] | None = None,
):
    tags = {"models": [{"name": MODEL, "digest": "abc123", "size": 42}]} if tags is None else tags
    show = {
        "parameters": "num_ctx 65536",
        "capabilities": ["completion", "tools"],
    } if show is None else show
    ps = {"models": []} if ps is None else ps

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if request.url.path.endswith("/api/tags"):
            return httpx.Response(tags_status, json=tags)
        if request.url.path.endswith("/api/show"):
            return httpx.Response(show_status, json=show)
        if request.url.path.endswith("/api/ps"):
            return httpx.Response(ps_status, json=ps)
        raise AssertionError(f"unexpected readiness request: {request.method} {request.url}")

    return httpx.MockTransport(handler)


def _build(tmp_path, *, config=None, transport=None, api_key="", **kwargs):
    return build_ollama_readiness_snapshot(
        config=config if config is not None else _config(),
        home=tmp_path,
        api_key=api_key,
        transport=transport if transport is not None else _transport(),
        **kwargs,
    )


def test_explicit_native_discovery_returns_sanitized_installed_models():
    seen: list[httpx.Request] = []
    result = discover_ollama_models(
        "http://127.0.0.1:11434/v1",
        api_key="ollama-local",
        transport=_transport(
            seen=seen,
            tags={
                "models": [
                    {"name": "qwen3:latest"},
                    {"model": "gemma4:27b"},
                    {"name": "qwen3:latest"},
                    {"name": "bad\x00name"},
                ]
            },
        ),
    )

    assert result.state == "reachable"
    assert result.models == ("qwen3:latest", "gemma4:27b", "bad name")
    assert [request.url.path for request in seen] == ["/api/tags"]
    assert seen[0].headers.get("authorization") is None
    assert seen[0].headers["accept-encoding"] == "identity"


def test_explicit_native_discovery_rejects_credentials_in_url_without_request():
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"models": []})

    result = discover_ollama_models(
        "http://user:secret@127.0.0.1:11434",
        transport=httpx.MockTransport(handler),
    )

    assert result.state == "invalid"
    assert result.issue_code == "ollama_endpoint_invalid"
    assert called is False


def test_not_configured_is_passive_and_profile_scoped(tmp_path):
    called = False

    def handler(_request):
        nonlocal called
        called = True
        raise AssertionError("not-configured readiness must not probe")

    first = _build(
        tmp_path / "one",
        config={"model": {}},
        transport=httpx.MockTransport(handler),
    )
    second = _build(
        tmp_path / "two",
        config={"model": {}},
        transport=httpx.MockTransport(handler),
    )

    assert called is False
    assert first.state == "not_configured"
    assert first.profile_scope_id != second.profile_scope_id


def test_named_legacy_custom_provider_resolves_endpoint_and_model(tmp_path):
    config = {
        "model": {"provider": "custom:local-ollama"},
        "custom_providers": [
            {
                "name": "Local Ollama",
                "base_url": URL,
                "model": MODEL,
            }
        ],
    }

    assert is_ollama_readiness_candidate(config) is True

    snapshot = _build(tmp_path, config=config)
    assert snapshot.state == "ready"
    assert snapshot.model == MODEL


def test_generic_named_legacy_custom_provider_is_a_local_candidate(tmp_path):
    config = {
        "model": {"provider": "custom:lab"},
        "custom_providers": [
            {
                "name": "Lab",
                "base_url": URL,
                "model": MODEL,
            }
        ],
    }

    assert is_ollama_readiness_candidate(config) is True
    assert _build(tmp_path, config=config).state == "ready"


def test_named_v12_custom_provider_uses_stripped_provider_key(tmp_path):
    config = {
        "model": {"provider": "custom:lab", "default": MODEL},
        "providers": {
            "lab": {
                "name": "Lab Runtime",
                "base_url": URL,
                "model": MODEL,
            }
        },
    }

    assert is_ollama_readiness_candidate(config) is True
    assert _build(tmp_path, config=config).state == "ready"


def test_readiness_uses_matching_custom_provider_tls_policy():
    config = {
        "providers": {
            "lab": {
                "base_url": "https://ollama.internal.example/v1",
                "ssl_verify": False,
            }
        }
    }

    assert (
        _resolve_readiness_verify(
            config,
            "https://ollama.internal.example/v1",
        )
        is False
    )


def test_ready_snapshot_reuses_show_and_reports_resources(tmp_path):
    seen: list[httpx.Request] = []
    snapshot = _build(
        tmp_path,
        transport=_transport(
            seen=seen,
            show={
                "parameters": "num_ctx 65536",
                "capabilities": ["completion", "tools", "vision"],
            },
            ps={
                "models": [
                    {
                        "name": MODEL,
                        "size": 100,
                        "size_vram": 80,
                    }
                ]
            },
        ),
        include_resources=True,
    )

    assert snapshot.state == "ready"
    assert snapshot.server_type == "ollama"
    assert snapshot.model_state == "installed"
    assert snapshot.effective_context_length == 65536
    assert snapshot.context_source == "ollama_show"
    assert snapshot.tools_state == "supported"
    assert snapshot.vision_state == "supported"
    assert snapshot.resource_state == "loaded"
    assert snapshot.loaded is True
    assert snapshot.loaded_size_bytes == 100
    assert snapshot.loaded_vram_bytes == 80
    assert [request.url.path for request in seen].count("/api/show") == 1


def test_missing_model_has_precise_remediation(tmp_path):
    snapshot = _build(
        tmp_path,
        transport=_transport(tags={"models": [{"name": "another:latest"}]}),
    )

    assert snapshot.state == "model_missing"
    assert snapshot.model_state == "missing"
    assert [issue.code for issue in snapshot.issues] == ["ollama_model_missing"]


def test_low_context_and_no_tools_block_agent_readiness(tmp_path):
    snapshot = _build(
        tmp_path,
        transport=_transport(
            show={
                "model_info": {"qwen.context_length": 32768},
                "capabilities": ["completion", "vision"],
            }
        ),
    )

    assert snapshot.state == "blocked"
    assert snapshot.context_state == "too_small"
    assert snapshot.tools_state == "unsupported"
    assert {issue.code for issue in snapshot.issues} == {
        "ollama_context_too_small",
        "ollama_tools_unsupported",
    }


def test_missing_capability_evidence_is_degraded_not_ready(tmp_path):
    snapshot = _build(
        tmp_path,
        transport=_transport(show={"model_info": {"qwen.context_length": 131072}}),
    )

    assert snapshot.state == "degraded"
    assert snapshot.context_state == "ready"
    assert snapshot.tools_state == "unknown"
    assert snapshot.vision_state == "unknown"
    assert "ollama_tools_unknown" in {issue.code for issue in snapshot.issues}


def test_model_context_cap_matches_runtime_but_metadata_alone_is_not_proof(tmp_path):
    capped = _build(
        tmp_path / "capped",
        config=_config(context_length=65536),
        transport=_transport(
            show={
                "model_info": {"qwen.context_length": 131072},
                "capabilities": ["completion", "tools"],
            }
        ),
    )
    unproven = _build(
        tmp_path / "unproven",
        config=_config(context_length=65536),
        transport=_transport(show={"capabilities": ["completion", "tools"]}),
    )

    assert capped.effective_context_length == 65536
    assert capped.context_source == "config_cap"
    assert capped.state == "ready"
    assert unproven.effective_context_length is None
    assert unproven.context_state == "unknown"
    assert unproven.state == "degraded"


def test_ollama_context_override_above_reported_model_is_blocked(tmp_path):
    snapshot = _build(
        tmp_path,
        config=_config(ollama_num_ctx=65536),
        transport=_transport(
            show={
                "model_info": {"qwen.context_length": 32768},
                "capabilities": ["completion", "tools"],
            }
        ),
    )

    assert snapshot.effective_context_length == 65536
    assert snapshot.context_source == "config_ollama_num_ctx"
    assert snapshot.context_state == "exceeds_model"
    assert snapshot.state == "blocked"


def test_ollama_context_override_is_validated_against_model_max_not_current_allocation(
    tmp_path,
):
    snapshot = _build(
        tmp_path,
        config=_config(ollama_num_ctx=65536),
        transport=_transport(
            show={
                "parameters": "num_ctx 4096",
                "model_info": {"qwen.context_length": 131072},
                "capabilities": ["completion", "tools"],
            }
        ),
    )

    assert snapshot.effective_context_length == 65536
    assert snapshot.context_source == "config_ollama_num_ctx"
    assert snapshot.context_state == "ready"
    assert snapshot.state == "ready"


def test_larger_context_override_without_model_max_is_degraded_not_ready(tmp_path):
    snapshot = _build(
        tmp_path,
        config=_config(ollama_num_ctx=65536),
        transport=_transport(
            show={
                "parameters": "num_ctx 4096",
                "capabilities": ["completion", "tools"],
            }
        ),
    )

    assert snapshot.effective_context_length == 65536
    assert snapshot.context_source == "config_ollama_num_ctx"
    assert snapshot.context_state == "override_unverified"
    assert snapshot.state == "degraded"
    assert "ollama_context_override_unverified" in {
        issue.code for issue in snapshot.issues
    }


def test_model_context_cap_still_bounds_explicit_ollama_allocation(tmp_path):
    snapshot = _build(
        tmp_path,
        config=_config(context_length=32768, ollama_num_ctx=65536),
        transport=_transport(
            show={
                "parameters": "num_ctx 4096",
                "model_info": {"qwen.context_length": 131072},
                "capabilities": ["completion", "tools"],
            }
        ),
    )

    assert snapshot.effective_context_length == 32768
    assert snapshot.context_source == "config_cap"
    assert snapshot.context_state == "too_small"
    assert snapshot.state == "blocked"


def test_invalid_runtime_context_overrides_fail_closed(tmp_path):
    for field, value in (
        ("ollama_num_ctx", 0),
        ("ollama_num_ctx", -1),
        ("ollama_num_ctx", True),
        ("context_length", -1),
        ("context_length", True),
    ):
        snapshot = _build(
            tmp_path / f"{field}-{value}",
            config=_config(**{field: value}),
        )

        assert snapshot.effective_context_length is None
        assert snapshot.context_source == "invalid_config"
        assert snapshot.context_state == "invalid_config"
        assert snapshot.state == "blocked"
        assert "ollama_context_config_invalid" in {
            issue.code for issue in snapshot.issues
        }


def test_unreachable_and_wrong_protocol_are_distinct(tmp_path):
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("secret host details", request=request)

    offline = _build(tmp_path / "offline", transport=httpx.MockTransport(unreachable))
    incompatible = _build(
        tmp_path / "wrong",
        transport=_transport(tags={"data": []}),
    )

    assert offline.state == "unreachable"
    assert offline.transport_state == "unreachable"
    assert incompatible.state == "incompatible"
    assert incompatible.transport_state == "incompatible"


def test_probe_timeout_is_a_total_wall_clock_bound(tmp_path):
    payload = json.dumps({"models": [{"name": MODEL}]}).encode()

    class TrickleHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            for byte in payload:
                try:
                    self.wfile.write(bytes([byte]))
                    self.wfile.flush()
                except OSError:
                    break
                time.sleep(0.05)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), TrickleHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    config = _config(base_url=f"http://127.0.0.1:{server.server_port}/v1")
    try:
        started = time.monotonic()
        snapshot = build_ollama_readiness_snapshot(
            config=config,
            home=tmp_path,
            api_key="",
            timeout=0.2,
        )
        elapsed = time.monotonic() - started
    finally:
        server.shutdown()
        server.server_close()

    # The unguarded per-read timeout takes roughly 2.5 seconds for this body;
    # leave ample scheduler headroom while still proving the 0.2s wall bound.
    assert elapsed < 1.0
    assert snapshot.state == "unreachable"
    assert snapshot.transport_state == "unreachable"


def test_probe_response_body_has_a_hard_size_cap(tmp_path):
    class OversizedStream(httpx.SyncByteStream):
        def __iter__(self):
            yield b"{" + (b"x" * (4 * 1024 * 1024))

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=OversizedStream())

    snapshot = _build(tmp_path, transport=httpx.MockTransport(handler))

    assert snapshot.state == "unreachable"
    assert snapshot.transport_state == "unreachable"


def test_probe_rejects_compressed_bodies_before_decoding(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Accept-Encoding"] == "identity"
        return httpx.Response(
            200,
            headers={"Content-Encoding": "gzip"},
            content=b"not-decoded-by-readiness",
        )

    snapshot = _build(tmp_path, transport=httpx.MockTransport(handler))

    assert snapshot.state == "unreachable"
    assert snapshot.transport_state == "unreachable"


def test_readiness_client_never_inherits_proxy_environment(
    tmp_path,
    monkeypatch,
):
    seen_kwargs = {}
    real_client = httpx.Client

    def _recording_client(*args, **kwargs):
        seen_kwargs.update(kwargs)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", _recording_client)
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:9999")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:9999")

    snapshot = _build(tmp_path, transport=_transport())

    assert snapshot.state == "ready"
    assert seen_kwargs["trust_env"] is False
    assert seen_kwargs["follow_redirects"] is False


def test_direct_cloud_alias_probe_never_claims_local_ollama_applicability(tmp_path):
    for alias in ("ollama-cloud", "ollama_cloud"):
        snapshot = _build(
            tmp_path / alias,
            config={
                "model": {
                    "provider": alias,
                    "default": MODEL,
                    "base_url": "https://ollama.com/v1",
                }
            },
            transport=_transport(tags_status=401, tags={"error": "cloud"}),
        )
        assert snapshot.state == "auth_failed"
        assert snapshot.applicable is False


def test_auth_failure_and_serialization_never_expose_secret(tmp_path):
    secret = "fabric-super-secret"
    snapshot = _build(
        tmp_path,
        api_key=secret,
        transport=_transport(tags_status=401, tags={"error": secret}),
    )
    encoded = json.dumps(snapshot.to_dict(), sort_keys=True)

    assert snapshot.state == "auth_failed"
    assert secret not in encoded
    assert "Authorization" not in encoded
    assert URL not in encoded


def test_only_canonical_ollama_digest_can_enter_snapshot(tmp_path):
    secret = "response-body-secret"
    rejected = _build(
        tmp_path / "rejected",
        transport=_transport(
            tags={"models": [{"name": MODEL, "digest": secret, "size": 42}]}
        ),
    )
    canonical = "sha256:" + ("a" * 64)
    accepted = _build(
        tmp_path / "accepted",
        transport=_transport(
            tags={"models": [{"name": MODEL, "digest": canonical, "size": 42}]}
        ),
    )

    assert rejected.model_digest is None
    assert secret not in json.dumps(rejected.to_dict())
    assert accepted.model_digest == canonical


def test_profile_runtime_extra_headers_are_used_but_never_serialized(
    tmp_path,
    monkeypatch,
):
    secret = "private-header-value"
    seen: list[httpx.Request] = []
    monkeypatch.setattr(
        "fabric_cli.runtime_provider.resolve_runtime_provider",
        lambda **_kwargs: {
            "base_url": URL,
            "api_key": "no-key-required",
            "extra_headers": {"X-Fabric-Endpoint-Key": secret},
        },
    )

    snapshot = build_ollama_readiness_snapshot(
        config=_config(),
        home=tmp_path,
        api_key=None,
        transport=_transport(seen=seen),
    )
    encoded = json.dumps(snapshot.to_dict(), sort_keys=True)

    assert snapshot.state == "ready"
    assert seen[0].headers["X-Fabric-Endpoint-Key"] == secret
    assert secret not in encoded
    assert "X-Fabric-Endpoint-Key" not in encoded


def test_runtime_access_resolution_failure_never_probes_anonymously(
    tmp_path,
    monkeypatch,
):
    called = False
    secret = "resolver-secret-detail"

    def handler(_request):
        nonlocal called
        called = True
        raise AssertionError("failed access resolution must not probe")

    monkeypatch.setattr(
        "fabric_cli.runtime_provider.resolve_runtime_provider",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError(secret)),
    )
    snapshot = build_ollama_readiness_snapshot(
        config=_config(),
        home=tmp_path,
        api_key=None,
        transport=httpx.MockTransport(handler),
    )
    encoded = json.dumps(snapshot.to_dict(), sort_keys=True)

    assert called is False
    assert snapshot.state == "access_unavailable"
    assert snapshot.transport_state == "not_checked"
    assert [issue.code for issue in snapshot.issues] == [
        "ollama_access_resolution_failed"
    ]
    assert secret not in encoded


def test_current_profile_preserves_shell_exported_runtime_secret(
    monkeypatch,
):
    from agent.secret_scope import get_secret

    secret = "shell-profile-key"
    seen: list[httpx.Request] = []
    monkeypatch.setenv("LAB_KEY", secret)
    monkeypatch.setattr(
        "fabric_cli.runtime_provider.resolve_runtime_provider",
        lambda **_kwargs: {
            "base_url": URL,
            "api_key": get_secret("LAB_KEY") or "",
        },
    )

    snapshot = build_ollama_readiness_snapshot(
        config=_config(),
        api_key=None,
        transport=_transport(seen=seen),
    )

    assert snapshot.state == "ready"
    assert seen[0].headers["Authorization"] == f"Bearer {secret}"


def test_existing_secret_scope_is_authoritative_and_restored(
    monkeypatch,
):
    from agent.secret_scope import (
        current_secret_scope,
        get_secret,
        reset_secret_scope,
        set_secret_scope,
    )

    seen: list[httpx.Request] = []
    outer = {"LAB_KEY": "outer-profile-key"}
    monkeypatch.setenv("LAB_KEY", "wrong-shell-key")
    monkeypatch.setattr(
        "fabric_cli.runtime_provider.resolve_runtime_provider",
        lambda **_kwargs: {
            "base_url": URL,
            "api_key": get_secret("LAB_KEY") or "",
        },
    )
    token = set_secret_scope(outer)
    try:
        snapshot = build_ollama_readiness_snapshot(
            config=_config(),
            api_key=None,
            transport=_transport(seen=seen),
        )
        assert current_secret_scope() is outer
    finally:
        reset_secret_scope(token)

    assert snapshot.state == "ready"
    assert seen[0].headers["Authorization"] == "Bearer outer-profile-key"


def test_explicit_home_uses_profile_env_then_restores_outer_scope(
    tmp_path,
    monkeypatch,
):
    from agent.secret_scope import (
        current_secret_scope,
        get_secret,
        reset_secret_scope,
        set_secret_scope,
    )

    profile_home = tmp_path / "worker"
    profile_home.mkdir()
    (profile_home / ".env").write_text("LAB_KEY=worker-profile-key\n", encoding="utf-8")
    seen: list[httpx.Request] = []
    outer = {"LAB_KEY": "launch-profile-key"}
    monkeypatch.setattr(
        "fabric_cli.runtime_provider.resolve_runtime_provider",
        lambda **_kwargs: {
            "base_url": URL,
            "api_key": get_secret("LAB_KEY") or "",
        },
    )
    token = set_secret_scope(outer)
    try:
        snapshot = build_ollama_readiness_snapshot(
            config=_config(),
            home=profile_home,
            api_key=None,
            transport=_transport(seen=seen),
        )
        assert current_secret_scope() is outer
    finally:
        reset_secret_scope(token)

    assert snapshot.state == "ready"
    assert seen[0].headers["Authorization"] == "Bearer worker-profile-key"


def test_two_real_profile_homes_resolve_their_own_custom_provider_secret(
    tmp_path,
):
    from agent.secret_scope import (
        current_secret_scope,
        reset_secret_scope,
        set_secret_scope,
    )
    from fabric_constants import (
        get_fabric_home,
        reset_fabric_home_override,
        set_fabric_home_override,
    )

    def write_profile(home, secret):
        home.mkdir(parents=True)
        (home / "config.yaml").write_text(
            "\n".join(
                (
                    "model:",
                    f"  default: {MODEL}",
                    "  provider: custom:lab",
                    "providers:",
                    "  lab:",
                    "    name: Lab",
                    f"    base_url: {URL}",
                    "    key_env: LAB_KEY",
                    f"    model: {MODEL}",
                    "",
                )
            ),
            encoding="utf-8",
        )
        (home / ".env").write_text(f"LAB_KEY={secret}\n", encoding="utf-8")

    launch_home = tmp_path / "launch"
    named_home = tmp_path / "profiles" / "worker"
    default_home = tmp_path / "default"
    launch_home.mkdir()
    write_profile(named_home, "named-secret")
    write_profile(default_home, "default-secret")

    named_seen: list[httpx.Request] = []
    default_seen: list[httpx.Request] = []
    home_token = set_fabric_home_override(launch_home)
    scope_token = set_secret_scope({"LAB_KEY": "launch-secret"})
    try:
        named = build_ollama_readiness_snapshot(
            home=named_home,
            transport=_transport(seen=named_seen),
        )
        default = build_ollama_readiness_snapshot(
            home=default_home,
            transport=_transport(seen=default_seen),
        )
        assert get_fabric_home() == launch_home
        assert current_secret_scope() == {"LAB_KEY": "launch-secret"}

        try:
            build_ollama_readiness_snapshot(
                home=named_home,
                timeout="invalid",  # type: ignore[arg-type]
                transport=_transport(),
            )
        except ValueError:
            pass
        else:
            raise AssertionError("invalid timeout should raise ValueError")
        assert get_fabric_home() == launch_home
        assert current_secret_scope() == {"LAB_KEY": "launch-secret"}
    finally:
        reset_secret_scope(scope_token)
        reset_fabric_home_override(home_token)

    assert named.state == "ready"
    assert default.state == "ready"
    assert named.profile_scope_id != default.profile_scope_id
    assert named_seen[0].headers["Authorization"] == "Bearer named-secret"
    assert default_seen[0].headers["Authorization"] == "Bearer default-secret"


def test_endpoint_userinfo_query_and_fragment_fail_before_network(tmp_path):
    called = False

    def handler(_request):
        nonlocal called
        called = True
        raise AssertionError("invalid secret-bearing URL must not be probed")

    snapshot = _build(
        tmp_path,
        config=_config(base_url="http://user:pass@127.0.0.1:11434/v1?token=secret#x"),
        transport=httpx.MockTransport(handler),
    )

    assert called is False
    assert snapshot.state == "invalid_endpoint"
    assert snapshot.transport_state == "invalid"
    encoded = json.dumps(snapshot.to_dict())
    assert "user" not in encoded
    assert "pass" not in encoded
    assert "token" not in encoded


def test_resource_probe_failure_does_not_erase_model_readiness(tmp_path):
    snapshot = _build(
        tmp_path,
        include_resources=True,
        transport=_transport(ps_status=500, ps={"error": "sensitive"}),
    )

    assert snapshot.state == "ready"
    assert snapshot.resource_state == "unknown"
    assert snapshot.loaded is None
