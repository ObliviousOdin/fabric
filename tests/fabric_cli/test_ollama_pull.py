from __future__ import annotations

from copy import deepcopy
import _thread
import json
import os
from pathlib import Path
import stat
import sys
import threading
import time
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from fabric_cli import ollama_pull


DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
LAYER_DIGEST = "sha256:" + "c" * 64


class ChunkStream(httpx.SyncByteStream):
    def __init__(self, chunks: list[bytes], *, interrupt: bool = False) -> None:
        self.chunks = chunks
        self.interrupt = interrupt
        self.closed = False

    def __iter__(self):
        for chunk in self.chunks:
            yield chunk
        if self.interrupt:
            raise KeyboardInterrupt

    def close(self) -> None:
        self.closed = True


class TricklingStream(httpx.SyncByteStream):
    def __init__(self, delay: float = 0.01) -> None:
        self.delay = delay
        self.closed = False

    def __iter__(self):
        while not self.closed:
            time.sleep(self.delay)
            yield b" "

    def close(self) -> None:
        self.closed = True


class NeverReadStream(httpx.SyncByteStream):
    def __init__(self) -> None:
        self.closed = False

    def __iter__(self):
        raise AssertionError("encoded response body must not be decoded or read")
        yield b""  # pragma: no cover

    def close(self) -> None:
        self.closed = True


class Daemon:
    def __init__(
        self,
        *,
        tags: list[Any],
        pull_status: int = 200,
        pull_chunks: list[bytes] | None = None,
        pull_interrupt: bool = False,
        pull_headers: dict[str, str] | None = None,
    ) -> None:
        self.tags = list(tags)
        self.pull_status = pull_status
        self.pull_headers = dict(pull_headers or {})
        self.pull_stream = ChunkStream(
            pull_chunks
            or [b'{"status":"pulling manifest"}\n', b'{"status":"success"}\n'],
            interrupt=pull_interrupt,
        )
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/api/tags":
            value = self.tags.pop(0) if len(self.tags) > 1 else self.tags[0]
            if isinstance(value, BaseException):
                raise value
            if isinstance(value, httpx.SyncByteStream):
                return httpx.Response(200, stream=value)
            if isinstance(value, httpx.Response):
                return value
            return httpx.Response(200, json={"models": value})
        if request.url.path == "/api/pull":
            return httpx.Response(
                self.pull_status,
                headers=self.pull_headers,
                stream=self.pull_stream,
            )
        raise AssertionError("unexpected request path")


def installed(digest: str, name: str = "qwen3:latest") -> list[dict[str, str]]:
    return [{"name": name, "digest": digest}]


def run_pull(tmp_path: Path, daemon: Daemon, **kwargs: Any):
    return ollama_pull.pull_ollama_model(
        kwargs.pop("model", "qwen3"),
        kwargs.pop("host", None),
        home=kwargs.pop("home", tmp_path / "profile"),
        default_root=kwargs.pop("default_root", tmp_path / "root"),
        transport=httpx.MockTransport(daemon),
        **kwargs,
    )


def ledger_payload(home: Path) -> dict[str, Any]:
    paths = list((home / "runtime" / "ollama-pulls").glob("*.json"))
    assert len(paths) == 1
    return json.loads(paths[0].read_text(encoding="utf-8"))


def local_config(*, endpoint: str = "http://127.0.0.1:11434") -> dict[str, Any]:
    return {
        "model": {
            "default": "qwen3",
            "provider": "ollama",
            "base_url": endpoint,
        }
    }


def test_happy_path_posts_exact_request_and_uses_final_catalog_digest(tmp_path: Path):
    daemon = Daemon(
        tags=[[], installed(DIGEST_B)],
        pull_chunks=[
            (
                '{"status":"pulling layer","digest":"%s",'
                '"completed":4,"total":10}\n' % LAYER_DIGEST
            ).encode(),
            b'{"status":"success"}\n',
        ],
    )
    updates: list[ollama_pull.OllamaPullProgress] = []

    result = run_pull(tmp_path, daemon, progress_callback=updates.append)

    assert result.phase == "ready"
    assert result.exit_code == 0
    assert result.canonical_model == "qwen3:latest"
    assert result.final_model_digest == DIGEST_B
    assert result.final_model_digest != LAYER_DIGEST
    assert any(update.layer_digest == LAYER_DIGEST for update in updates)
    assert [request.url.path for request in daemon.requests] == [
        "/api/tags",
        "/api/pull",
        "/api/tags",
    ]
    pull = daemon.requests[1]
    assert pull.method == "POST"
    assert json.loads(pull.content) == {"model": "qwen3:latest", "stream": True}
    assert pull.url == httpx.URL("http://127.0.0.1:11434/api/pull")
    assert all(
        request.headers["Accept-Encoding"] == "identity"
        for request in daemon.requests
    )


def test_ledger_is_atomic_owner_only_and_contains_no_endpoint_or_layer_digest(tmp_path: Path):
    home = tmp_path / "profile"
    daemon = Daemon(tags=[[], installed(DIGEST_B)])

    result = run_pull(tmp_path, daemon, home=home)

    paths = list((home / "runtime" / "ollama-pulls").glob("*.json"))
    assert len(paths) == 1
    path = paths[0]
    payload = json.loads(path.read_text())
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert payload == result.to_ledger_dict()
    serialized = path.read_text()
    assert "127.0.0.1" not in serialized
    assert "11434" not in serialized
    assert LAYER_DIGEST not in serialized
    assert not list(path.parent.glob("*.tmp"))


@pytest.mark.parametrize(
    "host, code",
    [
        ("http://8.8.8.8:11434", "OLLAMA_ENDPOINT_NOT_PRIVATE"),
        ("http://169.254.169.254:11434", "OLLAMA_ENDPOINT_NOT_PRIVATE"),
        ("http://100.100.100.200:11434", "OLLAMA_ENDPOINT_NOT_PRIVATE"),
        ("http://[fd00:ec2::254]:11434", "OLLAMA_ENDPOINT_NOT_PRIVATE"),
        ("http://0.0.0.0:11434", "OLLAMA_ENDPOINT_NOT_PRIVATE"),
        ("http://192.0.2.1:11434", "OLLAMA_ENDPOINT_NOT_PRIVATE"),
        ("http://198.18.0.1:11434", "OLLAMA_ENDPOINT_NOT_PRIVATE"),
        ("http://user:pass@127.0.0.1:11434", "OLLAMA_ENDPOINT_INVALID"),
        ("http://127.0.0.1:11434?token=x", "OLLAMA_ENDPOINT_INVALID"),
        ("http://127.0.0.1:11434/#x", "OLLAMA_ENDPOINT_INVALID"),
        ("ftp://127.0.0.1:11434", "OLLAMA_ENDPOINT_INVALID"),
        ("http://127.0.0.1:11434/proxy", "OLLAMA_ENDPOINT_INVALID"),
    ],
)
def test_endpoint_policy_rejects_unsafe_destinations(tmp_path: Path, host: str, code: str):
    with pytest.raises(ollama_pull.OllamaPullError) as caught:
        ollama_pull.resolve_ollama_pull_target("qwen3", host, home=tmp_path)
    assert caught.value.code == code
    assert host not in str(caught.value)


def test_private_dns_hostname_fails_closed_before_httpx_can_resolve_again(tmp_path: Path):
    resolver_called = False

    def resolver(*_args, **_kwargs):
        nonlocal resolver_called
        resolver_called = True
        return [(2, 1, 6, "", ("10.0.0.4", 11434))]

    with pytest.raises(ollama_pull.OllamaPullError) as caught:
        ollama_pull.resolve_ollama_pull_target(
            "qwen3", "http://ollama.internal:11434", home=tmp_path, resolver=resolver
        )
    assert caught.value.code == "OLLAMA_ENDPOINT_HOSTNAME_UNPINNED"
    assert resolver_called is False


def test_localhost_is_pinned_to_loopback_literal(tmp_path: Path):
    target = ollama_pull.resolve_ollama_pull_target(
        "qwen3", "http://localhost:11434", home=tmp_path
    )
    default_target = ollama_pull.resolve_ollama_pull_target(
        "qwen3", "http://127.0.0.1:11434", home=tmp_path
    )
    assert target.endpoint_kind == "loopback"
    assert target.endpoint_fingerprint == default_target.endpoint_fingerprint
    assert target.target_hash == default_target.target_hash

    mapped_target = ollama_pull.resolve_ollama_pull_target(
        "qwen3", "http://[::ffff:127.0.0.1]:11434", home=tmp_path
    )
    assert mapped_target.endpoint_fingerprint == default_target.endpoint_fingerprint
    assert mapped_target.target_hash == default_target.target_hash


@pytest.mark.parametrize(
    "host",
    [
        "http://10.0.0.4:11434",
        "http://100.64.0.5:11434",
        "http://[fd00::1]:11434",
    ],
)
def test_rfc1918_tailscale_and_ipv6_ula_destinations_are_allowed(
    tmp_path: Path, host: str
):
    target = ollama_pull.resolve_ollama_pull_target("qwen3", host, home=tmp_path)
    assert target.endpoint_kind == "private-network"


def test_configured_cloud_model_never_becomes_local_pull_implicitly(tmp_path: Path):
    cloud = {
        "model": {
            "default": "qwen3:cloud",
            "provider": "ollama-cloud",
            "base_url": "https://ollama.com/v1",
        }
    }
    with pytest.raises(ollama_pull.OllamaPullError) as caught:
        ollama_pull.resolve_ollama_pull_target(config=cloud, home=tmp_path)
    assert caught.value.code == "OLLAMA_TARGET_NOT_CONFIGURED"

    explicit = ollama_pull.resolve_ollama_pull_target(
        "qwen3", config=cloud, home=tmp_path
    )
    default = ollama_pull.resolve_ollama_pull_target("qwen3", home=tmp_path)
    assert explicit.target_hash == default.target_hash


def test_configured_local_model_and_endpoint_are_used_without_explicit_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    config = local_config()
    monkeypatch.setattr(
        "fabric_cli.ollama_runtime._resolve_runtime_access",
        lambda *_args: ("http://127.0.0.1:11434", "", {}, True),
    )
    target = ollama_pull.resolve_ollama_pull_target(config=config, home=tmp_path)
    assert target.canonical_model == "qwen3:latest"
    assert target.endpoint_kind == "loopback"


def test_explicit_host_precedes_an_unusable_configured_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    config = local_config(endpoint="http://ollama.internal:11434")

    def should_not_resolve(*_args):
        raise AssertionError("an unrelated configured endpoint must not donate access")

    monkeypatch.setattr(
        "fabric_cli.ollama_runtime._resolve_runtime_access", should_not_resolve
    )
    explicit = ollama_pull.resolve_ollama_pull_target(
        "qwen3",
        "http://127.0.0.1:11434",
        config=config,
        home=tmp_path,
    )
    default = ollama_pull.resolve_ollama_pull_target("qwen3", home=tmp_path)
    assert explicit.target_hash == default.target_hash


def test_configured_credentials_headers_and_tls_are_reused_but_never_persisted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    config = local_config()
    seen_tls: dict[str, Any] = {}
    monkeypatch.setattr(
        "fabric_cli.ollama_runtime._resolve_runtime_access",
        lambda *_args: (
            "http://127.0.0.1:11434/v1",
            "profile-api-secret",
            {"X-Profile-Access": "header-secret"},
            True,
        ),
    )
    monkeypatch.setattr(
        "fabric_cli.config.get_custom_provider_tls_settings",
        lambda *_args, **_kwargs: {"ssl_ca_cert": "/safe/ca.pem", "ssl_verify": False},
    )

    def fake_verify(**kwargs):
        seen_tls.update(kwargs)
        return True

    monkeypatch.setattr("agent.ssl_verify.resolve_httpx_verify", fake_verify)
    daemon = Daemon(tags=[[], installed(DIGEST_B)])

    result = run_pull(tmp_path, daemon, config=config)

    assert result.exit_code == 0
    request = daemon.requests[0]
    assert request.headers["Authorization"] == "Bearer profile-api-secret"
    assert request.headers["X-Profile-Access"] == "header-secret"
    assert seen_tls == {
        "ca_bundle": "/safe/ca.pem",
        "ssl_verify": False,
        "base_url": "the configured Ollama endpoint",
    }
    persisted = json.dumps(ledger_payload(tmp_path / "profile"))
    assert "profile-api-secret" not in persisted
    assert "header-secret" not in persisted
    assert "ca.pem" not in persisted


def test_explicit_different_host_does_not_receive_configured_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    config = local_config()

    def should_not_resolve(*_args):
        raise AssertionError("configured access must not cross endpoint identities")

    monkeypatch.setattr(
        "fabric_cli.ollama_runtime._resolve_runtime_access", should_not_resolve
    )
    daemon = Daemon(tags=[[], installed(DIGEST_B)])
    result = run_pull(
        tmp_path,
        daemon,
        config=config,
        host="http://127.0.0.1:11435",
    )
    assert result.exit_code == 0
    assert "authorization" not in daemon.requests[0].headers
    assert daemon.requests[0].url.port == 11435


def test_unsafe_configured_header_fails_before_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        "fabric_cli.ollama_runtime._resolve_runtime_access",
        lambda *_args: (
            "http://127.0.0.1:11434",
            "",
            {"Host": "attacker.invalid"},
            True,
        ),
    )
    with pytest.raises(ollama_pull.OllamaPullError) as caught:
        ollama_pull.resolve_ollama_pull_target(config=local_config(), home=tmp_path)
    assert caught.value.code == "OLLAMA_ACCESS_INVALID"


def test_configured_accept_encoding_cannot_enable_response_decompression(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        "fabric_cli.ollama_runtime._resolve_runtime_access",
        lambda *_args: (
            "http://127.0.0.1:11434",
            "",
            {"Accept-Encoding": "gzip"},
            True,
        ),
    )
    with pytest.raises(ollama_pull.OllamaPullError) as caught:
        ollama_pull.resolve_ollama_pull_target(config=local_config(), home=tmp_path)
    assert caught.value.code == "OLLAMA_ACCESS_INVALID"


def test_no_redirect_is_followed(tmp_path: Path):
    redirect = httpx.Response(307, headers={"Location": "http://10.0.0.9/api/tags"})
    daemon = Daemon(tags=[redirect])
    result = run_pull(tmp_path, daemon)
    assert result.terminal_code == "OLLAMA_PROTOCOL_MISMATCH"
    assert result.exit_code == 1
    assert all(request.url.host == "127.0.0.1" for request in daemon.requests)
    assert not any(request.url.host == "10.0.0.9" for request in daemon.requests)


@pytest.mark.parametrize(
    "tags, expected",
    [
        ([httpx.Response(401)], "OLLAMA_AUTH_FAILED"),
        ([httpx.Response(200, json={"not_models": []})], "OLLAMA_PROTOCOL_MISMATCH"),
        ([httpx.ConnectError("secret transport detail")], "OLLAMA_UNREACHABLE"),
    ],
)
def test_preflight_failures_are_sanitized(
    tmp_path: Path, tags: list[Any], expected: str
):
    daemon = Daemon(tags=tags)
    result = run_pull(tmp_path, daemon)
    assert result.terminal_code == expected
    assert result.phase == "failed"
    assert result.partial_state == "partial_unknown"
    rendered = ollama_pull.format_ollama_pull_result(result)
    serialized = json.dumps(ledger_payload(tmp_path / "profile"))
    assert "secret transport detail" not in rendered
    assert "secret transport detail" not in serialized
    assert "127.0.0.1" not in serialized


def test_failed_preflight_cannot_reclassify_an_existing_model_as_pull_success(
    tmp_path: Path,
):
    daemon = Daemon(tags=[httpx.Response(401), installed(DIGEST_B)])
    result = run_pull(tmp_path, daemon)
    assert result.phase == "failed"
    assert result.exit_code == 1
    assert result.terminal_code == "OLLAMA_AUTH_FAILED"
    assert result.partial_state == "partial_unknown"
    assert result.final_model_digest is None
    assert not any(request.url.path == "/api/pull" for request in daemon.requests)


def test_encoded_catalog_is_rejected_without_decoding_its_body(tmp_path: Path):
    encoded = NeverReadStream()
    daemon = Daemon(
        tags=[
            httpx.Response(
                200,
                headers={"Content-Encoding": "gzip"},
                stream=encoded,
            ),
            [],
        ]
    )
    result = run_pull(tmp_path, daemon)
    assert result.terminal_code == "OLLAMA_PROTOCOL_MISMATCH"
    assert result.exit_code == 1
    assert encoded.closed is True


def test_encoded_pull_stream_is_rejected_without_reading_it(tmp_path: Path):
    daemon = Daemon(
        tags=[[], []],
        pull_headers={"Content-Encoding": "gzip"},
    )
    result = run_pull(tmp_path, daemon)
    assert result.terminal_code == "OLLAMA_PROTOCOL_MISMATCH"
    assert result.exit_code == 1
    assert daemon.pull_stream.closed is True


def test_daemon_no_space_is_classified_without_persisting_body(tmp_path: Path):
    daemon = Daemon(
        tags=[[], []],
        pull_chunks=[
            b'{"error":"write /secret/path: no space left on device token=abc"}\n'
        ],
    )
    result = run_pull(tmp_path, daemon)
    assert result.terminal_code == "OLLAMA_DISK_FULL"
    assert result.partial_state == "daemon_owned_partial_unknown"
    serialized = json.dumps(ledger_payload(tmp_path / "profile"))
    assert "/secret/path" not in serialized
    assert "token=abc" not in serialized


def test_final_model_requires_canonical_digest(tmp_path: Path):
    daemon = Daemon(tags=[[], installed("abc123"), installed("abc123")])
    result = run_pull(tmp_path, daemon)
    assert result.phase == "failed"
    assert result.terminal_code == "OLLAMA_DIGEST_INVALID"
    assert result.final_model_digest is None
    assert result.partial_state == "partial_unknown"


@pytest.mark.parametrize(
    "digest",
    ["sha256:" + "A" * 64, " sha256:" + "a" * 64, "sha256:" + "a" * 64 + " "],
)
def test_final_model_digest_must_be_exact_canonical_text(
    tmp_path: Path, digest: str
):
    daemon = Daemon(tags=[[], installed(digest), installed(digest)])
    result = run_pull(tmp_path, daemon)
    assert result.phase == "failed"
    assert result.terminal_code == "OLLAMA_DIGEST_INVALID"
    assert result.final_model_digest is None


def test_iter_ndjson_handles_split_chunks_and_drops_unknown_status_and_bad_counts():
    events = list(
        ollama_pull.iter_ollama_pull_events(
            [
                b'{"status":"future status","completed":999}\n{"status":"pull',
                (
                    'ing layer","digest":"%s","completed":11,"total":10}\n'
                    '{"status":"success"}' % LAYER_DIGEST
                ).encode(),
            ]
        )
    )
    assert len(events) == 2
    assert events[0].phase == "pulling"
    assert events[0].layer_digest == LAYER_DIGEST
    assert events[0].completed_bytes is None
    assert events[0].total_bytes == 10
    assert events[1].success is True


def test_iter_ndjson_enforces_total_and_line_bounds(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ollama_pull, "MAX_PULL_STREAM_BYTES", 8)
    with pytest.raises(ollama_pull.OllamaPullError) as caught:
        list(ollama_pull.iter_ollama_pull_events([b"123456789"]))
    assert caught.value.code == "OLLAMA_PROTOCOL_MISMATCH"

    monkeypatch.setattr(ollama_pull, "MAX_PULL_STREAM_BYTES", 1024)
    monkeypatch.setattr(ollama_pull, "MAX_PULL_LINE_BYTES", 4)
    with pytest.raises(ollama_pull.OllamaPullError):
        list(ollama_pull.iter_ollama_pull_events([b"12345"]))


def test_initial_tags_has_true_wall_clock_deadline_and_closes_stream(tmp_path: Path):
    trickle = TricklingStream()
    daemon = Daemon(tags=[trickle])
    started = time.monotonic()
    result = run_pull(tmp_path, daemon, preflight_timeout=0.05, reconcile_timeout=0.05)
    elapsed = time.monotonic() - started
    assert elapsed < 0.25
    assert trickle.closed is True
    assert result.terminal_code == "OLLAMA_UNREACHABLE"
    assert result.partial_state == "partial_unknown"


def test_reconciliation_has_true_wall_clock_deadline_and_closes_stream(tmp_path: Path):
    trickle = TricklingStream()
    daemon = Daemon(
        tags=[[], trickle],
        pull_chunks=[b'{"error":"ordinary failure"}\n'],
    )
    started = time.monotonic()
    result = run_pull(tmp_path, daemon, preflight_timeout=0.2, reconcile_timeout=0.05)
    elapsed = time.monotonic() - started
    assert elapsed < 0.3
    assert trickle.closed is True
    assert result.terminal_code == "OLLAMA_PULL_FAILED"
    assert result.partial_state == "partial_unknown"


def test_ctrl_c_during_tags_probe_closes_request_and_uses_fresh_reconciliation(
    tmp_path: Path,
):
    trickle = TricklingStream()
    daemon = Daemon(tags=[trickle, installed(DIGEST_B)])
    timer = threading.Timer(0.03, _thread.interrupt_main)
    timer.start()
    try:
        result = run_pull(
            tmp_path,
            daemon,
            preflight_timeout=1.0,
            reconcile_timeout=0.2,
        )
    finally:
        timer.cancel()
        timer.join(timeout=1)
    assert trickle.closed is True
    assert result.phase == "cancelled"
    assert result.exit_code == 130
    assert result.partial_state == "partial_unknown"
    assert result.final_model_digest is None
    assert [request.url.path for request in daemon.requests] == [
        "/api/tags",
        "/api/tags",
    ]


def test_ctrl_c_closes_response_and_reports_prior_model_preserved(tmp_path: Path):
    daemon = Daemon(
        tags=[installed(DIGEST_A), installed(DIGEST_A)],
        pull_chunks=[b'{"status":"pulling manifest"}\n'],
        pull_interrupt=True,
    )
    result = run_pull(tmp_path, daemon)
    assert daemon.pull_stream.closed is True
    assert result.exit_code == 130
    assert result.phase == "cancelled"
    assert result.terminal_code == "OLLAMA_CLIENT_CANCELLED"
    assert result.pre_model_digest == DIGEST_A
    assert result.final_model_digest == DIGEST_A
    assert result.partial_state == "prior_model_preserved"


def test_ctrl_c_completion_race_reports_ready_but_retains_130(tmp_path: Path):
    daemon = Daemon(
        tags=[[], installed(DIGEST_B)],
        pull_chunks=[b'{"status":"pulling manifest"}\n'],
        pull_interrupt=True,
    )
    result = run_pull(tmp_path, daemon)
    assert result.exit_code == 130
    assert result.phase == "ready"
    assert result.terminal_code == "OLLAMA_CLIENT_CANCELLED_READY"
    assert result.final_model_digest == DIGEST_B
    assert result.partial_state == "ready"
    assert "cancelled" in ollama_pull.format_ollama_pull_result(result).lower()


def test_invalid_prior_digest_cannot_make_failed_pull_look_successful(tmp_path: Path):
    daemon = Daemon(
        tags=[installed("not-canonical"), installed(DIGEST_B)],
        pull_chunks=[b'{"error":"ordinary failure"}\n'],
    )
    result = run_pull(tmp_path, daemon)
    assert result.phase == "failed"
    assert result.exit_code == 1
    assert result.terminal_code == "OLLAMA_PULL_FAILED"
    assert result.partial_state == "partial_unknown"
    assert result.final_model_digest is None


def test_observed_absence_allows_completion_race_after_pull_failure(tmp_path: Path):
    daemon = Daemon(
        tags=[[], installed(DIGEST_B)],
        pull_chunks=[b'{"error":"ordinary failure"}\n'],
    )
    result = run_pull(tmp_path, daemon)
    assert result.phase == "ready"
    assert result.exit_code == 0
    assert result.terminal_code == "OLLAMA_PULL_READY_AFTER_FAILURE"
    assert result.final_model_digest == DIGEST_B


def test_ctrl_c_absent_model_reports_daemon_owned_partial_unknown(tmp_path: Path):
    daemon = Daemon(
        tags=[[], []],
        pull_chunks=[b'{"status":"pulling manifest"}\n'],
        pull_interrupt=True,
    )
    result = run_pull(tmp_path, daemon)
    assert result.exit_code == 130
    assert result.partial_state == "daemon_owned_partial_unknown"


def test_callback_keyboard_interrupt_before_post_does_not_claim_daemon_partial(
    tmp_path: Path,
):
    daemon = Daemon(tags=[[], []])

    def cancel(update: ollama_pull.OllamaPullProgress):
        if update.phase == "pulling":
            raise KeyboardInterrupt

    result = run_pull(tmp_path, daemon, progress_callback=cancel)
    assert result.exit_code == 130
    assert result.partial_state == "partial_unknown"
    assert not any(request.url.path == "/api/pull" for request in daemon.requests)


def test_ordinary_callback_error_does_not_abort_pull(tmp_path: Path):
    daemon = Daemon(tags=[[], installed(DIGEST_B)])

    def broken_renderer(_update):
        raise RuntimeError("renderer secret")

    result = run_pull(tmp_path, daemon, progress_callback=broken_renderer)
    assert result.exit_code == 0


@pytest.mark.skipif(
    sys.platform == "win32", reason="Symlinks require elevated privileges on Windows"
)
def test_ledger_symlink_and_hardlink_targets_fail_closed(tmp_path: Path):
    home = tmp_path / "profile"
    target = ollama_pull.resolve_ollama_pull_target("qwen3", home=home)
    ledger_dir = home / "runtime" / "ollama-pulls"
    ledger_dir.mkdir(parents=True)
    victim = tmp_path / "victim"
    victim.write_text("do not change")
    ledger = ledger_dir / f"{target.target_hash}.json"
    ledger.symlink_to(victim)
    daemon = Daemon(tags=[[], installed(DIGEST_B)])
    with pytest.raises(ollama_pull.OllamaPullStateError):
        run_pull(tmp_path, daemon, home=home)
    assert victim.read_text() == "do not change"
    assert daemon.requests == []

    ledger.unlink()
    os.link(victim, ledger)
    with pytest.raises(ollama_pull.OllamaPullStateError):
        run_pull(tmp_path, daemon, home=home)
    assert victim.read_text() == "do not change"
    assert daemon.requests == []


@pytest.mark.skipif(
    sys.platform == "win32", reason="Symlinks require elevated privileges on Windows"
)
def test_redirected_ledger_directory_fails_before_network(tmp_path: Path):
    home = tmp_path / "profile"
    (home / "runtime").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (home / "runtime" / "ollama-pulls").symlink_to(outside, target_is_directory=True)
    daemon = Daemon(tags=[[], installed(DIGEST_B)])
    with pytest.raises(ollama_pull.OllamaPullStateError):
        run_pull(tmp_path, daemon, home=home)
    assert daemon.requests == []


def test_shared_endpoint_model_lock_is_cross_profile_and_model_specific(tmp_path: Path):
    root = tmp_path / "root"
    (tmp_path / "profiles" / "one").mkdir(parents=True)
    (tmp_path / "profiles" / "two").mkdir(parents=True)
    one = ollama_pull._prepare_ollama_pull(
        "qwen3",
        None,
        config={},
        home=tmp_path / "profiles" / "one",
        default_root=root,
    )
    two = ollama_pull._prepare_ollama_pull(
        "qwen3",
        None,
        config={},
        home=tmp_path / "profiles" / "two",
        default_root=root,
    )
    other = ollama_pull._prepare_ollama_pull(
        "llama3",
        None,
        config={},
        home=tmp_path / "profiles" / "two",
        default_root=root,
    )
    assert one.target.target_hash == two.target.target_hash
    assert other.target.target_hash != one.target.target_hash
    with ollama_pull._pull_lease(root, one.target.target_hash):
        with pytest.raises(ollama_pull.OllamaPullBusyError):
            with ollama_pull._pull_lease(root, two.target.target_hash):
                pass
        with ollama_pull._pull_lease(root, other.target.target_hash):
            pass


def test_config_mapping_and_selected_model_state_are_not_mutated(tmp_path: Path):
    config = {"model": {"default": "qwen3", "provider": "ollama", "base_url": ""}}
    before = deepcopy(config)
    daemon = Daemon(tags=[[], installed(DIGEST_B)])
    result = run_pull(tmp_path, daemon, config=config, model="qwen3")
    assert result.exit_code == 0
    assert config == before


def test_command_confirms_and_executes_same_prepared_target(
    monkeypatch: pytest.MonkeyPatch,
):
    first = SimpleNamespace(canonical_model="first:latest")
    prepared = SimpleNamespace(target=first)
    prepared_calls = 0
    executed: list[Any] = []

    def prepare(*_args, **_kwargs):
        nonlocal prepared_calls
        prepared_calls += 1
        return prepared

    def execute(value, **_kwargs):
        executed.append(value)
        return SimpleNamespace(
            phase="ready", exit_code=0, terminal_code="OLLAMA_PULL_READY"
        )

    monkeypatch.setattr(ollama_pull, "_prepare_ollama_pull", prepare)
    monkeypatch.setattr(ollama_pull, "_execute_prepared_pull", execute)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: "yes")
    monkeypatch.setattr(ollama_pull, "format_ollama_pull_result", lambda _result: "ready")
    assert ollama_pull.cmd_ollama_pull(SimpleNamespace(model="x", host=None, yes=False)) == 0
    assert prepared_calls == 1
    assert executed == [prepared]


def test_command_requires_yes_when_noninteractive(monkeypatch: pytest.MonkeyPatch):
    prepared = SimpleNamespace(target=SimpleNamespace(canonical_model="qwen3:latest"))
    monkeypatch.setattr(ollama_pull, "_prepare_ollama_pull", lambda *_a, **_k: prepared)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    called = False

    def execute(*_args, **_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(ollama_pull, "_execute_prepared_pull", execute)
    assert ollama_pull.cmd_ollama_pull(SimpleNamespace(model="qwen3", yes=False)) == 1
    assert called is False


def test_command_decline_returns_130_without_execution(monkeypatch: pytest.MonkeyPatch):
    prepared = SimpleNamespace(target=SimpleNamespace(canonical_model="qwen3:latest"))
    monkeypatch.setattr(ollama_pull, "_prepare_ollama_pull", lambda *_a, **_k: prepared)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: "no")
    monkeypatch.setattr(
        ollama_pull,
        "_execute_prepared_pull",
        lambda *_a, **_k: pytest.fail("declined pull must not execute"),
    )
    assert ollama_pull.cmd_ollama_pull(SimpleNamespace(model="qwen3", yes=False)) == 130
