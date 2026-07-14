"""Credential onboarding for the bundled Firecrawl providers.

The connector intentionally runs only Firecrawl's official login command. It
does not run ``init`` or any skill/editor setup command, and it disables the
CLI's optional authentication telemetry for every Fabric-managed invocation.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Mapping, Optional


FIRECRAWL_CLI_PACKAGE = "firecrawl-cli@1.19.24"
FIRECRAWL_API_KEYS_URL = "https://firecrawl.dev/app/api-keys"
FIRECRAWL_LOGIN_TIMEOUT_SECONDS = 360

_SUBPROCESS_ENV_OVERLAY_KEYS = frozenset({
    "PATH",
    "HOME",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "SYSTEMROOT",
    "COMSPEC",
    "PATHEXT",
    "TMP",
    "TEMP",
    "TMPDIR",
    "LANG",
    "TERM",
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "XDG_RUNTIME_DIR",
    "DBUS_SESSION_BUS_ADDRESS",
    "WSL_INTEROP",
    "WSL_DISTRO_NAME",
    "WSLENV",
})


def firecrawl_cli_credentials_path(home: Path, platform: str) -> Path:
    """Return the one official credential path for ``platform``."""
    if platform == "darwin":
        return home / "Library" / "Application Support" / "firecrawl-cli" / "credentials.json"
    if platform == "win32":
        return home / "AppData" / "Roaming" / "firecrawl-cli" / "credentials.json"
    return home / ".config" / "firecrawl-cli" / "credentials.json"


def read_firecrawl_cli_credentials(home: Path, platform: str) -> Optional[str]:
    """Read and validate only the official CLI's stored Firecrawl API key."""
    path = firecrawl_cli_credentials_path(home, platform)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None

    if not isinstance(payload, dict):
        return None
    key = payload.get("apiKey")
    if not isinstance(key, str):
        return None
    key = key.strip()
    if not key.startswith("fc-") or any(ch.isspace() for ch in key):
        return None
    return key


def _present_api_key_link(url: str, *, label: str, open_browser: bool) -> None:
    """Use Fabric's QR/link helper, retaining an exact plain-link fallback."""
    try:
        from fabric_cli.setup_links import present_setup_link

        present_setup_link(url, label=label, open_browser=open_browser)
    except Exception:
        print(f"  {label}: {url}")


def _build_login_env(environ: Optional[Mapping[str, str]]) -> dict[str, str]:
    """Build a minimal environment for the downloaded third-party CLI.

    ``hermes_subprocess_env`` intentionally preserves unknown environment
    variables because normal terminal children may need them. A setup child
    downloaded through ``npx`` has a tighter trust boundary, so copy only the
    process essentials allowlisted above; arbitrary application secrets such
    as ``DATABASE_URL`` or ``NPM_TOKEN`` must never cross it.
    """
    from tools.environments.local import hermes_subprocess_env

    base_env = hermes_subprocess_env(inherit_credentials=False)
    child_env = {
        key: value
        for key, value in base_env.items()
        if key in _SUBPROCESS_ENV_OVERLAY_KEYS and isinstance(value, str)
    }
    if environ is not None:
        # Dependency-injected tests and callers may override process essentials,
        # but never reintroduce arbitrary provider/tool credentials.
        for key in _SUBPROCESS_ENV_OVERLAY_KEYS:
            value = environ.get(key)
            if isinstance(value, str):
                child_env[key] = value
    child_env["FIRECRAWL_NO_TELEMETRY"] = "1"
    return child_env


def _credentials_home(
    child_env: Mapping[str, str],
    platform: str,
) -> Path:
    """Return the same home directory Node's ``os.homedir()`` will use."""
    if platform == "win32":
        raw = child_env.get("USERPROFILE") or child_env.get("HOME")
    else:
        raw = child_env.get("HOME") or child_env.get("USERPROFILE")
    return Path(raw).expanduser() if raw else Path.home()


def _browser_open_is_safe() -> bool:
    """Use the same local/graphical guards as Fabric's model auth flows."""
    try:
        from fabric_cli.auth import _can_open_graphical_browser, _is_remote_session

        return not _is_remote_session() and _can_open_graphical_browser()
    except Exception:
        return False


def connect_firecrawl(
    *,
    home: Optional[Path] = None,
    platform: Optional[str] = None,
    environ: Optional[Mapping[str, str]] = None,
    runner: Callable[..., object] = subprocess.run,
    which: Callable[[str], Optional[str]] = shutil.which,
    prompt: Optional[Callable[..., str]] = None,
    save_secret: Optional[Callable[[str, str], object]] = None,
    present_link: Callable[..., object] = _present_api_key_link,
) -> Optional[str]:
    """Connect Firecrawl through browser login, then manual-key fallback.

    A returned value is always a validated ``fc-`` key that has already been
    persisted through Fabric's active profile secret writer. Failure and user
    cancellation return ``None`` without changing Fabric credentials.
    """
    from fabric_cli.cli_output import print_info, print_success, print_warning
    from fabric_cli.cli_output import prompt as default_prompt
    from fabric_cli.config import save_env_value

    resolved_platform = sys.platform if platform is None else platform
    child_env = _build_login_env(environ)
    resolved_home = (
        _credentials_home(child_env, resolved_platform)
        if home is None
        else Path(home)
    )
    prompt_fn = prompt or default_prompt
    save_secret_fn = save_secret or save_env_value

    npx = which("npx")
    browser_login_safe = _browser_open_is_safe()
    if npx and browser_login_safe:
        print_info(
            f"Running official {FIRECRAWL_CLI_PACKAGE} browser login via npx "
            "(telemetry disabled)."
        )
        try:
            completed = runner(
                [npx, "-y", FIRECRAWL_CLI_PACKAGE, "login", "--method", "browser"],
                env=child_env,
                timeout=FIRECRAWL_LOGIN_TIMEOUT_SECONDS,
                check=False,
            )
        except KeyboardInterrupt:
            print_warning("Firecrawl browser login cancelled.")
            return None
        except subprocess.TimeoutExpired:
            print_warning("Firecrawl browser login timed out; use an API key instead.")
        except OSError as exc:
            print_warning(f"Could not start Firecrawl browser login: {exc}")
        else:
            if getattr(completed, "returncode", 1) == 0:
                key = read_firecrawl_cli_credentials(resolved_home, resolved_platform)
                if key:
                    try:
                        save_secret_fn("FIRECRAWL_API_KEY", key)
                    except Exception as exc:
                        print_warning(f"Could not save the Firecrawl API key: {exc}")
                        return None
                    print_success("Firecrawl connected.")
                    return key
                print_warning(
                    "Firecrawl login finished but no valid credential was found; "
                    "use an API key instead."
                )
            else:
                print_warning("Firecrawl browser login did not complete; use an API key instead.")
    elif not npx:
        print_info("Node.js/npx was not found; use a Firecrawl API key instead.")
    else:
        print_info(
            "Remote/headless session detected; use the phone-friendly API-key "
            "link instead of starting a local browser callback."
        )

    present_link(
        FIRECRAWL_API_KEYS_URL,
        label="Firecrawl API keys",
        open_browser=browser_login_safe,
    )
    while True:
        value = str(
            prompt_fn(
                "Paste your Firecrawl API key (Enter to cancel)",
                password=True,
            )
            or ""
        ).strip()
        if not value:
            print_warning("Firecrawl setup cancelled.")
            return None
        if not value.startswith("fc-") or any(ch.isspace() for ch in value):
            print_warning('Invalid Firecrawl API key; keys must start with "fc-".')
            continue
        try:
            save_secret_fn("FIRECRAWL_API_KEY", value)
        except Exception as exc:
            print_warning(f"Could not save the Firecrawl API key: {exc}")
            return None
        print_success("Firecrawl connected.")
        return value
