from __future__ import annotations

import pytest

from fabric_link.controller_store import (
    DESKTOP_LINK_KEYRING_SERVICE,
    DesktopControllerStateStore,
    LinkControllerStateCorrupt,
    LinkControllerStateUnavailable,
)


class MemoryKeyring:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str], str] = {}
        self.fail = False

    def get_password(self, service_name: str, username: str) -> str | None:
        if self.fail:
            raise RuntimeError("unavailable")
        return self.records.get((service_name, username))

    def set_password(self, service_name: str, username: str, password: str) -> None:
        if self.fail:
            raise RuntimeError("unavailable")
        self.records[(service_name, username)] = password

    def delete_password(self, service_name: str, username: str) -> None:
        if self.fail:
            raise RuntimeError("unavailable")
        self.records.pop((service_name, username), None)


def test_desktop_store_round_trips_opaque_state_only():
    vault = MemoryKeyring()
    store = DesktopControllerStateStore(vault)

    assert store.load("controller-1") is None
    store.store("controller-1", b"opaque-mls-state")

    record = vault.records[(DESKTOP_LINK_KEYRING_SERVICE, "controller-1")]
    assert record.startswith("v1:")
    assert "opaque-mls-state" not in record
    assert store.load("controller-1") == b"opaque-mls-state"

    store.remove("controller-1")
    assert store.load("controller-1") is None


@pytest.mark.parametrize("controller_id", ["", "contains space", "../../state", "a" * 129])
def test_desktop_store_rejects_unscoped_controller_identifiers(controller_id):
    store = DesktopControllerStateStore(MemoryKeyring())

    with pytest.raises(ValueError, match="identifier"):
        store.load(controller_id)


@pytest.mark.parametrize("state", [b"", "not-bytes", b"x" * (20 * 1024 * 1024 + 1)])
def test_desktop_store_rejects_invalid_opaque_state(state):
    store = DesktopControllerStateStore(MemoryKeyring())

    with pytest.raises(ValueError, match="state"):
        store.store("controller-1", state)  # type: ignore[arg-type]


def test_desktop_store_treats_malformed_vault_records_as_corrupt():
    vault = MemoryKeyring()
    vault.records[(DESKTOP_LINK_KEYRING_SERVICE, "controller-1")] = "v1:not base64!"
    store = DesktopControllerStateStore(vault)

    with pytest.raises(LinkControllerStateCorrupt, match="invalid state record"):
        store.load("controller-1")


def test_desktop_store_fails_closed_when_the_vault_raises():
    vault = MemoryKeyring()
    vault.fail = True
    store = DesktopControllerStateStore(vault)

    with pytest.raises(LinkControllerStateUnavailable, match="credential vault"):
        store.store("controller-1", b"opaque-mls-state")


@pytest.mark.parametrize(
    ("platform", "module", "expected"),
    [
        ("darwin", "keyring.backends.macOS", True),
        ("darwin", "keyring.backends.fail", False),
        ("win32", "keyring.backends.Windows", True),
        ("win32", "keyring.backends.fail", False),
        ("linux", "keyring.backends.SecretService", True),
        ("linux", "keyring.backends.KWallet", True),
        ("linux", "keyrings.alt.file", False),
        ("freebsd", "keyring.backends.macOS", False),
    ],
)
def test_desktop_store_accepts_only_direct_os_backends(monkeypatch, platform, module, expected):
    backend_type = type("Backend", (), {"__module__": module})
    monkeypatch.setattr("fabric_link.controller_store.sys.platform", platform)

    assert DesktopControllerStateStore._is_supported_system_backend(backend_type()) is expected
