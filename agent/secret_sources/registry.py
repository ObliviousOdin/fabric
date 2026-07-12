"""Secret-source registry + apply orchestrator.

This module owns everything that must be uniform across secret backends
so no individual source can get it wrong:

* registration (name/scheme uniqueness, API-version gating)
* per-source wall-clock timeout enforcement around ``fetch()``
* precedence: mapped sources beat bulk sources; within a shape,
  ``secrets.sources`` order (or registration order) decides; first
  claim wins — later sources never silently clobber an earlier one
* ``override_existing`` semantics (may beat .env/shell, never another
  secret source, never a protected var)
* cross-source conflict warnings (shadowed claims are always surfaced)
* provenance: which source supplied every applied var

The single entry point for startup is :func:`apply_all`, called from
``fabric_cli.env_loader._apply_external_secret_sources()``.

Plugins register additional sources via
``PluginContext.register_secret_source()`` which lands in
:func:`register_source`.  In-tree sources are registered lazily by
:func:`_ensure_builtin_sources` — the set of bundled sources is
deliberately closed (Bitwarden, and 1Password once it lands); new
third-party backends ship as standalone plugin repos implementing
:class:`agent.secret_sources.base.SecretSource`.
"""

from __future__ import annotations

import concurrent.futures
import logging
import math
import os
import threading
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Collection, Dict, List, Mapping, Optional

from agent.secret_sources.base import (
    SECRET_SOURCE_API_VERSION,
    ErrorKind,
    FetchResult,
    SecretSource,
    is_valid_env_name,
)

logger = logging.getLogger(__name__)

# Ordered registry: name → source instance.  Python dicts preserve
# insertion order, which doubles as the default apply order.
_SOURCES: Dict[str, SecretSource] = {}
_BUILTINS_LOADED = False
_REGISTRY_LOCK = threading.RLock()
_REGISTRY_GENERATION = 0

# The bundled backends both default their own value caches to five minutes.
# The profile resolver uses the shortest enabled-source TTL so its aggregate
# snapshot can never outlive one of the source caches it represents.
_DEFAULT_SOURCE_CACHE_TTL_SECONDS = 300.0

# The environment a source may inspect during one fetch.  An explicit
# ``apply_all(..., environ=mapping)`` call installs an immutable snapshot in
# the fetch worker's own context, so concurrent profile resolutions never
# consult or mutate one shared process environment.
_RESOLUTION_ENV: ContextVar[Optional[Mapping[str, str]]] = ContextVar(
    "_SECRET_SOURCE_RESOLUTION_ENV",
    default=None,
)
_RESOLUTION_FORCE_REFRESH: ContextVar[bool] = ContextVar(
    "_SECRET_SOURCE_RESOLUTION_FORCE_REFRESH",
    default=False,
)


def get_resolution_environment() -> Mapping[str, str]:
    """Return the current per-fetch environment or the legacy process env.

    This is an additive adapter hook: bundled sources use it for bootstrap
    credentials and child-process construction, while existing third-party
    sources retain their required ``fetch(cfg, home_path)`` signature.
    """
    scoped = _RESOLUTION_ENV.get()
    return scoped if scoped is not None else os.environ


def get_resolution_force_refresh() -> bool:
    """Return whether this fetch must bypass and replace source-local caches.

    The aggregate resolver uses this for explicit ``force=True`` calls and for
    the first successful fetch after ``reset_secret_source_cache()``.  It is a
    ContextVar so concurrent homes can refresh independently without clearing a
    process-global source cache out from under another in-flight resolution.
    Existing third-party sources remain compatible; bundled sources opt in by
    consulting this additive hook.
    """
    return _RESOLUTION_FORCE_REFRESH.get()


def _call_in_resolution_context(
    environ: Mapping[str, str],
    home_path: Path,
    callback,
    *,
    force_refresh: bool = False,
):
    """Run one source hook with an immutable env and target home installed."""
    from fabric_constants import (
        reset_fabric_home_override,
        set_fabric_home_override,
    )

    env_token: Token = _RESOLUTION_ENV.set(MappingProxyType(dict(environ)))
    refresh_token: Token = _RESOLUTION_FORCE_REFRESH.set(bool(force_refresh))
    home_token = set_fabric_home_override(home_path)
    try:
        return callback()
    finally:
        reset_fabric_home_override(home_token)
        _RESOLUTION_FORCE_REFRESH.reset(refresh_token)
        _RESOLUTION_ENV.reset(env_token)


@dataclass
class AppliedVar:
    """Provenance record for one env var the orchestrator set."""

    name: str
    source: str          # SecretSource.name
    shape: str           # "mapped" | "bulk"
    overrode_env: bool   # replaced a pre-existing .env/shell value


@dataclass
class SourceReport:
    """One source's outcome within an :class:`ApplyReport`."""

    name: str
    label: str
    result: FetchResult
    applied: List[str] = field(default_factory=list)
    skipped_existing: List[str] = field(default_factory=list)   # .env/shell won
    skipped_claimed: List[str] = field(default_factory=list)    # earlier source won
    skipped_protected: List[str] = field(default_factory=list)  # bootstrap-auth guard
    skipped_invalid: List[str] = field(default_factory=list)    # bad env-var name


@dataclass
class ApplyReport:
    """Merged outcome of one orchestrated apply pass."""

    sources: List[SourceReport] = field(default_factory=list)
    provenance: Dict[str, AppliedVar] = field(default_factory=dict)
    conflicts: List[str] = field(default_factory=list)  # human-readable warnings
    cache_ttl_seconds: Optional[float] = None
    cacheable: bool = True

    @property
    def applied_any(self) -> bool:
        return bool(self.provenance)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_source(source: SecretSource, *, replace: bool = False) -> bool:
    """Register a secret source.  Returns True on success.

    Rejections are logged, never raised — a bad plugin must not take
    down startup.  ``replace`` allows tests / user plugins to override
    a bundled source of the same name (last-writer-wins like model
    providers), but scheme collisions across *different* names are
    always rejected.
    """
    global _REGISTRY_GENERATION
    with _REGISTRY_LOCK:
        if not isinstance(source, SecretSource):
            logger.warning(
                "Ignoring secret source %r: does not inherit from SecretSource",
                source,
            )
            return False
        name = getattr(source, "name", "") or ""
        if not name or not name.replace("_", "").isalnum() or name != name.lower():
            logger.warning("Ignoring secret source with invalid name %r", name)
            return False
        if getattr(source, "api_version", None) != SECRET_SOURCE_API_VERSION:
            logger.warning(
                "Ignoring secret source '%s': built against secret-source API v%s, "
                "this Fabric speaks v%s",
                name,
                getattr(source, "api_version", "?"),
                SECRET_SOURCE_API_VERSION,
            )
            return False
        if getattr(source, "shape", None) not in ("mapped", "bulk"):
            logger.warning(
                "Ignoring secret source '%s': shape must be 'mapped' or 'bulk', got %r",
                name,
                getattr(source, "shape", None),
            )
            return False
        if name in _SOURCES and not replace:
            logger.warning(
                "Secret source '%s' already registered; ignoring duplicate", name
            )
            return False
        scheme = getattr(source, "scheme", None)
        if scheme:
            for other_name, other in _SOURCES.items():
                if other_name != name and getattr(other, "scheme", None) == scheme:
                    logger.warning(
                        "Ignoring secret source '%s': scheme '%s://' is already "
                        "owned by source '%s'",
                        name,
                        scheme,
                        other_name,
                    )
                    return False
        _SOURCES[name] = source
        _REGISTRY_GENERATION += 1
        return True


def get_source(name: str) -> Optional[SecretSource]:
    _ensure_builtin_sources()
    with _REGISTRY_LOCK:
        return _SOURCES.get(name)


def list_sources() -> List[SecretSource]:
    _ensure_builtin_sources()
    with _REGISTRY_LOCK:
        return list(_SOURCES.values())


def get_registry_generation() -> int:
    """Return a monotonic identity for the complete registered source set."""
    _ensure_builtin_sources()
    with _REGISTRY_LOCK:
        return _REGISTRY_GENERATION


def _ensure_builtin_sources() -> None:
    """Idempotently register the bundled sources.

    Lazy so importing this module stays cheap and so a broken bundled
    source can never break registration of the others.
    """
    global _BUILTINS_LOADED
    # Keep the lock for the complete registration pass.  Setting the loaded
    # flag before imports prevents recursive initialization, while the lock
    # prevents another cold resolver from observing the flag alongside an
    # empty or half-populated registry.
    with _REGISTRY_LOCK:
        if _BUILTINS_LOADED:
            return
        _BUILTINS_LOADED = True
        try:
            from agent.secret_sources.bitwarden import BitwardenSource

            register_source(BitwardenSource())
        except Exception:  # noqa: BLE001 — never block startup
            logger.warning(
                "Failed to register bundled Bitwarden secret source",
                exc_info=True,
            )
        try:
            from agent.secret_sources.onepassword import OnePasswordSource

            register_source(OnePasswordSource())
        except Exception:  # noqa: BLE001 — never block startup
            logger.warning(
                "Failed to register bundled 1Password secret source",
                exc_info=True,
            )


def _reset_registry_for_tests() -> None:
    global _BUILTINS_LOADED, _REGISTRY_GENERATION
    with _REGISTRY_LOCK:
        _SOURCES.clear()
        _BUILTINS_LOADED = False
        _REGISTRY_GENERATION += 1


def _coerce_source_cache_ttl_seconds(cfg: dict) -> float:
    """Return the resolver TTL matching bundled source cache semantics."""
    try:
        ttl = float((cfg or {}).get(
            "cache_ttl_seconds", _DEFAULT_SOURCE_CACHE_TTL_SECONDS
        ))
    except (TypeError, ValueError):
        return _DEFAULT_SOURCE_CACHE_TTL_SECONDS
    if not math.isfinite(ttl):
        return _DEFAULT_SOURCE_CACHE_TTL_SECONDS
    return max(0.0, ttl)


def _mapped_expected_env_names(source: SecretSource, cfg: dict) -> set[str]:
    """Return valid explicitly mapped names a complete fetch must contain.

    Mapped adapters conventionally expose an ``env`` name-to-reference map.
    Comparing valid configured names with ``FetchResult.secrets`` carries the
    backend's "partial pulls are not cacheable" contract through the generic
    orchestrator without adding backend-specific core logic.
    """
    env_map = (cfg or {}).get("env")
    if not isinstance(env_map, dict):
        return set()
    scheme = getattr(source, "scheme", None)
    prefix = f"{scheme}://" if scheme else None
    expected: set[str] = set()
    for name, reference in env_map.items():
        if not isinstance(name, str) or not is_valid_env_name(name):
            continue
        if not isinstance(reference, str):
            continue
        if prefix is not None and not reference.strip().startswith(prefix):
            continue
        expected.add(name)
    return expected


# ---------------------------------------------------------------------------
# Orchestrated apply
# ---------------------------------------------------------------------------


def _fetch_with_timeout(
    source: SecretSource,
    cfg: dict,
    home_path: Path,
    environ: Mapping[str, str],
    *,
    force_refresh: bool = False,
) -> FetchResult:
    """Run source.fetch() under a wall-clock budget; never raises.

    The budget is enforced with a daemon worker thread: a source that
    blows its budget is reported as ``TIMEOUT`` and its (eventual)
    result is discarded.  The thread itself may linger until process
    exit — acceptable for a startup-only path, and strictly better than
    an unbounded hang on every ``fabric`` invocation.
    """
    # The caller's mapping is also the apply target.  Snapshot it before the
    # worker starts so neither concurrent writes nor another source's result
    # can change the bootstrap identity half-way through this fetch.
    fetch_env = MappingProxyType(dict(environ))
    timeout = _call_in_resolution_context(
        fetch_env,
        home_path,
        lambda: source.fetch_timeout_seconds(cfg),
    )
    executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=1, thread_name_prefix=f"secret-src-{source.name}"
    )
    def _fetch_in_scope() -> FetchResult:
        return _call_in_resolution_context(
            fetch_env,
            home_path,
            lambda: source.fetch(cfg, home_path),
            force_refresh=force_refresh,
        )

    try:
        future = executor.submit(_fetch_in_scope)
        try:
            result = future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            future.cancel()
            res = FetchResult()
            res.error = (
                f"fetch exceeded {timeout:.0f}s budget — startup continued "
                "without this source (raise secrets."
                f"{source.name}.timeout_seconds if the backend is just slow)"
            )
            res.error_kind = ErrorKind.TIMEOUT
            return res
        except Exception as exc:  # noqa: BLE001 — contract violation, contain it
            res = FetchResult()
            res.error = f"fetch raised {type(exc).__name__}: {exc}"
            res.error_kind = ErrorKind.INTERNAL
            return res
    finally:
        executor.shutdown(wait=False)

    if not isinstance(result, FetchResult):
        res = FetchResult()
        res.error = (
            f"fetch returned {type(result).__name__} instead of FetchResult"
        )
        res.error_kind = ErrorKind.INTERNAL
        return res
    return result


def _ordered_enabled_sources(
    secrets_cfg: dict,
    *,
    environ: Mapping[str, str],
    home_path: Path,
    require_scoped_environment: bool,
) -> List[SecretSource]:
    """Resolve which sources run, in which order.

    Order: the optional ``secrets.sources`` list wins; sources not named
    there follow in registration order.  Enabled = the source's own
    ``is_enabled`` says so for its config section.  Mapped-vs-bulk
    precedence is applied on top of this order by :func:`apply_all`.
    """
    _ensure_builtin_sources()
    with _REGISTRY_LOCK:
        # Registration may continue on another thread (for example while a
        # plugin loads).  One apply pass operates on one stable ordered view.
        sources = dict(_SOURCES)

    explicit = secrets_cfg.get("sources")
    order: List[str] = []
    if isinstance(explicit, list):
        for entry in explicit:
            if isinstance(entry, str) and entry in sources and entry not in order:
                order.append(entry)
        unknown = [e for e in explicit
                   if isinstance(e, str) and e not in sources]
        if unknown:
            logger.warning(
                "secrets.sources names unknown source(s): %s (known: %s)",
                ", ".join(unknown), ", ".join(sources) or "none",
            )
    for name in sources:
        if name not in order:
            order.append(name)

    enabled: List[SecretSource] = []
    for name in order:
        source = sources[name]
        cfg = secrets_cfg.get(name)
        cfg = cfg if isinstance(cfg, dict) else {}
        if require_scoped_environment and not bool(
            getattr(source, "supports_scoped_environment", False)
        ):
            # Do not execute even ``is_enabled`` on an unscoped plugin.  Its
            # default declaration says its hooks may consult shared process
            # state.  Raw config is sufficient to include an explicitly
            # enabled source in the report, where it receives the fail-closed
            # compatibility error.
            if bool(cfg.get("enabled")):
                enabled.append(source)
            continue
        try:
            source_enabled = _call_in_resolution_context(
                environ,
                home_path,
                lambda: source.is_enabled(cfg),
            )
            if source_enabled:
                enabled.append(source)
        except Exception:  # noqa: BLE001
            logger.warning("Secret source '%s' is_enabled() raised; skipping",
                           name, exc_info=True)
    return enabled


def apply_all(
    secrets_cfg: dict,
    home_path: Path,
    environ: Optional[Dict[str, str]] = None,
    *,
    immutable_vars: Collection[str] = (),
    require_scoped_environment: bool = False,
    force_refresh: bool = False,
) -> ApplyReport:
    """Fetch from every enabled source and apply the merged result to env.

    ``environ`` defaults to ``os.environ``.  An explicit mapping is both the
    isolated fetch context and the apply target.  ``immutable_vars`` names
    administrator-managed values that no external source may replace.  When
    ``require_scoped_environment`` is true, enabled legacy adapters that have
    not opted into the per-fetch environment contract are skipped fail-closed.
    ``force_refresh`` asks cache-aware sources to skip stale local reads while
    still replacing their caches after a complete successful fetch.

    Precedence per env var (most-specific intent wins):

    1. Pre-existing env (.env / shell) — unless the winning source has
       ``override_existing: true``.
    2. Mapped sources, in configured order.
    3. Bulk sources, in configured order.

    First claim wins.  A later source that also carries the var gets a
    ``skipped_claimed`` entry and a conflict warning — never a silent
    clobber, and ``override_existing`` never applies across sources.
    """
    env = environ if environ is not None else os.environ
    report = ApplyReport()

    secrets_cfg = secrets_cfg if isinstance(secrets_cfg, dict) else {}
    enabled = _ordered_enabled_sources(
        secrets_cfg,
        environ=env,
        home_path=home_path,
        require_scoped_environment=require_scoped_environment,
    )
    if not enabled:
        return report

    # The resolver caches the aggregate result no longer than the shortest
    # enabled source's own configured cache.  A zero TTL therefore disables
    # aggregate reuse too, matching the bundled backends' no-cache behavior.
    report.cache_ttl_seconds = min(
        _coerce_source_cache_ttl_seconds(
            secrets_cfg.get(source.name)
            if isinstance(secrets_cfg.get(source.name), dict)
            else {}
        )
        for source in enabled
    )

    # Mapped sources outrank bulk sources regardless of list order:
    # an explicit VAR→ref binding is stronger intent than a project dump.
    ordered = ([s for s in enabled if s.shape == "mapped"]
               + [s for s in enabled if s.shape == "bulk"])

    # Fetch phase.
    fetches: List[tuple[SecretSource, dict, FetchResult]] = []
    protected: Dict[str, str] = {
        var: "managed scope"
        for var in immutable_vars
        if isinstance(var, str) and is_valid_env_name(var)
    }  # var → source/policy that protects it
    for source in ordered:
        cfg = secrets_cfg.get(source.name)
        cfg = cfg if isinstance(cfg, dict) else {}
        if require_scoped_environment and not bool(
            getattr(source, "supports_scoped_environment", False)
        ):
            result = FetchResult(
                error=(
                    f"secret source {source.name!r} does not declare profile-scoped "
                    "environment support; skipped to prevent cross-profile "
                    "credential access"
                ),
                error_kind=ErrorKind.INTERNAL,
            )
        else:
            result = _fetch_with_timeout(
                source,
                cfg,
                home_path,
                env,
                force_refresh=force_refresh,
            )
        fetches.append((source, cfg, result))
        expected_names = _mapped_expected_env_names(source, cfg)
        if result.error or not expected_names.issubset(result.secrets):
            report.cacheable = False
        if require_scoped_environment and not bool(
            getattr(source, "supports_scoped_environment", False)
        ):
            continue
        try:
            protected_vars = _call_in_resolution_context(
                env,
                home_path,
                lambda: source.protected_env_vars(cfg),
            )
            for var in protected_vars:
                protected.setdefault(var, source.name)
        except Exception:  # noqa: BLE001
            pass

    # Apply phase — sequential, first-wins, fully attributed.
    claimed: Dict[str, str] = {}  # var → source name that won it
    for source, cfg, result in fetches:
        sr = SourceReport(name=source.name,
                          label=source.label or source.name,
                          result=result)
        report.sources.append(sr)
        if not result.ok:
            continue

        try:
            override = _call_in_resolution_context(
                env,
                home_path,
                lambda: source.override_existing(cfg),
            )
        except Exception:  # noqa: BLE001
            override = False

        for var, value in result.secrets.items():
            if not isinstance(var, str) or not isinstance(value, str):
                continue
            if not is_valid_env_name(var):
                sr.skipped_invalid.append(var)
                continue
            if var in protected:
                sr.skipped_protected.append(var)
                continue
            if var in claimed:
                sr.skipped_claimed.append(var)
                report.conflicts.append(
                    f"{var}: kept value from {claimed[var]}; "
                    f"{source.name} also supplies it (first source wins — "
                    "remove one binding or reorder secrets.sources)"
                )
                continue
            existed = bool(env.get(var))
            if existed and not override:
                sr.skipped_existing.append(var)
                continue
            env[var] = value
            claimed[var] = source.name
            sr.applied.append(var)
            report.provenance[var] = AppliedVar(
                name=var,
                source=source.name,
                shape=source.shape,
                overrode_env=existed,
            )

    return report
