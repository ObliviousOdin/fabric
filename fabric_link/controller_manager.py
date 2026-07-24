"""Local operator API for Desktop and CLI Fabric Link controller surfaces."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Any

from .capabilities import normalize_grants
from .controller import (
    ControllerRelaySession,
    LinkControllerError,
    PersistentLinkController,
    await_enrollment_response,
    finish_controller_enrollment,
    publish_enrollment_request,
    start_controller_enrollment,
)
from .controller_profile import (
    ControllerProfile,
    ControllerProfileStore,
)
from .controller_store import DesktopControllerStateStore
from .core import load_openmls_core
from .protocol import (
    LinkRequest,
    PairingPayload,
    canonical_dumps,
    canonical_loads,
)
from .store import credential_fingerprint


@dataclass(frozen=True)
class ControllerEnrollmentPresentation:
    controller_id: str
    label: str
    machine_fingerprint: str
    short_auth_string: str
    relay_origin: str
    expires_at: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "controller_id": self.controller_id,
            "label": self.label,
            "machine_fingerprint": self.machine_fingerprint,
            "short_auth_string": self.short_auth_string,
            "relay_origin": self.relay_origin,
            "expires_at": self.expires_at,
        }


def controller_profiles() -> ControllerProfileStore:
    return ControllerProfileStore(
        vault=DesktopControllerStateStore.from_system(),
    )


def controller_profile_payload(profile: ControllerProfile) -> dict[str, Any]:
    return {
        "id": profile.controller_id,
        "label": profile.label,
        "platform": profile.platform,
        "relay": profile.relay_origin,
        "status": profile.status,
        "grants": list(profile.grants),
        "machine_fingerprint": credential_fingerprint(
            profile.machine_public_key
        ),
    }


def list_controller_profiles() -> list[dict[str, Any]]:
    with controller_profiles() as profiles:
        return [controller_profile_payload(profile) for profile in profiles.list()]


def start_controller_pairing(
    *,
    pairing_url: str,
    label: str,
    platform: str,
    requested_grants: tuple[str, ...],
    now: int | None = None,
) -> ControllerEnrollmentPresentation:
    current_time = int(time.time()) if now is None else now
    payload = PairingPayload.from_url(
        pairing_url,
        now=current_time,
        allow_loopback_http=True,
    )
    grants = normalize_grants(requested_grants)
    with controller_profiles() as profiles:
        start = start_controller_enrollment(
            profiles=profiles,
            core=load_openmls_core(),
            payload=payload,
            label=label,
            platform=platform,
            requested_grants=grants,
            now=current_time,
        )
        try:
            publish_enrollment_request(start=start, payload=payload)
        except Exception:
            profiles.remove(start.profile.controller_id)
            raise
    return ControllerEnrollmentPresentation(
        controller_id=start.profile.controller_id,
        label=start.profile.label,
        machine_fingerprint=credential_fingerprint(payload.machine_key),
        short_auth_string=start.short_auth_string,
        relay_origin=payload.relay,
        expires_at=payload.expires_at,
    )


def finish_controller_pairing(
    *,
    controller_id: str,
    timeout_seconds: float | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    current_time = int(time.time()) if now is None else now
    with controller_profiles() as profiles:
        profile = profiles.get(controller_id)
        if profile is None:
            raise LinkControllerError("controller_profile_not_found")
        if profile.status == "active":
            return controller_profile_payload(profile)
        bundle = profiles.load_secret(controller_id)
        if bundle.pairing_payload is None:
            raise LinkControllerError("controller_enrollment_state_missing")
        payload = PairingPayload.from_cbor(
            bundle.pairing_payload,
            now=current_time,
            allow_loopback_http=True,
        )
        remaining = max(1, payload.expires_at - current_time)
        timeout = remaining if timeout_seconds is None else min(
            remaining,
            max(1, int(timeout_seconds)),
        )
        encrypted_response = await_enrollment_response(
            payload=payload,
            timeout_seconds=timeout,
        )
        activated = finish_controller_enrollment(
            profiles=profiles,
            core=load_openmls_core(),
            controller_id=controller_id,
            encrypted_response=encrypted_response,
            now=int(time.time()),
        )
        return controller_profile_payload(activated)


def forget_controller_profile(controller_id: str) -> None:
    with controller_profiles() as profiles:
        if profiles.get(controller_id) is None:
            raise LinkControllerError("controller_profile_not_found")
        profiles.remove(controller_id)


def resolve_controller_profile(
    profiles: ControllerProfileStore,
    reference: str,
) -> ControllerProfile:
    exact = profiles.get(reference)
    if exact is not None:
        return exact
    if len(reference) < 8:
        raise LinkControllerError("controller_reference_too_short")
    matches = [
        profile
        for profile in profiles.list()
        if profile.controller_id.startswith(reference)
    ]
    if len(matches) != 1:
        raise LinkControllerError(
            "controller_profile_not_found"
            if not matches
            else "controller_reference_ambiguous"
        )
    return matches[0]


def invoke_controller(
    *,
    profile_reference: str,
    method: str,
    params: dict[str, Any],
    timeout_seconds: float,
    idempotency_key: bytes | None = None,
) -> Any:
    if not isinstance(params, dict):
        raise LinkControllerError("controller_params_must_be_object")
    current_time = int(time.time())
    with controller_profiles() as profiles:
        profile = resolve_controller_profile(profiles, profile_reference)
        controller = PersistentLinkController(
            profiles=profiles,
            core=load_openmls_core(),
            controller_id=profile.controller_id,
        )
        response = ControllerRelaySession(
            controller=controller,
            timeout_seconds=timeout_seconds,
        ).invoke(
            LinkRequest(
                request_id=secrets.token_bytes(16),
                idempotency_key=idempotency_key or secrets.token_bytes(16),
                issued_at=current_time,
                expires_at=current_time
                + min(300, max(30, int(timeout_seconds) + 10)),
                method=method,
                params_cbor=canonical_dumps(params),
            )
        )
    if not response.ok:
        raise LinkControllerError(response.error_code or "remote_request_failed")
    if response.result_cbor is None:
        raise LinkControllerError("remote_response_missing")
    return canonical_loads(response.result_cbor, maximum=1024 * 1024)


def dispatch_controller_work(
    *,
    profile_reference: str,
    prompt: str,
    title: str,
    timeout_seconds: float,
    idempotency_key: str | None = None,
) -> Any:
    text = prompt.strip()
    if not text:
        raise LinkControllerError("dispatch_prompt_required")
    key = idempotency_key or f"link-{secrets.token_hex(16)}"
    return invoke_controller(
        profile_reference=profile_reference,
        method="job.create",
        params={
            "idempotency_key": key,
            "kind": "background_prompt",
            "text": text,
            "title": title.strip() or "Dispatched from Fabric Link",
        },
        timeout_seconds=timeout_seconds,
        idempotency_key=secrets.token_bytes(16),
    )
