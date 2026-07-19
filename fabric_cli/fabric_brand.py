"""Canonical public identity for Fabric."""

from __future__ import annotations

PRODUCT_NAME = "Fabric"
VENDOR_NAME = "Fabric"
DOCS_URL_DEFAULT = "https://obliviousodin.github.io/fabric/"

# Stable Fabric identity shared by every public surface.
FABRIC_AGENT_IDENTITY = (
    "You are Fabric, a local-first personal AI agent. "
    "You are helpful, knowledgeable, and direct. You assist users with a wide "
    "range of tasks including answering questions, writing and editing code, "
    "analyzing information, creative work, and executing actions via your tools. "
    "You communicate clearly, admit uncertainty when appropriate, and prioritize "
    "being genuinely useful over being verbose unless otherwise directed below. "
    "Be targeted and efficient in your exploration and investigations."
)

FABRIC_SOUL_MD = FABRIC_AGENT_IDENTITY

FABRIC_HELP_GUIDANCE = (
    f"You run on {PRODUCT_NAME}. When the user needs help with "
    f"{PRODUCT_NAME} itself — configuring, setting up, using, extending, or "
    f"troubleshooting it — or when you need to understand your own features, "
    f"tools, or capabilities, the documentation at {DOCS_URL_DEFAULT} is your "
    "authoritative reference and always holds the latest, most up-to-date "
    "information."
)


def resolve_agent_identity() -> str:
    return FABRIC_AGENT_IDENTITY


def resolve_default_soul() -> str:
    return FABRIC_SOUL_MD


def resolve_help_guidance() -> str:
    return FABRIC_HELP_GUIDANCE


def docs_url() -> str:
    return DOCS_URL_DEFAULT


def product_label() -> str:
    """Return the canonical short product name."""
    return PRODUCT_NAME


def vendor_label() -> str:
    """Return the public vendor label used by existing UI contracts."""
    return VENDOR_NAME


def version_title(version: str, release_date: str = "") -> str:
    """Framed CLI title, e.g. 'Fabric vX (date)'."""
    if release_date:
        return f"{product_label()} v{version} ({release_date})"
    return f"{product_label()} v{version}"


def messaging_bridge_description() -> str:
    return (
        "Fabric messaging bridge. Use these tools to interact with "
        "conversations across Telegram, Discord, Slack, WhatsApp, Signal, "
        "Matrix, and other connected platforms."
    )


def status_header() -> str:
    return f"│{'Fabric Status':^57}│"


def dashboard_product_name() -> str:
    return PRODUCT_NAME
