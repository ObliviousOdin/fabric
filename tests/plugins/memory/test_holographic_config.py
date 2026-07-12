"""Configuration contracts for the bundled Holographic memory provider."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from plugins.memory.holographic import HolographicMemoryProvider


@pytest.mark.parametrize("disabled", [False, "false", "0", "no", "off", ""])
def test_auto_extract_false_values_do_not_run_extraction(disabled):
    provider = HolographicMemoryProvider(config={"auto_extract": disabled})
    provider._store = object()
    extracted = []
    provider._auto_extract_facts = lambda messages: extracted.append(messages)

    provider.on_session_end([{"role": "user", "content": "remember this"}])

    assert extracted == []


@pytest.mark.parametrize("enabled", [True, "true", "1", "yes", "on"])
def test_auto_extract_true_values_run_once(enabled):
    provider = HolographicMemoryProvider(config={"auto_extract": enabled})
    provider._store = object()
    extracted = []
    messages = [{"role": "user", "content": "remember this"}]
    provider._auto_extract_facts = lambda value: extracted.append(value)

    provider.on_session_end(messages)

    assert extracted == [messages]


def test_save_config_uses_fail_closed_atomic_config_writer(tmp_path, monkeypatch):
    from fabric_cli import config as config_module

    config_path = tmp_path / "config.yaml"
    config_path.write_text("display:\n  skin: fabric\n", encoding="utf-8")
    writes = []

    def capture_write(path: Path, data: dict, **kwargs):
        writes.append((path, data, kwargs))

    monkeypatch.setattr(config_module, "atomic_config_write", capture_write)
    provider = HolographicMemoryProvider(config={})

    provider.save_config({"auto_extract": "false"}, tmp_path)

    assert writes == [
        (
            config_path,
            {
                "display": {"skin": "fabric"},
                "plugins": {
                    "hermes-memory-store": {"auto_extract": "false"}
                },
            },
            {"sort_keys": False},
        )
    ]


def test_save_config_preserves_unrelated_settings(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("display:\n  skin: fabric\n", encoding="utf-8")
    provider = HolographicMemoryProvider(config={})

    provider.save_config(
        {"auto_extract": "false", "default_trust": "0.7"},
        tmp_path,
    )

    assert yaml.safe_load(config_path.read_text(encoding="utf-8")) == {
        "display": {"skin": "fabric"},
        "plugins": {
            "hermes-memory-store": {
                "auto_extract": "false",
                "default_trust": "0.7",
            }
        },
    }


def test_save_config_propagates_atomic_write_failure(tmp_path, monkeypatch):
    from fabric_cli import config as config_module

    original = "display:\n  skin: fabric\n"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(original, encoding="utf-8")

    def fail_write(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(config_module, "atomic_config_write", fail_write)
    provider = HolographicMemoryProvider(config={})

    with pytest.raises(OSError, match="disk full"):
        provider.save_config({"auto_extract": "true"}, tmp_path)

    assert config_path.read_text(encoding="utf-8") == original


def test_save_config_rejects_non_mapping_yaml_without_overwrite(tmp_path):
    original = "- not\n- a\n- mapping\n"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(original, encoding="utf-8")
    provider = HolographicMemoryProvider(config={})

    with pytest.raises(RuntimeError, match="mapping"):
        provider.save_config({"auto_extract": "true"}, tmp_path)

    assert yaml.safe_load(config_path.read_text(encoding="utf-8")) == [
        "not",
        "a",
        "mapping",
    ]
