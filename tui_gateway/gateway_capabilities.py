"""Pure capability contract for authenticated mobile gateway clients.

This module deliberately describes protocol availability, not runtime readiness.
It must stay independent of configuration, profiles, credentials, plugins, and
host discovery so the response is deterministic and safe to expose after each
authenticated gateway connection.
"""

from collections.abc import Iterable


GATEWAY_CONTRACT_VERSION = 1
GATEWAY_MIN_COMPATIBLE = 1


# ``voice.record`` and ``voice.tts`` intentionally stay out of this mobile
# manifest: both operate audio hardware on the gateway host. Phone audio needs
# a separate transport contract before a mobile client may advertise voice.
FEATURE_METHODS: dict[str, frozenset[str]] = {
    "baseline_chat": frozenset({
        "session.create",
        "session.list",
        "session.resume",
        "prompt.submit",
    }),
    "background_work": frozenset({
        "session.active_list",
        "prompt.background",
        "session.steer",
    }),
    "delegation": frozenset({"delegation.status", "spawn_tree.list"}),
    # Repository discovery plus branch/undo is a session baseline, not the
    # structured diff/test/push/PR workflow implied by a broad "code" feature.
    "code_session_baseline": frozenset({
        "projects.discover_repos",
        "session.branch",
        "session.undo",
    }),
    "files": frozenset({"image.attach_bytes", "pdf.attach", "file.attach"}),
    "live_view": frozenset({"visual.status", "visual.frame"}),
    "handoff": frozenset({"handoff.request"}),
    "automation": frozenset({"cron.manage"}),
}


# Optional feature families are additive-optional (durable_work precedent in
# apps/mobile/contracts/gateway-feature-registry-v1.json): an omitted key means
# the family is unavailable, and the advertised boolean must always equal
# "required methods ⊆ advertised methods". Pets exposes display+adopt only;
# generation, management, and scale stay desktop/host surfaces.
OPTIONAL_FEATURE_METHODS: dict[str, frozenset[str]] = {
    "session_transcript": frozenset({"session.transcript"}),
    "pets": frozenset({
        "pet.info",
        "pet.info.meta",
        "pet.gallery",
        "pet.select",
        "pet.disable",
        "pet.thumb",
    }),
}


MOBILE_METHODS: tuple[str, ...] = tuple(
    sorted(
        set().union(*FEATURE_METHODS.values())
        | set().union(*OPTIONAL_FEATURE_METHODS.values())
        | {
            "approval.respond",
            "clarify.respond",
            "commands.catalog",
            "connection.context",
            "computer.screenshot",
            "process.kill",
            "process.list",
            "secret.respond",
            "session.close",
            "session.interrupt",
            "slash.exec",
            "sudo.respond",
        }
    )
)


def build_gateway_capabilities(
    registered_methods: Iterable[str], *, version: str, release_date: str
) -> dict:
    """Build a deterministic, redacted snapshot of the mobile RPC surface.

    ``registered_methods`` may be the live method registry or any iterable of
    method names. Only the explicitly reviewed ``MOBILE_METHODS`` allow-list is
    advertised; unreviewed registry entries can never leak through this
    boundary. Feature flags are derived from the methods required for that
    feature instead of being configured independently.
    """

    registered = frozenset(registered_methods)
    advertised = [name for name in MOBILE_METHODS if name in registered]

    return {
        "contract": {
            "name": "fabric.gateway",
            "version": GATEWAY_CONTRACT_VERSION,
            "min_compatible": GATEWAY_MIN_COMPATIBLE,
        },
        "server": {"version": version, "release_date": release_date},
        "execution": {
            "location": "gateway",
            "tool_execution": "gateway",
            "survives_client_disconnect": True,
            "survives_gateway_restart": False,
            "requires_gateway_host_online": True,
        },
        "features": {
            feature: required.issubset(registered)
            for feature, required in (
                FEATURE_METHODS | OPTIONAL_FEATURE_METHODS
            ).items()
        },
        "methods": advertised,
    }
