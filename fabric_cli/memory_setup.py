"""fabric memory setup|status — configure memory provider plugins.

Auto-detects installed memory providers via the plugin system.
Interactive curses-based UI for provider selection, then walks through
the provider's config schema. Writes config to config.yaml + .env.
"""

from __future__ import annotations

import os
import sys
import shlex
from pathlib import Path

from fabric_constants import get_fabric_home
from fabric_cli.secret_prompt import masked_secret_prompt

_CANCELLED = -1


def _memory_tier_state(mem_config: object) -> tuple[bool, bool]:
    """Return effective MEMORY.md and USER.md enablement from config."""
    from fabric_cli.memory_status import memory_tier_state

    return memory_tier_state(mem_config)


# ---------------------------------------------------------------------------
# Curses-based interactive picker (same pattern as fabric tools)
# ---------------------------------------------------------------------------

def _curses_select(
    title: str,
    items: list[tuple[str, str]],
    default: int = 0,
    *,
    cancel_returns: int | None = None,
) -> int:
    """Interactive single-select with arrow keys.

    items: list of (label, description) tuples.
    Returns selected index, or cancel_returns/default on escape/quit.
    """
    from fabric_cli.curses_ui import curses_radiolist

    if cancel_returns is None:
        cancel_returns = default

    # Format (label, desc) tuples into display strings
    display_items = [
        f"{label} - {desc}" if desc else label
        for label, desc in items
    ]
    result = curses_radiolist(title, display_items, selected=default, cancel_returns=cancel_returns)
    _clear_interactive_transition()
    return result


def _print_cancelled_setup() -> None:
    print("\n  Cancelled. No changes saved.\n")


def _clear_interactive_transition() -> None:
    """Clear stale curses content before entering a follow-up setup screen."""
    if not sys.stdout.isatty():
        return
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


def _prompt(label: str, default: str | None = None, secret: bool = False) -> str:
    """Prompt for a value with optional default and secret masking."""
    suffix = f" [{default}]" if default else ""
    if secret:
        val = masked_secret_prompt(f"  {label}{suffix}: ")
    else:
        sys.stdout.write(f"  {label}{suffix}: ")
        sys.stdout.flush()
        val = sys.stdin.readline().strip()
    return val or (default or "")


def _prompt_external_write_consent(config: dict, provider_name: str) -> bool:
    """Collect explicit profile consent for external content capture.

    Returns ``False`` on cancel without changing the config.  The caller owns
    persistence so provider-specific setup hooks receive the selected policy
    in the same profile mapping they later save.
    """

    memory_config = config.get("memory")
    if not isinstance(memory_config, dict):
        memory_config = {}
        config["memory"] = memory_config

    print(
        "\n  External memory capture can send completed turns, session "
        "transcripts, memory-tool writes, compression context, and delegation "
        f"results to {provider_name}."
    )
    print(
        "  Recall can remain available while capture is blocked and may still "
        "send the current query to the selected provider. This choice applies "
        "only to the active profile.\n"
    )
    existing = memory_config.get("external_write_consent") is True
    selected = _curses_select(
        "  External memory capture",
        [
            (
                "Allow external capture",
                f"permit {provider_name} to store user-derived content",
            ),
            (
                "Keep capture blocked",
                "recall remains available; write-capable hooks and tools stay disabled",
            ),
        ],
        default=0 if existing else 1,
        cancel_returns=_CANCELLED,
    )
    if selected == _CANCELLED:
        _print_cancelled_setup()
        return False
    memory_config["external_write_consent"] = selected == 0
    return True


def _file_signature(path: Path) -> tuple[int, int] | None:
    """Return a cheap change signature for setup-owned config persistence."""

    try:
        stat_result = path.stat()
    except OSError:
        return None
    return stat_result.st_mtime_ns, stat_result.st_size


def _persist_consent_after_provider_setup(
    *,
    config_path: Path,
    before_signature: tuple[int, int] | None,
    consent: bool,
) -> None:
    """Persist consent only when the provider wizard actually saved config.

    Provider-specific setup hooks have no success return value. A config-file
    change is their existing durable success signal. This avoids granting a
    newly selected consent value when a user cancels an already-configured
    provider's wizard, while still covering legacy hooks (Honcho) that ignore
    the mapping passed to ``post_setup`` and reload config themselves.
    """

    if _file_signature(config_path) == before_signature:
        return
    from fabric_cli.config import load_config, save_config

    persisted = load_config()
    if not isinstance(persisted.get("memory"), dict):
        persisted["memory"] = {}
    persisted["memory"]["external_write_consent"] = consent
    save_config(persisted)


# ---------------------------------------------------------------------------
# Provider discovery
# ---------------------------------------------------------------------------

def _install_dependencies(provider_name: str) -> None:
    """Install pip dependencies declared in plugin.yaml."""
    import subprocess
    from plugins.memory import find_provider_dir

    plugin_dir = find_provider_dir(provider_name)
    if not plugin_dir:
        return
    yaml_path = plugin_dir / "plugin.yaml"
    if not yaml_path.exists():
        return

    try:
        import yaml
        with open(yaml_path, encoding="utf-8") as f:
            meta = yaml.safe_load(f) or {}
    except Exception:
        return

    pip_deps = meta.get("pip_dependencies", [])
    if not pip_deps:
        return

    # pip name → import name mapping for packages where they differ
    _IMPORT_NAMES = {
        "honcho-ai": "honcho",
        "mem0ai": "mem0",
        "hindsight-client": "hindsight_client",
        "hindsight-all": "hindsight",
    }

    # Check which packages are missing
    missing = []
    for dep in pip_deps:
        import_name = _IMPORT_NAMES.get(dep, dep.replace("-", "_").split("[")[0])
        try:
            __import__(import_name)
        except ImportError:
            missing.append(dep)

    if not missing:
        return

    print(f"\n  Installing dependencies: {', '.join(missing)}")

    from fabric_cli.tools_config import _pip_install

    manual_cmd = f"uv pip install {' '.join(missing)}"
    try:
        result = _pip_install(["--quiet"] + missing, timeout=120)
        if result.returncode == 0:
            print(f"  ✓ Installed {', '.join(missing)}")
        else:
            print(f"  ⚠ Failed to install {', '.join(missing)}")
            stderr = (result.stderr or "")[:200]
            if stderr:
                print(f"    {stderr}")
            print(f"  Run manually: {manual_cmd}")
    except Exception as e:
        print(f"  ⚠ Install failed: {e}")
        print(f"  Run manually: {manual_cmd}")

    # Also show external dependencies (non-pip) if any
    ext_deps = meta.get("external_dependencies", [])
    for dep in ext_deps:
        dep_name = dep.get("name", "")
        check_cmd = dep.get("check", "")
        install_cmd = dep.get("install", "")
        if check_cmd:
            try:
                subprocess.run(
                    shlex.split(check_cmd), check=True, capture_output=True, timeout=5
                )
            except Exception:
                if install_cmd:
                    print(f"\n  ⚠ '{dep_name}' not found. Install with:")
                    print(f"    {install_cmd}")


def _get_available_providers() -> list:
    """Discover memory providers from plugins/memory/.

    Returns list of (name, description, provider_instance) tuples.
    """
    try:
        from plugins.memory import discover_memory_providers, load_memory_provider
        raw = discover_memory_providers()
    except Exception:
        raw = []

    results = []
    for name, desc, available in raw:
        try:
            provider = load_memory_provider(name)
            if not provider:
                continue
        except Exception:
            continue

        schema = provider.get_config_schema() if hasattr(provider, "get_config_schema") else []
        has_secrets = any(f.get("secret") for f in schema)
        has_non_secrets = any(not f.get("secret") for f in schema)
        if has_secrets and has_non_secrets:
            setup_hint = "API key / local"
        elif has_secrets:
            setup_hint = "requires API key"
        elif not schema:
            setup_hint = "no setup needed"
        else:
            setup_hint = "local"

        results.append((name, setup_hint, provider))
    try:
        from fabric_cli.fabric_capabilities import FABRIC_MEMORY_PROVIDERS, filter_fabric_keys

        filtered = filter_fabric_keys(
            results,
            FABRIC_MEMORY_PROVIDERS,
            key=lambda item: item[0],
        )
        kept = {item[0] for item in filtered}

        # Curation controls beginner discovery, never the user's existing
        # state. Keep a configured adapter and user-installed adapters visible
        # even when they are outside the bundled default catalog.
        try:
            from fabric_cli.config import load_config
            from plugins import memory as memory_plugins

            config = load_config()
            memory_config = config.get("memory") if isinstance(config, dict) else {}
            selected = (
                str(memory_config.get("provider") or "").strip()
                if isinstance(memory_config, dict)
                else ""
            )
            bundled_root = Path(memory_plugins.__file__).resolve().parent
            for item in results:
                name = item[0]
                provider_dir = memory_plugins.find_provider_dir(name)
                is_user = bool(
                    provider_dir is not None
                    and provider_dir.parent.resolve() != bundled_root
                )
                if name == selected or is_user:
                    kept.add(name)
        except Exception:
            pass
        return [item for item in results if item[0] in kept]
    except Exception:
        return results


# ---------------------------------------------------------------------------
# Setup wizard
# ---------------------------------------------------------------------------

def cmd_setup_provider(provider_name: str) -> None:
    """Run memory setup for a specific provider, skipping the picker."""
    from fabric_cli.config import get_config_path, load_config, save_config

    providers = _get_available_providers()
    match = None
    for name, desc, provider in providers:
        if name == provider_name:
            match = (name, desc, provider)
            break

    if match is None:
        # An explicit provider slug is an operator choice, not beginner
        # catalog discovery. Any installed bundled/user adapter remains
        # addressable even when the curated picker does not advertise it.
        try:
            from plugins.memory import load_memory_provider

            provider = load_memory_provider(provider_name)
            if provider is not None:
                match = (provider_name, "installed", provider)
        except Exception:
            pass

    if not match:
        print(f"\n  Memory provider '{provider_name}' not found.")
        print("  Run 'fabric memory setup' to see available providers.\n")
        return

    name, _, provider = match

    _clear_interactive_transition()

    config = load_config()
    if not isinstance(config.get("memory"), dict):
        config["memory"] = {}
    if not _prompt_external_write_consent(config, name):
        return

    _install_dependencies(name)

    if hasattr(provider, "post_setup"):
        consent = config["memory"].get("external_write_consent") is True
        config_path = get_config_path()
        before_signature = _file_signature(config_path)
        hermes_home = str(get_fabric_home())
        provider.post_setup(hermes_home, config)
        _persist_consent_after_provider_setup(
            config_path=config_path,
            before_signature=before_signature,
            consent=consent,
        )
        return

    # Fallback: generic schema-based setup (same as cmd_setup)
    config["memory"]["provider"] = name
    save_config(config)
    print(f"\n  Memory provider: {name}")
    print("  Activation saved to config.yaml\n")


def cmd_setup(args) -> None:
    """Interactive memory provider setup wizard."""
    from fabric_cli.config import get_config_path, load_config, save_config

    providers = _get_available_providers()

    if not providers:
        print("\n  No memory provider plugins detected.")
        print("  Install a plugin to ~/.fabric/plugins/ and try again.\n")
        return

    # Build picker items
    items = []
    for name, desc, _ in providers:
        items.append((name, f"— {desc}"))
    items.append(("Built-in only", "— MEMORY.md / USER.md (default)"))

    builtin_idx = len(items) - 1
    selected = _curses_select("Memory provider setup", items, default=builtin_idx, cancel_returns=_CANCELLED)
    if selected == _CANCELLED:
        _print_cancelled_setup()
        return

    config = load_config()
    if not isinstance(config.get("memory"), dict):
        config["memory"] = {}

    # Built-in only
    if selected >= len(providers):
        config["memory"]["provider"] = ""
        config["memory"]["external_write_consent"] = False
        save_config(config)
        print("\n  ✓ Memory provider: built-in only")
        print("  Saved to config.yaml\n")
        return

    name, _, provider = providers[selected]

    _clear_interactive_transition()

    if not _prompt_external_write_consent(config, name):
        return

    # Install pip dependencies if declared in plugin.yaml
    _install_dependencies(name)

    # If the provider has a post_setup hook, delegate entirely to it.
    # The hook handles its own config, connection test, and activation.
    if hasattr(provider, "post_setup"):
        consent = config["memory"].get("external_write_consent") is True
        config_path = get_config_path()
        before_signature = _file_signature(config_path)
        hermes_home = str(get_fabric_home())
        provider.post_setup(hermes_home, config)
        _persist_consent_after_provider_setup(
            config_path=config_path,
            before_signature=before_signature,
            consent=consent,
        )
        return

    schema = provider.get_config_schema() if hasattr(provider, "get_config_schema") else []

    provider_config = config["memory"].get(name, {})
    if not isinstance(provider_config, dict):
        provider_config = {}

    env_path = get_fabric_home() / ".env"
    env_writes = {}

    if schema:
        print(f"\n  Configuring {name}:\n")

        for field in schema:
            key = field["key"]
            desc = field.get("description", key)
            default = field.get("default")
            # Dynamic default: look up default from another field's value
            default_from = field.get("default_from")
            if default_from and isinstance(default_from, dict):
                ref_field = default_from.get("field", "")
                ref_map = default_from.get("map", {})
                ref_value = provider_config.get(ref_field, "")
                if ref_value and ref_value in ref_map:
                    default = ref_map[ref_value]
            is_secret = field.get("secret", False)
            choices = field.get("choices")
            env_var = field.get("env_var")
            url = field.get("url")

            # Skip fields whose "when" condition doesn't match
            when = field.get("when")
            if when and isinstance(when, dict):
                if not all(provider_config.get(k) == v for k, v in when.items()):
                    continue

            if choices and not is_secret:
                # Use curses picker for choice fields
                choice_items = [(c, "") for c in choices]
                current = provider_config.get(key, default)
                current_idx = 0
                if current and current in choices:
                    current_idx = choices.index(current)
                sel = _curses_select(f"  {desc}", choice_items, default=current_idx, cancel_returns=_CANCELLED)
                if sel == _CANCELLED:
                    _print_cancelled_setup()
                    return
                provider_config[key] = choices[sel]
            elif is_secret:
                # Prompt for secret
                existing = os.environ.get(env_var, "") if env_var else ""
                if existing:
                    masked = f"...{existing[-4:]}" if len(existing) > 4 else "set"
                    val = _prompt(f"{desc} (current: {masked}, blank to keep)", secret=True)
                else:
                    hint = f"  Get yours at {url}" if url else ""
                    if hint:
                        print(hint)
                    val = _prompt(desc, secret=True)
                if val and env_var:
                    env_writes[env_var] = val
            else:
                # Regular text prompt
                current = provider_config.get(key)
                effective_default = current or default
                val = _prompt(desc, default=str(effective_default) if effective_default else None)
                if val:
                    provider_config[key] = val
                    # Also write to .env if this field has an env_var
                    if env_var and env_var not in env_writes:
                        env_writes[env_var] = val

    # Write activation key to config.yaml
    config["memory"]["provider"] = name
    save_config(config)

    # Write non-secret config to provider's native location
    hermes_home = str(get_fabric_home())
    if provider_config and hasattr(provider, "save_config"):
        try:
            provider.save_config(provider_config, hermes_home)
        except Exception as e:
            print(f"  Failed to write provider config: {e}")

    # Write secrets to .env
    if env_writes:
        _write_env_vars(env_path, env_writes)

    print(f"\n  Memory provider: {name}")
    print("  Activation saved to config.yaml")
    if provider_config:
        print("  Provider config saved")
    if env_writes:
        print("  API keys saved to .env")
    print("\n  Start a new session to activate.\n")


def _write_env_vars(env_path: Path, env_writes: dict) -> None:
    """Append or update env vars in .env file."""
    env_path.parent.mkdir(parents=True, exist_ok=True)

    existing_lines = []
    if env_path.exists():
        existing_lines = env_path.read_text(encoding="utf-8").splitlines()

    updated_keys = set()
    new_lines = []
    for line in existing_lines:
        key_match = line.split("=", 1)[0].strip() if "=" in line else ""
        if key_match in env_writes:
            new_lines.append(f"{key_match}={env_writes[key_match]}")
            updated_keys.add(key_match)
        else:
            new_lines.append(line)

    for key, val in env_writes.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={val}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    # Restrict permissions — .env holds API keys and tokens.
    try:
        import stat
        env_path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
    except OSError:
        pass  # Windows or read-only FS


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def cmd_status(args) -> None:
    """Show the shared side-effect-free memory readiness snapshot."""
    from fabric_cli.config import load_config
    from fabric_cli.memory_status import (
        build_memory_status_snapshot,
        format_memory_status_snapshot,
    )

    config = load_config()
    snapshot = build_memory_status_snapshot(config=config)
    print(f"\n{format_memory_status_snapshot(snapshot)}")

    if snapshot["providers"]:
        print("\n  Installed plugins:")
        for row in snapshot["providers"]:
            if not row["discovered"]:
                continue
            marker = " ← eligible" if row["activation_eligible"] else (" ← selected" if row["selected"] else "")
            source = row.get("source", "unknown")
            print(f"    • {row['name']}  ({source}){marker}")

    print()


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

def memory_command(args) -> None:
    """Route memory subcommands."""
    sub = getattr(args, "memory_command", None)
    if sub == "setup":
        provider = getattr(args, "provider", None)
        if provider:
            cmd_setup_provider(provider)
        else:
            cmd_setup(args)
    elif sub == "status":
        cmd_status(args)
    else:
        cmd_status(args)
