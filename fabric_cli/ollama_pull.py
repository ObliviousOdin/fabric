"""Foreground, profile-scoped Ollama model pulls.

This module is a domain adapter, not a model tool.  It deliberately exposes
only sanitized progress and terminal records: endpoint URLs, headers,
credentials, response bodies, and transport exception text never cross its
public boundary or enter the profile ledger.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import socket
import stat
import tempfile
import threading
from typing import Any
from urllib.parse import urlsplit
import uuid

from fabric_constants import get_default_fabric_root, get_fabric_home
from tools.skill_install import is_path_redirect


OLLAMA_PULL_SCHEMA_VERSION = 1
DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"
MAX_TAGS_BODY_BYTES = 1024 * 1024
MAX_PULL_STREAM_BYTES = 16 * 1024 * 1024
MAX_PULL_LINE_BYTES = 64 * 1024
MAX_PULL_RECORDS = 10_000
MAX_PROGRESS_BYTES = (1 << 63) - 1

_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_MODEL_RE = re.compile(
    r"^[a-z0-9][a-z0-9._-]*(?:/[a-z0-9][a-z0-9._-]*)*"
    r"(?::[a-z0-9][a-z0-9._-]*)?$"
)
_HEADER_NAME_RE = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_CGNAT = ipaddress.IPv4Network("100.64.0.0/10")
_RFC1918 = (
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
)
_IPV6_ULA = ipaddress.IPv6Network("fc00::/7")
_METADATA_ADDRESSES = frozenset(
    {
        ipaddress.ip_address("100.100.100.200"),  # Alibaba Cloud IMDS
        ipaddress.ip_address("169.254.169.254"),  # AWS/GCP/Azure/OCI IMDS
        ipaddress.ip_address("fd00:ec2::254"),  # AWS IMDS IPv6
    }
)
_FORBIDDEN_EXTRA_HEADERS = frozenset(
    {
        "accept-encoding",
        "connection",
        "content-length",
        "host",
        "te",
        "transfer-encoding",
        "upgrade",
    }
)

_PHASES = frozenset(
    {"queued", "preflight", "pulling", "verifying", "ready", "cancelled", "failed"}
)
_PARTIAL_STATES = frozenset(
    {
        "not_checked",
        "ready",
        "prior_model_preserved",
        "daemon_owned_partial_unknown",
        "partial_unknown",
    }
)


class OllamaPullError(RuntimeError):
    """A safe, machine-classified error raised before a pull can run."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class OllamaPullBusyError(OllamaPullError):
    """Another process already owns the endpoint-and-model pull lease."""


class OllamaPullStateError(OllamaPullError):
    """The durable state or lock path failed its trust checks."""


@dataclass(frozen=True)
class ResolvedOllamaPullTarget:
    """Public, secret-free identity for one pull target."""

    profile_scope_id: str
    endpoint_kind: str
    endpoint_fingerprint: str
    canonical_model: str
    target_hash: str


@dataclass(frozen=True)
class OllamaPullProgress:
    """One allowlisted progress update safe for UI rendering."""

    phase: str
    canonical_model: str
    completed_bytes: int | None = None
    total_bytes: int | None = None
    layer_digest: str | None = None


@dataclass(frozen=True)
class OllamaPullResult:
    """Sanitized terminal snapshot returned to the CLI adapter."""

    schema_version: int
    operation_id: str
    profile_scope_id: str
    endpoint_kind: str
    endpoint_fingerprint: str
    canonical_model: str
    phase: str
    completed_bytes: int | None
    total_bytes: int | None
    pre_model_digest: str | None
    final_model_digest: str | None
    terminal_code: str
    partial_state: str
    disk_preflight: str
    exit_code: int

    def to_ledger_dict(self) -> dict[str, Any]:
        """Return the exact secret-free profile-ledger representation."""

        return asdict(self)


@dataclass(frozen=True)
class _Endpoint:
    root_url: str
    material: str
    kind: str
    fingerprint: str


@dataclass(frozen=True)
class _Access:
    endpoint: _Endpoint
    headers: dict[str, str]
    verify: Any


@dataclass(frozen=True)
class _PreparedPull:
    target: ResolvedOllamaPullTarget
    access: _Access
    home: Path
    default_root: Path


@dataclass(frozen=True)
class _PullEvent:
    phase: str
    completed_bytes: int | None
    total_bytes: int | None
    layer_digest: str | None
    success: bool


@dataclass(frozen=True)
class _Catalog:
    model_digest: str | None
    model_present: bool
    digest_valid: bool


class _AdapterFailure(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class _Operation:
    operation_id: str
    target: ResolvedOllamaPullTarget
    ledger_path: Path
    phase: str = "queued"
    completed_bytes: int | None = None
    total_bytes: int | None = None
    pre_model_digest: str | None = None
    final_model_digest: str | None = None
    preflight_observed: bool = False
    pre_model_present: bool = False
    pull_attempted: bool = False
    terminal_code: str = "OLLAMA_PULL_PENDING"
    partial_state: str = "not_checked"
    exit_code: int = 1

    def result(self) -> OllamaPullResult:
        return OllamaPullResult(
            schema_version=OLLAMA_PULL_SCHEMA_VERSION,
            operation_id=self.operation_id,
            profile_scope_id=self.target.profile_scope_id,
            endpoint_kind=self.target.endpoint_kind,
            endpoint_fingerprint=self.target.endpoint_fingerprint,
            canonical_model=self.target.canonical_model,
            phase=self.phase,
            completed_bytes=self.completed_bytes,
            total_bytes=self.total_bytes,
            pre_model_digest=self.pre_model_digest,
            final_model_digest=self.final_model_digest,
            terminal_code=self.terminal_code,
            partial_state=self.partial_state,
            disk_preflight="unavailable",
            exit_code=self.exit_code,
        )


ProgressCallback = Callable[[OllamaPullProgress], None]
AddressResolver = Callable[..., list[tuple[Any, ...]]]


def _profile_scope_id(home: Path) -> str:
    try:
        material = str(home.expanduser().resolve())
    except OSError:
        material = str(home.expanduser().absolute())
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _canonical_model(raw_model: str | None) -> str:
    value = str(raw_model or "").strip()
    if not value or len(value) > 256 or _CONTROL_RE.search(value):
        raise OllamaPullError("OLLAMA_MODEL_INVALID", "Use a valid Ollama model name.")
    try:
        from fabric_cli.ollama_runtime import _bare_model

        value = _bare_model(value)
    except OllamaPullError:
        raise
    except Exception:
        raise OllamaPullError(
            "OLLAMA_MODEL_INVALID", "Use a valid Ollama model name."
        ) from None
    value = value.strip().lower()
    if not value or len(value) > 200 or not _MODEL_RE.fullmatch(value):
        raise OllamaPullError("OLLAMA_MODEL_INVALID", "Use a valid Ollama model name.")
    name, separator, tag = value.rpartition(":")
    if not separator:
        name, tag = value, "latest"
    if any(part in {".", ".."} for part in name.split("/")) or not tag:
        raise OllamaPullError("OLLAMA_MODEL_INVALID", "Use a valid Ollama model name.")
    return f"{name}:{tag}"


def _allowed_destination(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    mapped = address.ipv4_mapped if isinstance(address, ipaddress.IPv6Address) else None
    if mapped is not None:
        return _allowed_destination(mapped)
    if (
        address in _METADATA_ADDRESSES
        or address.is_unspecified
        or address.is_link_local
        or address.is_multicast
    ):
        return False
    if address.is_loopback:
        return True
    if isinstance(address, ipaddress.IPv4Address):
        return address in _CGNAT or any(address in network for network in _RFC1918)
    return address in _IPV6_ULA


def _validate_endpoint(
    raw_endpoint: str,
    *,
    resolver: AddressResolver,
) -> _Endpoint:
    value = str(raw_endpoint or "").strip()
    if not value or len(value) > 2048 or _CONTROL_RE.search(value):
        raise OllamaPullError(
            "OLLAMA_ENDPOINT_INVALID", "Use a local or private HTTP(S) Ollama endpoint."
        )
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise OllamaPullError(
            "OLLAMA_ENDPOINT_INVALID", "Use a local or private HTTP(S) Ollama endpoint."
        ) from None
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/", "/v1", "/v1/"}
        or "%" in parsed.netloc
        or "%" in parsed.path
    ):
        raise OllamaPullError(
            "OLLAMA_ENDPOINT_INVALID", "Use a local or private HTTP(S) Ollama endpoint."
        )
    host = parsed.hostname.lower().rstrip(".")
    if not host or not host.isascii() or any(char.isspace() for char in host):
        raise OllamaPullError(
            "OLLAMA_ENDPOINT_INVALID", "Use a local or private HTTP(S) Ollama endpoint."
        )
    effective_port = port or (443 if parsed.scheme.lower() == "https" else 80)
    if effective_port < 1 or effective_port > 65535:
        raise OllamaPullError(
            "OLLAMA_ENDPOINT_INVALID", "Use a local or private HTTP(S) Ollama endpoint."
        )

    # httpx resolves hostnames again while connecting.  A preflight
    # ``getaddrinfo`` check alone would therefore be vulnerable to DNS
    # rebinding.  Until Fabric has a transport that pins the validated address
    # while preserving HTTPS hostname/SNI verification, this mutation accepts
    # only IP literals.  ``localhost`` is converted to a loopback literal so it
    # cannot be rebound between validation and POST.
    del resolver
    if host == "localhost":
        address: ipaddress.IPv4Address | ipaddress.IPv6Address = ipaddress.ip_address(
            "127.0.0.1"
        )
    else:
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            raise OllamaPullError(
                "OLLAMA_ENDPOINT_HOSTNAME_UNPINNED",
                "Use a private IP literal for this Ollama pull endpoint.",
            ) from None
    if not _allowed_destination(address):
        raise OllamaPullError(
            "OLLAMA_ENDPOINT_NOT_PRIVATE",
            "Ollama pulls are limited to local or private destinations.",
        )
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        # Collapse mapped literals before endpoint fingerprinting and locking;
        # otherwise 127.0.0.1 and ::ffff:127.0.0.1 could address the same
        # daemon while acquiring different single-flight leases.
        address = address.ipv4_mapped

    scheme = parsed.scheme.lower()
    default_port = 443 if scheme == "https" else 80
    canonical_host = address.compressed
    host_text = f"[{canonical_host}]" if ":" in canonical_host else canonical_host
    authority = host_text if effective_port == default_port else f"{host_text}:{effective_port}"
    material = f"{scheme}://{authority}"
    fingerprint = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    if address.is_loopback:
        kind = "loopback"
    else:
        kind = "private-network"
    return _Endpoint(
        root_url=material,
        material=material,
        kind=kind,
        fingerprint=fingerprint,
    )


@contextmanager
def _scoped_profile(home: Path) -> Iterator[None]:
    from agent.secret_scope import build_profile_secret_scope, reset_secret_scope, set_secret_scope
    from fabric_constants import reset_fabric_home_override, set_fabric_home_override

    home_token = set_fabric_home_override(home)
    secret_token = set_secret_scope(build_profile_secret_scope(home))
    try:
        yield
    finally:
        try:
            reset_secret_scope(secret_token)
        finally:
            reset_fabric_home_override(home_token)


def _safe_headers(raw_headers: Mapping[str, Any], api_key: str) -> dict[str, str]:
    headers: dict[str, str] = {
        "Accept": "application/x-ndjson, application/json",
        "Accept-Encoding": "identity",
    }
    for raw_name, raw_value in raw_headers.items():
        name = str(raw_name).strip()
        value = str(raw_value)
        lowered = name.lower()
        if (
            not name
            or len(name) > 128
            or not _HEADER_NAME_RE.fullmatch(name)
            or lowered in _FORBIDDEN_EXTRA_HEADERS
            or len(value) > 8192
            or _CONTROL_RE.search(value)
        ):
            raise OllamaPullError(
                "OLLAMA_ACCESS_INVALID",
                "The configured Ollama access policy contains an unsafe header.",
            )
        headers[name] = value
    if api_key and not any(name.lower() == "authorization" for name in headers):
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _resolve_target_and_access(
    *,
    model: str | None,
    host: str | None,
    config: Mapping[str, Any] | None,
    home: Path,
    resolver: AddressResolver,
) -> tuple[ResolvedOllamaPullTarget, _Access]:
    from fabric_cli.config import get_custom_provider_tls_settings, load_config
    from fabric_cli.ollama_runtime import _configured_values, is_ollama_readiness_candidate

    with _scoped_profile(home):
        cfg = dict(config) if config is not None else load_config()
        cfg_model, provider, cfg_url, _, _, _ = _configured_values(cfg)
        configured_local = is_ollama_readiness_candidate(cfg)

        explicit_model = bool(str(model or "").strip())
        selected_model = model if explicit_model else (cfg_model if configured_local else None)
        if selected_model is None:
            raise OllamaPullError(
                "OLLAMA_TARGET_NOT_CONFIGURED",
                "Specify a model or configure a local Ollama model for this profile.",
            )

        if str(host or "").strip():
            raw_endpoint = str(host).strip()
        elif configured_local:
            raw_endpoint = cfg_url
        elif explicit_model:
            raw_endpoint = DEFAULT_OLLAMA_HOST
        else:  # Defensive: selected_model can only exist through a branch above.
            raise OllamaPullError(
                "OLLAMA_TARGET_NOT_CONFIGURED",
                "Specify a model or configure a local Ollama model for this profile.",
            )

        endpoint = _validate_endpoint(raw_endpoint, resolver=resolver)
        configured_endpoint: _Endpoint | None = None
        if configured_local:
            try:
                configured_endpoint = _validate_endpoint(cfg_url, resolver=resolver)
            except OllamaPullError:
                # An explicit destination is authoritative.  An unrelated
                # configured endpoint that cannot satisfy this mutation's
                # stricter pinning policy must not block it or donate access.
                if not str(host or "").strip():
                    raise
        reuse_configured_access = bool(
            configured_endpoint and configured_endpoint.material == endpoint.material
        )

        resolved_headers: Mapping[str, Any] = {}
        resolved_key = ""
        if reuse_configured_access:
            from fabric_cli.ollama_runtime import _resolve_runtime_access

            resolved_url, resolved_key, resolved_headers, resolved = _resolve_runtime_access(
                provider, cfg_url, str(selected_model)
            )
            if not resolved:
                raise OllamaPullError(
                    "OLLAMA_ACCESS_UNAVAILABLE",
                    "Fabric could not resolve this profile's stored Ollama access policy.",
                )
            resolved_endpoint = _validate_endpoint(resolved_url, resolver=resolver)
            if resolved_endpoint.material != endpoint.material:
                raise OllamaPullError(
                    "OLLAMA_ACCESS_ENDPOINT_MISMATCH",
                    "The stored Ollama access policy resolved to a different destination.",
                )
            if not isinstance(resolved_key, str):
                raise OllamaPullError(
                    "OLLAMA_ACCESS_INVALID",
                    "The configured Ollama access policy is not supported for model pulls.",
                )

        headers = _safe_headers(resolved_headers, resolved_key)
        if reuse_configured_access:
            from agent.ssl_verify import resolve_httpx_verify

            tls = get_custom_provider_tls_settings(cfg_url, config=cfg)
            verify = resolve_httpx_verify(
                ca_bundle=tls.get("ssl_ca_cert"),
                ssl_verify=tls.get("ssl_verify"),
                base_url="the configured Ollama endpoint",
            )
        else:
            verify = True

    canonical_model = _canonical_model(selected_model)
    target_material = f"{endpoint.material}\0{canonical_model}"
    target_hash = hashlib.sha256(target_material.encode("utf-8")).hexdigest()
    target = ResolvedOllamaPullTarget(
        profile_scope_id=_profile_scope_id(home),
        endpoint_kind=endpoint.kind,
        endpoint_fingerprint=endpoint.fingerprint,
        canonical_model=canonical_model,
        target_hash=target_hash,
    )
    return target, _Access(endpoint=endpoint, headers=headers, verify=verify)


def resolve_ollama_pull_target(
    model: str | None = None,
    host: str | None = None,
    *,
    config: Mapping[str, Any] | None = None,
    home: Path | None = None,
    resolver: AddressResolver = socket.getaddrinfo,
) -> ResolvedOllamaPullTarget:
    """Resolve a pull target without returning its endpoint or credentials."""

    effective_home = Path(home) if home is not None else Path(get_fabric_home())
    target, _ = _resolve_target_and_access(
        model=model,
        host=host,
        config=config,
        home=effective_home,
        resolver=resolver,
    )
    return target


def _prepare_ollama_pull(
    model: str | None,
    host: str | None,
    *,
    config: Mapping[str, Any] | None = None,
    home: Path | None = None,
    default_root: Path | None = None,
    resolver: AddressResolver = socket.getaddrinfo,
) -> _PreparedPull:
    effective_home = Path(home) if home is not None else Path(get_fabric_home())
    target, access = _resolve_target_and_access(
        model=model,
        host=host,
        config=config,
        home=effective_home,
        resolver=resolver,
    )
    if default_root is None:
        if effective_home.parent.name == "profiles":
            effective_root = effective_home.parent.parent
        else:
            effective_root = Path(get_default_fabric_root())
            try:
                effective_home.resolve().relative_to(effective_root.resolve())
            except (OSError, ValueError):
                effective_root = effective_home
    else:
        effective_root = Path(default_root)
    return _PreparedPull(
        target=target,
        access=access,
        home=effective_home,
        default_root=effective_root,
    )


def _secure_directory(root: Path, *parts: str) -> Path:
    """Create trusted descendants while rejecting redirect components."""

    try:
        root = root.expanduser().resolve()
        if not root.is_dir():
            root.mkdir(parents=True, mode=0o700, exist_ok=True)
        if not root.is_dir():
            raise OSError
        current = root
        for part in parts:
            current = current / part
            if is_path_redirect(current):
                raise OSError
            try:
                current.mkdir(mode=0o700)
            except FileExistsError:
                pass
            info = current.lstat()
            if not stat.S_ISDIR(info.st_mode) or is_path_redirect(current):
                raise OSError
            if current.resolve() != current:
                raise OSError
        return current
    except (OSError, RuntimeError):
        raise OllamaPullStateError(
            "OLLAMA_STATE_UNSAFE", "The Ollama pull state path is not safe to use."
        ) from None


def _atomic_ledger_write(path: Path, payload: Mapping[str, Any]) -> None:
    """Atomically write a 0600 regular file without following link targets."""

    parent = path.parent
    temp_path: str | None = None
    try:
        if is_path_redirect(parent) or parent.resolve() != parent:
            raise OSError
        if path.exists() or path.is_symlink():
            if is_path_redirect(path):
                raise OSError
            existing = path.lstat()
            if not stat.S_ISREG(existing.st_mode) or existing.st_nlink != 1:
                raise OSError
        encoded = json.dumps(
            dict(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
        if len(encoded) > 64 * 1024:
            raise OSError
        descriptor, temp_path = tempfile.mkstemp(
            dir=str(parent), prefix=f".{path.stem}-", suffix=".tmp"
        )
        try:
            if hasattr(os, "fchmod"):
                os.fchmod(descriptor, 0o600)
            written = 0
            while written < len(encoded):
                written += os.write(descriptor, encoded[written:])
            os.fsync(descriptor)
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
                raise OSError
        finally:
            os.close(descriptor)

        if is_path_redirect(parent) or parent.resolve() != parent:
            raise OSError
        if path.exists() or path.is_symlink():
            if is_path_redirect(path):
                raise OSError
            current = path.lstat()
            if not stat.S_ISREG(current.st_mode) or current.st_nlink != 1:
                raise OSError
        os.replace(temp_path, path)
        temp_path = None
        os.chmod(path, 0o600)
        final = path.lstat()
        if not stat.S_ISREG(final.st_mode) or final.st_nlink != 1:
            raise OSError
        if os.name != "nt":
            directory_fd = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except (OSError, RuntimeError, TypeError, ValueError):
        raise OllamaPullStateError(
            "OLLAMA_STATE_UNSAFE", "The Ollama pull state could not be stored safely."
        ) from None
    finally:
        if temp_path is not None:
            try:
                os.unlink(temp_path)
            except OSError:
                pass


_process_lock_guard = threading.Lock()
_process_locks: set[str] = set()


@contextmanager
def _pull_lease(default_root: Path, target_hash: str) -> Iterator[None]:
    lock_dir = _secure_directory(default_root, "runtime", "ollama-pull-locks")
    lock_path = lock_dir / f"{target_hash}.lock"
    lock_key = str(lock_path)
    with _process_lock_guard:
        if lock_key in _process_locks:
            raise OllamaPullBusyError(
                "OLLAMA_PULL_BUSY", "Another pull is already running for this Ollama model."
            )
        _process_locks.add(lock_key)

    descriptor: int | None = None
    acquired = False
    try:
        if is_path_redirect(lock_path):
            raise OllamaPullStateError(
                "OLLAMA_STATE_UNSAFE", "The Ollama pull lock path is not safe to use."
            )
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(lock_path, flags, 0o600)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise OllamaPullStateError(
                "OLLAMA_STATE_UNSAFE", "The Ollama pull lock path is not safe to use."
            )
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        try:
            if os.name == "nt":
                import msvcrt

                if opened.st_size == 0:
                    os.write(descriptor, b" ")
                    os.fsync(descriptor)
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except (BlockingIOError, OSError):
            raise OllamaPullBusyError(
                "OLLAMA_PULL_BUSY", "Another pull is already running for this Ollama model."
            ) from None
        yield
    finally:
        if descriptor is not None:
            if acquired:
                try:
                    if os.name == "nt":
                        import msvcrt

                        os.lseek(descriptor, 0, os.SEEK_SET)
                        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(descriptor, fcntl.LOCK_UN)
                except OSError:
                    pass
            os.close(descriptor)
        with _process_lock_guard:
            _process_locks.discard(lock_key)


def _bounded_nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 0 or value > MAX_PROGRESS_BYTES:
        return None
    return value


def _canonical_digest(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value if _DIGEST_RE.fullmatch(value) else None


def _classify_error_text(value: Any) -> str:
    text = str(value or "").lower()
    if any(
        marker in text
        for marker in ("no space left on device", "insufficient disk space", "disk quota exceeded")
    ):
        return "OLLAMA_DISK_FULL"
    return "OLLAMA_PULL_FAILED"


def iter_ollama_pull_events(chunks: Iterable[bytes]) -> Iterator[_PullEvent]:
    """Parse bounded Ollama NDJSON into allowlisted, sanitized events."""

    buffer = bytearray()
    total_seen = 0
    record_count = 0

    def parse_line(raw: bytes) -> _PullEvent | None:
        nonlocal record_count
        record_count += 1
        if record_count > MAX_PULL_RECORDS or len(raw) > MAX_PULL_LINE_BYTES:
            raise OllamaPullError(
                "OLLAMA_PROTOCOL_MISMATCH", "The Ollama pull stream exceeded its safe limits."
            )
        try:
            item = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise OllamaPullError(
                "OLLAMA_PROTOCOL_MISMATCH", "The endpoint returned an invalid Ollama pull stream."
            ) from None
        if not isinstance(item, Mapping):
            raise OllamaPullError(
                "OLLAMA_PROTOCOL_MISMATCH", "The endpoint returned an invalid Ollama pull stream."
            )
        if item.get("error"):
            code = _classify_error_text(item.get("error"))
            message = (
                "Ollama reported insufficient disk space."
                if code == "OLLAMA_DISK_FULL"
                else "Ollama could not complete the model pull."
            )
            raise OllamaPullError(code, message)
        status = str(item.get("status") or "").strip().lower()
        if status == "success":
            phase, success = "verifying", True
        elif status.startswith(("pulling ", "downloading ")):
            phase, success = "pulling", False
        elif status.startswith(("verifying ", "writing ", "removing ")):
            phase, success = "verifying", False
        else:
            return None
        total = _bounded_nonnegative_int(item.get("total"))
        completed = _bounded_nonnegative_int(item.get("completed"))
        if total is not None and completed is not None and completed > total:
            completed = None
        return _PullEvent(
            phase=phase,
            completed_bytes=completed,
            total_bytes=total,
            layer_digest=_canonical_digest(item.get("digest")),
            success=success,
        )

    for chunk in chunks:
        if not isinstance(chunk, bytes):
            raise OllamaPullError(
                "OLLAMA_PROTOCOL_MISMATCH", "The endpoint returned an invalid Ollama pull stream."
            )
        total_seen += len(chunk)
        if total_seen > MAX_PULL_STREAM_BYTES:
            raise OllamaPullError(
                "OLLAMA_PROTOCOL_MISMATCH", "The Ollama pull stream exceeded its safe limits."
            )
        buffer.extend(chunk)
        while True:
            newline = buffer.find(b"\n")
            if newline < 0:
                break
            raw = bytes(buffer[:newline]).rstrip(b"\r")
            del buffer[: newline + 1]
            if not raw:
                continue
            event = parse_line(raw)
            if event is not None:
                yield event
        if len(buffer) > MAX_PULL_LINE_BYTES:
            raise OllamaPullError(
                "OLLAMA_PROTOCOL_MISMATCH", "The Ollama pull stream exceeded its safe limits."
            )
    if buffer:
        event = parse_line(bytes(buffer).rstrip(b"\r"))
        if event is not None:
            yield event


def _read_bounded_json(response: Any, limit: int) -> Any:
    content_encoding = response.headers.get("content-encoding", "").strip().lower()
    if content_encoding and content_encoding != "identity":
        raise _AdapterFailure("OLLAMA_PROTOCOL_MISMATCH")
    content_length = response.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > limit:
                raise _AdapterFailure("OLLAMA_PROTOCOL_MISMATCH")
        except ValueError:
            raise _AdapterFailure("OLLAMA_PROTOCOL_MISMATCH") from None
    body = bytearray()
    chunks = (
        (response.content,)
        if response.is_stream_consumed
        else response.iter_raw()
    )
    for chunk in chunks:
        body.extend(chunk)
        if len(body) > limit:
            raise _AdapterFailure("OLLAMA_PROTOCOL_MISMATCH")
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise _AdapterFailure("OLLAMA_PROTOCOL_MISMATCH") from None


def _fetch_catalog_sync(
    client: Any,
    access: _Access,
    model: str,
    request_timeout: float,
    active: dict[str, Any],
    active_lock: threading.Lock,
) -> _Catalog:
    try:
        with client.stream(
            "GET", f"{access.endpoint.root_url}/api/tags", timeout=request_timeout
        ) as response:
            with active_lock:
                active["response"] = response
            status = int(response.status_code)
            if status in {401, 403}:
                raise _AdapterFailure("OLLAMA_AUTH_FAILED")
            if 300 <= status < 400 or status != 200:
                raise _AdapterFailure("OLLAMA_PROTOCOL_MISMATCH")
            payload = _read_bounded_json(response, MAX_TAGS_BODY_BYTES)
    except KeyboardInterrupt:
        raise
    except _AdapterFailure:
        raise
    except Exception:
        raise _AdapterFailure("OLLAMA_UNREACHABLE") from None
    if not isinstance(payload, Mapping) or not isinstance(payload.get("models"), list):
        raise _AdapterFailure("OLLAMA_PROTOCOL_MISMATCH")
    try:
        from fabric_cli.ollama_runtime import _matches_model
    except Exception:
        raise _AdapterFailure("OLLAMA_PROTOCOL_MISMATCH") from None
    for entry in payload["models"]:
        if not isinstance(entry, Mapping):
            continue
        candidate = str(entry.get("name") or entry.get("model") or "")
        if not _matches_model(candidate, model):
            continue
        digest = _canonical_digest(entry.get("digest"))
        return _Catalog(model_digest=digest, model_present=True, digest_valid=digest is not None)
    return _Catalog(model_digest=None, model_present=False, digest_valid=True)


def _fetch_catalog(client: Any, access: _Access, model: str, timeout: float) -> _Catalog:
    """Fetch tags behind a true wall-clock deadline.

    httpx's read timeout is an inactivity budget; a daemon can otherwise send
    one tiny chunk per interval forever.  A daemon worker lets the caller stop
    waiting at the absolute deadline and actively close both the response and
    client.  No worker exception text crosses this boundary.
    """

    try:
        requested_budget = float(timeout)
    except (TypeError, ValueError):
        requested_budget = 5.0
    if not math.isfinite(requested_budget):
        requested_budget = 5.0
    budget = max(0.05, min(requested_budget, 30.0))
    done = threading.Event()
    active: dict[str, Any] = {}
    active_lock = threading.Lock()

    def fetch() -> None:
        try:
            result = _fetch_catalog_sync(
                client, access, model, budget, active, active_lock
            )
        except BaseException as exc:  # transported only by type/classification
            with active_lock:
                active["error"] = exc
        else:
            with active_lock:
                active["result"] = result
        finally:
            done.set()

    worker = threading.Thread(target=fetch, name="ollama-tags-probe", daemon=True)
    worker.start()

    def close_active_request() -> None:
        with active_lock:
            response = active.get("response")
        if response is not None:
            try:
                response.close()
            except Exception:
                pass
        try:
            client.close()
        except Exception:
            pass

    try:
        completed = done.wait(budget)
    except KeyboardInterrupt:
        close_active_request()
        raise
    if not completed:
        close_active_request()
        raise _AdapterFailure("OLLAMA_UNREACHABLE")

    with active_lock:
        error = active.get("error")
        result = active.get("result")
    if isinstance(error, KeyboardInterrupt):
        raise KeyboardInterrupt
    if isinstance(error, _AdapterFailure):
        raise _AdapterFailure(error.code)
    if error is not None or not isinstance(result, _Catalog):
        raise _AdapterFailure("OLLAMA_UNREACHABLE")
    return result


def _emit(
    operation: _Operation,
    callback: ProgressCallback | None,
    *,
    layer_digest: str | None = None,
) -> None:
    if operation.phase not in _PHASES:
        raise OllamaPullStateError(
            "OLLAMA_STATE_UNSAFE", "The Ollama pull entered an invalid state."
        )
    if operation.partial_state not in _PARTIAL_STATES:
        raise OllamaPullStateError(
            "OLLAMA_STATE_UNSAFE", "The Ollama pull entered an invalid state."
        )
    _atomic_ledger_write(operation.ledger_path, operation.result().to_ledger_dict())
    if callback is None:
        return
    update = OllamaPullProgress(
        phase=operation.phase,
        canonical_model=operation.target.canonical_model,
        completed_bytes=operation.completed_bytes,
        total_bytes=operation.total_bytes,
        layer_digest=layer_digest,
    )
    try:
        callback(update)
    except KeyboardInterrupt:
        raise
    except Exception:
        # Rendering cannot corrupt or abort the domain operation.
        pass


def _run_stream(
    client: Any,
    access: _Access,
    operation: _Operation,
    callback: ProgressCallback | None,
) -> None:
    operation.pull_attempted = True
    try:
        with client.stream(
            "POST",
            f"{access.endpoint.root_url}/api/pull",
            json={"model": operation.target.canonical_model, "stream": True},
        ) as response:
            status = int(response.status_code)
            if status in {401, 403}:
                raise _AdapterFailure("OLLAMA_AUTH_FAILED")
            if status == 507:
                raise _AdapterFailure("OLLAMA_DISK_FULL")
            if 300 <= status < 400 or status != 200:
                raise _AdapterFailure("OLLAMA_PULL_FAILED")
            content_encoding = response.headers.get("content-encoding", "").strip().lower()
            if content_encoding and content_encoding != "identity":
                raise _AdapterFailure("OLLAMA_PROTOCOL_MISMATCH")
            content_length = response.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > MAX_PULL_STREAM_BYTES:
                        raise _AdapterFailure("OLLAMA_PROTOCOL_MISMATCH")
                except ValueError:
                    raise _AdapterFailure("OLLAMA_PROTOCOL_MISMATCH") from None
            saw_success = False
            try:
                events = iter_ollama_pull_events(response.iter_raw())
                for event in events:
                    operation.phase = event.phase
                    if event.completed_bytes is not None:
                        operation.completed_bytes = event.completed_bytes
                    if event.total_bytes is not None:
                        operation.total_bytes = event.total_bytes
                    _emit(operation, callback, layer_digest=event.layer_digest)
                    if event.success:
                        saw_success = True
                        break
            except OllamaPullError as exc:
                raise _AdapterFailure(exc.code) from None
            if not saw_success:
                raise _AdapterFailure("OLLAMA_PULL_FAILED")
    except KeyboardInterrupt:
        raise
    except _AdapterFailure:
        raise
    except Exception:
        raise _AdapterFailure("OLLAMA_UNREACHABLE") from None


def _reconcile(
    client: Any,
    access: _Access,
    operation: _Operation,
    timeout: float,
) -> tuple[str, str | None]:
    try:
        catalog = _fetch_catalog(
            client, access, operation.target.canonical_model, max(0.2, timeout)
        )
    except (KeyboardInterrupt, _AdapterFailure):
        return "partial_unknown", None
    if catalog.model_present and catalog.digest_valid and catalog.model_digest:
        if not operation.preflight_observed or not operation.pull_attempted:
            return "partial_unknown", None
        if operation.pre_model_present and operation.pre_model_digest is None:
            return "partial_unknown", None
        if operation.pre_model_present and operation.pre_model_digest == catalog.model_digest:
            return "prior_model_preserved", catalog.model_digest
        return "ready", catalog.model_digest
    if catalog.model_present:
        return "partial_unknown", None
    if not operation.pull_attempted:
        return "partial_unknown", None
    return "daemon_owned_partial_unknown", None


def _terminal_failure(
    client: Any,
    access: _Access,
    operation: _Operation,
    callback: ProgressCallback | None,
    code: str,
    reconcile_timeout: float,
) -> OllamaPullResult:
    operation.phase = "failed"
    operation.terminal_code = code
    operation.exit_code = 1
    partial, digest = _reconcile(client, access, operation, reconcile_timeout)
    operation.partial_state = partial
    operation.final_model_digest = digest
    if partial == "ready" and digest:
        operation.phase = "ready"
        operation.terminal_code = "OLLAMA_PULL_READY_AFTER_FAILURE"
        operation.exit_code = 0
    _emit(operation, callback)
    return operation.result()


def _terminal_cancelled(
    client: Any,
    access: _Access,
    operation: _Operation,
    callback: ProgressCallback | None,
    reconcile_timeout: float,
) -> OllamaPullResult:
    operation.phase = "cancelled"
    operation.terminal_code = "OLLAMA_CLIENT_CANCELLED"
    operation.exit_code = 130
    _emit(operation, callback)
    partial, digest = _reconcile(client, access, operation, reconcile_timeout)
    operation.partial_state = partial
    operation.final_model_digest = digest
    if partial == "ready" and digest:
        operation.phase = "ready"
        operation.terminal_code = "OLLAMA_CLIENT_CANCELLED_READY"
    _emit(operation, callback)
    return operation.result()


def _terminal_cancelled_without_reconciliation(
    operation: _Operation,
    callback: ProgressCallback | None,
) -> OllamaPullResult:
    """Record cancellation when a fresh bounded catalog probe is unavailable."""

    operation.phase = "cancelled"
    operation.terminal_code = "OLLAMA_CLIENT_CANCELLED"
    operation.partial_state = "partial_unknown"
    operation.final_model_digest = None
    operation.exit_code = 130
    _emit(operation, callback)
    return operation.result()


def _failure_message(code: str) -> str:
    return {
        "OLLAMA_AUTH_FAILED": "The configured Ollama endpoint rejected its stored credential.",
        "OLLAMA_DISK_FULL": "Ollama reported insufficient disk space.",
        "OLLAMA_PROTOCOL_MISMATCH": "The endpoint did not satisfy the Ollama pull protocol.",
        "OLLAMA_UNREACHABLE": "The configured Ollama endpoint is unreachable.",
        "OLLAMA_VERIFICATION_FAILED": "The pulled model could not be verified in Ollama.",
        "OLLAMA_DIGEST_INVALID": "Ollama did not report a canonical installed model digest.",
    }.get(code, "Ollama could not complete the model pull.")


def _execute_prepared_pull(
    prepared: _PreparedPull,
    *,
    progress_callback: ProgressCallback | None = None,
    transport: Any | None = None,
    preflight_timeout: float = 10.0,
    reconcile_timeout: float = 5.0,
) -> OllamaPullResult:
    target = prepared.target
    access = prepared.access
    ledger_dir = _secure_directory(prepared.home, "runtime", "ollama-pulls")
    operation = _Operation(
        operation_id=uuid.uuid4().hex,
        target=target,
        ledger_path=ledger_dir / f"{target.target_hash}.json",
    )

    import httpx

    timeout = httpx.Timeout(
        connect=max(0.2, preflight_timeout),
        read=None,
        write=30.0,
        pool=10.0,
    )

    def make_client() -> Any:
        return httpx.Client(
            headers=access.headers,
            verify=access.verify,
            transport=transport,
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
        )

    with _pull_lease(prepared.default_root, target.target_hash):
        _emit(operation, progress_callback)
        try:
            with make_client() as client:
                try:
                    operation.phase = "preflight"
                    _emit(operation, progress_callback)
                    catalog = _fetch_catalog(
                        client,
                        access,
                        target.canonical_model,
                        max(0.2, preflight_timeout),
                    )
                    operation.preflight_observed = True
                    operation.pre_model_present = catalog.model_present
                    operation.pre_model_digest = (
                        catalog.model_digest
                        if catalog.model_present and catalog.digest_valid
                        else None
                    )
                    operation.phase = "pulling"
                    _emit(operation, progress_callback)
                    _run_stream(client, access, operation, progress_callback)
                    operation.phase = "verifying"
                    _emit(operation, progress_callback)
                    final_catalog = _fetch_catalog(
                        client,
                        access,
                        target.canonical_model,
                        max(0.2, preflight_timeout),
                    )
                    if not final_catalog.model_present:
                        raise _AdapterFailure("OLLAMA_VERIFICATION_FAILED")
                    if not final_catalog.digest_valid or not final_catalog.model_digest:
                        raise _AdapterFailure("OLLAMA_DIGEST_INVALID")
                    operation.phase = "ready"
                    operation.final_model_digest = final_catalog.model_digest
                    operation.terminal_code = "OLLAMA_PULL_READY"
                    operation.partial_state = "ready"
                    operation.exit_code = 0
                    _emit(operation, progress_callback)
                    return operation.result()
                except KeyboardInterrupt:
                    # A Ctrl+C during the threaded tags probe closes this
                    # client to terminate its active response. Reconcile with
                    # a fresh client so cancellation never races the abandoned
                    # request and still gets one bounded catalog check.
                    try:
                        client.close()
                    except Exception:
                        pass
                    try:
                        with make_client() as reconcile_client:
                            return _terminal_cancelled(
                                reconcile_client,
                                access,
                                operation,
                                progress_callback,
                                reconcile_timeout,
                            )
                    except OllamaPullStateError:
                        raise
                    except Exception:
                        return _terminal_cancelled_without_reconciliation(
                            operation, progress_callback
                        )
                except _AdapterFailure as exc:
                    return _terminal_failure(
                        client,
                        access,
                        operation,
                        progress_callback,
                        exc.code,
                        reconcile_timeout,
                    )
        except KeyboardInterrupt:
            # Client construction itself can be interrupted; no response is
            # available to close, but the same terminal contract still holds.
            return _terminal_cancelled_without_reconciliation(
                operation, progress_callback
            )
        except OllamaPullStateError:
            raise
        except Exception:
            # Client construction/TLS failures are sanitized just like request
            # failures.  No raw exception text is retained or returned.
            operation.phase = "failed"
            operation.terminal_code = "OLLAMA_UNREACHABLE"
            operation.partial_state = "partial_unknown"
            operation.exit_code = 1
            _emit(operation, progress_callback)
            return operation.result()


def pull_ollama_model(
    model: str | None = None,
    host: str | None = None,
    *,
    config: Mapping[str, Any] | None = None,
    home: Path | None = None,
    default_root: Path | None = None,
    progress_callback: ProgressCallback | None = None,
    transport: Any | None = None,
    resolver: AddressResolver = socket.getaddrinfo,
    preflight_timeout: float = 10.0,
    reconcile_timeout: float = 5.0,
) -> OllamaPullResult:
    """Resolve once, pull, and verify without mutating Fabric configuration.

    Validation and unsafe-state failures raise :class:`OllamaPullError` with a
    fixed safe message.  Network/protocol/daemon outcomes return a terminal
    result so callers can map ``exit_code`` directly, including cancellation.
    """

    prepared = _prepare_ollama_pull(
        model,
        host,
        config=config,
        home=home,
        default_root=default_root,
        resolver=resolver,
    )
    return _execute_prepared_pull(
        prepared,
        progress_callback=progress_callback,
        transport=transport,
        preflight_timeout=preflight_timeout,
        reconcile_timeout=reconcile_timeout,
    )


def format_ollama_pull_progress(progress: OllamaPullProgress) -> str:
    """Render one sanitized progress update without endpoint/access details."""

    if progress.phase not in _PHASES:
        return "Ollama pull status unavailable."
    if progress.completed_bytes is not None and progress.total_bytes is not None:
        return (
            f"{progress.phase.capitalize()} {progress.canonical_model}: "
            f"{progress.completed_bytes}/{progress.total_bytes} bytes"
        )
    return f"{progress.phase.capitalize()} {progress.canonical_model}."


def format_ollama_pull_result(result: OllamaPullResult) -> str:
    """Render a fixed terminal message; never interpolate raw failure data."""

    if result.phase == "ready":
        if result.exit_code == 130:
            return (
                "Client request cancelled; reconciliation found the model installed and "
                "digest-verified."
            )
        return (
            "Ollama model installed and digest-verified. Fabric's selected model was "
            "not changed; configure and verify this model in the same profile."
        )
    if result.phase == "cancelled":
        return "Client request cancelled; daemon-owned partial state was not deleted."
    return _failure_message(result.terminal_code)


def cmd_ollama_pull(args: Any) -> int:
    """Run the foreground pull command from an argparse-like namespace.

    The caller must apply the global profile override before invoking this
    function.  It consumes only ``model``, ``host``, and ``yes`` attributes,
    performs the TTY/confirmation contract, prints sanitized messages, and
    returns ``0``, ``1``, or ``130`` without calling :func:`sys.exit`.
    """

    import sys

    model = getattr(args, "model", None)
    host = getattr(args, "host", None)
    try:
        prepared = _prepare_ollama_pull(model, host)
        target = prepared.target
    except OllamaPullError as exc:
        print(str(exc))
        return 1

    if not bool(getattr(args, "yes", False)):
        if not sys.stdin.isatty():
            print("Non-interactive Ollama pulls require --yes after explicit user approval.")
            return 1
        try:
            answer = input(
                f"Pull {target.canonical_model} with Ollama? "
                "This may use substantial bandwidth and disk space. [y/N] "
            )
        except (EOFError, KeyboardInterrupt):
            print("Client request cancelled; no pull was started.")
            return 130
        if answer.strip().lower() not in {"y", "yes"}:
            print("Client request cancelled; no pull was started.")
            return 130

    def render(update: OllamaPullProgress) -> None:
        print(format_ollama_pull_progress(update))

    try:
        result = _execute_prepared_pull(
            prepared,
            progress_callback=render,
        )
    except OllamaPullError as exc:
        print(str(exc))
        return 1
    print(format_ollama_pull_result(result))
    return result.exit_code if result.exit_code in {0, 1, 130} else 1
