from types import SimpleNamespace

import pytest

from fabric_cli import moa_cmd
from fabric_cli.moa_cmd import build_subscription_moa_presets, cmd_moa


CATALOG = {
    "openai-codex": {"gpt-5.5", "gpt-5.6-sol", "gpt-5.6-terra"},
    "xai-oauth": {"grok-4.3", "grok-4.5", "grok-composer-2.5-fast"},
}


def test_model_options_forwards_live_refresh_to_payload(monkeypatch):
    context = object()
    seen = {}
    monkeypatch.setattr(moa_cmd, "load_picker_context", lambda: context)

    def fake_payload(received_context, **kwargs):
        seen["context"] = received_context
        seen.update(kwargs)
        return {
            "providers": [
                {
                    "slug": "openai-codex",
                    "models": [{"id": "gpt-5.6-sol"}],
                }
            ]
        }

    monkeypatch.setattr(moa_cmd, "build_models_payload", fake_payload)

    assert moa_cmd._model_options(refresh_models=True)[0]["slug"] == "openai-codex"
    assert seen["context"] is context
    assert seen["refresh"] is True


def test_subscription_catalog_uses_only_live_entitlement_helpers(monkeypatch):
    monkeypatch.setattr(moa_cmd, "_live_codex_model_ids", lambda: {"gpt-live"})
    monkeypatch.setattr(moa_cmd, "_live_xai_model_ids", lambda: {"grok-live"})

    assert moa_cmd._subscription_catalog() == {
        "openai-codex": {"gpt-live"},
        "xai-oauth": {"grok-live"},
    }


def test_live_xai_catalog_probes_hidden_oauth_models(monkeypatch):
    import httpx

    calls = []

    class FakeResponse:
        def __init__(self, status_code, payload=None):
            self.status_code = status_code
            self._payload = payload or {}

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *, headers, timeout):
            assert headers == {"Authorization": "Bearer live-token"}
            assert timeout == 15.0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, url):
            calls.append(url)
            if url.endswith("/models"):
                return FakeResponse(200, {"data": [{"id": "grok-4.5"}]})
            if url.endswith("/models/grok-composer-2.5-fast"):
                return FakeResponse(200, {"id": "grok-composer-2.5-fast"})
            # Optional preferred candidates can be unentitled even when both
            # required lanes are available; a per-model 403 is candidate-local.
            return FakeResponse(403)

    monkeypatch.setattr(
        "fabric_cli.auth.resolve_xai_oauth_runtime_credentials",
        lambda **_kwargs: {
            "base_url": "https://api.x.ai/v1",
            "api_key": "live-token",
        },
    )
    monkeypatch.setattr(httpx, "Client", FakeClient)

    models = moa_cmd._live_xai_model_ids()

    assert models == {"grok-4.5", "grok-composer-2.5-fast"}
    assert "https://api.x.ai/v1/models/grok-composer-2.5-fast" in calls


def test_live_xai_catalog_fails_closed_when_collection_refresh_fails(monkeypatch):
    import httpx

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, _url):
            return type("Response", (), {"status_code": 503})()

    monkeypatch.setattr(
        "fabric_cli.auth.resolve_xai_oauth_runtime_credentials",
        lambda **_kwargs: {
            "base_url": "https://api.x.ai/v1",
            "api_key": "live-token",
        },
    )
    monkeypatch.setattr(httpx, "Client", FakeClient)

    with pytest.raises(RuntimeError, match="Could not refresh the live xAI"):
        moa_cmd._live_xai_model_ids()


def _args(**overrides):
    values = {
        "moa_command": "bootstrap",
        "template": "subscriptions",
        "dry_run": False,
        "force": False,
        "keep_default": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_build_subscription_presets_selects_best_live_models():
    presets, chosen = build_subscription_moa_presets(CATALOG)

    assert chosen == {
        "gpt_aggregator": "gpt-5.6-sol",
        "gpt_reference": "gpt-5.6-terra",
        "grok_critic": "grok-4.5",
        "grok_worker": "grok-composer-2.5-fast",
    }
    assert set(presets) == {"subscription-plan", "subscription-review"}
    for preset in presets.values():
        assert preset["fanout"] == "user_turn"
        assert "reference_max_tokens" not in preset
        assert preset["aggregator"]["reasoning_effort"] == "high"
        assert all(slot.get("role") for slot in preset["reference_models"])


def test_build_subscription_presets_omits_unsupported_grok_effort():
    presets, chosen = build_subscription_moa_presets(
        {
            "openai-codex": {"gpt-5.5", "gpt-5.4"},
            "xai-oauth": {
                "grok-4.20-0309-reasoning",
                "grok-composer-2.5-fast",
            },
        }
    )

    assert chosen["grok_critic"] == "grok-4.20-0309-reasoning"
    for preset in presets.values():
        grok_slot = preset["reference_models"][0]
        assert grok_slot["model"] == "grok-4.20-0309-reasoning"
        assert "reasoning_effort" not in grok_slot


def test_build_subscription_presets_fails_closed_when_a_provider_is_missing():
    with pytest.raises(RuntimeError, match="xAI subscription models are unavailable"):
        build_subscription_moa_presets({"openai-codex": {"gpt-5.6-sol"}})


def test_build_subscription_presets_never_invents_unavailable_model_ids():
    with pytest.raises(RuntimeError, match="No supported model found for GPT aggregator"):
        build_subscription_moa_presets(
            {
                "openai-codex": {"some-future-model"},
                "xai-oauth": {"grok-4.5", "grok-composer-2.5-fast"},
            }
        )


def test_bootstrap_dry_run_does_not_save(monkeypatch, capsys):
    monkeypatch.setattr("fabric_cli.moa_cmd.load_config", lambda: {})
    monkeypatch.setattr("fabric_cli.moa_cmd._subscription_catalog", lambda **_kwargs: CATALOG)
    saved = []
    monkeypatch.setattr("fabric_cli.moa_cmd.save_config", lambda config: saved.append(config))

    cmd_moa(_args(dry_run=True))

    assert saved == []
    output = capsys.readouterr().out
    assert "Would install subscription-backed MoA presets" in output
    assert "Dry run only; config was not changed." in output


def test_bootstrap_refuses_to_clobber_managed_names_without_force(monkeypatch):
    monkeypatch.setattr(
        "fabric_cli.moa_cmd.load_config",
        lambda: {
            "moa": {
                "default_preset": "subscription-plan",
                "presets": {
                    "subscription-plan": {
                        "reference_models": [
                            {"provider": "openai-codex", "model": "user-custom-model"}
                        ]
                    }
                },
            }
        },
    )
    monkeypatch.setattr("fabric_cli.moa_cmd._subscription_catalog", lambda **_kwargs: CATALOG)
    monkeypatch.setattr(
        "fabric_cli.moa_cmd.save_config",
        lambda _config: pytest.fail("conflicting bootstrap must not save"),
    )

    with pytest.raises(SystemExit, match="Refusing to overwrite existing MoA preset"):
        cmd_moa(_args())


def test_bootstrap_force_installs_both_presets_and_preserves_others(monkeypatch):
    monkeypatch.setattr(
        "fabric_cli.moa_cmd.load_config",
        lambda: {
            "moa": {
                "default_preset": "custom",
                "presets": {
                    "custom": {
                        "reference_models": [
                            {"provider": "openai-codex", "model": "gpt-5.5"}
                        ]
                    },
                    "subscription-plan": {
                        "reference_models": [
                            {"provider": "openai-codex", "model": "old-model"}
                        ]
                    },
                },
            }
        },
    )
    monkeypatch.setattr("fabric_cli.moa_cmd._subscription_catalog", lambda **_kwargs: CATALOG)
    saved = []
    monkeypatch.setattr("fabric_cli.moa_cmd.save_config", lambda config: saved.append(config))

    cmd_moa(_args(force=True))

    assert len(saved) == 1
    moa = saved[0]["moa"]
    assert moa["default_preset"] == "subscription-plan"
    assert set(moa["presets"]) == {"custom", "subscription-plan", "subscription-review"}
    assert moa["presets"]["subscription-plan"]["fanout"] == "user_turn"
    assert moa["presets"]["subscription-review"]["reference_max_tokens"] is None
