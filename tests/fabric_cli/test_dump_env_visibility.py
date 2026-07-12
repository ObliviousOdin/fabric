"""`hermes debug` must not report a shell-only API key as plainly "set".

The dump reads ``os.getenv`` — the invoking terminal's environment — but the
managed backends (launchd / systemd / the desktop-spawned ``serve`` process)
load credentials from ``~/.hermes/.env``, not the login shell. A key exported
in the shell but absent from ``.env`` is invisible to the backend, yet the dump
used to print a bare "set", sending support down a phantom "the key is
configured" path (the real cause behind gated tools like ``web_search`` going
missing on Desktop). The dump now flags that mismatch.
"""

from pathlib import Path
from types import SimpleNamespace


def _api_key_line(out: str, label: str) -> str:
    for line in out.splitlines():
        if line.strip().startswith(f"{label} "):
            return line
    raise AssertionError(f"no '{label}' api_keys line in dump output:\n{out}")


def test_dump_flags_shell_only_key_not_in_dotenv(monkeypatch, capsys, tmp_path):
    from fabric_cli import dump
    from fabric_cli.config import get_fabric_home

    monkeypatch.setattr(dump, "get_project_root", lambda: tmp_path / "noproject")

    home = get_fabric_home()
    home.mkdir(parents=True, exist_ok=True)
    # .env has some OTHER key but NOT firecrawl.
    (home / ".env").write_text("OPENROUTER_API_KEY=sk-or-xxxx\n")
    # firecrawl is exported in the (test) shell only.
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-shell-only")

    dump.run_dump(SimpleNamespace(show_keys=False))

    line = _api_key_line(capsys.readouterr().out, "firecrawl")
    assert "set" in line
    assert "shell only" in line
    assert ".env" in line


def test_dump_does_not_flag_key_present_in_dotenv(monkeypatch, capsys, tmp_path):
    from fabric_cli import dump
    from fabric_cli.config import get_fabric_home

    monkeypatch.setattr(dump, "get_project_root", lambda: tmp_path / "noproject")

    home = get_fabric_home()
    home.mkdir(parents=True, exist_ok=True)
    (home / ".env").write_text("FIRECRAWL_API_KEY=fc-in-dotenv\n")
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-in-dotenv")

    dump.run_dump(SimpleNamespace(show_keys=False))

    line = _api_key_line(capsys.readouterr().out, "firecrawl")
    assert "set" in line
    assert "shell only" not in line


def test_dump_leaves_unset_key_untouched(monkeypatch, capsys, tmp_path):
    from fabric_cli import dump
    from fabric_cli.config import get_fabric_home

    monkeypatch.setattr(dump, "get_project_root", lambda: tmp_path / "noproject")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    home = get_fabric_home()
    home.mkdir(parents=True, exist_ok=True)
    (home / ".env").write_text("OPENROUTER_API_KEY=sk-or-xxxx\n")

    dump.run_dump(SimpleNamespace(show_keys=False))

    line = _api_key_line(capsys.readouterr().out, "tavily")
    assert "not set" in line
    assert "shell only" not in line


def _run_curated_dump(monkeypatch, capsys, tmp_path, config=None) -> str:
    from fabric_cli import dump

    home = tmp_path / ".fabric"
    home.mkdir(exist_ok=True)
    (home / ".env").write_text("", encoding="utf-8")

    monkeypatch.setattr(dump, "get_fabric_home", lambda: home)
    monkeypatch.setattr(dump, "get_env_path", lambda: home / ".env")
    monkeypatch.setattr(dump, "get_project_root", lambda: tmp_path / "noproject")
    monkeypatch.setattr(dump, "display_fabric_home", lambda: "~/.fabric")
    monkeypatch.setattr(dump, "load_fabric_dotenv", lambda **kwargs: None)
    monkeypatch.setattr(
        dump,
        "load_config",
        lambda: config if config is not None else {"toolsets": ["hermes-cli"]},
    )
    monkeypatch.setattr(dump, "_gateway_status", lambda: "stopped")

    dump.run_dump(SimpleNamespace(show_keys=False))
    return capsys.readouterr().out


def test_dump_uses_fabric_labels_and_curated_provider_credentials(
    monkeypatch, capsys, tmp_path
):
    monkeypatch.delenv("FABRIC_CAPABILITY_CATALOG", raising=False)
    monkeypatch.delenv("FABRIC_MODEL_PROVIDERS", raising=False)

    out = _run_curated_dump(monkeypatch, capsys, tmp_path)

    assert "--- fabric dump ---" in out
    assert "--- hermes dump ---" not in out
    assert "fabric_home:      ~/.fabric" in out
    assert "hermes_home:" not in out
    assert _api_key_line(out, "openai")
    assert _api_key_line(out, "xai")
    assert _api_key_line(out, "openrouter")
    assert _api_key_line(out, "anthropic")
    assert "nous " not in out
    assert "toolsets:           fabric-core" in out
    assert "toolsets:           hermes-cli" not in out


def test_dump_legacy_catalog_restores_hidden_provider_credentials(
    monkeypatch, capsys, tmp_path
):
    monkeypatch.setenv("FABRIC_CAPABILITY_CATALOG", "0")
    monkeypatch.delenv("FABRIC_MODEL_PROVIDERS", raising=False)

    out = _run_curated_dump(monkeypatch, capsys, tmp_path)

    assert _api_key_line(out, "openrouter")
    assert _api_key_line(out, "anthropic")
    assert _api_key_line(out, "nous")


def test_dump_neutralizes_preserved_hidden_model_and_config_overrides(
    monkeypatch, capsys, tmp_path
):
    monkeypatch.delenv("FABRIC_CAPABILITY_CATALOG", raising=False)
    monkeypatch.delenv("FABRIC_MODEL_PROVIDERS", raising=False)
    config = {
        "model": {"provider": "nous", "default": "nous/hermes-4"},
        "toolsets": ["hermes-cli", "web"],
        "fallback_providers": [
            {"provider": "nous", "model": "nous/hermes-4"},
            {"provider": "xai", "model": "grok-4.5"},
        ],
    }

    out = _run_curated_dump(monkeypatch, capsys, tmp_path, config=config)

    assert "model:            (legacy model configured)" in out
    assert "provider:         (legacy provider configured)" in out
    assert "['fabric-core', 'web']" in out
    assert "(legacy provider configured)" in out
    assert "grok-4.5" in out
    assert "nous/hermes-4" not in out
    assert "hermes-cli" not in out


def test_dump_provider_override_restores_preserved_model_and_fallback(
    monkeypatch, capsys, tmp_path
):
    monkeypatch.delenv("FABRIC_CAPABILITY_CATALOG", raising=False)
    monkeypatch.setenv("FABRIC_MODEL_PROVIDERS", "nous")
    config = {
        "model": {"provider": "nous", "default": "nous/hermes-4"},
        "fallback_providers": [
            {"provider": "nous", "model": "nous/hermes-4"},
        ],
    }

    out = _run_curated_dump(monkeypatch, capsys, tmp_path, config=config)

    assert "model:            nous/hermes-4" in out
    assert "provider:         nous" in out
    assert "fallback_providers: [{'provider': 'nous', 'model': 'nous/hermes-4'}]" in out
