"""Tests for the secret-source tracking in ``fabric_cli.env_loader``.

These cover the small public surface that lets `fabric model` / `fabric setup`
label detected credentials with their origin ("from Bitwarden") so users
don't see an unexplained "credentials ✓" line when their .env is empty.
"""

from __future__ import annotations

import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fabric_cli import env_loader  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_sources():
    """Each test starts with a clean source map and applied-home guard."""
    env_loader._SECRET_SOURCES.clear()
    env_loader._LEGACY_APPLIED_SECRET_VALUES.clear()
    env_loader.reset_secret_source_cache()
    env_loader._SECRET_SOURCE_FORCE_REFRESH_HOMES.clear()
    yield
    env_loader._SECRET_SOURCES.clear()
    env_loader._LEGACY_APPLIED_SECRET_VALUES.clear()
    env_loader.reset_secret_source_cache()
    env_loader._SECRET_SOURCE_FORCE_REFRESH_HOMES.clear()


def test_get_secret_source_returns_none_for_untracked_var():
    assert env_loader.get_secret_source("ANTHROPIC_API_KEY") is None


def test_get_secret_source_returns_label_for_tracked_var():
    env_loader._SECRET_SOURCES["ANTHROPIC_API_KEY"] = "bitwarden"
    assert env_loader.get_secret_source("ANTHROPIC_API_KEY") == "bitwarden"


def test_format_secret_source_suffix_empty_for_untracked():
    # Credentials from .env or the shell shouldn't add noise — the
    # implicit case stays unlabeled.
    assert env_loader.format_secret_source_suffix("ANTHROPIC_API_KEY") == ""


def test_format_secret_source_suffix_bitwarden_uses_proper_name():
    env_loader._SECRET_SOURCES["ANTHROPIC_API_KEY"] = "bitwarden"
    assert (
        env_loader.format_secret_source_suffix("ANTHROPIC_API_KEY")
        == " (from Bitwarden)"
    )


def test_format_secret_source_suffix_generic_label_for_future_sources():
    # Future-proofing: a new secret source (e.g. "vault") should still
    # produce a sensible label without needing to edit every call site.
    env_loader._SECRET_SOURCES["OPENAI_API_KEY"] = "vault"
    assert (
        env_loader.format_secret_source_suffix("OPENAI_API_KEY")
        == " (from vault)"
    )


def test_format_secret_source_suffix_onepassword_uses_proper_name():
    env_loader._SECRET_SOURCES["OPENAI_API_KEY"] = "onepassword"
    assert (
        env_loader.format_secret_source_suffix("OPENAI_API_KEY")
        == " (from 1Password)"
    )


def test_apply_external_secret_sources_records_bitwarden_origin(tmp_path, monkeypatch):
    """End-to-end: when the Bitwarden source fetches keys, applied vars
    end up in ``_SECRET_SOURCES`` so the UI can label them."""

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("BWS_ACCESS_TOKEN", "0.test-token")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "secrets:\n"
        "  bitwarden:\n"
        "    enabled: true\n"
        "    project_id: test-project\n"
        "    access_token_env: BWS_ACCESS_TOKEN\n",
        encoding="utf-8",
    )

    # Stub the fetch layer under the SecretSource adapter.
    import agent.secret_sources.bitwarden as bw_module

    monkeypatch.setattr(bw_module, "find_bws", lambda **_kw: Path("/fake/bws"))
    monkeypatch.setattr(
        bw_module,
        "fetch_bitwarden_secrets",
        lambda **_kw: ({"ANTHROPIC_API_KEY": "sk-ant-test"}, []),
    )

    from agent.secret_sources import registry as reg_module

    reg_module._reset_registry_for_tests()

    env_loader._apply_external_secret_sources(tmp_path)

    assert env_loader.get_secret_source("ANTHROPIC_API_KEY") == "bitwarden"
    assert (
        env_loader.get_profile_secret_source_value(tmp_path, "ANTHROPIC_API_KEY")
        == "sk-ant-test"
    )
    assert (
        env_loader.get_profile_secret_source_value(
            tmp_path / "profiles" / "other",
            "ANTHROPIC_API_KEY",
        )
        is None
    )
    assert (
        env_loader.format_secret_source_suffix("ANTHROPIC_API_KEY")
        == " (from Bitwarden)"
    )


def test_apply_external_secret_sources_noop_when_disabled(tmp_path, monkeypatch):
    """Disabled Bitwarden config must not touch the source map."""

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "secrets:\n"
        "  bitwarden:\n"
        "    enabled: false\n",
        encoding="utf-8",
    )

    env_loader._apply_external_secret_sources(tmp_path)

    assert env_loader.get_secret_source("ANTHROPIC_API_KEY") is None


def test_apply_external_secret_sources_dedupes_within_process(tmp_path, monkeypatch):
    """``load_fabric_dotenv()`` is called at module-import time from several
    hot modules (cli.py, fabric_cli/main.py, run_agent.py, ...).  The
    Bitwarden status line previously printed once per call — 3-5x per
    startup.  The applied-home guard must short-circuit subsequent calls
    so the heavy work (config re-parse, Bitwarden lookup, status print)
    runs exactly once per HERMES_HOME per process.
    """

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("BWS_ACCESS_TOKEN", "0.test-token")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "secrets:\n"
        "  bitwarden:\n"
        "    enabled: true\n"
        "    project_id: test-project\n"
        "    access_token_env: BWS_ACCESS_TOKEN\n",
        encoding="utf-8",
    )

    call_count = {"n": 0}

    def _fake_fetch(**_kwargs):
        call_count["n"] += 1
        return {"ANTHROPIC_API_KEY": "sk-ant-test"}, []

    import agent.secret_sources.bitwarden as bw_module
    monkeypatch.setattr(bw_module, "find_bws", lambda **_kw: Path("/fake/bws"))
    monkeypatch.setattr(bw_module, "fetch_bitwarden_secrets", _fake_fetch)

    from agent.secret_sources import registry as reg_module

    reg_module._reset_registry_for_tests()

    # Five calls in a row, simulating module-import-time invocations from
    # cli.py, fabric_cli/main.py, run_agent.py, trajectory_compressor.py,
    # gateway/run.py.  Only the first should actually call the backend.
    for _ in range(5):
        env_loader._apply_external_secret_sources(tmp_path)

    assert call_count["n"] == 1, (
        "Bitwarden backend was called {} time(s); expected exactly 1 — "
        "the applied-home guard is broken.".format(call_count["n"])
    )

    # Source tracking still works after dedup.
    assert env_loader.get_secret_source("ANTHROPIC_API_KEY") == "bitwarden"

    # reset_secret_source_cache() forces a fresh pull on the next call.
    env_loader.reset_secret_source_cache()
    assert (
        env_loader.get_profile_secret_source_value(tmp_path, "ANTHROPIC_API_KEY")
        is None
    )
    assert env_loader.get_secret_source("ANTHROPIC_API_KEY") is None
    assert env_loader.get_legacy_applied_secret_names(tmp_path) == {
        "ANTHROPIC_API_KEY"
    }
    env_loader._apply_external_secret_sources(tmp_path)
    assert call_count["n"] == 2


def test_apply_external_secret_sources_records_onepassword_origin(tmp_path, monkeypatch):
    """When the 1Password source resolves refs, applied vars end up in
    ``_SECRET_SOURCES`` labeled ``onepassword``."""

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    (tmp_path / "config.yaml").write_text(
        "secrets:\n"
        "  onepassword:\n"
        "    enabled: true\n"
        "    env:\n"
        "      ANTHROPIC_API_KEY: 'op://Private/Anthropic/credential'\n",
        encoding="utf-8",
    )

    import agent.secret_sources.onepassword as op_module

    monkeypatch.setattr(op_module, "find_op", lambda *_a, **_kw: Path("/fake/op"))
    monkeypatch.setattr(
        op_module,
        "fetch_onepassword_secrets",
        lambda **_kw: ({"ANTHROPIC_API_KEY": "sk-ant-test"}, []),
    )

    from agent.secret_sources import registry as reg_module

    reg_module._reset_registry_for_tests()

    env_loader._apply_external_secret_sources(tmp_path)

    assert env_loader.get_secret_source("ANTHROPIC_API_KEY") == "onepassword"
    assert (
        env_loader.format_secret_source_suffix("ANTHROPIC_API_KEY")
        == " (from 1Password)"
    )


def test_apply_external_secret_sources_survives_non_dict_section(tmp_path, monkeypatch):
    """A malformed `secrets:` section must not abort startup (fail-open).

    Both `onepassword: true` (non-dict) and a bad bitwarden section must be
    coerced to empty config instead of raising AttributeError up through
    load_fabric_dotenv().
    """

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        "secrets:\n"
        "  bitwarden: true\n"
        "  onepassword: true\n",
        encoding="utf-8",
    )

    # Must not raise and must not record anything.
    env_loader._apply_external_secret_sources(tmp_path)
    assert env_loader.get_secret_source("ANYTHING") is None


def test_apply_external_secret_sources_bad_ttl_does_not_crash(tmp_path, monkeypatch):
    """A non-numeric cache_ttl_seconds must be coerced, not crash startup."""

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        "secrets:\n"
        "  onepassword:\n"
        "    enabled: true\n"
        "    cache_ttl_seconds: not-a-number\n"
        "    env:\n"
        "      K: 'op://V/I/F'\n",
        encoding="utf-8",
    )

    captured = {}

    def _fake_fetch(**kwargs):
        captured.update(kwargs)
        return {}, []

    import agent.secret_sources.onepassword as op_module
    monkeypatch.setattr(op_module, "find_op", lambda *_a, **_kw: Path("/fake/op"))
    monkeypatch.setattr(op_module, "fetch_onepassword_secrets", _fake_fetch)

    from agent.secret_sources import registry as reg_module

    reg_module._reset_registry_for_tests()

    env_loader._apply_external_secret_sources(tmp_path)

    # Coerced to the 300s default rather than raising ValueError.
    assert captured["cache_ttl_seconds"] == 300


def test_profile_resolution_is_non_mutating_and_two_home_concurrent(
    tmp_path, monkeypatch
):
    """Two target homes resolve exact values without sharing launch secrets.

    The barrier is inside ``fetch`` so both per-home workers must be live at
    once.  Holding one process-global cache lock across fetch would deadlock or
    time out here, making the concurrency contract deterministic rather than
    timing-based.
    """
    from agent.secret_sources import registry as reg
    from agent.secret_sources.base import FetchResult, SecretSource

    home_a = tmp_path / "profiles" / "a"
    home_b = tmp_path / "profiles" / "b"
    barrier = threading.Barrier(2, timeout=5)
    snapshots = {}

    for home, suffix in ((home_a, "a"), (home_b, "b")):
        home.mkdir(parents=True)
        (home / ".env").write_text(
            f"BWS_ACCESS_TOKEN=bws-{suffix}\n",
            encoding="utf-8",
        )
        (home / ".op.env").write_text(
            f"OP_SERVICE_ACCOUNT_TOKEN=op-{suffix}\n",
            encoding="utf-8",
        )
        (home / "config.yaml").write_text(
            "secrets:\n  scoped_test:\n    enabled: true\n",
            encoding="utf-8",
        )

    class ScopedTestSource(SecretSource):
        name = "scoped_test"
        label = "Scoped test"
        shape = "mapped"
        supports_scoped_environment = True

        def fetch(self, cfg, home_path):
            from fabric_constants import get_fabric_home

            env = dict(reg.get_resolution_environment())
            assert get_fabric_home() == home_path
            snapshots[home_path.name] = env
            barrier.wait()
            return FetchResult(
                secrets={
                    "RESULT_API_KEY": (
                        f"{env['BWS_ACCESS_TOKEN']}:{env['OP_SERVICE_ACCOUNT_TOKEN']}"
                        "\u200b"
                    )
                }
            )

    monkeypatch.setenv("BWS_ACCESS_TOKEN", "launch-bws")
    monkeypatch.setenv("OP_SERVICE_ACCOUNT_TOKEN", "launch-op")
    monkeypatch.setenv("OPENAI_API_KEY", "launch-provider")
    monkeypatch.setenv("OP_SESSION_shared", "interactive-session")
    launch_values = {
        key: os.environ[key]
        for key in (
            "BWS_ACCESS_TOKEN",
            "OP_SERVICE_ACCOUNT_TOKEN",
            "OPENAI_API_KEY",
            "OP_SESSION_shared",
        )
    }

    reg._reset_registry_for_tests()
    monkeypatch.setattr(reg, "_ensure_builtin_sources", lambda: None)
    assert reg.register_source(ScopedTestSource())
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            future_a = pool.submit(env_loader.resolve_external_secret_sources, home_a)
            future_b = pool.submit(env_loader.resolve_external_secret_sources, home_b)
            result_a = future_a.result(timeout=10)
            result_b = future_b.result(timeout=10)
    finally:
        reg._reset_registry_for_tests()

    assert result_a.values == {"RESULT_API_KEY": "bws-a:op-a"}
    assert result_b.values == {"RESULT_API_KEY": "bws-b:op-b"}
    assert result_a.provenance == {"RESULT_API_KEY": "scoped_test"}
    assert result_b.provenance == {"RESULT_API_KEY": "scoped_test"}
    assert snapshots["a"]["BWS_ACCESS_TOKEN"] == "bws-a"
    assert snapshots["b"]["BWS_ACCESS_TOKEN"] == "bws-b"
    assert snapshots["a"]["OP_SERVICE_ACCOUNT_TOKEN"] == "op-a"
    assert snapshots["b"]["OP_SERVICE_ACCOUNT_TOKEN"] == "op-b"
    assert snapshots["a"]["OP_SESSION_shared"] == "interactive-session"
    assert snapshots["b"]["OP_SESSION_shared"] == "interactive-session"
    assert "OPENAI_API_KEY" not in snapshots["a"]
    assert "OPENAI_API_KEY" not in snapshots["b"]
    assert {
        key: os.environ[key]
        for key in launch_values
    } == launch_values
    assert env_loader.get_profile_secret_source_values(home_a) == result_a.values
    assert env_loader.get_profile_secret_source_values(home_b) == result_b.values
    assert env_loader.get_profile_secret_source_provenance(home_a) == (
        result_a.provenance
    )
    assert env_loader.get_profile_secret_source_provenance(home_b) == (
        result_b.provenance
    )


def test_profile_resolution_cache_honors_shortest_source_ttl(tmp_path, monkeypatch):
    from agent.secret_sources import registry as reg
    from agent.secret_sources.base import FetchResult, SecretSource

    calls = []
    clock = [100.0]
    (tmp_path / "config.yaml").write_text(
        "secrets:\n"
        "  scoped_test:\n"
        "    enabled: true\n"
        "    cache_ttl_seconds: 10\n",
        encoding="utf-8",
    )

    class ScopedTestSource(SecretSource):
        name = "scoped_test"
        label = "Scoped test"
        supports_scoped_environment = True

        def fetch(self, cfg, home_path):
            calls.append(home_path)
            return FetchResult(secrets={"RESULT_API_KEY": f"value-{len(calls)}"})

    monkeypatch.setattr(env_loader, "_secret_source_cache_now", lambda: clock[0])
    reg._reset_registry_for_tests()
    monkeypatch.setattr(reg, "_ensure_builtin_sources", lambda: None)
    assert reg.register_source(ScopedTestSource())
    try:
        first = env_loader.resolve_external_secret_sources(tmp_path)
        cached = env_loader.resolve_external_secret_sources(tmp_path)
        clock[0] += 10.01
        refreshed = env_loader.resolve_external_secret_sources(tmp_path)
    finally:
        reg._reset_registry_for_tests()

    assert first.values == {"RESULT_API_KEY": "value-1"}
    assert not first.from_cache
    assert cached.values == first.values
    assert cached.from_cache
    assert refreshed.values == {"RESULT_API_KEY": "value-2"}
    assert not refreshed.from_cache
    assert len(calls) == 2


def test_profile_resolution_cache_tracks_all_input_file_content(
    tmp_path, monkeypatch
):
    from agent.secret_sources import registry as reg
    from agent.secret_sources.base import FetchResult, SecretSource

    project_env = tmp_path / "project.env"
    calls = []

    def _write_config(marker: str) -> None:
        (tmp_path / "config.yaml").write_text(
            "secrets:\n"
            "  scoped_test:\n"
            "    enabled: true\n"
            "    cache_ttl_seconds: 3600\n"
            f"    marker: {marker}\n",
            encoding="utf-8",
        )

    _write_config("one")
    (tmp_path / ".env").write_text("LOCAL_INPUT=one\n", encoding="utf-8")
    (tmp_path / ".op.env").write_text("OP_INPUT=one\n", encoding="utf-8")
    project_env.write_text("PROJECT_INPUT=one\n", encoding="utf-8")

    class ScopedTestSource(SecretSource):
        name = "scoped_test"
        label = "Scoped test"
        supports_scoped_environment = True

        def fetch(self, cfg, home_path):
            env = reg.get_resolution_environment()
            calls.append(home_path)
            joined = ":".join(
                (
                    str(cfg["marker"]),
                    env["LOCAL_INPUT"],
                    env["OP_INPUT"],
                    env["PROJECT_INPUT"],
                )
            )
            return FetchResult(secrets={"RESULT_API_KEY": joined})

    reg._reset_registry_for_tests()
    monkeypatch.setattr(reg, "_ensure_builtin_sources", lambda: None)
    assert reg.register_source(ScopedTestSource())
    try:
        first = env_loader.resolve_external_secret_sources(
            tmp_path, project_env=project_env
        )
        cached = env_loader.resolve_external_secret_sources(
            tmp_path, project_env=project_env
        )

        (tmp_path / ".env").write_text("LOCAL_INPUT=two\n", encoding="utf-8")
        after_env = env_loader.resolve_external_secret_sources(
            tmp_path, project_env=project_env
        )

        (tmp_path / ".op.env").write_text("OP_INPUT=two\n", encoding="utf-8")
        after_op_env = env_loader.resolve_external_secret_sources(
            tmp_path, project_env=project_env
        )

        project_env.write_text("PROJECT_INPUT=two\n", encoding="utf-8")
        after_project = env_loader.resolve_external_secret_sources(
            tmp_path, project_env=project_env
        )

        _write_config("two")
        after_config = env_loader.resolve_external_secret_sources(
            tmp_path, project_env=project_env
        )
    finally:
        reg._reset_registry_for_tests()

    assert first.values == {"RESULT_API_KEY": "one:one:one:one"}
    assert cached.from_cache
    assert after_env.values == {"RESULT_API_KEY": "one:two:one:one"}
    assert after_op_env.values == {"RESULT_API_KEY": "one:two:two:one"}
    assert after_project.values == {"RESULT_API_KEY": "one:two:two:two"}
    assert after_config.values == {"RESULT_API_KEY": "two:two:two:two"}
    assert len(calls) == 5


@pytest.mark.parametrize(
    "auth_name",
    [
        "OP_SESSION_team",
        "OP_ACCOUNT",
        "OP_CONNECT_HOST",
        "OP_CONNECT_TOKEN",
    ],
)
def test_profile_resolution_cache_tracks_value_safe_process_auth_inputs(
    tmp_path, monkeypatch, auth_name
):
    from agent.secret_sources import registry as reg
    from agent.secret_sources.base import FetchResult, SecretSource

    calls = []
    (tmp_path / "config.yaml").write_text(
        "secrets:\n  scoped_test:\n    enabled: true\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(auth_name, "auth-value-one")

    class ScopedTestSource(SecretSource):
        name = "scoped_test"
        label = "Scoped test"
        supports_scoped_environment = True

        def fetch(self, cfg, home_path):
            calls.append(home_path)
            value = reg.get_resolution_environment()[auth_name]
            return FetchResult(secrets={"RESULT_API_KEY": value})

    reg._reset_registry_for_tests()
    monkeypatch.setattr(reg, "_ensure_builtin_sources", lambda: None)
    assert reg.register_source(ScopedTestSource())
    try:
        first = env_loader.resolve_external_secret_sources(tmp_path)
        cached = env_loader.resolve_external_secret_sources(tmp_path)
        metadata = next(iter(env_loader._PROFILE_SECRET_SOURCE_CACHE_METADATA.values()))
        monkeypatch.setenv(auth_name, "auth-value-two")
        refreshed = env_loader.resolve_external_secret_sources(tmp_path)
    finally:
        reg._reset_registry_for_tests()

    assert first.values == {"RESULT_API_KEY": "auth-value-one"}
    assert cached.from_cache
    assert refreshed.values == {"RESULT_API_KEY": "auth-value-two"}
    assert len(calls) == 2
    assert "auth-value-one" not in repr(metadata.input_fingerprint)


def test_legacy_cache_tracks_configured_bootstrap_and_resolution_mode(
    tmp_path, monkeypatch
):
    from agent.secret_sources import registry as reg
    from agent.secret_sources.base import FetchResult, SecretSource

    calls = []
    (tmp_path / "config.yaml").write_text(
        "secrets:\n"
        "  bitwarden:\n"
        "    enabled: true\n"
        "    access_token_env: CUSTOM_BOOTSTRAP_TOKEN\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CUSTOM_BOOTSTRAP_TOKEN", "bootstrap-one")

    class ScopedBitwardenSource(SecretSource):
        name = "bitwarden"
        label = "Scoped Bitwarden"
        supports_scoped_environment = True

        def fetch(self, cfg, home_path):
            calls.append(home_path)
            value = reg.get_resolution_environment().get(
                "CUSTOM_BOOTSTRAP_TOKEN", "missing"
            )
            return FetchResult(secrets={"RESULT_API_KEY": value})

    reg._reset_registry_for_tests()
    monkeypatch.setattr(reg, "_ensure_builtin_sources", lambda: None)
    assert reg.register_source(ScopedBitwardenSource())
    try:
        first = env_loader._resolve_external_secret_sources(
            tmp_path,
            allow_process_bootstrap=True,
        )
        cached = env_loader._resolve_external_secret_sources(
            tmp_path,
            allow_process_bootstrap=True,
        )
        monkeypatch.setenv("CUSTOM_BOOTSTRAP_TOKEN", "bootstrap-two")
        refreshed = env_loader._resolve_external_secret_sources(
            tmp_path,
            allow_process_bootstrap=True,
        )
        isolated = env_loader.resolve_external_secret_sources(tmp_path)
    finally:
        reg._reset_registry_for_tests()

    assert first.values == {"RESULT_API_KEY": "bootstrap-one"}
    assert cached.from_cache
    assert refreshed.values == {"RESULT_API_KEY": "bootstrap-two"}
    assert isolated.values == {"RESULT_API_KEY": "missing"}
    assert not isolated.from_cache
    assert len(calls) == 3


def test_profile_resolution_cache_tracks_managed_value_snapshot(tmp_path, monkeypatch):
    from agent.secret_sources import registry as reg
    from agent.secret_sources.base import FetchResult, SecretSource
    from fabric_cli import managed_scope

    calls = []
    managed = [{"MANAGED_API_KEY": "managed-one"}]
    (tmp_path / "config.yaml").write_text(
        "secrets:\n  scoped_test:\n    enabled: true\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(managed_scope, "load_managed_env", lambda: dict(managed[0]))

    class ScopedTestSource(SecretSource):
        name = "scoped_test"
        label = "Scoped test"
        supports_scoped_environment = True

        def fetch(self, cfg, home_path):
            calls.append(home_path)
            value = reg.get_resolution_environment()["MANAGED_API_KEY"]
            return FetchResult(secrets={"RESULT_API_KEY": value})

    reg._reset_registry_for_tests()
    monkeypatch.setattr(reg, "_ensure_builtin_sources", lambda: None)
    assert reg.register_source(ScopedTestSource())
    try:
        first = env_loader.resolve_external_secret_sources(tmp_path)
        cached = env_loader.resolve_external_secret_sources(tmp_path)
        managed[0] = {"MANAGED_API_KEY": "managed-two"}
        refreshed = env_loader.resolve_external_secret_sources(tmp_path)
    finally:
        reg._reset_registry_for_tests()

    assert first.values == {"RESULT_API_KEY": "managed-one"}
    assert cached.from_cache
    assert refreshed.values == {"RESULT_API_KEY": "managed-two"}
    assert len(calls) == 2


def test_profile_resolution_cache_invalidates_when_plugin_registers(
    tmp_path, monkeypatch
):
    from agent.secret_sources import registry as reg
    from agent.secret_sources.base import FetchResult, SecretSource

    (tmp_path / "config.yaml").write_text(
        "secrets:\n  late_source:\n    enabled: true\n",
        encoding="utf-8",
    )

    class LateSource(SecretSource):
        name = "late_source"
        label = "Late source"
        supports_scoped_environment = True

        def fetch(self, cfg, home_path):
            return FetchResult(secrets={"RESULT_API_KEY": "registered"})

    reg._reset_registry_for_tests()
    monkeypatch.setattr(reg, "_ensure_builtin_sources", lambda: None)
    try:
        before_registration = env_loader.resolve_external_secret_sources(tmp_path)
        cached_empty = env_loader.resolve_external_secret_sources(tmp_path)
        assert reg.register_source(LateSource())
        after_registration = env_loader.resolve_external_secret_sources(tmp_path)
    finally:
        reg._reset_registry_for_tests()

    assert before_registration.values == {}
    assert cached_empty.from_cache
    assert after_registration.values == {"RESULT_API_KEY": "registered"}
    assert not after_registration.from_cache


def test_profile_resolution_does_not_cache_partial_mapped_pull(
    tmp_path, monkeypatch
):
    from agent.secret_sources import registry as reg
    from agent.secret_sources.base import FetchResult, SecretSource

    calls = []
    (tmp_path / "config.yaml").write_text(
        "secrets:\n"
        "  scoped_test:\n"
        "    enabled: true\n"
        "    cache_ttl_seconds: 3600\n"
        "    env:\n"
        "      GOOD_API_KEY: op://Vault/good/value\n"
        "      RETRY_API_KEY: op://Vault/retry/value\n",
        encoding="utf-8",
    )

    class ScopedTestSource(SecretSource):
        name = "scoped_test"
        label = "Scoped test"
        shape = "mapped"
        scheme = "op"
        supports_scoped_environment = True

        def fetch(self, cfg, home_path):
            calls.append(home_path)
            secrets = {"GOOD_API_KEY": "good"}
            warnings = ["temporary per-reference failure"]
            if len(calls) > 1:
                secrets["RETRY_API_KEY"] = "recovered"
                warnings = []
            return FetchResult(secrets=secrets, warnings=warnings)

    reg._reset_registry_for_tests()
    monkeypatch.setattr(reg, "_ensure_builtin_sources", lambda: None)
    assert reg.register_source(ScopedTestSource())
    try:
        partial = env_loader.resolve_external_secret_sources(tmp_path)
        recovered = env_loader.resolve_external_secret_sources(tmp_path)
        cached = env_loader.resolve_external_secret_sources(tmp_path)
    finally:
        reg._reset_registry_for_tests()

    assert partial.values == {"GOOD_API_KEY": "good"}
    assert not partial.successful
    assert recovered.values == {
        "GOOD_API_KEY": "good",
        "RETRY_API_KEY": "recovered",
    }
    assert recovered.successful
    assert cached.from_cache
    assert len(calls) == 2


def test_profile_resolution_retries_partial_onepassword_warning(
    tmp_path, monkeypatch
):
    from agent.secret_sources import onepassword as op
    from agent.secret_sources import registry as reg

    calls = []
    (tmp_path / "config.yaml").write_text(
        "secrets:\n"
        "  onepassword:\n"
        "    enabled: true\n"
        "    cache_ttl_seconds: 3600\n"
        "    env:\n"
        "      GOOD_API_KEY: op://Vault/good/value\n"
        "      RETRY_API_KEY: op://Vault/retry/value\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(op, "find_op", lambda *_args, **_kwargs: Path("/fake/op"))

    def _fetch_onepassword(**_kwargs):
        calls.append(True)
        if len(calls) == 1:
            return {"GOOD_API_KEY": "good"}, ["temporary read failure"]
        return {
            "GOOD_API_KEY": "good",
            "RETRY_API_KEY": "recovered",
        }, []

    monkeypatch.setattr(op, "fetch_onepassword_secrets", _fetch_onepassword)
    reg._reset_registry_for_tests()
    try:
        partial = env_loader.resolve_external_secret_sources(tmp_path)
        recovered = env_loader.resolve_external_secret_sources(tmp_path)
        cached = env_loader.resolve_external_secret_sources(tmp_path)
    finally:
        reg._reset_registry_for_tests()

    assert partial.values == {"GOOD_API_KEY": "good"}
    assert not partial.successful
    assert recovered.values == {
        "GOOD_API_KEY": "good",
        "RETRY_API_KEY": "recovered",
    }
    assert cached.from_cache
    assert len(calls) == 2


def test_profile_resolution_retries_transient_failure_instead_of_caching_empty(
    tmp_path, monkeypatch
):
    from agent.secret_sources import registry as reg
    from agent.secret_sources.base import ErrorKind, FetchResult, SecretSource

    calls = []
    (tmp_path / "config.yaml").write_text(
        "secrets:\n"
        "  scoped_test:\n"
        "    enabled: true\n"
        "    cache_ttl_seconds: 3600\n",
        encoding="utf-8",
    )

    class ScopedTestSource(SecretSource):
        name = "scoped_test"
        label = "Scoped test"
        supports_scoped_environment = True

        def fetch(self, cfg, home_path):
            calls.append(home_path)
            if len(calls) == 1:
                return FetchResult(
                    error="temporary network failure",
                    error_kind=ErrorKind.NETWORK,
                )
            return FetchResult(secrets={"RESULT_API_KEY": "recovered"})

    reg._reset_registry_for_tests()
    monkeypatch.setattr(reg, "_ensure_builtin_sources", lambda: None)
    assert reg.register_source(ScopedTestSource())
    try:
        failed = env_loader.resolve_external_secret_sources(tmp_path)
        recovered = env_loader.resolve_external_secret_sources(tmp_path)
        cached = env_loader.resolve_external_secret_sources(tmp_path)
    finally:
        reg._reset_registry_for_tests()

    assert failed.values == {}
    assert not failed.from_cache
    assert recovered.values == {"RESULT_API_KEY": "recovered"}
    assert not recovered.from_cache
    assert cached.values == recovered.values
    assert cached.from_cache
    assert len(calls) == 2


def test_legacy_apply_retries_network_failure_then_succeeds(tmp_path, monkeypatch):
    from agent.secret_sources import registry as reg
    from agent.secret_sources.base import ErrorKind, FetchResult, SecretSource

    calls = []
    (tmp_path / "config.yaml").write_text(
        "secrets:\n  legacy_test:\n    enabled: true\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("LEGACY_RESULT_API_KEY", raising=False)

    class LegacyTestSource(SecretSource):
        name = "legacy_test"
        label = "Legacy test"

        def fetch(self, cfg, home_path):
            calls.append(home_path)
            if len(calls) == 1:
                return FetchResult(
                    error="temporary network failure",
                    error_kind=ErrorKind.NETWORK,
                )
            return FetchResult(secrets={"LEGACY_RESULT_API_KEY": "recovered"})

    reg._reset_registry_for_tests()
    monkeypatch.setattr(reg, "_ensure_builtin_sources", lambda: None)
    assert reg.register_source(LegacyTestSource())
    try:
        env_loader._apply_external_secret_sources(tmp_path)
        assert "LEGACY_RESULT_API_KEY" not in os.environ
        env_loader._apply_external_secret_sources(tmp_path)
    finally:
        reg._reset_registry_for_tests()

    assert os.environ["LEGACY_RESULT_API_KEY"] == "recovered"
    assert len(calls) == 2


def test_legacy_apply_refreshes_for_ttl_config_and_dotenv_changes(
    tmp_path, monkeypatch
):
    from agent.secret_sources import registry as reg
    from agent.secret_sources.base import FetchResult, SecretSource

    calls = []
    clock = [100.0]

    def _write_config(marker: str) -> None:
        (tmp_path / "config.yaml").write_text(
            "secrets:\n"
            "  legacy_test:\n"
            "    enabled: true\n"
            "    cache_ttl_seconds: 10\n"
            f"    marker: {marker}\n",
            encoding="utf-8",
        )

    _write_config("one")
    (tmp_path / ".env").write_text("LEGACY_INPUT=one\n", encoding="utf-8")
    monkeypatch.delenv("LEGACY_RESULT_API_KEY", raising=False)

    class LegacyTestSource(SecretSource):
        name = "legacy_test"
        label = "Legacy test"

        def fetch(self, cfg, home_path):
            calls.append(home_path)
            env = reg.get_resolution_environment()
            return FetchResult(
                secrets={
                    "LEGACY_RESULT_API_KEY": (
                        f"{cfg['marker']}:{env['LEGACY_INPUT']}:{len(calls)}"
                    )
                }
            )

    monkeypatch.setattr(env_loader, "_secret_source_cache_now", lambda: clock[0])
    reg._reset_registry_for_tests()
    monkeypatch.setattr(reg, "_ensure_builtin_sources", lambda: None)
    assert reg.register_source(LegacyTestSource())
    try:
        env_loader._apply_external_secret_sources(tmp_path)
        env_loader._apply_external_secret_sources(tmp_path)
        assert len(calls) == 1

        clock[0] += 10.01
        env_loader._apply_external_secret_sources(tmp_path)
        assert os.environ["LEGACY_RESULT_API_KEY"] == "one:one:2"

        (tmp_path / ".env").write_text("LEGACY_INPUT=two\n", encoding="utf-8")
        env_loader._apply_external_secret_sources(tmp_path)
        assert os.environ["LEGACY_RESULT_API_KEY"] == "one:two:3"

        _write_config("two")
        env_loader._apply_external_secret_sources(tmp_path)
    finally:
        reg._reset_registry_for_tests()

    assert os.environ["LEGACY_RESULT_API_KEY"] == "two:two:4"
    assert len(calls) == 4


def test_legacy_apply_removes_dropped_key_but_preserves_local_replacement(
    tmp_path, monkeypatch
):
    from agent.secret_sources import registry as reg
    from agent.secret_sources.base import FetchResult, SecretSource

    enabled = [True]
    (tmp_path / "config.yaml").write_text(
        "secrets:\n  legacy_test:\n    enabled: true\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("DROPPED_API_KEY", raising=False)
    monkeypatch.delenv("REPLACED_API_KEY", raising=False)

    class LegacyTestSource(SecretSource):
        name = "legacy_test"
        label = "Legacy test"

        def fetch(self, cfg, home_path):
            if enabled[0]:
                return FetchResult(
                    secrets={
                        "DROPPED_API_KEY": "external-drop",
                        "REPLACED_API_KEY": "external-replace",
                    }
                )
            return FetchResult()

    reg._reset_registry_for_tests()
    monkeypatch.setattr(reg, "_ensure_builtin_sources", lambda: None)
    assert reg.register_source(LegacyTestSource())
    try:
        env_loader._apply_external_secret_sources(tmp_path)
        assert os.environ["DROPPED_API_KEY"] == "external-drop"
        assert os.environ["REPLACED_API_KEY"] == "external-replace"

        # Simulate load_fabric_dotenv applying a newly configured local value
        # before the external refresh notices that the vault stopped returning
        # either key.
        os.environ["REPLACED_API_KEY"] = "local-replacement"
        env_loader.reset_secret_source_cache()
        assert env_loader.get_legacy_applied_secret_names(tmp_path) == {
            "DROPPED_API_KEY",
            "REPLACED_API_KEY",
        }
        enabled[0] = False
        (tmp_path / "config.yaml").write_text(
            "secrets:\n  legacy_test:\n    enabled: false\n",
            encoding="utf-8",
        )
        env_loader._apply_external_secret_sources(tmp_path)
    finally:
        reg._reset_registry_for_tests()

    assert "DROPPED_API_KEY" not in os.environ
    assert os.environ["REPLACED_API_KEY"] == "local-replacement"


def test_legacy_applied_names_outlive_ttl_until_successful_reconciliation(
    tmp_path, monkeypatch
):
    from agent.secret_sources import registry as reg
    from agent.secret_sources.base import FetchResult, SecretSource

    clock = [100.0]
    (tmp_path / "config.yaml").write_text(
        "secrets:\n"
        "  legacy_test:\n"
        "    enabled: true\n"
        "    cache_ttl_seconds: 10\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("DATABASE_URL", raising=False)

    class LegacyTestSource(SecretSource):
        name = "legacy_test"
        label = "Legacy test"

        def fetch(self, cfg, home_path):
            return FetchResult(secrets={"DATABASE_URL": "external-database"})

    monkeypatch.setattr(env_loader, "_secret_source_cache_now", lambda: clock[0])
    reg._reset_registry_for_tests()
    monkeypatch.setattr(reg, "_ensure_builtin_sources", lambda: None)
    assert reg.register_source(LegacyTestSource())
    try:
        env_loader._apply_external_secret_sources(tmp_path)
        assert env_loader.get_legacy_applied_secret_names(tmp_path) == {
            "DATABASE_URL"
        }

        clock[0] += 10.01
        assert env_loader.get_profile_secret_source_values(tmp_path) == {}
        assert env_loader.get_legacy_applied_secret_names(tmp_path) == {
            "DATABASE_URL"
        }

        (tmp_path / "config.yaml").write_text(
            "secrets:\n  legacy_test:\n    enabled: false\n",
            encoding="utf-8",
        )
        env_loader._apply_external_secret_sources(tmp_path)
    finally:
        reg._reset_registry_for_tests()

    assert "DATABASE_URL" not in os.environ
    assert env_loader.get_legacy_applied_secret_names(tmp_path) == set()


def test_reset_prevents_inflight_resolution_from_repopulating_cache(
    tmp_path, monkeypatch
):
    from agent.secret_sources import registry as reg
    from agent.secret_sources.base import FetchResult, SecretSource

    entered_fetch = threading.Event()
    release_fetch = threading.Event()
    calls = []
    (tmp_path / "config.yaml").write_text(
        "secrets:\n  scoped_test:\n    enabled: true\n",
        encoding="utf-8",
    )

    class ScopedTestSource(SecretSource):
        name = "scoped_test"
        label = "Scoped test"
        supports_scoped_environment = True

        def fetch(self, cfg, home_path):
            calls.append(home_path)
            if len(calls) == 1:
                entered_fetch.set()
                assert release_fetch.wait(timeout=5)
            return FetchResult(secrets={"RESULT_API_KEY": f"value-{len(calls)}"})

    reg._reset_registry_for_tests()
    monkeypatch.setattr(reg, "_ensure_builtin_sources", lambda: None)
    assert reg.register_source(ScopedTestSource())
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                env_loader.resolve_external_secret_sources,
                tmp_path,
            )
            assert entered_fetch.wait(timeout=5)
            env_loader.reset_secret_source_cache()
            release_fetch.set()
            stale_result = future.result(timeout=5)

        assert stale_result.values == {}
        assert stale_result.provenance == {}
        assert env_loader.get_profile_secret_source_values(tmp_path) == {}
        assert env_loader.get_profile_secret_source_provenance(tmp_path) == {}
        assert env_loader.get_secret_source("RESULT_API_KEY") is None

        fresh_result = env_loader.resolve_external_secret_sources(tmp_path)
    finally:
        release_fetch.set()
        reg._reset_registry_for_tests()

    assert fresh_result.values == {"RESULT_API_KEY": "value-2"}
    assert env_loader.get_profile_secret_source_values(tmp_path) == (
        fresh_result.values
    )
    assert len(calls) == 2


def test_profile_resolution_skips_unscoped_plugin_without_executing(
    tmp_path, monkeypatch
):
    from agent.secret_sources import registry as reg
    from agent.secret_sources.base import FetchResult, SecretSource

    class LegacySource(SecretSource):
        name = "legacy"
        label = "Legacy"

        def is_enabled(self, cfg):
            raise AssertionError("unsafe legacy is_enabled must not execute")

        def protected_env_vars(self, cfg):
            raise AssertionError("unsafe legacy protected hook must not execute")

        def fetch(self, cfg, home_path):
            raise AssertionError("unsafe legacy source must not execute")

    (tmp_path / "config.yaml").write_text(
        "secrets:\n  legacy:\n    enabled: true\n",
        encoding="utf-8",
    )
    reg._reset_registry_for_tests()
    monkeypatch.setattr(reg, "_ensure_builtin_sources", lambda: None)
    assert reg.register_source(LegacySource())
    try:
        resolution = env_loader.resolve_external_secret_sources(tmp_path)
    finally:
        reg._reset_registry_for_tests()

    assert resolution.values == {}
    assert resolution.provenance == {}
    assert resolution.report is not None
    assert "does not declare profile-scoped" in (
        resolution.report.sources[0].result.error
    )


def test_profile_resolution_keeps_managed_secret_immutable(tmp_path, monkeypatch):
    from agent.secret_sources import registry as reg
    from agent.secret_sources.base import FetchResult, SecretSource
    from fabric_cli import managed_scope

    managed = tmp_path / "managed"
    home = tmp_path / "profile"
    managed.mkdir()
    home.mkdir()
    (managed / ".env").write_text(
        "PINNED_API_KEY=managed-value\n",
        encoding="utf-8",
    )
    (home / "config.yaml").write_text(
        "secrets:\n  scoped_test:\n    enabled: true\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_MANAGED_DIR", str(managed))
    managed_scope.invalidate_managed_cache()

    class ScopedTestSource(SecretSource):
        name = "scoped_test"
        label = "Scoped test"
        supports_scoped_environment = True

        def override_existing(self, cfg):
            return True

        def fetch(self, cfg, home_path):
            return FetchResult(secrets={"PINNED_API_KEY": "vault-value"})

    reg._reset_registry_for_tests()
    monkeypatch.setattr(reg, "_ensure_builtin_sources", lambda: None)
    assert reg.register_source(ScopedTestSource())
    try:
        resolution = env_loader.resolve_external_secret_sources(home)
    finally:
        reg._reset_registry_for_tests()
        managed_scope.invalidate_managed_cache()

    assert resolution.values == {}
    assert "PINNED_API_KEY" in resolution.report.sources[0].skipped_protected


@pytest.mark.parametrize("trigger", ["reset", "force"])
@pytest.mark.parametrize("stale_layer", ["memory", "disk"])
def test_bundled_bitwarden_refresh_replaces_source_local_caches(
    tmp_path, monkeypatch, trigger, stale_layer
):
    """Aggregate reset/force must bypass BWS L1 and L2, then replace L2."""
    from agent.secret_sources import bitwarden as bw
    from agent.secret_sources import registry as reg

    (tmp_path / ".env").write_text(
        "BWS_ACCESS_TOKEN=stable-token\n", encoding="utf-8"
    )
    (tmp_path / "config.yaml").write_text(
        "secrets:\n"
        "  bitwarden:\n"
        "    enabled: true\n"
        "    project_id: stable-project\n"
        "    cache_ttl_seconds: 3600\n",
        encoding="utf-8",
    )
    calls = []
    current = ["value-1"]

    def _run_bws(*_args, **_kwargs):
        calls.append(current[0])
        return {"RESULT_API_KEY": current[0]}, []

    monkeypatch.setattr(bw, "find_bws", lambda **_kwargs: Path("/fake/bws"))
    monkeypatch.setattr(bw, "_run_bws_list", _run_bws)
    bw._reset_cache_for_tests(tmp_path)
    reg._reset_registry_for_tests()
    try:
        first = env_loader.resolve_external_secret_sources(tmp_path)
        assert first.values == {"RESULT_API_KEY": "value-1"}
        assert calls == ["value-1"]

        current[0] = "value-2"
        if stale_layer == "disk":
            bw._CACHE.clear()
        if trigger == "reset":
            # Reset must still reach source-local caches after the aggregate
            # value metadata has already expired/been evicted.
            with env_loader._SECRET_SOURCE_CACHE_LOCK:
                env_loader._evict_profile_secret_source_cache_locked(
                    str(tmp_path.resolve())
                )
            env_loader.reset_secret_source_cache()
            refreshed = env_loader.resolve_external_secret_sources(tmp_path)
        else:
            refreshed = env_loader.resolve_external_secret_sources(
                tmp_path, force=True
            )

        assert refreshed.values == {"RESULT_API_KEY": "value-2"}
        assert calls == ["value-1", "value-2"]

        # A forced refresh must replace the disk entry, not merely bypass it for
        # this one call.  Clear L1 and prove a normal direct read gets v2 from L2.
        bw._CACHE.clear()
        disk_values, _warnings = bw.fetch_bitwarden_secrets(
            access_token="stable-token",
            project_id="stable-project",
            binary=Path("/fake/bws"),
            cache_ttl_seconds=3600,
            home_path=tmp_path,
        )
        assert disk_values == {"RESULT_API_KEY": "value-2"}
        assert calls == ["value-1", "value-2"]
    finally:
        bw._reset_cache_for_tests(tmp_path)
        reg._reset_registry_for_tests()


@pytest.mark.parametrize("trigger", ["reset", "force"])
@pytest.mark.parametrize("stale_layer", ["memory", "disk"])
def test_bundled_onepassword_refresh_replaces_source_local_caches(
    tmp_path, monkeypatch, trigger, stale_layer
):
    """Aggregate reset/force must bypass 1Password L1/L2, then replace L2."""
    from agent.secret_sources import onepassword as op
    from agent.secret_sources import registry as reg

    reference = "op://Private/Test/value"
    (tmp_path / ".env").write_text(
        "OP_SERVICE_ACCOUNT_TOKEN=stable-token\n", encoding="utf-8"
    )
    (tmp_path / "config.yaml").write_text(
        "secrets:\n"
        "  onepassword:\n"
        "    enabled: true\n"
        "    cache_ttl_seconds: 3600\n"
        "    env:\n"
        f"      RESULT_API_KEY: {reference}\n",
        encoding="utf-8",
    )
    calls = []
    current = ["value-1"]

    def _run_op(*_args, **_kwargs):
        calls.append(current[0])
        return current[0]

    monkeypatch.setattr(op, "find_op", lambda _binary_path="": Path("/fake/op"))
    monkeypatch.setattr(op, "_run_op_read", _run_op)
    op._reset_cache_for_tests(tmp_path)
    reg._reset_registry_for_tests()
    try:
        first = env_loader.resolve_external_secret_sources(tmp_path)
        assert first.values == {"RESULT_API_KEY": "value-1"}
        assert calls == ["value-1"]

        current[0] = "value-2"
        if stale_layer == "disk":
            op._CACHE.clear()
        if trigger == "reset":
            with env_loader._SECRET_SOURCE_CACHE_LOCK:
                env_loader._evict_profile_secret_source_cache_locked(
                    str(tmp_path.resolve())
                )
            env_loader.reset_secret_source_cache()
            refreshed = env_loader.resolve_external_secret_sources(tmp_path)
        else:
            refreshed = env_loader.resolve_external_secret_sources(
                tmp_path, force=True
            )

        assert refreshed.values == {"RESULT_API_KEY": "value-2"}
        assert calls == ["value-1", "value-2"]

        op._CACHE.clear()
        disk_values, _warnings = op.fetch_onepassword_secrets(
            references={"RESULT_API_KEY": reference},
            token_env="OP_SERVICE_ACCOUNT_TOKEN",
            binary=Path("/fake/op"),
            cache_ttl_seconds=3600,
            home_path=tmp_path,
            environ={"OP_SERVICE_ACCOUNT_TOKEN": "stable-token"},
        )
        assert disk_values == {"RESULT_API_KEY": "value-2"}
        assert calls == ["value-1", "value-2"]
    finally:
        op._reset_cache_for_tests(tmp_path)
        reg._reset_registry_for_tests()


def test_force_refresh_signal_is_context_local_across_concurrent_homes(
    tmp_path, monkeypatch
):
    from agent.secret_sources import registry as reg
    from agent.secret_sources.base import FetchResult, SecretSource

    homes = [tmp_path / "one", tmp_path / "two"]
    for home in homes:
        home.mkdir()
        (home / "config.yaml").write_text(
            "secrets:\n  scoped_test:\n    enabled: true\n    marker: first\n",
            encoding="utf-8",
        )

    phase = ["prime"]
    barrier = threading.Barrier(2)
    observed = {}

    class ScopedTestSource(SecretSource):
        name = "scoped_test"
        label = "Scoped test"
        supports_scoped_environment = True

        def fetch(self, cfg, home_path):
            if phase[0] == "concurrent":
                barrier.wait(timeout=5)
                observed[home_path.name] = reg.get_resolution_force_refresh()
            return FetchResult(secrets={"RESULT_API_KEY": str(cfg["marker"])})

    reg._reset_registry_for_tests()
    monkeypatch.setattr(reg, "_ensure_builtin_sources", lambda: None)
    assert reg.register_source(ScopedTestSource())
    try:
        for home in homes:
            env_loader.resolve_external_secret_sources(home)

        # Force home one. Invalidate only home two's aggregate via a real config
        # content change so it fetches concurrently without a force request.
        (homes[1] / "config.yaml").write_text(
            "secrets:\n  scoped_test:\n    enabled: true\n    marker: second\n",
            encoding="utf-8",
        )
        phase[0] = "concurrent"
        with ThreadPoolExecutor(max_workers=2) as pool:
            forced = pool.submit(
                env_loader.resolve_external_secret_sources,
                homes[0],
                force=True,
            )
            normal = pool.submit(env_loader.resolve_external_secret_sources, homes[1])
            assert forced.result(timeout=5).values == {
                "RESULT_API_KEY": "first"
            }
            assert normal.result(timeout=5).values == {
                "RESULT_API_KEY": "second"
            }
    finally:
        reg._reset_registry_for_tests()

    assert observed == {"one": True, "two": False}
