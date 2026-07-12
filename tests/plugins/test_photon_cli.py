"""Photon setup compatibility tests for the Fabric public distribution."""

from plugins.platforms.photon import auth, cli


def test_default_project_uses_single_lookup_when_legacy_name_matches(monkeypatch):
    calls = []
    legacy = {"id": "legacy-project"}

    def find_project(_token, name):
        calls.append(name)
        return legacy if name == auth.LEGACY_DEFAULT_PROJECT_NAME else None

    monkeypatch.setattr(auth, "find_project_by_name", find_project)

    name, project = cli._find_existing_setup_project("token", None)

    assert calls == [auth.DEFAULT_PROJECT_NAME]
    assert name == auth.DEFAULT_PROJECT_NAME
    assert project == legacy


def test_explicit_project_name_never_falls_back_to_legacy(monkeypatch):
    calls = []

    def find_project(_token, name):
        calls.append(name)
        return None

    monkeypatch.setattr(auth, "find_project_by_name", find_project)

    name, project = cli._find_existing_setup_project("token", "Custom")

    assert calls == ["Custom"]
    assert name == "Custom"
    assert project is None
