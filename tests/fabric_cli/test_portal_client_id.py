from __future__ import annotations

from types import SimpleNamespace


def test_portal_login_forwards_registered_client_id(monkeypatch):
    from fabric_cli import portal_cli
    from fabric_cli import setup as setup_mod

    args = SimpleNamespace(client_id="registered-nous-client")
    captured = {}

    monkeypatch.setattr(portal_cli, "load_config", lambda: {"model": {}})

    def _capture(config, *, args=None):
        captured["config"] = config
        captured["args"] = args

    monkeypatch.setattr(setup_mod, "_run_portal_one_shot", _capture)

    assert portal_cli._cmd_login(args) == 0
    assert captured == {"config": {"model": {}}, "args": args}


def test_portal_setup_forwards_registered_client_id_to_model_flow(monkeypatch):
    from fabric_cli import main as main_mod
    from fabric_cli import setup as setup_mod

    args = SimpleNamespace(client_id="registered-nous-client")
    config = {"model": {}}
    captured = {}

    def _capture(model_config, current_model="", args=None):
        captured["config"] = model_config
        captured["current_model"] = current_model
        captured["args"] = args

    monkeypatch.setattr(main_mod, "_model_flow_nous", _capture)
    monkeypatch.setattr("fabric_cli.config.load_config", lambda: config)

    setup_mod._run_portal_one_shot(config, args=args)

    assert captured == {
        "config": config,
        "current_model": "",
        "args": args,
    }
