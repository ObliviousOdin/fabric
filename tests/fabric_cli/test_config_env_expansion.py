"""Tests for ${ENV_VAR} substitution in config.yaml values."""

import os

import pytest
from fabric_cli.config import _expand_env_vars, get_env_value, load_config


class TestExpandEnvVars:
    def test_simple_substitution(self):
        with pytest.MonkeyPatch().context() as mp:
            mp.setenv("MY_KEY", "secret123")
            assert _expand_env_vars("${MY_KEY}") == "secret123"

    def test_missing_var_kept_verbatim(self):
        with pytest.MonkeyPatch().context() as mp:
            mp.delenv("UNDEFINED_VAR_XYZ", raising=False)
            assert _expand_env_vars("${UNDEFINED_VAR_XYZ}") == "${UNDEFINED_VAR_XYZ}"

    def test_no_placeholder_unchanged(self):
        assert _expand_env_vars("plain-value") == "plain-value"

    def test_dict_recursive(self):
        with pytest.MonkeyPatch().context() as mp:
            mp.setenv("TOKEN", "tok-abc")
            result = _expand_env_vars({"key": "${TOKEN}", "other": "literal"})
            assert result == {"key": "tok-abc", "other": "literal"}

    def test_nested_dict(self):
        with pytest.MonkeyPatch().context() as mp:
            mp.setenv("API_KEY", "sk-xyz")
            result = _expand_env_vars({"model": {"api_key": "${API_KEY}"}})
            assert result["model"]["api_key"] == "sk-xyz"

    def test_list_items(self):
        with pytest.MonkeyPatch().context() as mp:
            mp.setenv("VAL", "hello")
            result = _expand_env_vars(["${VAL}", "literal", 42])
            assert result == ["hello", "literal", 42]

    def test_non_string_values_untouched(self):
        assert _expand_env_vars(42) == 42
        assert _expand_env_vars(3.14) == 3.14
        assert _expand_env_vars(True) is True
        assert _expand_env_vars(None) is None

    def test_multiple_placeholders_in_one_string(self):
        with pytest.MonkeyPatch().context() as mp:
            mp.setenv("HOST", "localhost")
            mp.setenv("PORT", "5432")
            assert _expand_env_vars("${HOST}:${PORT}") == "localhost:5432"

    def test_dict_keys_not_expanded(self):
        with pytest.MonkeyPatch().context() as mp:
            mp.setenv("KEY", "value")
            result = _expand_env_vars({"${KEY}": "no-expand-key"})
            assert "${KEY}" in result

    def test_active_profile_scope_wins_over_process_environment(self, monkeypatch):
        from agent.secret_scope import reset_secret_scope, set_secret_scope

        monkeypatch.setenv("PROFILE_CONFIG_TOKEN", "launch-token")
        token = set_secret_scope({"PROFILE_CONFIG_TOKEN": "worker-token"})
        try:
            assert _expand_env_vars("${PROFILE_CONFIG_TOKEN}") == "worker-token"
        finally:
            reset_secret_scope(token)

        assert _expand_env_vars("${PROFILE_CONFIG_TOKEN}") == "launch-token"

    def test_active_profile_scope_missing_key_never_falls_back(self, monkeypatch):
        from agent.secret_scope import reset_secret_scope, set_secret_scope

        monkeypatch.setenv("PROFILE_CONFIG_TOKEN", "launch-token")
        token = set_secret_scope({})
        try:
            assert _expand_env_vars("${PROFILE_CONFIG_TOKEN}") == (
                "${PROFILE_CONFIG_TOKEN}"
            )
            assert get_env_value("PROFILE_CONFIG_TOKEN") is None
        finally:
            reset_secret_scope(token)

    def test_unscoped_multiplex_read_fails_closed(self, monkeypatch):
        from agent.secret_scope import (
            UnscopedSecretError,
            set_multiplex_active,
        )

        monkeypatch.setenv("PROFILE_CONFIG_TOKEN", "launch-token")
        set_multiplex_active(True)
        try:
            with pytest.raises(UnscopedSecretError):
                _expand_env_vars("${PROFILE_CONFIG_TOKEN}")
            with pytest.raises(UnscopedSecretError):
                get_env_value("PROFILE_CONFIG_TOKEN")
        finally:
            set_multiplex_active(False)

    def test_home_template_uses_context_local_profile_home(
        self, tmp_path, monkeypatch
    ):
        from fabric_constants import (
            reset_fabric_home_override,
            set_fabric_home_override,
        )

        worker_home = tmp_path / "profiles" / "worker"
        monkeypatch.setenv("FABRIC_HOME", str(tmp_path / "launch"))
        token = set_fabric_home_override(worker_home)
        try:
            assert _expand_env_vars("${FABRIC_HOME}/memory.db") == (
                f"{worker_home}/memory.db"
            )
        finally:
            reset_fabric_home_override(token)


class TestLoadConfigExpansion:
    def test_load_config_expands_env_vars(self, tmp_path, monkeypatch):
        config_yaml = (
            "model:\n"
            "  api_key: ${GOOGLE_API_KEY}\n"
            "platforms:\n"
            "  telegram:\n"
            "    token: ${TELEGRAM_BOT_TOKEN}\n"
            "plain: no-substitution\n"
        )
        config_file = tmp_path / "config.yaml"
        config_file.write_text(config_yaml)

        monkeypatch.setenv("GOOGLE_API_KEY", "gsk-test-key")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "1234567:ABC-token")
        # Patch the imported function's own globals. Other tests may reload
        # fabric_cli.config, making string-target monkeypatches hit a different
        # module object than this collection-time imported load_config().
        monkeypatch.setitem(load_config.__globals__, "get_config_path", lambda: config_file)

        config = load_config()

        assert config["model"]["api_key"] == "gsk-test-key"
        assert config["platforms"]["telegram"]["token"] == "1234567:ABC-token"
        assert config["plain"] == "no-substitution"

    def test_load_config_unresolved_kept_verbatim(self, tmp_path, monkeypatch):
        config_yaml = "model:\n  api_key: ${NOT_SET_XYZ_123}\n"
        config_file = tmp_path / "config.yaml"
        config_file.write_text(config_yaml)

        monkeypatch.delenv("NOT_SET_XYZ_123", raising=False)
        monkeypatch.setitem(load_config.__globals__, "get_config_path", lambda: config_file)

        config = load_config()

        assert config["model"]["api_key"] == "${NOT_SET_XYZ_123}"


class TestLoadConfigCacheEnvStaleness:
    """The load_config() cache must not pin expansions made against a stale
    environment (#58514): a load before load_fabric_dotenv() runs, or an env
    var rotated in-process, must not keep serving the old expansion."""

    def test_env_var_appearing_after_first_load_invalidates_cache(self, tmp_path, monkeypatch):
        config_yaml = "auxiliary:\n  vision:\n    api_key: ${LATE_DOTENV_KEY_58514}\n"
        config_file = tmp_path / "config.yaml"
        config_file.write_text(config_yaml)

        monkeypatch.delenv("LATE_DOTENV_KEY_58514", raising=False)
        monkeypatch.setitem(load_config.__globals__, "get_config_path", lambda: config_file)

        # First load happens before the var exists (pre-dotenv): literal kept.
        assert load_config()["auxiliary"]["vision"]["api_key"] == "${LATE_DOTENV_KEY_58514}"

        # .env load brings the var in — same file mtime/size, env changed.
        monkeypatch.setenv("LATE_DOTENV_KEY_58514", "nvapi-real")
        assert load_config()["auxiliary"]["vision"]["api_key"] == "nvapi-real"

    def test_env_var_rotation_invalidates_cache(self, tmp_path, monkeypatch):
        config_yaml = "providers:\n  mistral:\n    api_key: ${ROTATED_KEY_58514}\n"
        config_file = tmp_path / "config.yaml"
        config_file.write_text(config_yaml)

        monkeypatch.setenv("ROTATED_KEY_58514", "key-v1")
        monkeypatch.setitem(load_config.__globals__, "get_config_path", lambda: config_file)

        assert load_config()["providers"]["mistral"]["api_key"] == "key-v1"

        monkeypatch.setenv("ROTATED_KEY_58514", "key-v2")
        assert load_config()["providers"]["mistral"]["api_key"] == "key-v2"

    def test_unchanged_env_still_serves_cache(self, tmp_path, monkeypatch):
        config_yaml = "providers:\n  mistral:\n    api_key: ${STABLE_KEY_58514}\n"
        config_file = tmp_path / "config.yaml"
        config_file.write_text(config_yaml)

        monkeypatch.setenv("STABLE_KEY_58514", "key-stable")
        monkeypatch.setitem(load_config.__globals__, "get_config_path", lambda: config_file)

        load_config()
        # load_config_readonly() returns the cached object itself, so object
        # identity across calls proves the cache-hit path was taken (a rebuild
        # would produce a fresh dict).
        readonly = load_config.__globals__["load_config_readonly"]
        first = readonly()
        second = readonly()

        assert first is second
        assert first["providers"]["mistral"]["api_key"] == "key-stable"

    def test_profile_scope_rotation_invalidates_cached_expansion(
        self, tmp_path, monkeypatch
    ):
        from agent.secret_scope import reset_secret_scope, set_secret_scope

        config_file = tmp_path / "config.yaml"
        config_file.write_text("mcp_servers:\n  routed:\n    token: ${ROUTED_TOKEN}\n")
        monkeypatch.setenv("ROUTED_TOKEN", "launch-token")
        monkeypatch.setitem(load_config.__globals__, "get_config_path", lambda: config_file)

        first_token = set_secret_scope({"ROUTED_TOKEN": "worker-a"})
        try:
            assert load_config()["mcp_servers"]["routed"]["token"] == "worker-a"
        finally:
            reset_secret_scope(first_token)

        second_token = set_secret_scope({"ROUTED_TOKEN": "worker-b"})
        try:
            assert load_config()["mcp_servers"]["routed"]["token"] == "worker-b"
        finally:
            reset_secret_scope(second_token)

    def test_managed_policy_root_is_part_of_cache_identity(
        self, tmp_path, monkeypatch
    ):
        """Equal stat tuples from different managed roots cannot alias."""
        from fabric_cli import managed_scope

        config_file = tmp_path / "config.yaml"
        config_file.write_text("timezone: User/Zone\n", encoding="utf-8")
        monkeypatch.setitem(
            load_config.__globals__,
            "get_config_path",
            lambda: config_file,
        )

        managed_a = tmp_path / "managed-a"
        managed_b = tmp_path / "managed-b"
        managed_a.mkdir()
        managed_b.mkdir()
        policy_a = managed_a / "config.yaml"
        policy_b = managed_b / "config.yaml"
        policy_a.write_text("timezone: Mars/One\n", encoding="utf-8")
        policy_b.write_text("timezone: Mars/Two\n", encoding="utf-8")
        assert policy_a.stat().st_size == policy_b.stat().st_size
        same_ns = 1_700_000_000_000_000_000
        os.utime(policy_a, ns=(same_ns, same_ns))
        os.utime(policy_b, ns=(same_ns, same_ns))

        monkeypatch.setenv("FABRIC_MANAGED_DIR", str(managed_a))
        managed_scope.invalidate_managed_cache()
        assert load_config()["timezone"] == "Mars/One"

        monkeypatch.setenv("FABRIC_MANAGED_DIR", str(managed_b))
        managed_scope.invalidate_managed_cache()
        assert load_config()["timezone"] == "Mars/Two"


class TestLoadCliConfigExpansion:
    """Verify that load_cli_config() also expands ${VAR} references."""

    def test_cli_config_expands_auxiliary_api_key(self, tmp_path, monkeypatch):
        config_yaml = (
            "auxiliary:\n"
            "  vision:\n"
            "    api_key: ${TEST_VISION_KEY_XYZ}\n"
        )
        config_file = tmp_path / "config.yaml"
        config_file.write_text(config_yaml)

        monkeypatch.setenv("TEST_VISION_KEY_XYZ", "vis-key-123")
        # Patch the fabric home so load_cli_config finds our test config
        monkeypatch.setattr("cli._fabric_home", tmp_path)

        from cli import load_cli_config
        config = load_cli_config()

        assert config["auxiliary"]["vision"]["api_key"] == "vis-key-123"

    def test_cli_config_unresolved_kept_verbatim(self, tmp_path, monkeypatch):
        config_yaml = (
            "auxiliary:\n"
            "  vision:\n"
            "    api_key: ${UNSET_CLI_VAR_ABC}\n"
        )
        config_file = tmp_path / "config.yaml"
        config_file.write_text(config_yaml)

        monkeypatch.delenv("UNSET_CLI_VAR_ABC", raising=False)
        monkeypatch.setattr("cli._fabric_home", tmp_path)

        from cli import load_cli_config
        config = load_cli_config()

        assert config["auxiliary"]["vision"]["api_key"] == "${UNSET_CLI_VAR_ABC}"
