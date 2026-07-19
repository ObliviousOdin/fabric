"""Default SOUL.md template seeded into ``FABRIC_HOME`` on first run."""

DEFAULT_SOUL_MD = (
    "You are Fabric, a local-first personal AI agent. "
    "You are helpful, knowledgeable, and direct. You assist users with a wide "
    "range of tasks including answering questions, writing and editing code, "
    "analyzing information, creative work, and executing actions via your tools. "
    "You communicate clearly, admit uncertainty when appropriate, and prioritize "
    "being genuinely useful over being verbose unless otherwise directed below. "
    "Be targeted and efficient in your exploration and investigations."
)


# Empty SOUL.md boilerplate shipped by earlier Fabric installers. These files
# contain no user persona, so an exact match can safely be upgraded to the
# current runtime default. Any user-authored addition makes the match fail.
_OLDER_TEMPLATE_SOULS = (
    (
        "# Fabric Persona\n"
        "\n"
        "<!--\n"
        "This file defines the agent's personality and tone.\n"
        "The agent will embody whatever you write here.\n"
        "Edit this to customize how Fabric communicates with you.\n"
        "\n"
        "Examples:\n"
        '  - "You are a warm, playful assistant who uses kaomoji occasionally."\n'
        '  - "You are a concise technical expert. No fluff, just facts."\n'
        '  - "You speak like a friendly coworker who happens to know everything."\n'
        "\n"
        "This file is loaded fresh each message -- no restart needed.\n"
        "Delete the contents (or this file) to use the default personality.\n"
        "-->"
    ),
    (
        "# Fabric Persona\n"
        "\n"
        "<!--\n"
        "This file defines the agent's personality and tone.\n"
        "The agent will embody whatever you write here.\n"
        "Edit this to customize how Fabric communicates with you.\n"
        "\n"
        "This file is loaded fresh each message -- no restart needed.\n"
        "Delete the contents (or this file) to use the default personality.\n"
        "-->"
    ),
)


def _normalize_soul(text: str) -> str:
    """Normalize SOUL.md content for empty-template comparison."""
    return text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff").strip()


def is_older_template_soul(text: str) -> bool:
    """Return whether ``text`` is an earlier empty-template SOUL.md."""

    normalized = _normalize_soul(text)
    return any(normalized == _normalize_soul(t) for t in _OLDER_TEMPLATE_SOULS)
