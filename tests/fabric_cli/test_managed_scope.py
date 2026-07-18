"""Unit tests for fabric_cli.managed_scope (resolver + loaders + key helpers)."""
import textwrap
from pathlib import Path

import pytest


# ── Directory resolver ───────────────────────────────────────────────────────


def test_get_managed_dir_fabric_env_override(tmp_path, monkeypatch):
    from fabric_cli import managed_scope

    managed = tmp_path / "managed"
    managed.mkdir()
    monkeypatch.setenv("FABRIC_MANAGED_DIR", str(managed))
    assert managed_scope.get_managed_dir() == managed


def test_get_managed_dir_fabric_override_wins_legacy(tmp_path, monkeypatch):
    from fabric_cli import managed_scope

    fabric_managed = tmp_path / "fabric-managed"
    legacy_managed = tmp_path / "hermes-managed"
    fabric_managed.mkdir()
    legacy_managed.mkdir()
    monkeypatch.setenv("FABRIC_MANAGED_DIR", str(fabric_managed))
    monkeypatch.setenv("HERMES_MANAGED_DIR", str(legacy_managed))
    assert managed_scope.get_managed_dir() == fabric_managed


def test_get_managed_dir_legacy_env_override_remains_supported(tmp_path, monkeypatch):
    from fabric_cli import managed_scope

    managed = tmp_path / "managed"
    managed.mkdir()
    monkeypatch.delenv("FABRIC_MANAGED_DIR", raising=False)
    monkeypatch.setenv("HERMES_MANAGED_DIR", str(managed))
    assert managed_scope.get_managed_dir() == managed


def test_get_managed_dir_invalid_fabric_override_does_not_use_legacy(
    tmp_path, monkeypatch
):
    """An explicit canonical override keeps the legacy path from taking over."""
    from fabric_cli import managed_scope

    legacy_managed = tmp_path / "hermes-managed"
    legacy_managed.mkdir()
    monkeypatch.setenv("FABRIC_MANAGED_DIR", str(tmp_path / "nope"))
    monkeypatch.setenv("HERMES_MANAGED_DIR", str(legacy_managed))
    assert managed_scope.get_managed_dir() is None


def test_get_managed_dir_absent_override_returns_none(tmp_path, monkeypatch):
    from fabric_cli import managed_scope

    monkeypatch.setenv("HERMES_MANAGED_DIR", str(tmp_path / "nope"))
    # Override points at a non-existent dir → no managed scope.
    assert managed_scope.get_managed_dir() is None


def test_get_managed_dir_empty_override_falls_through(tmp_path, monkeypatch):
    from fabric_cli import managed_scope

    monkeypatch.setenv("HERMES_MANAGED_DIR", "   ")  # whitespace = unset
    # Under pytest the system defaults are ignored, so this is None; the
    # assertion that matters is that it does NOT raise.
    result = managed_scope.get_managed_dir()
    assert result is None or result.exists()


def test_get_managed_dir_default_ignored_under_pytest(monkeypatch):
    """The system default must be inert in the test suite (isolation guard)."""
    from fabric_cli import managed_scope

    monkeypatch.delenv("FABRIC_MANAGED_DIR", raising=False)
    monkeypatch.delenv("HERMES_MANAGED_DIR", raising=False)
    assert managed_scope.get_managed_dir() is None


def test_get_managed_dir_prefers_fabric_system_default(monkeypatch):
    from fabric_cli import managed_scope

    monkeypatch.delenv("FABRIC_MANAGED_DIR", raising=False)
    monkeypatch.delenv("FABRIC_MANAGED_DIR", raising=False)
    monkeypatch.setattr(managed_scope, "_under_pytest", lambda: False)
    monkeypatch.setattr(
        Path,
        "is_dir",
        lambda path: path in {Path("/etc/fabric"), Path("/etc/hermes")},
    )

    assert managed_scope.get_managed_dir() == Path("/etc/fabric")


def test_get_managed_dir_falls_back_to_legacy_system_default(monkeypatch):
    from fabric_cli import managed_scope

    monkeypatch.delenv("FABRIC_MANAGED_DIR", raising=False)
    monkeypatch.delenv("FABRIC_MANAGED_DIR", raising=False)
    monkeypatch.setattr(managed_scope, "_under_pytest", lambda: False)
    monkeypatch.setattr(Path, "is_dir", lambda path: path == Path("/etc/hermes"))

    assert managed_scope.get_managed_dir() == Path("/etc/hermes")


# ── Loaders + key helpers ────────────────────────────────────────────────────


def _write_managed(tmp_path, monkeypatch, *, config=None, env=None):
    from fabric_cli import managed_scope

    managed = tmp_path / "managed"
    managed.mkdir(exist_ok=True)
    if config is not None:
        (managed / "config.yaml").write_text(textwrap.dedent(config), encoding="utf-8")
    if env is not None:
        (managed / ".env").write_text(textwrap.dedent(env), encoding="utf-8")
    monkeypatch.setenv("FABRIC_MANAGED_DIR", str(managed))
    managed_scope.invalidate_managed_cache()
    return managed


def test_load_managed_config(tmp_path, monkeypatch):
    from fabric_cli import managed_scope

    _write_managed(
        tmp_path,
        monkeypatch,
        config="""
        model:
          default: managed/model
        """,
    )
    assert managed_scope.load_managed_config() == {"model": {"default": "managed/model"}}


def test_load_managed_config_absent_is_empty(tmp_path, monkeypatch):
    from fabric_cli import managed_scope

    monkeypatch.setenv("FABRIC_MANAGED_DIR", str(tmp_path / "nope"))
    managed_scope.invalidate_managed_cache()
    assert managed_scope.load_managed_config() == {}


def test_load_managed_config_malformed_fails_open(tmp_path, monkeypatch):
    from fabric_cli import managed_scope

    _write_managed(tmp_path, monkeypatch, config="model: : : not yaml :")
    assert managed_scope.load_managed_config() == {}  # fail-open, no raise


def test_managed_config_keys_are_dotted_leaves(tmp_path, monkeypatch):
    from fabric_cli import managed_scope

    _write_managed(
        tmp_path,
        monkeypatch,
        config="""
        model:
          default: m
        security:
          redact_secrets: true
        """,
    )
    assert managed_scope.managed_config_keys() == {
        "model.default",
        "security.redact_secrets",
    }


def test_is_key_managed(tmp_path, monkeypatch):
    from fabric_cli import managed_scope

    _write_managed(tmp_path, monkeypatch, config="model:\n  default: m\n")
    assert managed_scope.is_key_managed("model.default") is True
    assert managed_scope.is_key_managed("model.fallback") is False


def test_load_managed_env_and_is_env_managed(tmp_path, monkeypatch):
    from fabric_cli import managed_scope

    _write_managed(
        tmp_path, monkeypatch, env="OPENAI_API_BASE=https://org.example/v1\n"
    )
    assert managed_scope.load_managed_env() == {
        "OPENAI_API_BASE": "https://org.example/v1"
    }
    assert managed_scope.is_env_managed("OPENAI_API_BASE") is True
    assert managed_scope.is_env_managed("OTHER") is False


def test_editing_managed_config_invalidates_cache(tmp_path, monkeypatch):
    from fabric_cli import managed_scope

    managed = _write_managed(tmp_path, monkeypatch, config="model:\n  default: v1\n")
    assert managed_scope.load_managed_config()["model"]["default"] == "v1"
    (managed / "config.yaml").write_text("model:\n  default: v2\n", encoding="utf-8")
    managed_scope.invalidate_managed_cache()
    assert managed_scope.load_managed_config()["model"]["default"] == "v2"


def test_managed_dir_env_scrubbed_by_default():
    """conftest must scrub managed-dir vars so dev-shell values cannot leak in."""
    import os

    assert "FABRIC_MANAGED_DIR" not in os.environ
    assert "FABRIC_MANAGED_DIR" not in os.environ
