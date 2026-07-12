"""Regression tests for auth-store test isolation under Fabric and legacy homes."""

from pathlib import Path

import pytest


@pytest.mark.parametrize("home_name", [".fabric", ".hermes"])
def test_auth_file_path_refuses_real_user_store_during_tests(
    home_name, tmp_path, monkeypatch
):
    import fabric_cli.auth as auth

    monkeypatch.setenv("PYTEST_CURRENT_TEST", "auth-store-safety")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        auth,
        "_REAL_USER_AUTH_ROOTS",
        (tmp_path / ".fabric", tmp_path / ".hermes"),
    )
    target = tmp_path / home_name
    monkeypatch.setattr(auth, "get_fabric_home", lambda: target)

    with pytest.raises(RuntimeError, match="Refusing to touch real user auth store"):
        auth._auth_file_path()


@pytest.mark.parametrize("home_name", [".fabric", ".hermes"])
def test_global_auth_read_guard_covers_fabric_and_legacy_homes(
    home_name, tmp_path, monkeypatch
):
    import fabric_cli.auth as auth

    monkeypatch.setenv("PYTEST_CURRENT_TEST", "auth-store-safety")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        auth,
        "_REAL_USER_AUTH_ROOTS",
        (tmp_path / ".fabric", tmp_path / ".hermes"),
    )
    auth_path = tmp_path / home_name / "auth.json"
    auth_path.parent.mkdir(parents=True)
    auth_path.write_text('{"secret": "must-not-be-read"}\n', encoding="utf-8")
    monkeypatch.setattr(auth, "_global_auth_file_path", lambda: auth_path)

    touched = []

    def record_read(_path):
        touched.append("read")
        return {}

    monkeypatch.setattr(auth, "_load_auth_store", record_read)
    assert auth._load_global_auth_store() == {}
    assert not touched


@pytest.mark.parametrize("home_name", [".fabric", ".hermes"])
def test_global_auth_write_guard_covers_fabric_and_legacy_homes(
    home_name, tmp_path, monkeypatch
):
    import fabric_cli.auth as auth

    monkeypatch.setenv("PYTEST_CURRENT_TEST", "auth-store-safety")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        auth,
        "_REAL_USER_AUTH_ROOTS",
        (tmp_path / ".fabric", tmp_path / ".hermes"),
    )
    auth_path = tmp_path / home_name / "auth.json"
    auth_path.parent.mkdir(parents=True)
    auth_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(auth, "_global_auth_file_path", lambda: auth_path)

    touched = []

    def record_touch(*_args, **_kwargs):
        touched.append("touched")
        return {}

    monkeypatch.setattr(auth, "_load_auth_store", record_touch)
    monkeypatch.setattr(auth, "_save_auth_store", record_touch)
    auth._write_through_xai_oauth_to_global_root({"tokens": {"access_token": "test"}})
    assert not touched


def test_real_user_auth_roots_include_windows_local_appdata(tmp_path, monkeypatch):
    import fabric_cli.auth as auth

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert auth._resolve_real_user_auth_roots("nt") == (
        tmp_path / "fabric",
        tmp_path / "hermes",
    )
