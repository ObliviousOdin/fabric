"""Gateway contracts for first-party bundled pets."""

from __future__ import annotations

import shutil

from agent.pet import manifest, store
from fabric_cli import pets as pets_cli
from tui_gateway import server


def test_local_gallery_includes_offline_fabric_mascot(monkeypatch):
    monkeypatch.setattr(manifest, "prefetch", lambda: None)

    response = server._methods["pet.gallery"]("gallery", {"localOnly": True})
    pets = response["result"]["pets"]
    mascot = next(pet for pet in pets if pet["slug"] == "fabric-mascot")

    assert mascot["displayName"] == "Fabric Mascot"
    assert mascot["installed"] is True
    assert mascot["bundled"] is True
    assert mascot["curated"] is True
    assert mascot["generated"] is False


def test_bundled_pet_can_be_selected_without_manifest_download(monkeypatch):
    selected: list[str] = []
    monkeypatch.setattr(pets_cli, "_set_active", selected.append)

    response = server._methods["pet.select"]("select", {"slug": "fabric-mascot"})

    assert response["result"] == {
        "ok": True,
        "slug": "fabric-mascot",
        "displayName": "Fabric Mascot",
    }
    assert selected == ["fabric-mascot"]


def test_removing_bundled_pet_does_not_clear_active_config(monkeypatch):
    cleared: list[str] = []
    monkeypatch.setattr(pets_cli, "_clear_active_if", cleared.append)

    response = server._methods["pet.remove"]("remove", {"slug": "fabric-mascot"})

    assert response["result"] == {"ok": False, "slug": "fabric-mascot"}
    assert cleared == []


def test_removing_local_override_keeps_active_bundled_fallback(monkeypatch):
    local_dir = store.pets_dir() / "fabric-mascot"
    shutil.copytree(store.bundled_pets_dir() / "fabric-mascot", local_dir)
    override = store.load_pet("fabric-mascot")
    assert override is not None
    assert override.bundled is False

    cleared: list[str] = []
    monkeypatch.setattr(pets_cli, "_clear_active_if", cleared.append)

    response = server._methods["pet.remove"]("remove", {"slug": "fabric-mascot"})

    assert response["result"] == {"ok": True, "slug": "fabric-mascot"}
    fallback = store.load_pet("fabric-mascot")
    assert fallback is not None
    assert fallback.bundled is True
    assert cleared == []
