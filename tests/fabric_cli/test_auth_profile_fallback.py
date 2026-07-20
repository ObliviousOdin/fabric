"""Tests for cross-profile auth fallback.

When ``FABRIC_HOME`` points to a named profile, ``read_credential_pool()``
and ``get_provider_auth_state()`` fall back to the global-root
``auth.json`` per-provider when the profile has no entries for that
provider.  Writes still target the profile only.

See the #18594 follow-up report: profile workers couldn't see providers
authenticated only at the global root.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _make_auth_store(pool: dict | None = None, providers: dict | None = None) -> dict:
    store: dict = {"version": 1}
    if pool is not None:
        store["credential_pool"] = pool
    if providers is not None:
        store["providers"] = providers
    return store


@pytest.fixture()
def profile_env(tmp_path, monkeypatch):
    """Set up a global root + an active profile under Path.home()/.fabric/profiles/coder.

    * Path.home() -> tmp_path
    * Global root -> tmp_path/.fabric            (has its own auth.json fixture)
    * Profile     -> tmp_path/.fabric/profiles/coder   (active, FABRIC_HOME points here)

    This mirrors the real "named profile mounted under the default root"
    layout that profile users actually have on disk.
    """
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    global_root = tmp_path / ".fabric"
    global_root.mkdir()
    profile_dir = global_root / "profiles" / "coder"
    profile_dir.mkdir(parents=True)
    monkeypatch.setenv("FABRIC_HOME", str(profile_dir))
    return {"global": global_root, "profile": profile_dir}


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2))


# ---------------------------------------------------------------------------
# read_credential_pool — provider-slice reads
# ---------------------------------------------------------------------------


def test_profile_with_zero_entries_falls_back_to_global(profile_env):
    """Empty profile pool inherits the global-root entries for that provider."""
    from fabric_cli.auth import read_credential_pool

    _write(profile_env["global"] / "auth.json", _make_auth_store(pool={
        "openrouter": [{
            "id": "glob-1",
            "label": "global-key",
            "auth_type": "api_key",
            "priority": 0,
            "source": "manual",
            "access_token": "sk-or-global",
        }],
    }))
    # Profile auth.json: exists but has no openrouter entries.
    _write(profile_env["profile"] / "auth.json", _make_auth_store(pool={}))

    entries = read_credential_pool("openrouter")
    assert len(entries) == 1
    assert entries[0]["id"] == "glob-1"
    assert entries[0]["access_token"] == "sk-or-global"


def test_anthropic_status_marks_global_pool_fallback(profile_env, monkeypatch):
    """Accounts must not tell a profile user to remove a global key locally."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _write(profile_env["global"] / "auth.json", _make_auth_store(pool={
        "anthropic": [{
            "id": "glob-ant",
            "label": "global-key",
            "auth_type": "api_key",
            "priority": 0,
            "source": "manual",
            "access_token": "sk-ant-api03-global",
        }],
    }))
    _write(profile_env["profile"] / "auth.json", _make_auth_store(pool={}))

    from fabric_cli.web_server import (
        _anthropic_key_status,
        _oauth_provider_disconnect_hint,
    )

    status = _anthropic_key_status()
    assert status["source"] == "credential_pool_global"
    assert status["source_label"] == "default profile · fabric auth: global-key"
    hint = _oauth_provider_disconnect_hint({"id": "anthropic"}, status)
    assert "inherited from the default profile" in hint


def test_anthropic_prune_uses_global_fallback_on_first_load(profile_env, monkeypatch):
    """Pruning the last local OAuth row must expose the global key immediately."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _write(profile_env["global"] / "auth.json", _make_auth_store(pool={
        "anthropic": [{
            "id": "glob-ant",
            "label": "global-key",
            "auth_type": "api_key",
            "priority": 0,
            "source": "manual",
            "access_token": "sk-ant-api03-global",
        }],
    }))
    _write(profile_env["profile"] / "auth.json", _make_auth_store(pool={
        "anthropic": [{
            "id": "legacy-local",
            "label": "old subscription",
            "auth_type": "oauth",
            "priority": 0,
            "source": "manual:anthropic_pkce",
            "access_token": "sk-ant-oat01-old",
        }],
    }))

    from agent.credential_pool import load_pool
    from fabric_cli.auth import _resolve_anthropic_api_key
    from fabric_cli.web_server import _anthropic_key_status

    assert _resolve_anthropic_api_key() == (
        "sk-ant-api03-global",
        "credential_pool_global:global-key",
    )
    assert _anthropic_key_status()["source"] == "credential_pool_global"

    entries = load_pool("anthropic").entries()
    assert [(entry.id, entry.access_token) for entry in entries] == [
        ("glob-ant", "sk-ant-api03-global")
    ]
    profile_store = json.loads(
        (profile_env["profile"] / "auth.json").read_text(encoding="utf-8")
    )
    global_store = json.loads(
        (profile_env["global"] / "auth.json").read_text(encoding="utf-8")
    )
    assert profile_store["credential_pool"]["anthropic"] == []
    assert [
        entry["id"]
        for entry in global_store["credential_pool"]["anthropic"]
    ] == ["glob-ant"]


def test_anthropic_global_fallback_normalization_never_clones_secret(
    profile_env, monkeypatch
):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    global_rows = [
        {
            "id": "global-valid",
            "label": "global native",
            "auth_type": "api_key",
            "priority": 0,
            "source": "manual",
            "access_token": "sk-ant-api03-global",
            "base_url": "https://api.anthropic.com",
        },
        {
            "id": "global-legacy",
            "label": "old subscription",
            "auth_type": "oauth",
            "priority": 1,
            "source": "manual:anthropic_pkce",
            "access_token": "sk-ant-oat01-global-old",
        },
    ]
    global_payload = _make_auth_store(pool={"anthropic": global_rows})
    profile_payload = _make_auth_store(pool={})
    _write(profile_env["global"] / "auth.json", global_payload)
    _write(profile_env["profile"] / "auth.json", profile_payload)

    from agent.credential_pool import load_pool

    entries = load_pool("anthropic").entries()

    assert [(entry.id, entry.access_token) for entry in entries] == [
        ("global-valid", "sk-ant-api03-global")
    ]
    assert json.loads(
        (profile_env["profile"] / "auth.json").read_text(encoding="utf-8")
    ) == profile_payload
    assert json.loads(
        (profile_env["global"] / "auth.json").read_text(encoding="utf-8")
    ) == global_payload


def test_anthropic_global_missing_native_base_is_in_memory_only(
    profile_env, monkeypatch
):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    global_payload = _make_auth_store(pool={
        "anthropic": [{
            "id": "global-native-old",
            "label": "old native key",
            "auth_type": "api_key",
            "priority": 0,
            "source": "manual",
            "access_token": "sk-ant-api03-global",
        }],
    })
    profile_payload = _make_auth_store(pool={})
    _write(profile_env["global"] / "auth.json", global_payload)
    _write(profile_env["profile"] / "auth.json", profile_payload)

    from agent.credential_pool import load_pool

    for _ in range(2):
        pool = load_pool("anthropic")
        assert pool.read_only is True
        entries = pool.entries()
        assert len(entries) == 1
        assert entries[0].runtime_base_url == "https://api.anthropic.com"

    assert json.loads(
        (profile_env["profile"] / "auth.json").read_text(encoding="utf-8")
    ) == profile_payload
    assert json.loads(
        (profile_env["global"] / "auth.json").read_text(encoding="utf-8")
    ) == global_payload


def test_anthropic_inherited_pool_mutations_remain_read_only(
    profile_env, monkeypatch
):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    (profile_env["profile"] / "config.yaml").write_text(
        "credential_pool_strategies:\n  anthropic: round_robin\n",
        encoding="utf-8",
    )
    global_payload = _make_auth_store(pool={
        "anthropic": [
            {
                "id": "global-a",
                "label": "global A",
                "auth_type": "api_key",
                "priority": 0,
                "source": "manual",
                "access_token": "sk-ant-api03-global-a",
                "base_url": "https://api.anthropic.com",
            },
            {
                "id": "global-b",
                "label": "global B",
                "auth_type": "api_key",
                "priority": 1,
                "source": "manual",
                "access_token": "sk-ant-api03-global-b",
                "base_url": "https://api.anthropic.com",
            },
        ],
    })
    profile_payload = _make_auth_store(pool={})
    _write(profile_env["global"] / "auth.json", global_payload)
    _write(profile_env["profile"] / "auth.json", profile_payload)

    from agent.credential_pool import load_pool
    from fabric_cli.runtime_provider import _anthropic_pool_for_endpoint

    inherited = load_pool("anthropic")
    filtered = _anthropic_pool_for_endpoint(
        inherited,
        "https://api.anthropic.com/v1",
    )
    assert filtered is not None
    assert filtered.read_only is True
    first = filtered.select()
    assert first is not None
    assert filtered.mark_exhausted_and_rotate(
        status_code=429,
        error_context={"message": "rate limited"},
        api_key_hint=first.runtime_api_key,
    ) is not None

    assert json.loads(
        (profile_env["profile"] / "auth.json").read_text(encoding="utf-8")
    ) == profile_payload
    assert json.loads(
        (profile_env["global"] / "auth.json").read_text(encoding="utf-8")
    ) == global_payload


def test_anthropic_add_to_inherited_pool_creates_local_slice_only(
    profile_env, monkeypatch
):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    global_payload = _make_auth_store(pool={
        "anthropic": [{
            "id": "global-manual",
            "label": "global",
            "auth_type": "api_key",
            "priority": 0,
            "source": "manual",
            "access_token": "sk-ant-api03-global",
            "base_url": "https://api.anthropic.com",
        }],
    })
    _write(profile_env["global"] / "auth.json", global_payload)
    _write(
        profile_env["profile"] / "auth.json",
        _make_auth_store(pool={}),
    )

    from agent.credential_pool import (
        AUTH_TYPE_API_KEY,
        SOURCE_MANUAL,
        PooledCredential,
        load_pool,
    )

    pool = load_pool("anthropic")
    assert pool.read_only is True
    pool.add_entry(PooledCredential(
        provider="anthropic",
        id="profile-new",
        label="profile",
        auth_type=AUTH_TYPE_API_KEY,
        priority=0,
        source=SOURCE_MANUAL,
        access_token="sk-ant-api03-profile",
        base_url="https://api.anthropic.com",
    ))

    assert pool.read_only is False
    assert [entry.id for entry in pool.entries()] == ["profile-new"]
    profile_store = json.loads(
        (profile_env["profile"] / "auth.json").read_text(encoding="utf-8")
    )
    assert [
        entry["id"]
        for entry in profile_store["credential_pool"]["anthropic"]
    ] == ["profile-new"]
    assert json.loads(
        (profile_env["global"] / "auth.json").read_text(encoding="utf-8")
    ) == global_payload


def test_anthropic_failed_add_restores_inherited_read_only_view(
    profile_env, monkeypatch
):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    global_payload = _make_auth_store(pool={
        "anthropic": [{
            "id": "global-manual",
            "label": "global",
            "auth_type": "api_key",
            "priority": 0,
            "source": "manual",
            "access_token": "sk-ant-api03-global",
            "base_url": "https://api.anthropic.com",
        }],
    })
    profile_payload = _make_auth_store(pool={})
    _write(profile_env["global"] / "auth.json", global_payload)
    _write(profile_env["profile"] / "auth.json", profile_payload)

    from agent.credential_pool import (
        AUTH_TYPE_API_KEY,
        SOURCE_MANUAL,
        PooledCredential,
        load_pool,
    )

    pool = load_pool("anthropic")
    assert pool.select().id == "global-manual"
    monkeypatch.setattr(
        pool,
        "_persist",
        lambda: (_ for _ in ()).throw(OSError("read-only filesystem")),
    )

    with pytest.raises(OSError, match="read-only filesystem"):
        pool.add_entry(PooledCredential(
            provider="anthropic",
            id="profile-new",
            label="profile",
            auth_type=AUTH_TYPE_API_KEY,
            priority=0,
            source=SOURCE_MANUAL,
            access_token="sk-ant-api03-profile",
            base_url="https://api.anthropic.com",
        ))

    assert pool.read_only is True
    assert [entry.id for entry in pool.entries()] == ["global-manual"]
    assert pool.current().id == "global-manual"
    assert json.loads(
        (profile_env["profile"] / "auth.json").read_text(encoding="utf-8")
    ) == profile_payload
    assert json.loads(
        (profile_env["global"] / "auth.json").read_text(encoding="utf-8")
    ) == global_payload


def test_anthropic_profile_env_seed_never_copies_global_manual_rows(
    profile_env, monkeypatch
):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    (profile_env["profile"] / ".env").write_text(
        "ANTHROPIC_API_KEY=sk-ant-api03-profile\n",
        encoding="utf-8",
    )
    global_payload = _make_auth_store(pool={
        "anthropic": [{
            "id": "global-manual",
            "label": "global key",
            "auth_type": "api_key",
            "priority": 0,
            "source": "manual",
            "access_token": "sk-ant-api03-global",
            "base_url": "https://api.anthropic.com",
        }],
    })
    _write(profile_env["global"] / "auth.json", global_payload)
    _write(
        profile_env["profile"] / "auth.json",
        _make_auth_store(pool={}),
    )

    from agent.credential_pool import load_pool

    entries = load_pool("anthropic").entries()

    assert len(entries) == 1
    assert entries[0].source == "env:ANTHROPIC_API_KEY"
    assert entries[0].runtime_api_key == "sk-ant-api03-profile"
    profile_store = json.loads(
        (profile_env["profile"] / "auth.json").read_text(encoding="utf-8")
    )
    stored_rows = profile_store["credential_pool"]["anthropic"]
    assert [entry["source"] for entry in stored_rows] == [
        "env:ANTHROPIC_API_KEY"
    ]
    assert all("access_token" not in entry for entry in stored_rows)
    assert json.loads(
        (profile_env["global"] / "auth.json").read_text(encoding="utf-8")
    ) == global_payload


def test_anthropic_global_ambiguous_key_is_not_rebound_to_profile_route(
    profile_env, monkeypatch
):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    (profile_env["profile"] / "config.yaml").write_text(
        "model:\n"
        "  provider: anthropic\n"
        "  base_url: https://profile.example/anthropic\n",
        encoding="utf-8",
    )
    global_payload = _make_auth_store(pool={
        "anthropic": [{
            "id": "global-ambiguous",
            "label": "global proxy key without route",
            "auth_type": "api_key",
            "priority": 0,
            "source": "manual",
            "access_token": "eyJ.global.proxy",
        }],
    })
    profile_payload = _make_auth_store(pool={})
    _write(profile_env["global"] / "auth.json", global_payload)
    _write(profile_env["profile"] / "auth.json", profile_payload)

    from agent.credential_pool import load_pool
    from fabric_cli.auth import _resolve_anthropic_api_key_details

    assert load_pool("anthropic").entries() == []
    assert _resolve_anthropic_api_key_details() == (
        "",
        "",
        "https://profile.example/anthropic",
    )
    assert json.loads(
        (profile_env["profile"] / "auth.json").read_text(encoding="utf-8")
    ) == profile_payload
    assert json.loads(
        (profile_env["global"] / "auth.json").read_text(encoding="utf-8")
    ) == global_payload


def test_profile_with_entries_fully_shadows_global(profile_env):
    """Once the profile has any entries for a provider, global is ignored."""
    from fabric_cli.auth import read_credential_pool

    _write(profile_env["global"] / "auth.json", _make_auth_store(pool={
        "openrouter": [{
            "id": "glob-1",
            "label": "global-key",
            "auth_type": "api_key",
            "priority": 0,
            "source": "manual",
            "access_token": "sk-or-global",
        }],
    }))
    _write(profile_env["profile"] / "auth.json", _make_auth_store(pool={
        "openrouter": [{
            "id": "prof-1",
            "label": "profile-key",
            "auth_type": "api_key",
            "priority": 0,
            "source": "manual",
            "access_token": "sk-or-profile",
        }],
    }))

    entries = read_credential_pool("openrouter")
    assert len(entries) == 1
    assert entries[0]["id"] == "prof-1"
    assert entries[0]["access_token"] == "sk-or-profile"


def test_per_provider_shadowing_is_independent(profile_env):
    """Profile can override one provider while inheriting another from global."""
    from fabric_cli.auth import read_credential_pool

    _write(profile_env["global"] / "auth.json", _make_auth_store(pool={
        "openrouter": [{
            "id": "glob-or",
            "label": "global-or",
            "auth_type": "api_key",
            "priority": 0,
            "source": "manual",
            "access_token": "sk-or-global",
        }],
        "anthropic": [{
            "id": "glob-ant",
            "label": "global-ant",
            "auth_type": "api_key",
            "priority": 0,
            "source": "manual",
            "access_token": "sk-ant-global",
        }],
    }))
    _write(profile_env["profile"] / "auth.json", _make_auth_store(pool={
        # Profile has openrouter only — anthropic should still fall back.
        "openrouter": [{
            "id": "prof-or",
            "label": "profile-or",
            "auth_type": "api_key",
            "priority": 0,
            "source": "manual",
            "access_token": "sk-or-profile",
        }],
    }))

    or_entries = read_credential_pool("openrouter")
    ant_entries = read_credential_pool("anthropic")
    assert [e["id"] for e in or_entries] == ["prof-or"]
    assert [e["id"] for e in ant_entries] == ["glob-ant"]


def test_missing_global_auth_file_is_safe(profile_env):
    """Profile processes that never had a global auth.json still work."""
    from fabric_cli.auth import read_credential_pool

    # No global auth.json written at all.
    _write(profile_env["profile"] / "auth.json", _make_auth_store(pool={
        "openrouter": [{
            "id": "prof-1",
            "label": "profile",
            "auth_type": "api_key",
            "priority": 0,
            "source": "manual",
            "access_token": "sk-profile",
        }],
    }))

    assert read_credential_pool("openrouter")[0]["id"] == "prof-1"
    assert read_credential_pool("anthropic") == []


def test_malformed_global_auth_file_does_not_break_profile_read(profile_env):
    (profile_env["global"] / "auth.json").write_text("{not valid json")
    _write(profile_env["profile"] / "auth.json", _make_auth_store(pool={
        "openrouter": [{
            "id": "prof-1",
            "label": "profile",
            "auth_type": "api_key",
            "priority": 0,
            "source": "manual",
            "access_token": "sk-profile",
        }],
    }))

    from fabric_cli.auth import read_credential_pool

    # Profile reads still work; malformed global is silently ignored.
    assert read_credential_pool("openrouter")[0]["id"] == "prof-1"
    # And no fallback for anthropic since global is unreadable.
    assert read_credential_pool("anthropic") == []


# ---------------------------------------------------------------------------
# read_credential_pool — whole-pool reads (provider_id=None)
# ---------------------------------------------------------------------------


def test_whole_pool_merges_global_providers_when_missing_locally(profile_env):
    from fabric_cli.auth import read_credential_pool

    _write(profile_env["global"] / "auth.json", _make_auth_store(pool={
        "openrouter": [{
            "id": "glob-or",
            "label": "global-or",
            "auth_type": "api_key",
            "priority": 0,
            "source": "manual",
            "access_token": "sk-or-global",
        }],
        "anthropic": [{
            "id": "glob-ant",
            "label": "global-ant",
            "auth_type": "api_key",
            "priority": 0,
            "source": "manual",
            "access_token": "sk-ant-global",
        }],
    }))
    _write(profile_env["profile"] / "auth.json", _make_auth_store(pool={
        "openrouter": [{
            "id": "prof-or",
            "label": "profile-or",
            "auth_type": "api_key",
            "priority": 0,
            "source": "manual",
            "access_token": "sk-or-profile",
        }],
    }))

    pool = read_credential_pool(None)
    # Profile wins for openrouter, global fills in anthropic.
    assert [e["id"] for e in pool["openrouter"]] == ["prof-or"]
    assert [e["id"] for e in pool["anthropic"]] == ["glob-ant"]


# ---------------------------------------------------------------------------
# get_provider_auth_state — singleton fallback
# ---------------------------------------------------------------------------


def test_provider_auth_state_falls_back_to_global_when_profile_has_none(profile_env):
    from fabric_cli.auth import get_provider_auth_state

    _write(profile_env["global"] / "auth.json", _make_auth_store(providers={
        "nous": {"access_token": "nous-global", "refresh_token": "rt-global"},
    }))
    _write(profile_env["profile"] / "auth.json", _make_auth_store(providers={}))

    state = get_provider_auth_state("nous")
    assert state is not None
    assert state["access_token"] == "nous-global"


def test_provider_auth_state_profile_wins_when_present(profile_env):
    from fabric_cli.auth import get_provider_auth_state

    _write(profile_env["global"] / "auth.json", _make_auth_store(providers={
        "nous": {"access_token": "nous-global"},
    }))
    _write(profile_env["profile"] / "auth.json", _make_auth_store(providers={
        "nous": {"access_token": "nous-profile"},
    }))

    state = get_provider_auth_state("nous")
    assert state is not None
    assert state["access_token"] == "nous-profile"


def test_provider_auth_state_returns_none_when_neither_has_it(profile_env):
    from fabric_cli.auth import get_provider_auth_state

    _write(profile_env["global"] / "auth.json", _make_auth_store(providers={}))
    _write(profile_env["profile"] / "auth.json", _make_auth_store(providers={}))

    assert get_provider_auth_state("nous") is None


# ---------------------------------------------------------------------------
# _load_provider_state — internal global fallback (issue #18594 follow-up)
#
# Several runtime helpers (notably ``resolve_nous_runtime_credentials`` and
# ``resolve_nous_access_token``) call ``_load_provider_state`` directly with
# a profile-loaded auth store rather than going through
# ``get_provider_auth_state``. Without the fallback wired into
# ``_load_provider_state`` itself, those helpers raise ``"Fabric is not
# logged into Nous Portal"`` even though the user has a valid global Nous
# login. These tests pin the per-provider shadowing into the helper.
# ---------------------------------------------------------------------------


def test_load_provider_state_falls_back_to_global(profile_env):
    """When the loaded profile store has no provider entry, fall back to global."""
    from fabric_cli.auth import _load_auth_store, _load_provider_state

    _write(profile_env["global"] / "auth.json", _make_auth_store(providers={
        "nous": {"access_token": "global-nous-token", "refresh_token": "rt"},
    }))
    _write(profile_env["profile"] / "auth.json", _make_auth_store(providers={}))

    auth_store = _load_auth_store()
    state = _load_provider_state(auth_store, "nous")
    assert state is not None
    assert state["access_token"] == "global-nous-token"


def test_load_provider_state_profile_wins_over_global(profile_env):
    from fabric_cli.auth import _load_auth_store, _load_provider_state

    _write(profile_env["global"] / "auth.json", _make_auth_store(providers={
        "nous": {"access_token": "global-token"},
    }))
    _write(profile_env["profile"] / "auth.json", _make_auth_store(providers={
        "nous": {"access_token": "profile-token"},
    }))

    auth_store = _load_auth_store()
    state = _load_provider_state(auth_store, "nous")
    assert state is not None
    assert state["access_token"] == "profile-token"


def test_load_provider_state_returns_none_when_neither_has_it(profile_env):
    from fabric_cli.auth import _load_auth_store, _load_provider_state

    _write(profile_env["global"] / "auth.json", _make_auth_store(providers={}))
    _write(profile_env["profile"] / "auth.json", _make_auth_store(providers={}))

    auth_store = _load_auth_store()
    assert _load_provider_state(auth_store, "nous") is None


def test_load_provider_state_classic_mode_no_fallback(tmp_path, monkeypatch):
    """In classic mode there is no global to fall back to; behavior is unchanged."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    fabric_home = tmp_path / "classic"
    fabric_home.mkdir()
    monkeypatch.setenv("FABRIC_HOME", str(fabric_home))

    _write(fabric_home / "auth.json", _make_auth_store(providers={
        "nous": {"access_token": "classic-token"},
    }))

    from fabric_cli.auth import _load_auth_store, _load_provider_state

    auth_store = _load_auth_store()
    state = _load_provider_state(auth_store, "nous")
    assert state is not None
    assert state["access_token"] == "classic-token"
    # Absent providers still return None.
    assert _load_provider_state(auth_store, "anthropic") is None


def test_load_provider_state_malformed_global_does_not_break_profile(profile_env):
    """A corrupt global auth.json must not break profile reads."""
    (profile_env["global"] / "auth.json").write_text("{not valid json")
    _write(profile_env["profile"] / "auth.json", _make_auth_store(providers={
        "nous": {"access_token": "profile-token"},
    }))

    from fabric_cli.auth import _load_auth_store, _load_provider_state

    auth_store = _load_auth_store()
    state = _load_provider_state(auth_store, "nous")
    assert state is not None
    assert state["access_token"] == "profile-token"


# ---------------------------------------------------------------------------
# Classic mode — no fallback path should ever trigger
# ---------------------------------------------------------------------------


def test_classic_mode_does_not_double_read_same_file(tmp_path, monkeypatch):
    """In classic mode (FABRIC_HOME == global root), no fallback path runs.

    This guards against the merge accidentally duplicating entries when the
    profile and global resolve to the same directory.
    """
    # Put Path.home() under a subdir so the seat belt in _auth_file_path()
    # sees tmp_path/home/.fabric as the "real home" — which is NOT equal
    # to the FABRIC_HOME we set (tmp_path/classic), so the guard passes.
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    fabric_home = tmp_path / "classic"
    fabric_home.mkdir()
    monkeypatch.setenv("FABRIC_HOME", str(fabric_home))

    _write(fabric_home / "auth.json", _make_auth_store(pool={
        "openrouter": [{
            "id": "only",
            "label": "classic",
            "auth_type": "api_key",
            "priority": 0,
            "source": "manual",
            "access_token": "sk-classic",
        }],
    }))

    from fabric_cli.auth import read_credential_pool, _global_auth_file_path

    # Classic mode: FABRIC_HOME is set to a custom path that is NOT under
    # ~/.fabric/profiles/ — get_default_fabric_root() returns FABRIC_HOME
    # itself, so the profile root and global root are the same directory,
    # and the helper correctly returns None (no fallback).
    assert _global_auth_file_path() is None
    # And the read should return exactly one entry (not two).
    entries = read_credential_pool("openrouter")
    assert len(entries) == 1
    assert entries[0]["id"] == "only"


# ---------------------------------------------------------------------------
# Writes stay scoped to the profile
# ---------------------------------------------------------------------------


def test_write_credential_pool_targets_profile_not_global(profile_env):
    from fabric_cli.auth import read_credential_pool, write_credential_pool

    _write(profile_env["global"] / "auth.json", _make_auth_store(pool={
        "openrouter": [{
            "id": "glob-1",
            "label": "global",
            "auth_type": "api_key",
            "priority": 0,
            "source": "manual",
            "access_token": "sk-global",
        }],
    }))

    write_credential_pool("openrouter", [{
        "id": "prof-new",
        "label": "profile-new",
        "auth_type": "api_key",
        "priority": 0,
        "source": "manual",
        "access_token": "sk-profile-new",
    }])

    # Global auth.json unchanged.
    global_data = json.loads((profile_env["global"] / "auth.json").read_text())
    assert global_data["credential_pool"]["openrouter"][0]["id"] == "glob-1"

    # Profile auth.json holds the new entry.
    profile_data = json.loads((profile_env["profile"] / "auth.json").read_text())
    assert profile_data["credential_pool"]["openrouter"][0]["id"] == "prof-new"

    # Subsequent read returns profile (shadows global).
    assert [e["id"] for e in read_credential_pool("openrouter")] == ["prof-new"]
