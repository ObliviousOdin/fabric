"""Fail-closed secure persistence for opaque Fabric Link controller state.

The MLS state belongs to one controller device and includes private key
material.  Desktop deliberately keeps it in the local Python backend's OS
credential vault; it never reaches the Electron main process or renderer.
"""

from __future__ import annotations

import base64
import re
import sys
from typing import Protocol


DESKTOP_LINK_KEYRING_SERVICE = "io.github.obliviousodin.fabric.link.controller.v1"
_RECORD_VERSION = "v1"
_MAX_STATE_BYTES = 20 * 1024 * 1024
_CONTROLLER_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


class LinkControllerStateError(RuntimeError):
    """A controller-state operation was unsafe or could not be completed."""


class LinkControllerStateUnavailable(LinkControllerStateError):
    """No approved OS credential vault is available on this desktop."""


class LinkControllerStateCorrupt(LinkControllerStateError):
    """The OS vault returned an invalid controller-state record."""


class KeyringBackend(Protocol):
    def get_password(self, service_name: str, username: str) -> str | None: ...

    def set_password(self, service_name: str, username: str, password: str) -> None: ...

    def delete_password(self, service_name: str, username: str) -> None: ...


class DesktopControllerStateStore:
    """Stores a controller's opaque MLS state exclusively in an OS vault.

    ``from_system`` accepts only direct platform keyring backends.  It rejects
    Keyring's fail, chained, and third-party/file implementations so an
    installation cannot silently downgrade MLS private state into plaintext.
    Tests may pass an in-memory backend directly.
    """

    def __init__(
        self,
        backend: KeyringBackend,
        *,
        service: str = DESKTOP_LINK_KEYRING_SERVICE,
    ) -> None:
        for name in ("get_password", "set_password", "delete_password"):
            if not callable(getattr(backend, name, None)):
                raise LinkControllerStateUnavailable(
                    "desktop secure credential vault is unavailable"
                )
        self._backend = backend
        self._service = service

    @classmethod
    def from_system(cls) -> DesktopControllerStateStore:
        """Open a directly OS-backed vault, or fail before any state is written."""
        try:
            import keyring
        except ImportError as exc:
            raise LinkControllerStateUnavailable(
                "Fabric Link desktop support is not installed; install fabric-agent[link]"
            ) from exc

        try:
            backend = keyring.get_keyring()
        except Exception as exc:
            raise LinkControllerStateUnavailable(
                "desktop secure credential vault is unavailable"
            ) from exc
        if not cls._is_supported_system_backend(backend):
            raise LinkControllerStateUnavailable(
                "an OS credential vault is required for Fabric Link controller state"
            )
        return cls(backend)

    @staticmethod
    def _is_supported_system_backend(backend: object) -> bool:
        """Allow only direct, platform-owned keyring backends.

        A chain is intentionally rejected even when one member might be safe:
        its selection can change as packages and desktop sessions change.
        """
        module = type(backend).__module__
        if sys.platform == "darwin":
            return module.startswith("keyring.backends.macOS")
        if sys.platform == "win32":
            return module.startswith("keyring.backends.Windows")
        if sys.platform.startswith("linux"):
            return module.startswith((
                "keyring.backends.SecretService",
                "keyring.backends.KWallet",
            ))
        return False

    def load(self, controller_id: str) -> bytes | None:
        account = self._account(controller_id)
        try:
            record = self._backend.get_password(self._service, account)
        except Exception as exc:
            raise LinkControllerStateUnavailable(
                "desktop secure credential vault is unavailable"
            ) from exc
        if record is None:
            return None
        return self._decode(record)

    def store(self, controller_id: str, opaque_state: bytes) -> None:
        account = self._account(controller_id)
        state = self._validate_state(opaque_state)
        record = f"{_RECORD_VERSION}:{base64.urlsafe_b64encode(state).decode('ascii')}"
        try:
            self._backend.set_password(self._service, account, record)
        except Exception as exc:
            raise LinkControllerStateUnavailable(
                "desktop secure credential vault is unavailable"
            ) from exc

    def remove(self, controller_id: str) -> None:
        account = self._account(controller_id)
        try:
            self._backend.delete_password(self._service, account)
        except Exception as exc:
            raise LinkControllerStateUnavailable(
                "desktop secure credential vault is unavailable"
            ) from exc

    @staticmethod
    def _account(controller_id: str) -> str:
        if not isinstance(controller_id, str) or not _CONTROLLER_ID_PATTERN.fullmatch(
            controller_id
        ):
            raise ValueError("invalid Fabric Link controller identifier")
        return controller_id

    @staticmethod
    def _validate_state(opaque_state: bytes) -> bytes:
        if not isinstance(opaque_state, bytes) or not opaque_state:
            raise ValueError("Fabric Link controller state must be non-empty bytes")
        if len(opaque_state) > _MAX_STATE_BYTES:
            raise ValueError("Fabric Link controller state exceeds the secure-store limit")
        return opaque_state

    @classmethod
    def _decode(cls, record: str) -> bytes:
        if not isinstance(record, str):
            raise LinkControllerStateCorrupt(
                "desktop secure credential vault returned an invalid state record"
            )
        prefix, separator, encoded = record.partition(":")
        if prefix != _RECORD_VERSION or not separator or not encoded:
            raise LinkControllerStateCorrupt(
                "desktop secure credential vault returned an invalid state record"
            )
        try:
            opaque_state = base64.b64decode(
                encoded.encode("ascii"), altchars=b"-_", validate=True
            )
        except (UnicodeEncodeError, ValueError) as exc:
            raise LinkControllerStateCorrupt(
                "desktop secure credential vault returned an invalid state record"
            ) from exc
        try:
            return cls._validate_state(opaque_state)
        except ValueError as exc:
            raise LinkControllerStateCorrupt(
                "desktop secure credential vault returned an invalid state record"
            ) from exc
