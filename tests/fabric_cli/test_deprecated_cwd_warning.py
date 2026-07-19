"""Tests for the deprecated cwd environment warning."""


class TestDeprecatedCwdWarning:
    def test_messaging_cwd_triggers_warning(self, monkeypatch, capsys):
        monkeypatch.setenv("MESSAGING_CWD", "/some/path")
        monkeypatch.delenv("TERMINAL_CWD", raising=False)

        from fabric_cli.config import warn_deprecated_cwd_env_vars

        warn_deprecated_cwd_env_vars(config={})
        captured = capsys.readouterr()
        assert "MESSAGING_CWD" in captured.err
        assert "deprecated" in captured.err.lower()
        assert "config.yaml" in captured.err

    def test_terminal_cwd_warns_for_placeholder_config(self, monkeypatch, capsys):
        monkeypatch.setenv("TERMINAL_CWD", "/project")
        monkeypatch.delenv("MESSAGING_CWD", raising=False)

        from fabric_cli.config import warn_deprecated_cwd_env_vars

        warn_deprecated_cwd_env_vars(config={"terminal": {"cwd": "."}})
        assert "TERMINAL_CWD" in capsys.readouterr().err

    def test_explicit_config_suppresses_terminal_cwd_warning(self, monkeypatch, capsys):
        monkeypatch.setenv("TERMINAL_CWD", "/project")
        monkeypatch.delenv("MESSAGING_CWD", raising=False)

        from fabric_cli.config import warn_deprecated_cwd_env_vars

        warn_deprecated_cwd_env_vars(config={"terminal": {"cwd": "/project"}})
        assert "TERMINAL_CWD" not in capsys.readouterr().err

    def test_clean_env_is_silent(self, monkeypatch, capsys):
        monkeypatch.delenv("MESSAGING_CWD", raising=False)
        monkeypatch.delenv("TERMINAL_CWD", raising=False)

        from fabric_cli.config import warn_deprecated_cwd_env_vars

        warn_deprecated_cwd_env_vars(config={})
        assert capsys.readouterr().err == ""
