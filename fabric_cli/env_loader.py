"""Helpers for loading Fabric .env files consistently across entrypoints."""

from __future__ import annotations

import hashlib
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Optional

from dotenv import dotenv_values, load_dotenv
from utils import atomic_replace, fast_safe_load


# Env var name suffixes that indicate credential values.  These are the
# only env vars whose values we sanitize on load — we must not silently
# alter arbitrary user env vars, but credentials are known to require
# pure ASCII (they become HTTP header values).
_CREDENTIAL_SUFFIXES = ("_API_KEY", "_TOKEN", "_SECRET", "_KEY")

# Names we've already warned about during this process, so repeated
# load_fabric_dotenv() calls (user env + project env, gateway hot-reload,
# tests) don't spam the same warning multiple times.
_WARNED_KEYS: set[str] = set()

# Map of env-var name → source label ("bitwarden", etc.) for credentials
# that were injected by an external secret source during load_fabric_dotenv().
# Used by setup / `fabric model` flows to label detected credentials so
# users understand WHERE a key came from when their .env doesn't contain it
# directly (otherwise the "credentials detected ✓" line looks identical to
# the .env case and they don't know Bitwarden is wired up).
_SECRET_SOURCES: dict[str, str] = {}

# Home-qualified values applied by external secret sources.  ``_SECRET_SOURCES``
# above is display metadata only and cannot authorize a credential read: a
# long-lived process may load more than one profile, and the same env-var name
# can belong to different homes.  This map preserves the profile boundary while
# allowing a normal ``fabric -p <name>`` process to use Bitwarden/1Password
# values that were fetched specifically for that profile.
_PROFILE_SECRET_SOURCE_VALUES: dict[str, dict[str, str]] = {}
_PROFILE_SECRET_SOURCE_PROVENANCE: dict[str, dict[str, str]] = {}
_PROFILE_SECRET_SOURCE_ISOLATED: dict[str, bool] = {}
_RESOLVED_SECRET_SOURCE_HOMES: set[str] = set()

# Exact values last copied into process-global ``os.environ`` by the legacy
# single-profile path.  This lets a later successful refresh revoke a dropped
# vault key without deleting a local replacement written in the meantime.
_LEGACY_APPLIED_SECRET_VALUES: dict[str, dict[str, str]] = {}

# HERMES_HOME paths we've already pulled external secrets for during this
# process.  ``load_fabric_dotenv()`` is called at module-import time from
# several hot modules (cli.py, fabric_cli/main.py, run_agent.py,
# trajectory_compressor.py, gateway/run.py, ...), so without this guard the
# Bitwarden status line gets printed 3-5x per startup.  Bitwarden's own
# in-process cache prevents redundant network calls, but the print, the
# config re-parse, and the ASCII sanitization sweep still ran every time.
_APPLIED_HOMES: set[str] = set()

# Global metadata/cache mutations are short and synchronized.  Fetches use a
# per-home lock, so the same profile deduplicates while different profiles can
# resolve concurrently without holding this process-wide lock.
_SECRET_SOURCE_CACHE_LOCK = threading.RLock()
_SECRET_SOURCE_HOME_LOCKS: dict[str, threading.Lock] = {}
_SECRET_SOURCE_CACHE_GENERATION = 0
# Homes whose next successful aggregate resolution must bypass the bundled
# sources' own L1/L2 caches.  Aggregate invalidation alone is insufficient:
# Bitwarden and 1Password cache independently in memory and on disk.
_SECRET_SOURCE_FORCE_REFRESH_HOMES: set[str] = set()


@dataclass(frozen=True)
class _ExternalSecretCacheMetadata:
    """Validity boundary for one home-qualified aggregate snapshot."""

    input_fingerprint: tuple[tuple[str, str, str], ...]
    expires_at: Optional[float]
    isolated: bool
    generation: int


_PROFILE_SECRET_SOURCE_CACHE_METADATA: dict[
    str, _ExternalSecretCacheMetadata
] = {}


def _secret_source_cache_now() -> float:
    """Monotonic cache clock, split out for deterministic race/TTL tests."""
    return time.monotonic()


@dataclass(frozen=True)
class ExternalSecretResolution:
    """Profile-qualified external secrets returned without mutating env.

    ``values`` contains only variables actually won by an external source,
    after credential sanitization.  ``provenance`` maps each returned name to
    its registered source id.  Both are fresh dictionaries safe to merge into
    a context-local secret scope.  The raw report is retained for the legacy
    startup status printer but hidden from repr because it contains values.
    """

    home_path: Path
    values: dict[str, str] = field(repr=False)
    provenance: dict[str, str]
    report: Optional[Any] = field(default=None, repr=False)
    from_cache: bool = False
    successful: bool = False
    generation: Optional[int] = field(default=None, repr=False)


def _rebuild_secret_source_provenance_locked() -> None:
    """Rebuild display-only provenance from the live profile snapshots."""
    _SECRET_SOURCES.clear()
    for provenance in _PROFILE_SECRET_SOURCE_PROVENANCE.values():
        _SECRET_SOURCES.update(provenance)


def _evict_profile_secret_source_cache_locked(home_key: str) -> None:
    """Remove one aggregate snapshot; caller holds the global cache lock."""
    _RESOLVED_SECRET_SOURCE_HOMES.discard(home_key)
    _PROFILE_SECRET_SOURCE_VALUES.pop(home_key, None)
    _PROFILE_SECRET_SOURCE_PROVENANCE.pop(home_key, None)
    _PROFILE_SECRET_SOURCE_ISOLATED.pop(home_key, None)
    _PROFILE_SECRET_SOURCE_CACHE_METADATA.pop(home_key, None)
    _rebuild_secret_source_provenance_locked()


def _profile_secret_source_cache_is_live_locked(home_key: str) -> bool:
    """Check generation/TTL for an accessor and evict stale metadata."""
    metadata = _PROFILE_SECRET_SOURCE_CACHE_METADATA.get(home_key)
    live = bool(
        metadata is not None
        and metadata.generation == _SECRET_SOURCE_CACHE_GENERATION
        and (
            metadata.expires_at is None
            or _secret_source_cache_now() < metadata.expires_at
        )
    )
    if not live and home_key in _RESOLVED_SECRET_SOURCE_HOMES:
        _evict_profile_secret_source_cache_locked(home_key)
    return live


def get_secret_source(env_var: str) -> str | None:
    """Return the label of the secret source that supplied ``env_var``, if any.

    Returns ``"bitwarden"`` for keys pulled from Bitwarden Secrets Manager
    during the current process's ``load_fabric_dotenv()`` call.  Returns
    ``None`` for keys that came from ``.env``, the shell environment, or
    aren't tracked.  The returned label is metadata only: credential-pool
    persistence may store it to explain the origin of a borrowed secret, but
    must never treat it as authorization to persist the raw value.
    """
    with _SECRET_SOURCE_CACHE_LOCK:
        return _SECRET_SOURCES.get(env_var)


def get_profile_secret_source_value(
    home_path: str | os.PathLike,
    env_var: str,
) -> str | None:
    """Return an externally sourced value proven to belong to ``home_path``.

    Values appear here only when the secret-source orchestrator actually wrote
    them for this resolved profile home.  A same-named value inherited through
    ``os.environ`` is intentionally not enough to authorize the read.
    """
    try:
        home_key = str(Path(home_path).resolve())
    except (OSError, RuntimeError, ValueError):
        return None
    with _SECRET_SOURCE_CACHE_LOCK:
        if not _profile_secret_source_cache_is_live_locked(home_key):
            return None
        return _PROFILE_SECRET_SOURCE_VALUES.get(home_key, {}).get(env_var)


def get_profile_secret_source_values(
    home_path: str | os.PathLike,
) -> dict[str, str]:
    """Return a copy of all externally sourced values cached for one home."""
    try:
        home_key = str(Path(home_path).resolve())
    except (OSError, RuntimeError, ValueError):
        return {}
    with _SECRET_SOURCE_CACHE_LOCK:
        if not _profile_secret_source_cache_is_live_locked(home_key):
            return {}
        return dict(_PROFILE_SECRET_SOURCE_VALUES.get(home_key, {}))


def get_profile_secret_source_provenance(
    home_path: str | os.PathLike,
) -> dict[str, str]:
    """Return a copy of env-var to external-source provenance for one home."""
    try:
        home_key = str(Path(home_path).resolve())
    except (OSError, RuntimeError, ValueError):
        return {}
    with _SECRET_SOURCE_CACHE_LOCK:
        if not _profile_secret_source_cache_is_live_locked(home_key):
            return {}
        return dict(_PROFILE_SECRET_SOURCE_PROVENANCE.get(home_key, {}))


def get_legacy_applied_secret_names(
    home_path: str | os.PathLike | None = None,
) -> set[str]:
    """Return value-free names still owned by one legacy process-env apply.

    These names intentionally outlive aggregate resolver TTL eviction and
    cache resets because those operations do not remove matching values from
    ``os.environ``.  A successful legacy refresh reconciles them.  Child-env
    scrubbers can therefore block arbitrary vault names (for example
    ``DATABASE_URL``) without reading secret values.
    """
    try:
        if home_path is None:
            raw_home = (
                os.environ.get("FABRIC_HOME")
                or os.environ.get("HERMES_HOME")
                or ""
            ).strip()
            if raw_home:
                home_path = raw_home
            else:
                from fabric_constants import get_default_fabric_root

                home_path = get_default_fabric_root()
        home_key = str(Path(home_path).resolve())
    except (OSError, RuntimeError, ValueError):
        return set()
    with _SECRET_SOURCE_CACHE_LOCK:
        return set(_LEGACY_APPLIED_SECRET_VALUES.get(home_key, {}))


def reset_secret_source_cache() -> None:
    """Forget which HERMES_HOME paths have already had external secrets applied.

    The first call to ``_apply_external_secret_sources(home_path)`` in a
    process pulls from Bitwarden (or other configured backend), records the
    applied keys in ``_SECRET_SOURCES``, and remembers ``home_path`` so
    subsequent calls in the same process are no-ops.  Call this to force the
    next call to re-pull — useful for tests, and for long-running processes
    that want to refresh after a config change.
    """
    global _SECRET_SOURCE_CACHE_GENERATION
    with _SECRET_SOURCE_CACHE_LOCK:
        # An in-flight resolver captures the generation before fetching and
        # may publish only if it still matches.  Increment first so work that
        # began before this reset cannot repopulate the just-cleared cache.
        _SECRET_SOURCE_CACHE_GENERATION += 1
        _SECRET_SOURCE_FORCE_REFRESH_HOMES.update(
            _RESOLVED_SECRET_SOURCE_HOMES
            | _APPLIED_HOMES
            | set(_PROFILE_SECRET_SOURCE_CACHE_METADATA)
            | set(_LEGACY_APPLIED_SECRET_VALUES)
            | set(_SECRET_SOURCE_HOME_LOCKS)
        )
        _APPLIED_HOMES.clear()
        _RESOLVED_SECRET_SOURCE_HOMES.clear()
        _PROFILE_SECRET_SOURCE_VALUES.clear()
        _PROFILE_SECRET_SOURCE_PROVENANCE.clear()
        _PROFILE_SECRET_SOURCE_ISOLATED.clear()
        _PROFILE_SECRET_SOURCE_CACHE_METADATA.clear()
        # Do not clear _LEGACY_APPLIED_SECRET_VALUES: reset does not mutate
        # os.environ, so forgetting ownership here would prevent a later
        # disabled/empty refresh from revoking old values and would let
        # arbitrary vault names leak into profile-scoped child environments.
        _SECRET_SOURCES.clear()


def format_secret_source_suffix(env_var: str) -> str:
    """Return a human-readable suffix like ``" (from Bitwarden)"`` or ``""``.

    Use this when printing a detected credential so the user can see where
    it came from.  Empty string when the credential came from ``.env`` or
    the shell — those are the implicit / "default" cases users already
    understand.
    """
    source = get_secret_source(env_var)
    if not source:
        return ""
    if source == "bitwarden":
        return " (from Bitwarden)"
    # Ask the registry for the source's human label (e.g. "1Password").
    # Fall back to the raw source name for labels the registry doesn't
    # know (stale provenance from an uninstalled plugin, tests).
    try:
        from agent.secret_sources.registry import get_source

        registered = get_source(source)
        if registered is not None and registered.label:
            return f" (from {registered.label})"
    except Exception:  # noqa: BLE001 — label lookup must never raise
        pass
    return f" (from {source})"


def _format_offending_chars(value: str, limit: int = 3) -> str:
    """Return a compact 'U+XXXX ('c'), ...' summary of non-ASCII codepoints."""
    seen: list[str] = []
    for ch in value:
        if ord(ch) > 127:
            label = f"U+{ord(ch):04X}"
            if ch.isprintable():
                label += f" ({ch!r})"
            if label not in seen:
                seen.append(label)
            if len(seen) >= limit:
                break
    return ", ".join(seen)


def _sanitize_credential_mapping(
    environ: MutableMapping[str, str],
) -> None:
    """Strip non-ASCII credential characters from exactly one mapping.

    The explicit mapping is load-bearing for profile isolation: callers may
    sanitize a target profile's local resolution environment without reading
    or writing process-global ``os.environ``.

    Emits a one-line warning to stderr when characters are stripped.
    Silent stripping would mask copy-paste corruption (Unicode lookalike
    glyphs from PDFs / rich-text editors, ZWSP from web pages) as opaque
    provider-side "invalid API key" errors (see #6843).
    """
    for key, value in list(environ.items()):
        if not any(key.endswith(suffix) for suffix in _CREDENTIAL_SUFFIXES):
            continue
        try:
            value.encode("ascii")
            continue
        except UnicodeEncodeError:
            pass
        cleaned = value.encode("ascii", errors="ignore").decode("ascii")
        environ[key] = cleaned
        with _SECRET_SOURCE_CACHE_LOCK:
            already_warned = key in _WARNED_KEYS
            _WARNED_KEYS.add(key)
        if already_warned:
            continue
        stripped = len(value) - len(cleaned)
        detail = _format_offending_chars(value) or "non-printable"
        print(
            f"  Warning: {key} contained {stripped} non-ASCII character"
            f"{'s' if stripped != 1 else ''} ({detail}) — stripped so the "
            f"key can be sent as an HTTP header.",
            file=sys.stderr,
        )
        print(
            "  This usually means the key was copy-pasted from a PDF, "
            "rich-text editor, or web page that substituted lookalike\n"
            "  Unicode glyphs for ASCII letters. If authentication fails "
            "(e.g. \"API key not valid\"), re-copy the key from the\n"
            "  provider's dashboard and run `fabric setup` (or edit the "
            ".env file in a plain-text editor).",
            file=sys.stderr,
        )


def _sanitize_loaded_credentials() -> None:
    """Preserve the legacy sanitizer over process-global ``os.environ``."""
    _sanitize_credential_mapping(os.environ)


def _load_dotenv_with_fallback(path: Path, *, override: bool) -> None:
    try:
        load_dotenv(dotenv_path=path, override=override, encoding="utf-8")
    except UnicodeDecodeError:
        load_dotenv(dotenv_path=path, override=override, encoding="latin-1")
    # Strip non-ASCII characters from credential env vars that were just
    # loaded.  API keys must be pure ASCII since they're sent as HTTP
    # header values (httpx encodes headers as ASCII).  Non-ASCII chars
    # typically come from copy-pasting keys from PDFs or rich-text editors
    # that substitute Unicode lookalike glyphs (e.g. ʋ U+028B for v).
    _sanitize_loaded_credentials()


def _sanitize_env_file_if_needed(path: Path) -> None:
    """Pre-sanitize a .env file before python-dotenv reads it.

    python-dotenv does not handle corrupted lines where multiple
    KEY=VALUE pairs are concatenated on a single line (missing newline).
    This produces mangled values — e.g. a bot token duplicated 8×
    (see #8908).

    Also strips embedded null bytes which crash ``os.environ[k] = v``
    with ``ValueError: embedded null byte`` — typically introduced by
    copy-pasting API keys from terminals or rich-text editors.

    We delegate to ``fabric_cli.config._sanitize_env_lines`` which
    already knows all valid Fabric env-var names and can split
    concatenated lines correctly.
    """
    if not path.exists():
        return
    try:
        from fabric_cli.config import _sanitize_env_lines
    except ImportError:
        return  # early bootstrap — config module not available yet

    read_kw = {"encoding": "utf-8-sig", "errors": "replace"}
    try:
        with open(path, **read_kw) as f:
            original = f.readlines()
        # Strip null bytes before _sanitize_env_lines so they never
        # reach python-dotenv (which passes them to os.environ and
        # crashes with ValueError).
        stripped = [line.replace("\x00", "") for line in original]
        sanitized = _sanitize_env_lines(stripped)
        if sanitized != original:
            import tempfile
            fd, tmp = tempfile.mkstemp(
                dir=str(path.parent), suffix=".tmp", prefix=".env_"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.writelines(sanitized)
                    f.flush()
                    os.fsync(f.fileno())
                atomic_replace(tmp, path)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
    except Exception:
        pass  # best-effort — don't block gateway startup


_PROFILE_RESOLUTION_PROCESS_KEYS = frozenset(
    {
        # OS/runtime inputs needed to locate and launch trusted helper CLIs.
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "USERPROFILE",
        "SYSTEMROOT",
        "SystemRoot",
        "WINDIR",
        "APPDATA",
        "LOCALAPPDATA",
        "TMPDIR",
        "TMP",
        "TEMP",
        "LANG",
        "LANGUAGE",
        "LC_ALL",
        "LC_CTYPE",
        "TZ",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_RUNTIME_DIR",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
        "SSH_AUTH_SOCK",
        "DBUS_SESSION_BUS_ADDRESS",
        # 1Password desktop/Connect selection is intentionally process-wide.
        # The service-account token is profile-owned and is NOT listed here.
        "OP_ACCOUNT",
        "OP_CONNECT_HOST",
        "OP_CONNECT_TOKEN",
    }
)


def _read_dotenv_mapping(path: Path) -> dict[str, str]:
    """Parse one dotenv file without interpolation or environment mutation."""
    if not path.exists():
        return {}
    for encoding in ("utf-8", "latin-1"):
        try:
            parsed = dotenv_values(
                dotenv_path=path,
                encoding=encoding,
                interpolate=False,
            )
            return {
                str(key): str(value)
                for key, value in parsed.items()
                if isinstance(key, str) and value is not None
            }
        except UnicodeDecodeError:
            continue
        except Exception:  # noqa: BLE001 — profile resolution is fail-open
            return {}
    return {}


def _process_resolution_inputs() -> dict[str, str]:
    """Copy legitimate process-global inputs, excluding provider secrets."""
    copied = {
        key: value
        for key, value in os.environ.items()
        if key in _PROFILE_RESOLUTION_PROCESS_KEYS or key.startswith("OP_SESSION_")
    }
    return copied


def _legacy_bootstrap_input_names(secrets_cfg: Mapping[str, Any]) -> set[str]:
    """Return only enabled, explicitly configured legacy bootstrap names."""
    names: set[str] = set()
    bitwarden = secrets_cfg.get("bitwarden")
    if isinstance(bitwarden, dict) and bitwarden.get("enabled"):
        names.add(str(bitwarden.get("access_token_env") or "BWS_ACCESS_TOKEN"))
    onepassword = secrets_cfg.get("onepassword")
    if isinstance(onepassword, dict) and onepassword.get("enabled"):
        names.add(
            str(
                onepassword.get("service_account_token_env")
                or "OP_SERVICE_ACCOUNT_TOKEN"
            )
        )
    return names


def _legacy_bootstrap_inputs(secrets_cfg: Mapping[str, Any]) -> dict[str, str]:
    """Copy only configured vault bootstrap vars for legacy startup.

    The isolated public resolver never calls this.  It exists solely so a
    single-profile ``load_fabric_dotenv`` invocation can keep accepting an
    explicitly exported Bitwarden/1Password bootstrap token without seeding
    arbitrary launch-profile provider credentials into the target mapping.
    """
    names = _legacy_bootstrap_input_names(secrets_cfg)
    return {name: os.environ[name] for name in names if name in os.environ}


def _build_profile_resolution_environment(
    home_path: Path,
    *,
    project_env: Optional[Path] = None,
    secrets_cfg: Optional[Mapping[str, Any]] = None,
    allow_process_bootstrap: bool = False,
) -> tuple[dict[str, str], frozenset[str]]:
    """Build the target profile's local fetch/apply environment.

    Precedence mirrors startup without touching ``os.environ``: target ``.env``
    wins over process OS inputs, ``.op.env`` only fills missing values, project
    dotenv is a fallback when a target dotenv exists, and managed values win
    last.  The returned managed-name set is passed to the orchestrator as
    immutable policy.
    """
    environ = _process_resolution_inputs()
    user_env_path = home_path / ".env"
    user_values = _read_dotenv_mapping(user_env_path)
    environ.update(user_values)

    for key, value in _read_dotenv_mapping(home_path / ".op.env").items():
        environ.setdefault(key, value)

    if project_env is not None and project_env.exists():
        project_values = _read_dotenv_mapping(project_env)
        if user_env_path.exists():
            for key, value in project_values.items():
                environ.setdefault(key, value)
        else:
            environ.update(project_values)

    if allow_process_bootstrap:
        for key, value in _legacy_bootstrap_inputs(secrets_cfg or {}).items():
            environ.setdefault(key, value)

    managed_values: dict[str, str] = {}
    try:
        from fabric_cli.managed_scope import load_managed_env

        managed_values = load_managed_env()
    except Exception:  # noqa: BLE001 — managed scope must remain fail-open
        pass
    environ.update(managed_values)
    _sanitize_credential_mapping(environ)
    return environ, frozenset(managed_values)


def _secret_source_input_file_fingerprint(path: Path) -> tuple[str, str, str]:
    """Return a content-sensitive, non-plaintext signature for one input file."""
    resolved = path.expanduser().resolve()
    try:
        content = resolved.read_bytes()
    except FileNotFoundError:
        return (str(resolved), "missing", "")
    except OSError as exc:
        # Never reuse a prior successful snapshot while an input is currently
        # unreadable.  The errno is diagnostic identity only and contains no
        # secret material.
        return (str(resolved), "unreadable", str(exc.errno or type(exc).__name__))
    return (str(resolved), "sha256", hashlib.sha256(content).hexdigest())


def _secret_source_input_fingerprint(
    home_path: Path,
    project_env: Optional[Path],
) -> tuple[tuple[str, str, str], ...]:
    """Fingerprint every file that can affect a target-home resolution."""
    paths = [
        home_path / "config.yaml",
        home_path / ".env",
        home_path / ".op.env",
    ]
    if project_env is not None:
        paths.append(project_env)
    try:
        from fabric_cli.managed_scope import get_managed_dir

        managed_dir = get_managed_dir()
    except Exception:  # noqa: BLE001 — cache validation remains fail-open
        managed_dir = None
    if managed_dir is not None:
        paths.append(managed_dir / ".env")
    fingerprint = [
        _secret_source_input_file_fingerprint(path) for path in paths
    ]
    try:
        from agent.secret_sources.registry import get_registry_generation

        registry_generation = str(get_registry_generation())
    except Exception:  # noqa: BLE001 — cache validation remains fail-open
        # Never mistake a registry-read failure for the previous successful
        # source set.  A fresh marker prevents publishing this resolution.
        registry_generation = f"unavailable:{_secret_source_cache_now()}"
    fingerprint.append(
        ("<secret-source-registry>", "generation", registry_generation)
    )
    return tuple(fingerprint)


def _value_safe_mapping_fingerprint(
    label: str,
    environ: Mapping[str, str],
    names: set[str] | frozenset[str],
) -> tuple[str, str, str]:
    """Hash names, presence, and values without retaining plaintext metadata."""
    digest = hashlib.sha256()
    for name in sorted(names):
        encoded_name = name.encode("utf-8", errors="surrogatepass")
        digest.update(len(encoded_name).to_bytes(8, "big"))
        digest.update(encoded_name)
        if name not in environ:
            digest.update(b"\x00")
            continue
        digest.update(b"\x01")
        encoded_value = str(environ[name]).encode("utf-8", errors="surrogatepass")
        digest.update(len(encoded_value).to_bytes(8, "big"))
        digest.update(encoded_value)
    return (f"<{label}>", "sha256", digest.hexdigest())


def _secret_source_runtime_input_fingerprint(
    environ: Mapping[str, str],
    managed_names: frozenset[str],
    secrets_cfg: Mapping[str, Any],
    *,
    allow_process_bootstrap: bool,
) -> tuple[tuple[str, str, str], ...]:
    """Fingerprint exact auth/managed values that can affect this fetch mode."""
    auth_names = {
        "OP_ACCOUNT",
        "OP_CONNECT_HOST",
        "OP_CONNECT_TOKEN",
    }
    auth_names.update(name for name in environ if name.startswith("OP_SESSION_"))
    if allow_process_bootstrap:
        auth_names.update(_legacy_bootstrap_input_names(secrets_cfg))
    mode = "legacy" if allow_process_bootstrap else "isolated"
    return (
        ("<secret-source-resolution>", "mode", mode),
        _value_safe_mapping_fingerprint("secret-source-auth", environ, auth_names),
        _value_safe_mapping_fingerprint(
            "secret-source-managed", environ, managed_names
        ),
    )


def _cached_external_secret_resolution(
    home_path: Path,
    home_key: str,
) -> ExternalSecretResolution:
    metadata = _PROFILE_SECRET_SOURCE_CACHE_METADATA[home_key]
    return ExternalSecretResolution(
        home_path=home_path,
        values=dict(_PROFILE_SECRET_SOURCE_VALUES.get(home_key, {})),
        provenance=dict(_PROFILE_SECRET_SOURCE_PROVENANCE.get(home_key, {})),
        from_cache=True,
        successful=True,
        generation=metadata.generation,
    )


def _resolve_external_secret_sources(
    home_path: Path,
    *,
    project_env: Optional[Path] = None,
    force: bool = False,
    allow_process_bootstrap: bool = False,
) -> ExternalSecretResolution:
    """Internal resolver shared by isolated and legacy startup paths."""
    resolved_home = Path(home_path).resolve()
    resolved_project_env = (
        Path(project_env).expanduser().resolve() if project_env is not None else None
    )
    home_key = str(resolved_home)
    isolated = not allow_process_bootstrap

    # Capture the generation before waiting for the per-home lock.  A reset
    # that happens while this call is waiting or fetching invalidates the
    # publication, so pre-reset work can never resurrect cleared state.
    with _SECRET_SOURCE_CACHE_LOCK:
        resolution_generation = _SECRET_SOURCE_CACHE_GENERATION
        home_lock = _SECRET_SOURCE_HOME_LOCKS.setdefault(
            home_key, threading.Lock()
        )

    with home_lock:
        try:
            cfg, config_loaded = _load_secrets_config_with_status(resolved_home)
        except Exception:  # noqa: BLE001 — config errors must not block startup
            cfg, config_loaded = {}, False
        cfg = cfg if isinstance(cfg, dict) else {}
        working, managed_names = _build_profile_resolution_environment(
            resolved_home,
            project_env=resolved_project_env,
            secrets_cfg=cfg,
            allow_process_bootstrap=allow_process_bootstrap,
        )
        input_fingerprint = (
            _secret_source_input_fingerprint(
                resolved_home,
                resolved_project_env,
            )
            + (
                (
                    "<secret-source-config>",
                    "status",
                    "loaded" if config_loaded else "unavailable",
                ),
            )
            + _secret_source_runtime_input_fingerprint(
                working,
                managed_names,
                cfg,
                allow_process_bootstrap=allow_process_bootstrap,
            )
        )
        with _SECRET_SOURCE_CACHE_LOCK:
            if force:
                # Keep this intent until a complete, stable fetch publishes.
                # A failed forced fetch must not let the next normal call fall
                # back to the stale source-local entry it was meant to replace.
                _SECRET_SOURCE_FORCE_REFRESH_HOMES.add(home_key)
            source_force_refresh = (
                home_key in _SECRET_SOURCE_FORCE_REFRESH_HOMES
            )
            metadata = _PROFILE_SECRET_SOURCE_CACHE_METADATA.get(home_key)
            cache_is_safe = bool(metadata and metadata.isolated)
            cache_is_current = bool(
                metadata is not None
                and metadata.generation == resolution_generation
                and resolution_generation == _SECRET_SOURCE_CACHE_GENERATION
                and metadata.input_fingerprint == input_fingerprint
                and (
                    metadata.expires_at is None
                    or _secret_source_cache_now() < metadata.expires_at
                )
            )
            if (
                not force
                and home_key in _RESOLVED_SECRET_SOURCE_HOMES
                and cache_is_current
                and (not isolated or cache_is_safe)
            ):
                return _cached_external_secret_resolution(resolved_home, home_key)
            if resolution_generation == _SECRET_SOURCE_CACHE_GENERATION:
                _evict_profile_secret_source_cache_locked(home_key)
        report: Optional[Any] = None
        if config_loaded:
            try:
                from agent.secret_sources.registry import apply_all

                report = apply_all(
                    cfg,
                    resolved_home,
                    environ=working,
                    immutable_vars=managed_names,
                    require_scoped_environment=isolated,
                    force_refresh=source_force_refresh,
                )
            except Exception:  # noqa: BLE001 — external sources are fail-open
                report = None

        # Sources may return credentials containing copy/paste corruption.  The
        # local mapping is the sole source of truth; never re-read os.environ.
        _sanitize_credential_mapping(working)
        values: dict[str, str] = {}
        provenance: dict[str, str] = {}
        if report is not None:
            for name, applied in report.provenance.items():
                if name in working:
                    values[name] = working[name]
                    provenance[name] = applied.source

        try:
            final_cfg, final_config_loaded = _load_secrets_config_with_status(
                resolved_home
            )
        except Exception:  # noqa: BLE001 — stability check remains fail-open
            final_cfg, final_config_loaded = {}, False
        final_cfg = final_cfg if isinstance(final_cfg, dict) else {}
        final_working, final_managed_names = _build_profile_resolution_environment(
            resolved_home,
            project_env=resolved_project_env,
            secrets_cfg=final_cfg,
            allow_process_bootstrap=allow_process_bootstrap,
        )
        final_fingerprint = (
            _secret_source_input_fingerprint(
                resolved_home,
                resolved_project_env,
            )
            + (
                (
                    "<secret-source-config>",
                    "status",
                    "loaded" if final_config_loaded else "unavailable",
                ),
            )
            + _secret_source_runtime_input_fingerprint(
                final_working,
                final_managed_names,
                final_cfg,
                allow_process_bootstrap=allow_process_bootstrap,
            )
        )
        report_succeeded = bool(
            report is not None
            and getattr(report, "cacheable", True)
            and all(not source_report.result.error for source_report in report.sources)
        )
        inputs_stable = input_fingerprint == final_fingerprint

        # Replace the complete per-home snapshot under one lock.  Readers can
        # observe either the previous resolution or this one, never a partial
        # mix of values/provenance from concurrent homes.  Failed fetches are
        # deliberately not cached: a transient empty result must retry on the
        # next call instead of becoming a process-lifetime false success.
        with _SECRET_SOURCE_CACHE_LOCK:
            generation_stable = (
                resolution_generation == _SECRET_SOURCE_CACHE_GENERATION
            )
            may_publish = bool(
                report_succeeded
                and inputs_stable
                and generation_stable
            )
            if may_publish:
                ttl = report.cache_ttl_seconds
                expires_at = (
                    None
                    if ttl is None
                    else _secret_source_cache_now() + max(0.0, ttl)
                )
                _PROFILE_SECRET_SOURCE_VALUES[home_key] = dict(values)
                _PROFILE_SECRET_SOURCE_PROVENANCE[home_key] = dict(provenance)
                _PROFILE_SECRET_SOURCE_ISOLATED[home_key] = isolated
                _PROFILE_SECRET_SOURCE_CACHE_METADATA[home_key] = (
                    _ExternalSecretCacheMetadata(
                        input_fingerprint=final_fingerprint,
                        expires_at=expires_at,
                        isolated=isolated,
                        generation=resolution_generation,
                    )
                )
                _RESOLVED_SECRET_SOURCE_HOMES.add(home_key)
                _SECRET_SOURCE_FORCE_REFRESH_HOMES.discard(home_key)
                _rebuild_secret_source_provenance_locked()
            elif not generation_stable:
                # A reset raced this fetch.  The aggregate result is discarded,
                # but a bundled adapter may already have populated its own cache;
                # force the next generation to replace that entry too.
                _SECRET_SOURCE_FORCE_REFRESH_HOMES.add(home_key)

        if not inputs_stable or not generation_stable:
            # The caller asked for a target-home snapshot that no longer
            # exists.  Returning the pre-change values would leak stale
            # credentials even though publication was correctly rejected.
            values = {}
            provenance = {}
            report = None
            report_succeeded = False

        return ExternalSecretResolution(
            home_path=resolved_home,
            values=dict(values),
            provenance=dict(provenance),
            report=report,
            from_cache=False,
            successful=report_succeeded,
            generation=resolution_generation,
        )


def resolve_external_secret_sources(
    home_path: str | os.PathLike,
    *,
    project_env: str | os.PathLike | None = None,
    force: bool = False,
) -> ExternalSecretResolution:
    """Resolve one profile's external secrets without mutating ``os.environ``.

    Only the target home's dotenv files, the optional project fallback,
    administrator-managed values, and legitimate OS/interactive-1Password
    process inputs participate.  The returned values/provenance are exact
    copies suitable for merging into a context-local secret scope.
    """
    return _resolve_external_secret_sources(
        Path(home_path),
        project_env=Path(project_env) if project_env is not None else None,
        force=force,
        allow_process_bootstrap=False,
    )


def load_fabric_dotenv(
    *,
    fabric_home: str | os.PathLike | None = None,
    project_env: str | os.PathLike | None = None,
) -> list[Path]:
    """Load Fabric environment files with user config taking precedence.

    Behavior:
    - `~/.hermes/.env` overrides stale shell-exported values when present.
    - project `.env` acts as a dev fallback and only fills missing values when
      the user env exists.
    - if no user env exists, the project `.env` also overrides stale shell vars.
    """
    loaded: list[Path] = []

    if fabric_home is not None:
        home_path = Path(fabric_home)
    else:
        env_home = (os.getenv("FABRIC_HOME") or os.getenv("HERMES_HOME") or "").strip()
        if env_home:
            home_path = Path(env_home)
        else:
            try:
                from fabric_constants import get_fabric_home
                home_path = get_fabric_home()
            except Exception:
                # public-release-audit: allow-legacy-compat -- reads the previous home during one-way migration
                legacy = Path.home() / ".hermes"
                modern = Path.home() / ".fabric"
                home_path = legacy if legacy.exists() and not modern.exists() else modern
    user_env = home_path / ".env"
    project_env_path = Path(project_env) if project_env else None

    # Fix corrupted .env files before python-dotenv parses them (#8908).
    if user_env.exists():
        _sanitize_env_file_if_needed(user_env)
    if project_env_path and project_env_path.exists():
        _sanitize_env_file_if_needed(project_env_path)

    if user_env.exists():
        _load_dotenv_with_fallback(user_env, override=True)
        loaded.append(user_env)

    # Load .op.env AFTER .env so that .env values win, but the bootstrap
    # token (OP_SERVICE_ACCOUNT_TOKEN) becomes available for
    # apply_onepassword_secrets() even in cron / subprocess environments
    # that inherit no shell state (no systemd EnvironmentFile, no op run).
    # .op.env is gitignored — the service-account token never enters the
    # committed .env file.
    # Users on systemd can alternatively use:
    #   EnvironmentFile=-/path/to/.hermes/.op.env
    # in their gateway unit, which takes precedence (override=False below
    # ensures .op.env never clobbers a token already in the environment).
    op_env = home_path / ".op.env"
    if op_env.exists() and not os.environ.get("OP_SERVICE_ACCOUNT_TOKEN"):
        _load_dotenv_with_fallback(op_env, override=False)

    if project_env_path and project_env_path.exists():
        _load_dotenv_with_fallback(project_env_path, override=not loaded)
        loaded.append(project_env_path)

    _apply_external_secret_sources(home_path, project_env=project_env_path)
    _apply_managed_env()

    return loaded


def _apply_managed_env() -> None:
    """Apply the managed-scope .env last, with override, so it beats user/shell.

    Managed scope is machine-global (independent of HERMES_HOME / profile). v1
    enforcement is "applied last with override=True" — at the end of startup load
    ``os.environ`` holds the managed value for every managed key, beating both the
    user ``.env`` and any pre-existing shell export. This deliberately inverts the
    usual env-over-config precedence for the pinned keys (see
    ``docs/design/managed-scope.md`` §4.1).

    This does NOT prevent the agent from later mutating ``os.environ`` in-process
    or ``export``-ing in a subprocess shell; that hard boundary is a documented
    v2 item (design §8.1). v1 relies on filesystem permissions only.

    Fail-open: a missing managed dir or .env is the common case and a no-op; any
    error here is swallowed so managed scope can never block startup.
    """
    try:
        from fabric_cli import managed_scope

        managed_dir = managed_scope.get_managed_dir()
    except Exception:  # noqa: BLE001 — managed scope must never block startup
        return
    if managed_dir is None:
        return
    managed_env = managed_dir / ".env"
    if not managed_env.exists():
        return
    _sanitize_env_file_if_needed(managed_env)
    _load_dotenv_with_fallback(managed_env, override=True)


def _apply_external_secret_sources(
    home_path: Path,
    *,
    project_env: Optional[Path] = None,
) -> None:
    """Pull secrets from every enabled external source into env.

    Runs AFTER dotenv loads but resolves through a per-call mapping, then
    copies only the exact externally applied values into ``os.environ`` for
    legacy single-profile callers.  Any failure is swallowed — external
    secret sources must never block startup.

    The heavy lifting (source ordering, mapped-beats-bulk precedence,
    first-claim-wins conflict handling, override semantics, provenance)
    lives in ``agent.secret_sources.registry.apply_all``; this wrapper owns
    legacy process-env application and startup status lines.  Home-qualified
    values are never reconstructed by reading shared ``os.environ`` after the
    fetch.

    Successful calls deduplicate through the target-home resolver cache, so
    import-time invocations from several hot modules still fetch and print
    once.  Unlike a process-lifetime applied-home guard, that cache expires at
    the shortest source TTL and invalidates when config/dotenv inputs change;
    failed or unstable resolutions retry instead of pinning an empty result.
    """
    home_key = str(Path(home_path).resolve())

    try:
        resolution = _resolve_external_secret_sources(
            Path(home_path),
            project_env=project_env,
            allow_process_bootstrap=True,
        )
    except Exception:  # noqa: BLE001 — external sources must not block startup
        with _SECRET_SOURCE_CACHE_LOCK:
            _APPLIED_HOMES.discard(home_key)
        return

    # Keep the legacy bookkeeping truthful for scheduler/tests that reset it,
    # but never let it decide freshness.  The resolver metadata is the single
    # validity authority.  Reconcile the exact last-applied snapshot so a
    # successful refresh can revoke dropped vault keys.  Deletion is
    # compare-and-remove: a newly loaded local .env or other runtime replacement
    # always wins over the old external value.
    with _SECRET_SOURCE_CACHE_LOCK:
        if resolution.generation != _SECRET_SOURCE_CACHE_GENERATION:
            _APPLIED_HOMES.discard(home_key)
            return
        if _profile_secret_source_cache_is_live_locked(home_key):
            _APPLIED_HOMES.add(home_key)
        else:
            _APPLIED_HOMES.discard(home_key)
        previous = dict(_LEGACY_APPLIED_SECRET_VALUES.get(home_key, {}))
        if resolution.successful:
            for name, old_value in previous.items():
                if name not in resolution.values and os.environ.get(name) == old_value:
                    os.environ.pop(name, None)
            os.environ.update(resolution.values)
            _LEGACY_APPLIED_SECRET_VALUES[home_key] = dict(resolution.values)
        else:
            # Preserve prior values on fail-open refreshes, but still accept a
            # successful contribution from another source in a partial report.
            os.environ.update(resolution.values)
            previous.update(resolution.values)
            if previous:
                _LEGACY_APPLIED_SECRET_VALUES[home_key] = previous

    report = resolution.report
    if report is None:
        return

    for src in report.sources:
        if src.applied:
            print(
                f"  {src.label}: applied {len(src.applied)} "
                f"secret{'s' if len(src.applied) != 1 else ''} "
                f"({', '.join(sorted(src.applied))})",
                file=sys.stderr,
            )
        if src.result.error:
            print(f"  {src.label}: {src.result.error}", file=sys.stderr)
        for warn in src.result.warnings:
            print(f"  {src.label}: {warn}", file=sys.stderr)
    for conflict in report.conflicts:
        print(f"  Secret sources: {conflict}", file=sys.stderr)


def _load_secrets_config_with_status(home_path: Path) -> tuple[dict, bool]:
    """Read ``secrets:`` and distinguish valid emptiness from read failure.

    Imported lazily and isolated from the main config loader so a
    malformed config can't take down dotenv loading entirely.
    """
    config_path = home_path / "config.yaml"
    if not config_path.exists():
        return {}, True
    try:
        import yaml  # type: ignore
    except ImportError:
        return {}, False
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = fast_safe_load(f) or {}
    except Exception:  # noqa: BLE001
        return {}, False
    if not isinstance(data, dict):
        return {}, False
    secrets = data.get("secrets")
    if secrets is None:
        return {}, True
    if not isinstance(secrets, dict):
        return {}, False
    return secrets, True


def _load_secrets_config(home_path: Path) -> dict:
    """Read just the ``secrets:`` section out of config.yaml."""
    return _load_secrets_config_with_status(home_path)[0]
