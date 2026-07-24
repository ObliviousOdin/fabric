"""Narrow adapter around the generated Fabric Link OpenMLS binding."""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Protocol

from .protocol import FABRIC_LINK_PROTOCOL_VERSION


class LinkCoreUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class PairBootstrap:
    host_state: bytes = field(repr=False)
    welcome: bytes = field(repr=False)


@dataclass(frozen=True)
class StateUpdate:
    opaque_state: bytes = field(repr=False)
    message: bytes = field(repr=False)


@dataclass(frozen=True)
class ControllerBootstrap:
    """Initial opaque controller state and one MLS KeyPackage for enrollment."""

    opaque_state: bytes = field(repr=False)
    key_package: bytes = field(repr=False)


@dataclass(frozen=True)
class ControllerDecryption:
    """A decrypted controller message plus the state that must replace the old state."""

    opaque_state: bytes = field(repr=False)
    plaintext: bytes = field(repr=False)


@dataclass(frozen=True)
class HostDecryption:
    """A decrypted host message plus the state that must replace the old state."""

    opaque_state: bytes = field(repr=False)
    plaintext: bytes = field(repr=False)


@dataclass(frozen=True)
class ControllerMembershipUpdate:
    """The result of applying a host membership commit on a controller."""

    opaque_state: bytes = field(repr=False)
    active: bool


class LinkCryptoCore(Protocol):
    def create_controller(self, *, identity: bytes) -> ControllerBootstrap: ...

    def controller_key_package(self, *, opaque_state: bytes) -> bytes: ...

    def host_encrypt(self, *, opaque_state: bytes, plaintext: bytes) -> StateUpdate: ...

    def host_decrypt(
        self, *, opaque_state: bytes, message: bytes
    ) -> HostDecryption: ...

    def controller_encrypt(
        self, *, opaque_state: bytes, plaintext: bytes
    ) -> StateUpdate: ...

    def create_pair(
        self,
        *,
        host_identity: bytes,
        group_id: bytes,
        controller_key_package: bytes,
    ) -> PairBootstrap: ...

    def remove_controller(self, *, host_state: bytes) -> StateUpdate: ...

    def join_controller(self, *, opaque_state: bytes, welcome: bytes) -> bytes: ...

    def decrypt_controller(
        self, *, opaque_state: bytes, message: bytes
    ) -> ControllerDecryption: ...

    def apply_controller_commit(
        self, *, opaque_state: bytes, commit: bytes
    ) -> ControllerMembershipUpdate: ...


class OpenMLSCore:
    def __init__(self, binding: object) -> None:
        self._binding = binding
        try:
            version = int(binding.fabric_link_protocol_version())
        except (AttributeError, TypeError, ValueError) as exc:
            raise LinkCoreUnavailable("invalid Fabric Link core binding") from exc
        if version != FABRIC_LINK_PROTOCOL_VERSION:
            raise LinkCoreUnavailable("Fabric Link core protocol mismatch")
        try:
            ciphersuite = str(binding.fabric_link_ciphersuite())
        except (AttributeError, TypeError, ValueError) as exc:
            raise LinkCoreUnavailable("invalid Fabric Link core binding") from exc
        if (
            ciphersuite
            != "MLS_128_DHKEMX25519_AES128GCM_SHA256_Ed25519"
        ):
            raise LinkCoreUnavailable("Fabric Link core ciphersuite mismatch")

    def create_pair(
        self,
        *,
        host_identity: bytes,
        group_id: bytes,
        controller_key_package: bytes,
    ) -> PairBootstrap:
        pair = self._binding.fabric_link_create_pair(
            host_identity,
            group_id,
            controller_key_package,
        )
        return PairBootstrap(
            host_state=bytes(pair.host_state),
            welcome=bytes(pair.welcome),
        )

    def create_controller(self, *, identity: bytes) -> ControllerBootstrap:
        bootstrap = self._binding.fabric_link_create_controller(identity)
        return ControllerBootstrap(
            opaque_state=bytes(bootstrap.opaque_state),
            key_package=bytes(bootstrap.key_package),
        )

    def controller_key_package(self, *, opaque_state: bytes) -> bytes:
        return bytes(self._binding.fabric_link_controller_key_package(opaque_state))

    def host_encrypt(self, *, opaque_state: bytes, plaintext: bytes) -> StateUpdate:
        update = self._binding.fabric_link_host_encrypt(opaque_state, plaintext)
        return StateUpdate(
            opaque_state=bytes(update.opaque_state),
            message=bytes(update.message),
        )

    def host_decrypt(
        self, *, opaque_state: bytes, message: bytes
    ) -> HostDecryption:
        decrypted = self._binding.fabric_link_host_decrypt(opaque_state, message)
        return HostDecryption(
            opaque_state=bytes(decrypted.opaque_state),
            plaintext=bytes(decrypted.plaintext),
        )

    def controller_encrypt(
        self, *, opaque_state: bytes, plaintext: bytes
    ) -> StateUpdate:
        update = self._binding.fabric_link_controller_encrypt(
            opaque_state,
            plaintext,
        )
        return StateUpdate(
            opaque_state=bytes(update.opaque_state),
            message=bytes(update.message),
        )

    def remove_controller(self, *, host_state: bytes) -> StateUpdate:
        update = self._binding.fabric_link_host_remove_controller(host_state)
        return StateUpdate(
            opaque_state=bytes(update.opaque_state),
            message=bytes(update.message),
        )

    def join_controller(self, *, opaque_state: bytes, welcome: bytes) -> bytes:
        return bytes(
            self._binding.fabric_link_controller_join(opaque_state, welcome)
        )

    def decrypt_controller(
        self, *, opaque_state: bytes, message: bytes
    ) -> ControllerDecryption:
        decrypted = self._binding.fabric_link_controller_decrypt(
            opaque_state,
            message,
        )
        return ControllerDecryption(
            opaque_state=bytes(decrypted.opaque_state),
            plaintext=bytes(decrypted.plaintext),
        )

    def apply_controller_commit(
        self, *, opaque_state: bytes, commit: bytes
    ) -> ControllerMembershipUpdate:
        update = self._binding.fabric_link_controller_apply_commit(
            opaque_state,
            commit,
        )
        return ControllerMembershipUpdate(
            opaque_state=bytes(update.opaque_state),
            active=bool(update.active),
        )


def load_openmls_core() -> OpenMLSCore:
    """Load only an installed generated binding; never downgrade to fake crypto."""
    try:
        binding = importlib.import_module("fabric_link_core")
    except (ImportError, OSError) as exc:
        raise LinkCoreUnavailable(
            "Fabric Link OpenMLS core is not installed for this platform"
        ) from exc
    return OpenMLSCore(binding)
