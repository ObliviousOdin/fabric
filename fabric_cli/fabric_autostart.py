"""Offer to launch the local dashboard after interactive setup or auth.

After an operator finishes brain setup (``fabric setup`` / ``fabric auth add``,
including the device-code login surfaced in the Fabric Agent Console), offer to
bring the Fabric dashboard up so they aren't left to start it by hand.
"""

from __future__ import annotations

import os
import subprocess
import sys

DASHBOARD_HOST = "127.0.0.1"
DASHBOARD_PORT = 9119


def _autostart_pref() -> str:
    """Return ``always``, ``never``, or ``ask`` from dashboard config."""
    try:
        from fabric_cli.config import load_config_readonly

        config = load_config_readonly()
        dashboard = config.get("dashboard", {}) if isinstance(config, dict) else {}
        raw = dashboard.get("autostart", "ask") if isinstance(dashboard, dict) else "ask"
    except Exception:
        raw = "ask"

    if isinstance(raw, bool):
        return "always" if raw else "never"
    value = str(raw or "ask").strip().lower()
    if value in {"always", "on", "true", "yes", "1"}:
        return "always"
    if value in {"never", "off", "false", "no", "0"}:
        return "never"
    return "ask"


def _is_interactive() -> bool:
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except Exception:
        return False


def _already_running() -> bool:
    try:
        from fabric_cli.main import _dashboard_listening

        return _dashboard_listening(DASHBOARD_HOST, DASHBOARD_PORT)
    except Exception:
        return False


def maybe_launch_dashboard(args, *, trigger: str) -> None:
    """Offer to launch the dashboard after a successful setup/auth step.

    Gated so it never surprises scripted/headless callers (e.g. the gateway
    pairing scripts, which run non-interactively):

      * ``--no-dashboard`` or ``dashboard.autostart: never`` → skip
      * already running                                      → just print URL
      * not a TTY and autostart is not ``always``            → print a tip, skip
      * otherwise prompt (default yes), unless ``always`` forces it
    """
    if getattr(args, "no_dashboard", False):
        return
    pref = _autostart_pref()
    if pref == "never":
        return

    url = f"http://{DASHBOARD_HOST}:{DASHBOARD_PORT}"

    if _already_running():
        print(f"Fabric dashboard already running at {url}")
        return

    if pref != "always":
        if not _is_interactive():
            # Don't spin up a long-running server behind a non-interactive
            # caller's back — tell them how and move on.
            print(f"Tip: run `fabric dashboard` to open the dashboard ({url}).")
            return
        try:
            answer = input(f"Start the Fabric dashboard now? ({url}) [Y/n] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if answer in ("n", "no"):
            print(f"Skipped. Run `fabric dashboard` anytime ({url}).")
            return

    _spawn_dashboard(url)


def _spawn_dashboard(url: str) -> None:
    """Start ``dashboard`` detached so the current command can return."""
    # Open a browser only on a local graphical session; headless/remote engine
    # boxes get the server bound to loopback with the URL printed instead.
    open_browser = False
    try:
        from fabric_cli.auth import _can_open_graphical_browser, _is_remote_session

        open_browser = (not _is_remote_session()) and _can_open_graphical_browser()
    except Exception:
        open_browser = False

    argv = [
        sys.executable,
        "-m",
        "fabric_cli.main",
        "dashboard",
        "--host",
        DASHBOARD_HOST,
        "--port",
        str(DASHBOARD_PORT),
    ]
    if not open_browser:
        argv.append("--no-open")

    log = subprocess.DEVNULL
    log_path = None
    try:
        from fabric_cli.config import get_fabric_home

        log_path = get_fabric_home() / "dashboard-autostart.log"
        log = open(log_path, "ab")
    except Exception:
        log = subprocess.DEVNULL
        log_path = None

    popen_kwargs = {"stdout": log, "stderr": log, "stdin": subprocess.DEVNULL}
    if os.name == "posix":
        # Detach from the CLI's process group so it outlives this command.
        popen_kwargs["start_new_session"] = True

    try:
        subprocess.Popen(argv, **popen_kwargs)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"Could not start the dashboard automatically ({exc}).")
        print("  Run it yourself: fabric dashboard")
        return

    print(f"Fabric dashboard starting at {url}")
    if log_path is not None:
        print(f"  (logs: {log_path})")
    if not open_browser:
        print("  Open that URL in your browser to use it.")
