"""Authoritative, read-only memory capability and lifecycle snapshot.

The CLI, dashboard REST API, and TUI/desktop JSON-RPC surface all consume this
module.  It deliberately separates facts that older status UIs conflated:

* installed/discovered: an adapter directory exists;
* runtime ready: the adapter's cheap, network-free ``is_available`` check passed;
* selected: ``memory.provider`` names the adapter;
* activation-eligible: static prerequisites permit a future session to try the
  adapter; this is never presented as proof that a live session initialized it;
* healthy: only known after an explicit live health probe (never performed here).

In online mode, status inspection imports only bundled provider adapters.
User-installed providers are inventoried from files/manifests without executing
their modules, constructors, or availability hooks. In ``local_ai`` and
``air_gapped`` modes, no external adapter is imported or probed at all. Status
never initializes a provider, performs a health request, or exposes provider
configuration-field or secret values. Deliberate status facts such as the selected
provider name and tier-enabled flags remain visible.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shlex
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from agent.memory_provider import (
    MemoryCapabilitySupport,
    MemoryProviderCapabilities,
)
from agent.memory_write_policy import resolve_external_memory_write_policy
from fabric_constants import get_fabric_home
from utils import is_truthy_value


MEMORY_STATUS_SCHEMA_VERSION = 2
_CAPABILITY_KEYS = (
    "recall",
    "capture",
    "store",
    "search",
    "list",
    "edit",
    "delete",
    "export",
    "import",
    "backup",
    "provenance",
    "health",
    "local_only",
    "deletion_guarantee",
)
_SUPPORT_VALUES = {member.value for member in MemoryCapabilitySupport}
_RESTRICTED_MEMORY_EGRESS_MODES = frozenset({"local_ai", "air_gapped"})


def _memory_egress_mode(config: Mapping[str, Any] | None) -> str:
    """Return the normalized profile egress mode needed by memory status.

    Status must decide whether adapter inspection is safe before importing the
    plugin loader.  Reading this one non-secret field directly also keeps the
    snapshot profile-scoped and uncached.  Full config validation remains the
    responsibility of :mod:`agent.egress_policy` and ``fabric config``.
    """

    if not isinstance(config, Mapping):
        return "online"
    security = config.get("security")
    if not isinstance(security, Mapping):
        return "online"
    raw_mode = security.get("egress_mode", "online")
    if not isinstance(raw_mode, str):
        return "online"
    normalized = raw_mode.strip().lower()
    return normalized if normalized in _RESTRICTED_MEMORY_EGRESS_MODES else "online"


def _external_memory_policy_reason(egress_mode: str) -> str:
    if egress_mode == "air_gapped":
        return "whole_process_network_boundary_missing"
    return "external_memory_adapters_not_policy_integrated"


def normalize_memory_provider_name(value: object) -> str:
    """Return the configured external provider slug, or ``""`` for built-in."""

    name = str(value or "").strip()
    if name.lower() in {"built-in", "builtin", "none"}:
        return ""
    return name


def memory_tier_state(memory_config: object) -> tuple[bool, bool]:
    """Return effective MEMORY.md and USER.md enablement from merged config."""

    if not isinstance(memory_config, Mapping):
        memory_config = {}
    return (
        is_truthy_value(memory_config.get("memory_enabled"), default=True),
        is_truthy_value(memory_config.get("user_profile_enabled"), default=True),
    )


def _unknown_capabilities() -> dict[str, str]:
    return {key: MemoryCapabilitySupport.UNKNOWN.value for key in _CAPABILITY_KEYS}


def _normalize_capabilities(provider: Any) -> tuple[dict[str, str], bool]:
    """Return a strict capability mapping plus a declaration-error flag."""

    if provider is None:
        return _unknown_capabilities(), False
    getter = getattr(provider, "get_capabilities", None)
    if not callable(getter):
        return _unknown_capabilities(), False
    try:
        raw = getter()
    except Exception:
        return _unknown_capabilities(), True

    if isinstance(raw, MemoryProviderCapabilities):
        values: Mapping[str, object] = raw.as_dict()
    elif isinstance(raw, Mapping):
        values = raw
    else:
        return _unknown_capabilities(), True

    normalized = _unknown_capabilities()
    invalid = False
    for key in _CAPABILITY_KEYS:
        raw_value = values.get(key, MemoryCapabilitySupport.UNKNOWN.value)
        if isinstance(raw_value, MemoryCapabilitySupport):
            value = raw_value.value
        else:
            value = str(raw_value or "").strip().lower()
        if value not in _SUPPORT_VALUES:
            value = MemoryCapabilitySupport.UNKNOWN.value
            invalid = True
        normalized[key] = value
    return normalized, invalid


def _provider_source(provider_dir: object, bundled_root: Path) -> str:
    if not isinstance(provider_dir, Path):
        return "unknown"
    try:
        return (
            "bundled"
            if provider_dir.parent.resolve() == bundled_root.resolve()
            else "user"
        )
    except OSError:
        return "unknown"


def _looks_like_user_memory_provider(path: Path) -> bool:
    """Recognize a user memory adapter without importing untrusted code."""

    init_file = path / "__init__.py"
    if not init_file.is_file():
        return False
    try:
        source = init_file.read_text(encoding="utf-8", errors="replace")[:8192]
    except OSError:
        return False
    return "register_memory_provider" in source or "MemoryProvider" in source


def _static_provider_inventory(
    home: Path,
    bundled_root: Path,
) -> list[tuple[str, str, bool | None]]:
    """List bundled and user adapters without importing either category."""

    rows: list[tuple[str, str, bool | None]] = []
    seen: set[str] = set()
    roots = ((bundled_root, False), (home / "plugins", True))
    for root, user_root in roots:
        try:
            children = sorted(root.iterdir()) if root.is_dir() else []
        except OSError:
            children = []
        for child in children:
            name = child.name
            if (
                name in seen
                or name.startswith(("_", "."))
                or not child.is_dir()
                or not (child / "__init__.py").is_file()
                or (user_root and not _looks_like_user_memory_provider(child))
            ):
                continue
            seen.add(name)
            description = str(_provider_manifest(child).get("description") or "")
            # Availability is intentionally unobserved here. Bundled adapters
            # are inspected later; user adapters remain static-only.
            rows.append((name, description, None))
    return rows


def _static_provider_dir(
    name: str,
    *,
    home: Path,
    bundled_root: Path,
) -> Path | None:
    bundled = bundled_root / name
    if bundled.is_dir() and (bundled / "__init__.py").is_file():
        return bundled
    user = home / "plugins" / name
    if user.is_dir() and _looks_like_user_memory_provider(user):
        return user
    return None


def _load_profile_env(home: Path) -> dict[str, str]:
    """Read the selected profile's env file without mutating ``os.environ``."""

    try:
        if Path(get_fabric_home()).resolve() == home.resolve():
            from fabric_cli.config import load_env

            return load_env()
    except OSError:
        pass

    env_path = home / ".env"
    if not env_path.is_file():
        return {}
    try:
        from fabric_cli.config import _parse_env_value, _sanitize_env_lines

        raw_lines = env_path.read_text(
            encoding="utf-8-sig", errors="replace"
        ).splitlines(keepends=True)
        lines = _sanitize_env_lines(raw_lines)
        parsed: dict[str, str] = {}
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[7:]
            key, _, value = line.partition("=")
            parsed[key.strip()] = _parse_env_value(value)
        return parsed
    except Exception:
        return {}


def _read_json_mapping(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _provider_config_values(
    name: str,
    *,
    home: Path,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Collect common profile-scoped provider values without returning them."""

    values: dict[str, Any] = {}
    for path in (home / f"{name}.json", home / name / "config.json"):
        if path.is_file():
            values.update(_read_json_mapping(path))

    memory_config = config.get("memory")
    if isinstance(memory_config, Mapping):
        legacy = memory_config.get("provider_config")
        if isinstance(legacy, Mapping):
            values = {**legacy, **values}
        native = memory_config.get(name)
        if isinstance(native, Mapping):
            values.update(native)

    if name == "holographic":
        plugins_config = config.get("plugins")
        if isinstance(plugins_config, Mapping):
            native = plugins_config.get("hermes-memory-store")
            if isinstance(native, Mapping):
                values.update(native)
    return values


def _schema_env_names(schema: list[dict[str, Any]]) -> set[str]:
    return {
        str(field.get("env_var") or "").strip()
        for field in schema
        if str(field.get("env_var") or "").strip()
    }


def _field_effective_value(
    field: Mapping[str, Any],
    values: Mapping[str, Any],
    env: Mapping[str, str],
) -> object:
    key = str(field.get("key") or "")
    value = values.get(key)
    env_name = str(field.get("env_var") or "").strip()
    if value in (None, "") and env_name:
        value = env.get(env_name, "")
    if value in (None, "") and not field.get("secret"):
        value = field.get("default", "")
    return value


def _field_visible(
    field: Mapping[str, Any],
    schema: list[dict[str, Any]],
    values: Mapping[str, Any],
    env: Mapping[str, str],
) -> bool:
    when = field.get("when")
    if not isinstance(when, Mapping) or not when:
        return True
    by_key = {
        str(candidate.get("key") or ""): candidate
        for candidate in schema
        if candidate.get("key")
    }
    for dependency, expected in when.items():
        dep_field = by_key.get(str(dependency), {"key": str(dependency)})
        if str(_field_effective_value(dep_field, values, env)) != str(expected):
            return False
    return True


def _configuration_complete(
    name: str,
    provider: Any,
    *,
    home: Path,
    config: Mapping[str, Any],
    env: Mapping[str, str],
    required_env: list[str],
) -> tuple[bool | None, list[dict[str, Any]], set[str]]:
    """Return required-field completeness, schema, and declared env names."""

    getter = getattr(provider, "get_config_schema", None)
    if not callable(getter):
        schema: list[dict[str, Any]] = []
    else:
        try:
            raw_schema = getter()
            if not isinstance(raw_schema, list):
                return None, [], set()
            schema = [field for field in raw_schema if isinstance(field, dict)]
        except Exception:
            return None, [], set()

    values = _provider_config_values(name, home=home, config=config)
    required_fields = [
        field
        for field in schema
        if field.get("required") and _field_visible(field, schema, values, env)
    ]
    fields_complete = all(
        _field_effective_value(field, values, env) not in (None, "")
        for field in required_fields
    )
    required_any_groups = {
        str(field.get("required_any") or "").strip()
        for field in schema
        if str(field.get("required_any") or "").strip()
        and _field_visible(field, schema, values, env)
    }
    alternatives_complete = all(
        any(
            str(field.get("required_any") or "").strip() == group
            and _field_visible(field, schema, values, env)
            and _field_effective_value(field, values, env) not in (None, "")
            for field in schema
        )
        for group in required_any_groups
    )
    manifest_complete = all(bool(env.get(key)) for key in required_env)
    return (
        fields_complete and alternatives_complete and manifest_complete,
        schema,
        _schema_env_names(schema),
    )


def _provider_manifest(provider_dir: Path | None) -> dict[str, Any]:
    if provider_dir is None:
        return {}
    path = provider_dir / "plugin.yaml"
    if not path.is_file():
        return {}
    try:
        import yaml

        value = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


_DEPENDENCY_IMPORT_NAMES = {
    "honcho-ai": "honcho",
    "mem0ai": "mem0",
    "hindsight-client": "hindsight_client",
    "hindsight-all": "hindsight",
}


def _dependency_import_name(requirement: str) -> str:
    package = requirement
    for marker in ("[", "<", ">", "=", "!", "~", ";"):
        package = package.split(marker, 1)[0]
    package = package.strip()
    return _DEPENDENCY_IMPORT_NAMES.get(package, package.replace("-", "_"))


def _dependencies_available(manifest: Mapping[str, Any]) -> bool | None:
    """Perform import/path checks only; never execute manifest commands."""

    for requirement in _string_list(manifest.get("pip_dependencies")):
        module = _dependency_import_name(requirement)
        try:
            if not module or importlib.util.find_spec(module) is None:
                return False
        except (ImportError, ModuleNotFoundError, ValueError):
            return False

    unknown = False
    external = manifest.get("external_dependencies") or []
    if not isinstance(external, list):
        return None
    for raw in external:
        if not isinstance(raw, Mapping):
            continue
        check = str(raw.get("check") or "").strip()
        if not check:
            if raw.get("install"):
                unknown = True
            continue
        try:
            command = shlex.split(check)[0]
        except (ValueError, IndexError):
            unknown = True
            continue
        if not shutil.which(command):
            return False
    return None if unknown else True


def _profile_readiness_is_reliable(
    schema_env_names: set[str],
    required_env: list[str],
    profile_env: Mapping[str, str],
) -> bool:
    """Whether provider ``is_available`` observed this profile's credentials."""

    for key in schema_env_names | set(required_env):
        if str(profile_env.get(key) or "") != str(os.environ.get(key) or ""):
            return False
    return True


def _builtin_status(home: Path, memory_config: Mapping[str, Any]) -> dict[str, Any]:
    memory_enabled, user_profile_enabled = memory_tier_state(memory_config)
    files: dict[str, int] = {}
    memory_dir = home / "memories"
    for filename, key in (("MEMORY.md", "memory"), ("USER.md", "user")):
        path = memory_dir / filename
        try:
            files[key] = path.stat().st_size if path.is_file() else 0
        except OSError:
            files[key] = 0

    supported = MemoryCapabilitySupport.SUPPORTED.value
    unsupported = MemoryCapabilitySupport.UNSUPPORTED.value
    return {
        "name": "builtin",
        "description": "Profile-scoped MEMORY.md and USER.md curated memory.",
        "enabled": memory_enabled or user_profile_enabled,
        "runtime_active": "unknown",
        "tiers": {
            "memory": {"enabled": memory_enabled, "file": "MEMORY.md"},
            "user": {"enabled": user_profile_enabled, "file": "USER.md"},
        },
        "write_approval": is_truthy_value(
            memory_config.get("write_approval"), default=False
        ),
        "files": files,
        "health": {"state": "unknown", "checked": False, "reason": "not_probed"},
        "capabilities": {
            "recall": supported,
            "capture": unsupported,
            "store": supported,
            "search": unsupported,
            "list": supported,
            "edit": supported,
            "delete": supported,
            "export": unsupported,
            "import": unsupported,
            "backup": supported,
            "provenance": unsupported,
            "health": unsupported,
            "local_only": supported,
            # Removing a local entry is implemented, but secure erasure from
            # filesystem snapshots/backups is not promised by this adapter.
            "deletion_guarantee": unsupported,
        },
    }


def _build_memory_status_snapshot_impl(
    *,
    config: Mapping[str, Any] | None = None,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
    discover: Callable[[], list[tuple[str, str, bool | None]]] | None = None,
    load_provider: Callable[[str], Any] | None = None,
    find_provider_dir: Callable[[str], Path | None] | None = None,
) -> dict[str, Any]:
    """Build the shared memory status contract without live provider probes.

    Optional callables make the discovery boundary deterministic in tests and
    let alternative hosts reuse the serializer. Exceptions are converted into
    controlled issue codes; exception text is never returned because provider
    errors can contain endpoint URLs, credentials, or local paths.
    """

    if config is None:
        from fabric_cli.config import load_config

        loaded = load_config()
        config = loaded if isinstance(loaded, Mapping) else {}
    if home is None:
        home = Path(get_fabric_home())
    if env is None:
        env = _load_profile_env(home)

    memory_config_raw = config.get("memory") if isinstance(config, Mapping) else {}
    memory_config: Mapping[str, Any] = (
        memory_config_raw if isinstance(memory_config_raw, Mapping) else {}
    )
    memory_enabled, user_profile_enabled = memory_tier_state(memory_config)
    any_tier_enabled = memory_enabled or user_profile_enabled
    external_write_policy = resolve_external_memory_write_policy(memory_config)
    selected = normalize_memory_provider_name(memory_config.get("provider"))
    egress_mode = _memory_egress_mode(config)
    external_memory_blocked = egress_mode in _RESTRICTED_MEMORY_EGRESS_MODES

    injected_boundary = any(
        callback is not None for callback in (discover, load_provider, find_provider_dir)
    )
    if external_memory_blocked:
        # Restricted modes inventory adapters from disk only.  Do not import
        # ``plugins.memory``: its public discovery path constructs adapters and
        # calls ``is_available``.  Injected discovery/loader/resolver callbacks
        # are deliberately ignored so every host gets the same no-execution
        # status boundary; callers cannot accidentally pass the live plugin
        # discovery function through this read-only surface.
        bundled_root = Path(__file__).resolve().parents[1] / "plugins" / "memory"
        discover = (
            lambda: _static_provider_inventory(home, bundled_root)
        )
        find_provider_dir = (
            lambda name: _static_provider_dir(
                name,
                home=home,
                bundled_root=bundled_root,
            )
        )
    elif discover is None or load_provider is None or find_provider_dir is None:
        from plugins import memory as memory_plugins

        bundled_root = Path(memory_plugins.__file__).resolve().parent
        discover = discover or (
            lambda: _static_provider_inventory(home, bundled_root)
        )
        load_provider = load_provider or memory_plugins.load_memory_provider
        find_provider_dir = find_provider_dir or (
            lambda name: _static_provider_dir(
                name,
                home=home,
                bundled_root=bundled_root,
            )
        )
    else:
        # Only used for source labelling under injected discovery. Callers that
        # need an exact label can return paths rooted under this canonical dir.
        bundled_root = Path(__file__).resolve().parents[1] / "plugins" / "memory"

    issues: list[dict[str, str]] = []
    if egress_mode == "air_gapped":
        issues.append(
            {
                "code": "egress_policy_unavailable",
                "mode": "air_gapped",
                "reason": "whole_process_network_boundary_missing",
                "message": (
                    "security.egress_mode=air_gapped is configured but unavailable; "
                    "Fabric has no verified whole-process network boundary."
                ),
            }
        )
    raw_rows: list[tuple[str, str, bool | None]] = []
    try:
        discovered = discover()
        if isinstance(discovered, list):
            raw_rows = discovered
    except Exception:
        issues.append(
            {
                "code": "provider_discovery_failed",
                "message": "Memory provider discovery failed.",
            }
        )

    rows_by_name: dict[str, dict[str, Any]] = {}
    for raw in raw_rows:
        if not isinstance(raw, (tuple, list)) or len(raw) < 3:
            continue
        name = str(raw[0] or "").strip()
        if not name or name in rows_by_name:
            continue
        description = str(raw[1] or "")
        raw_process_readiness = raw[2]
        process_readiness: bool | None = None
        if not external_memory_blocked and raw_process_readiness is not None:
            process_readiness = bool(raw_process_readiness)

        provider_dir = None
        try:
            provider_dir = find_provider_dir(name)
        except Exception:
            pass
        source = _provider_source(provider_dir, bundled_root)
        # User plugin imports/constructors are outside the read-only status
        # trust boundary. Injected test/host boundaries remain caller-trusted.
        inspect_provider = not external_memory_blocked and (
            injected_boundary or source == "bundled"
        )
        provider = None
        load_failed = False
        load_inspected = False
        if inspect_provider:
            load_inspected = True
            try:
                provider = load_provider(name)
                load_failed = provider is None
            except Exception:
                load_failed = True
            if provider is not None and process_readiness is None:
                try:
                    process_readiness = bool(provider.is_available())
                except Exception:
                    process_readiness = False

        manifest = _provider_manifest(provider_dir)
        required_env = _string_list(manifest.get("requires_env"))
        dependencies_available = (
            None
            if external_memory_blocked
            else _dependencies_available(manifest)
        )
        if inspect_provider:
            configuration_complete, schema, schema_env_names = _configuration_complete(
                name,
                provider,
                home=home,
                config=config,
                env=env,
                required_env=required_env,
            )
            readiness_reliable = _profile_readiness_is_reliable(
                schema_env_names, required_env, env
            )
        else:
            configuration_complete, schema, schema_env_names = None, [], set()
            readiness_reliable = False
        adapter_ready: bool | None = (
            process_readiness if readiness_reliable else None
        )

        capabilities, declaration_invalid = _normalize_capabilities(provider)
        if load_inspected and load_failed:
            issues.append(
                {
                    "code": "provider_load_failed",
                    "provider": name,
                    "message": f"Memory provider '{name}' could not be loaded.",
                }
            )
        if declaration_invalid:
            issues.append(
                {
                    "code": "capability_declaration_invalid",
                    "provider": name,
                    "message": f"Memory provider '{name}' has an invalid capability declaration.",
                }
            )

        is_selected = name == selected
        activation_eligible = bool(
            is_selected
            and any_tier_enabled
            and not load_failed
            and dependencies_available is True
            and configuration_complete is True
            and adapter_ready is True
        )
        if external_memory_blocked:
            legacy_status = "unavailable"
        elif load_failed or dependencies_available is False:
            legacy_status = "unavailable"
        elif configuration_complete is False:
            legacy_status = "needs_config"
        elif adapter_ready is True:
            legacy_status = "ready"
        elif adapter_ready is None:
            legacy_status = "readiness_unknown"
        else:
            legacy_status = "unavailable"
        rows_by_name[name] = {
            "name": name,
            "description": description,
            "source": source,
            "installed": True,
            "discovered": True,
            # Legacy dashboard aliases. New clients use ``readiness`` below.
            "available": adapter_ready is True,
            "configured": (
                False
                if external_memory_blocked
                else configuration_complete is True
            ),
            "setup_complete": (
                False
                if external_memory_blocked
                else configuration_complete is True
            ),
            "selected": is_selected,
            "activation_eligible": activation_eligible,
            "runtime_active": "unknown",
            # Backward-compatible summary used by the existing dashboard.
            "status": legacy_status,
            "lifecycle": {
                "installation": "installed",
                "load": (
                    "not_inspected"
                    if external_memory_blocked
                    else (
                        "error"
                        if load_failed
                        else ("loaded" if load_inspected else "not_inspected")
                    )
                ),
                "configuration": (
                    "complete"
                    if configuration_complete is True
                    else ("incomplete" if configuration_complete is False else "unknown")
                ),
                "dependencies": (
                    "available"
                    if dependencies_available is True
                    else ("unavailable" if dependencies_available is False else "unknown")
                ),
                "adapter_readiness": (
                    "ready"
                    if adapter_ready is True
                    else ("not_ready" if adapter_ready is False else "unknown")
                ),
                "selection": "selected" if is_selected else "not_selected",
                "activation": "eligible" if activation_eligible else "ineligible",
                "runtime_activation": "unknown",
            },
            "readiness": {
                "configuration_complete": configuration_complete,
                "dependencies_available": dependencies_available,
                "adapter_ready": adapter_ready,
                "profile_observation_reliable": readiness_reliable,
            },
            "health": {"state": "unknown", "checked": False, "reason": "not_probed"},
            "capabilities_scope": "adapter_potential",
            "capabilities": capabilities,
            "effective_capabilities": _unknown_capabilities(),
        }

    if selected and selected not in rows_by_name:
        rows_by_name[selected] = {
            "name": selected,
            "description": "Configured provider was not found.",
            "source": "unknown",
            "installed": False,
            "discovered": False,
            "available": False,
            "configured": False,
            "setup_complete": False,
            "selected": True,
            "activation_eligible": False,
            "runtime_active": "unknown",
            "status": "unavailable" if external_memory_blocked else "missing",
            "lifecycle": {
                "installation": "missing",
                "load": "not_loaded",
                "configuration": "unknown",
                "dependencies": "unknown",
                "adapter_readiness": "unknown",
                "selection": "selected",
                "activation": "ineligible",
                "runtime_activation": "unknown",
            },
            "readiness": {
                "configuration_complete": None,
                "dependencies_available": None,
                "adapter_ready": None,
                "profile_observation_reliable": False,
            },
            "health": {"state": "unknown", "checked": False, "reason": "not_probed"},
            "capabilities_scope": "adapter_potential",
            "capabilities": _unknown_capabilities(),
            "effective_capabilities": _unknown_capabilities(),
        }
        issues.append(
            {
                "code": "selected_provider_missing",
                "provider": selected,
                "message": f"Selected memory provider '{selected}' is not installed.",
            }
        )

    if not selected:
        selection_state = "builtin_only"
    elif external_memory_blocked:
        selection_state = "unavailable"
    elif not any_tier_enabled:
        selection_state = "tiers_disabled"
    else:
        selected_row = rows_by_name[selected]
        readiness = selected_row["readiness"]
        if not selected_row["installed"]:
            selection_state = "missing"
        elif selected_row["lifecycle"]["load"] == "error" or readiness[
            "dependencies_available"
        ] is False:
            selection_state = "unavailable"
        elif readiness["configuration_complete"] is False:
            selection_state = "needs_config"
        elif not readiness["profile_observation_reliable"] or any(
            readiness[key] is None
            for key in (
                "configuration_complete",
                "dependencies_available",
                "adapter_ready",
            )
        ):
            selection_state = "readiness_unknown"
        elif readiness["adapter_ready"] is False:
            selection_state = "unavailable"
        else:
            selection_state = "eligible"

    eligible_external = selected if selection_state == "eligible" else None
    if selection_state == "tiers_disabled":
        issues.append(
            {
                "code": "memory_tiers_disabled",
                "provider": selected,
                "message": "The selected provider is ineligible because both memory tiers are disabled.",
            }
        )
    elif external_memory_blocked and selected:
        reason = _external_memory_policy_reason(egress_mode)
        if egress_mode == "air_gapped":
            message = (
                f"Memory provider '{selected}' is unavailable because "
                "air-gapped enforcement has no verified whole-process network boundary."
            )
        else:
            message = (
                f"Memory provider '{selected}' is unavailable while "
                "security.egress_mode=local_ai; external memory adapters are not "
                "yet integrated with the egress policy."
            )
        issues.append(
            {
                "code": "external_memory_blocked_by_egress_policy",
                "provider": selected,
                "mode": egress_mode,
                "reason": reason,
                "message": message,
            }
        )
    elif selection_state in {"needs_config", "unavailable", "readiness_unknown"}:
        issues.append(
            {
                "code": f"selected_provider_{selection_state}",
                "provider": selected,
                "message": (
                    f"Selected memory provider '{selected}' is {selection_state.replace('_', ' ')}."
                ),
            }
        )

    builtin = _builtin_status(home, memory_config)
    providers = [rows_by_name[name] for name in sorted(rows_by_name)]
    tiers = {
        "memory": {
            "enabled": memory_enabled,
            "bytes": builtin["files"]["memory"],
        },
        "user": {
            "enabled": user_profile_enabled,
            "bytes": builtin["files"]["user"],
        },
    }
    return {
        "schema_version": MEMORY_STATUS_SCHEMA_VERSION,
        # ``active`` is retained for current REST/desktop clients. It is the
        # configured external slug, not a health assertion.
        "active": selected,
        "selected_external_provider": selected or None,
        "eligible_external_provider": eligible_external,
        "selection": {
            "configured": selected or None,
            "state": selection_state,
            "runtime_active": "unknown",
        },
        "tiers": tiers,
        "write_policy": {
            "builtin_approval_required": builtin["write_approval"],
            "external_provider_writes": external_write_policy.as_status_dict(),
        },
        "memory_enabled": memory_enabled,
        "user_profile_enabled": user_profile_enabled,
        "any_tier_enabled": any_tier_enabled,
        "builtin": builtin,
        "builtin_files": builtin["files"],
        "providers": providers,
        "issues": issues,
    }


def build_memory_status_snapshot(
    *,
    config: Mapping[str, Any] | None = None,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
    discover: Callable[[], list[tuple[str, str, bool | None]]] | None = None,
    load_provider: Callable[[str], Any] | None = None,
    find_provider_dir: Callable[[str], Path | None] | None = None,
) -> dict[str, Any]:
    """Build a profile-owned snapshot under a temporary context-local home."""

    from fabric_constants import reset_fabric_home_override, set_fabric_home_override

    effective_home = Path(home) if home is not None else Path(get_fabric_home())
    try:
        already_scoped = effective_home.resolve() == Path(get_fabric_home()).resolve()
    except OSError:
        already_scoped = effective_home == Path(get_fabric_home())
    if already_scoped:
        return _build_memory_status_snapshot_impl(
            config=config,
            home=effective_home,
            env=env,
            discover=discover,
            load_provider=load_provider,
            find_provider_dir=find_provider_dir,
        )

    token = set_fabric_home_override(str(effective_home))
    try:
        return _build_memory_status_snapshot_impl(
            config=config,
            home=effective_home,
            env=env,
            discover=discover,
            load_provider=load_provider,
            find_provider_dir=find_provider_dir,
        )
    finally:
        reset_fabric_home_override(token)


def format_memory_status_snapshot(snapshot: Mapping[str, Any]) -> str:
    """Format the shared snapshot for CLI and messaging slash surfaces."""

    # A top-level ``-p`` override is consumed before argparse and does not
    # persist as the next process's active profile. Include it in remediation
    # commands so copying a status hint cannot grant or revoke consent on the
    # default profile by mistake. A custom HERMES_HOME has no valid ``-p``
    # spelling, so it retains the environment-scoped command.
    config_command = "fabric"
    try:
        from fabric_cli.profiles import get_active_profile_name

        profile_name = get_active_profile_name()
        if profile_name and profile_name != "custom":
            config_command += f" -p {shlex.quote(profile_name)}"
    except Exception:
        pass
    config_command += " config set memory.external_write_consent"

    tiers = snapshot.get("tiers") if isinstance(snapshot.get("tiers"), Mapping) else {}
    memory_tier = tiers.get("memory") if isinstance(tiers.get("memory"), Mapping) else {}
    user_tier = tiers.get("user") if isinstance(tiers.get("user"), Mapping) else {}
    selection = (
        snapshot.get("selection")
        if isinstance(snapshot.get("selection"), Mapping)
        else {}
    )
    selected = str(selection.get("configured") or snapshot.get("active") or "")
    state = str(selection.get("state") or ("eligible" if selected else "builtin_only"))

    lines = [
        "Memory status",
        "─" * 40,
        f"  MEMORY.md: {'enabled' if memory_tier.get('enabled', snapshot.get('memory_enabled', True)) else 'disabled'}",
        f"  USER.md:   {'enabled' if user_tier.get('enabled', snapshot.get('user_profile_enabled', True)) else 'disabled'}",
    ]
    if selected and state == "tiers_disabled":
        lines.append(
            f"  Provider:  {selected} (configured, inactive — all memory tiers disabled)"
        )
    else:
        lines.append(f"  Provider:  {selected or '(none)'}")
    lines.append(f"  Readiness: {state.replace('_', ' ')}")
    lines.append("  Runtime:   not observed; live health not probed")
    write_policy = (
        snapshot.get("write_policy")
        if isinstance(snapshot.get("write_policy"), Mapping)
        else {}
    )
    external_writes = (
        write_policy.get("external_provider_writes")
        if isinstance(write_policy.get("external_provider_writes"), Mapping)
        else {}
    )
    if not external_writes:
        lines.append("  External capture: unknown (policy not reported)")
    elif external_writes.get("state") == "allowed":
        lines.append("  External capture: allowed by explicit profile consent")
        if selected:
            lines.append(f"  Revoke:    {config_command} false")
    elif external_writes.get("consent_valid") is False:
        lines.append("  External capture: blocked (consent must be YAML true or false)")
        if selected:
            lines.append(f"  Repair:    {config_command} false")
    else:
        lines.append("  External capture: blocked (profile consent required)")
        if selected:
            lines.append(
                f"  Enable:    {config_command} true; "
                "then start a new session"
            )

    providers = snapshot.get("providers")
    if selected and isinstance(providers, list):
        row = next(
            (
                item
                for item in providers
                if isinstance(item, Mapping) and item.get("name") == selected
            ),
            None,
        )
        if isinstance(row, Mapping):
            capabilities = row.get("capabilities")
            if isinstance(capabilities, Mapping):
                supported = sorted(
                    str(name)
                    for name, support in capabilities.items()
                    if support == MemoryCapabilitySupport.SUPPORTED.value
                )
                if supported:
                    lines.append(f"  Adapter potential: {', '.join(supported)}")

    issues = snapshot.get("issues")
    if isinstance(issues, list) and issues:
        lines.append("  Issues:")
        for issue in issues:
            if isinstance(issue, Mapping) and issue.get("message"):
                lines.append(f"    ! {issue['message']}")
    return "\n".join(lines)
