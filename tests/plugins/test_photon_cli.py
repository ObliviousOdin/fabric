"""Photon setup project-selection tests."""

from plugins.platforms.photon import auth, cli


def test_default_project_uses_canonical_name(monkeypatch):
    calls = []
    canonical = {"id": "test-project"}

    def find_project(_token, name):
        calls.append(name)
        return canonical if name == auth.DEFAULT_PROJECT_NAME else None

    monkeypatch.setattr(auth, "find_project_by_name", find_project)

    name, project = cli._find_existing_setup_project("token", None)

    assert calls == [auth.DEFAULT_PROJECT_NAME]
    assert name == auth.DEFAULT_PROJECT_NAME
    assert project == canonical


def test_explicit_project_name_uses_requested_name(monkeypatch):
    calls = []

    def find_project(_token, name):
        calls.append(name)
        return None

    monkeypatch.setattr(auth, "find_project_by_name", find_project)

    name, project = cli._find_existing_setup_project("token", "Custom")

    assert calls == ["Custom"]
    assert name == "Custom"
    assert project is None
