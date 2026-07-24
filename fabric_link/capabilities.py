"""Reviewed Fabric Link methods and grant bundles.

This is an authorization allow-list, not a client capability catalog. A method
must also exist in the live gateway registry before Link can dispatch it.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable

LINK_REMOTE_METHODS: frozenset[str] = frozenset({
    "connection.context",
    "session.list",
    "session.transcript",
    "session.active_list",
    "session.remote_status",
    "session.attach",
    "session.detach",
    "session.input.submit",
    "events.poll",
    "process.list",
    "visual.status",
    "visual.frame",
    "session.create",
    "session.resume",
    "session.close",
    "session.interrupt",
    "prompt.submit",
    "job.create",
    "job.sync",
    "job.get",
    "job.list",
    "job.events",
    "job.cancel",
    "attention.get",
    "attention.list",
    "attention.respond",
    "session.steer",
    "delegation.status",
    "spawn_tree.list",
    "handoff.request",
    "approval.respond",
    "clarify.respond",
})

LINK_GRANT_METHODS: dict[str, frozenset[str]] = {
    "observe": frozenset({
        "connection.context",
        "session.list",
        "session.transcript",
        "session.active_list",
        "session.remote_status",
        "session.attach",
        "session.detach",
        "events.poll",
        "process.list",
        "visual.status",
        "visual.frame",
        "job.sync",
        "job.get",
        "job.list",
        "job.events",
        "attention.get",
        "attention.list",
    }),
    "chat": frozenset({
        "session.create",
        "session.resume",
        "session.close",
        "session.interrupt",
        "prompt.submit",
        "session.input.submit",
    }),
    "dispatch": frozenset({
        "job.create",
        "job.cancel",
        "session.steer",
        "delegation.status",
        "spawn_tree.list",
        "handoff.request",
    }),
    "approve": frozenset({
        "approval.respond",
        "clarify.respond",
        "attention.respond",
    }),
}

RECOMMENDED_GRANTS: tuple[str, ...] = ("observe", "chat", "dispatch")
DEFAULT_GRANTS: tuple[str, ...] = RECOMMENDED_GRANTS
_ALL_GRANTED_METHODS = frozenset().union(*LINK_GRANT_METHODS.values())

if not _ALL_GRANTED_METHODS <= LINK_REMOTE_METHODS:
    raise RuntimeError("Fabric Link grants exceed the reviewed method allow-list")


class LinkCapabilityError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def normalize_grants(
    grants: Iterable[str], *, allow_empty: bool = False
) -> tuple[str, ...]:
    normalized: set[str] = set()
    for grant in grants:
        if not isinstance(grant, str) or grant not in LINK_GRANT_METHODS:
            raise LinkCapabilityError("unknown_grant")
        normalized.add(grant)
    if not normalized and not allow_empty:
        raise LinkCapabilityError("empty_grants")
    return tuple(sorted(normalized))


def methods_for_grants(grants: Iterable[str]) -> frozenset[str]:
    normalized = normalize_grants(grants, allow_empty=True)
    return frozenset().union(*(LINK_GRANT_METHODS[grant] for grant in normalized))


def validate_method_registries(
    *,
    registered_methods: Collection[str],
    mobile_feature_methods: Collection[str],
) -> None:
    """Fail startup if the reviewed projection drifts from either live surface."""
    missing_runtime = LINK_REMOTE_METHODS - frozenset(registered_methods)
    missing_mobile = LINK_REMOTE_METHODS - frozenset(mobile_feature_methods)
    if missing_runtime or missing_mobile:
        raise LinkCapabilityError("link_method_registry_mismatch")


def grant_for_method(method: str) -> str:
    for grant, methods in LINK_GRANT_METHODS.items():
        if method in methods:
            return grant
    return "unreviewed"
