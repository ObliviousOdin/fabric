from __future__ import annotations

from types import SimpleNamespace

from fabric_link.controller import (
    ControllerRelaySession,
    LinkControllerError,
    PendingControllerRequest,
)
from fabric_link.protocol import LinkRequest, LinkResponse, canonical_dumps
from fabric_link.relay_contract import (
    RelayAcknowledgement,
    RelayDelivery,
    RelayMailbox,
    RelayPoll,
    RelayPublish,
    RelaySync,
)

NOW = 1_784_840_000


class FakeController:
    def __init__(self, request: LinkRequest) -> None:
        self.request = request
        self.profile = SimpleNamespace(
            relay_origin="https://relay.example",
            route_id=b"r" * 32,
            credential_serial=b"c" * 16,
        )

    def encrypt_request(self, request: LinkRequest) -> PendingControllerRequest:
        assert request == self.request
        return PendingControllerRequest(
            request_id=request.request_id,
            message_id=b"p" * 16,
            expires_at=request.expires_at,
            envelope=b"request-envelope",
        )

    def create_authentication(self, _challenge, *, now: int):
        raise AssertionError(f"unexpected authentication challenge at {now}")

    def decrypt_response(self, delivery_cbor: bytes) -> LinkResponse:
        if delivery_cbor != b"target-response":
            raise LinkControllerError("controller_response_request_mismatch")
        return LinkResponse(
            request_id=self.request.request_id,
            completed_at=NOW + 2,
            ok=True,
            result_cbor=canonical_dumps({"status": "ok"}),
            error_code=None,
        )


class PagedRelayClient:
    instance: "PagedRelayClient | None" = None

    def __init__(self, **_kwargs) -> None:
        type(self).instance = self
        self.after_sequences: list[int] = []
        self.acknowledgements: list[int] = []

    def connect(self) -> None:
        return None

    def publish(self, frame: RelayPublish) -> None:
        assert frame.opaque_record == b"request-envelope"

    def poll(self, frame: RelayPoll):
        self.after_sequences.append(frame.after_sequence)
        if frame.after_sequence == 0:
            deliveries = tuple(
                RelayDelivery(
                    mailbox=frame.mailbox,
                    sequence=sequence,
                    message_id=sequence.to_bytes(16, "big"),
                    expires_at=NOW + 60,
                    opaque_record=f"stale-{sequence}".encode(),
                )
                for sequence in range(1, 11)
            )
        elif frame.after_sequence == 10:
            deliveries = (
                RelayDelivery(
                    mailbox=frame.mailbox,
                    sequence=11,
                    message_id=(11).to_bytes(16, "big"),
                    expires_at=NOW + 60,
                    opaque_record=b"target-response",
                ),
            )
        else:
            deliveries = ()
        return deliveries, RelaySync(
            request_id=frame.request_id,
            count=len(deliveries),
            high_watermark=11,
        )

    def acknowledge(self, frame: RelayAcknowledgement) -> None:
        self.acknowledgements.append(frame.sequence)

    def close(self) -> None:
        return None


def test_controller_consumes_every_bounded_page_before_high_watermark() -> None:
    request = LinkRequest(
        request_id=b"q" * 16,
        idempotency_key=b"i" * 16,
        issued_at=NOW,
        expires_at=NOW + 60,
        method="job.create",
        params_cbor=canonical_dumps({"text": "ship it"}),
    )
    response = ControllerRelaySession(
        controller=FakeController(request),  # type: ignore[arg-type]
        timeout_seconds=1,
        poll_interval_seconds=0.001,
        client_factory=PagedRelayClient,
    ).invoke(request)

    client = PagedRelayClient.instance
    assert client is not None
    assert response.ok is True
    assert client.after_sequences == [0, 10]
    assert client.acknowledgements == list(range(1, 12))
