"""Process-local launch policy for Fabric entrypoints.

Invocation flags live in memory rather than being exposed as user-facing
environment variables. This module is intentionally tiny so early plugin,
hook, and MCP startup can consult the same policy without importing the CLI.
"""

_safe_mode = False
_ignore_user_config = False
_ignore_rules = False


def set_safe_mode(enabled: bool) -> None:
    global _safe_mode
    _safe_mode = bool(enabled)


def safe_mode_enabled() -> bool:
    return _safe_mode


def set_ignore_user_config(enabled: bool) -> None:
    global _ignore_user_config
    _ignore_user_config = bool(enabled)


def ignore_user_config_enabled() -> bool:
    return _ignore_user_config


def set_ignore_rules(enabled: bool) -> None:
    global _ignore_rules
    _ignore_rules = bool(enabled)


def ignore_rules_enabled() -> bool:
    return _ignore_rules
