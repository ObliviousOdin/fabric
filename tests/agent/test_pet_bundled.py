"""Behavior contracts for first-party pet packages bundled with Fabric."""

from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from io import BytesIO

from agent.pet import store
from agent.pet.generate import atlas


def test_fabric_mascot_is_available_without_profile_install():
    assert store.installed_pets() == []

    pet = store.load_pet("fabric-mascot")

    assert pet is not None
    assert pet.exists
    assert pet.bundled is True
    assert pet.display_name == "Fabric Mascot"
    assert pet.directory == store.bundled_pets_dir() / pet.slug
    available = {candidate.slug: candidate for candidate in store.available_pets()}
    assert available[pet.slug] == pet
    assert store.resolve_active_pet("fabric-mascot") == pet
    assert store.resolve_active_pet() == pet
    assert store.remove_pet("fabric-mascot") is False
    assert pet.spritesheet.is_file()


def test_fabric_mascot_atlas_satisfies_the_renderer_contract():
    pet = store.load_pet("fabric-mascot")
    assert pet is not None

    report = atlas.validate_atlas(pet.spritesheet)

    assert report["ok"], report
    assert report["errors"] == []
    assert report["warnings"] == []
    assert set(report["filled_states"]) == {state for state, _row, _count in atlas.ROW_SPECS}


def test_profile_pet_can_shadow_and_reveal_bundled_pet():
    bundled = store.load_pet("fabric-mascot")
    assert bundled is not None and bundled.bundled

    local_dir = store.pets_dir() / bundled.slug
    local_dir.mkdir()
    shutil.copyfile(bundled.spritesheet, local_dir / "spritesheet.webp")
    (local_dir / "pet.json").write_text(
        json.dumps(
            {
                "id": bundled.slug,
                "displayName": "Local Mascot Override",
                "spritesheetPath": "spritesheet.webp",
                "createdBy": "generator",
            }
        ),
        encoding="utf-8",
    )

    local = store.load_pet(bundled.slug)
    assert local is not None
    assert local.bundled is False
    assert local.generated is True
    assert local.display_name == "Local Mascot Override"
    available = {pet.slug: pet for pet in store.available_pets()}
    assert available[bundled.slug] == local
    assert store.resolve_active_pet("missing-pet") == local

    assert store.remove_pet(bundled.slug) is True
    revealed = store.load_pet(bundled.slug)
    assert revealed is not None and revealed.bundled


def test_bundled_pet_exports_as_a_clean_pet_package():
    filename, payload = store.export_pet("fabric-mascot")

    assert filename == "fabric-mascot.zip"
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == {
            "fabric-mascot/pet.json",
            "fabric-mascot/spritesheet.webp",
        }


def test_generated_slug_does_not_collide_with_bundled_pet():
    assert store.unique_slug("Fabric Mascot") == "fabric-mascot-2"


def test_cli_refuses_to_remove_bundled_pet(capsys):
    from fabric_cli.pets import _cmd_remove

    assert _cmd_remove(argparse.Namespace(slug="fabric-mascot")) == 1
    assert "ships with Fabric and cannot be removed" in capsys.readouterr().err
