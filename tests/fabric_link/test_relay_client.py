from __future__ import annotations

from collections import deque

import pytest

from fabric_link.relay_client import LinkRelayClient, LinkRelayClientError
from fabric_link.relay_contract import (
    RelayAuthentication,
    RelayChallenge,
    RelayDelivery,
    RelayFailure,
    RelayMailbox,
    RelayPoll,
    RelayPublish,
    RelayReady,
    RelayReceipt,
    RelaySync,
)

NOW = 1_784_840_000


class FakeSocket:
    subprotocol = "fabric-link-relay-v1"

    def __init__(self, responses) -> None:
        self.responses = deque(response.to_cbor() for response in responses)
        self.sent: list[bytes] = []
        self.closed = False

    def send(self, message: bytes) -> None:
        self.sent.append(message)

    def recv(self, timeout: float | None = None) -> bytes:
        del timeout
        return self.responses.popleft()

    def close(self) -> None:
        self.closed = True


def challenge() -> RelayChallenge:
    return RelayChallenge(
        nonce=b"n" * 32,
        server_time=NOW,
        expires_at=NOW + 30,
    )


def authentication(_challenge: RelayChallenge) -> RelayAuthentication:
    return RelayAuthentication(
        route_id=b"r" * 32,
        role="host",
        nonce=b"n" * 32,
        route_public_key=b"k" * 32,
        signature=b"s" * 64,
    )


def test_client_negotiates_binary_challenge_auth_and_receipts():
    socket = FakeSocket([
        challenge(),
        RelayReady(role="host"),
        RelayReceipt(message_id=b"m" * 16, sequence=1),
    ])
    client = LinkRelayClient(
        relay_origin="https://relay.example",
        authentication_factory=authentication,
        connector=lambda *_args, **_kwargs: socket,
    )
    assert client.connect() == RelayReady(role="host")
    mailbox = RelayMailbox(
        route_id=b"r" * 32,
        credential_serial=b"c" * 16,
        recipient="controller",
    )
    receipt = client.publish(
        RelayPublish(
            mailbox=mailbox,
            message_id=b"m" * 16,
            expires_at=NOW + 30,
            opaque_record=b"opaque",
        )
    )
    assert receipt.sequence == 1
    assert len(socket.sent) == 2
    client.close()
    assert socket.closed


def test_client_collects_one_exact_poll_page():
    mailbox = RelayMailbox(
        route_id=b"r" * 32,
        credential_serial=b"c" * 16,
        recipient="host",
    )
    socket = FakeSocket([
        challenge(),
        RelayDelivery(
            mailbox=mailbox,
            sequence=4,
            message_id=b"m" * 16,
            expires_at=NOW + 30,
            opaque_record=b"opaque",
        ),
        RelaySync(
            request_id=b"q" * 16,
            count=1,
            high_watermark=4,
        ),
    ])
    client = LinkRelayClient(
        relay_origin="https://relay.example",
        authentication_factory=None,
        connector=lambda *_args, **_kwargs: socket,
    )
    assert client.connect() is None
    deliveries, sync = client.poll(
        RelayPoll(
            mailbox=mailbox,
            request_id=b"q" * 16,
            after_sequence=3,
        )
    )
    assert deliveries[0].opaque_record == b"opaque"
    assert sync.high_watermark == 4


def test_client_maps_stable_relay_failure_without_returning_server_details():
    socket = FakeSocket([
        challenge(),
        RelayFailure(
            code="relay_mailbox_forbidden",
            correlation_id=b"m" * 16,
        ),
    ])
    client = LinkRelayClient(
        relay_origin="https://relay.example",
        authentication_factory=None,
        connector=lambda *_args, **_kwargs: socket,
    )
    client.connect()
    mailbox = RelayMailbox(
        route_id=b"r" * 32,
        credential_serial=b"c" * 16,
        recipient="host",
    )
    with pytest.raises(LinkRelayClientError, match="relay_mailbox_forbidden"):
        client.publish(
            RelayPublish(
                mailbox=mailbox,
                message_id=b"m" * 16,
                expires_at=NOW + 30,
                opaque_record=b"opaque",
            )
        )
