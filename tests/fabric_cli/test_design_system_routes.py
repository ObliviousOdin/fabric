from __future__ import annotations

from io import BytesIO
from pathlib import Path
import zipfile

from fastapi import FastAPI
from fastapi.testclient import TestClient

from fabric_cli.design_system_routes import design_system_router


def _zip_bytes(entries: dict[str, str]) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, content in entries.items():
            archive.writestr(path, content)
    return output.getvalue()


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(design_system_router())
    return TestClient(app)


def test_import_list_replace_and_delete_managed_design_system(
    tmp_path: Path, monkeypatch
) -> None:
    profile_home = tmp_path / "profile"
    monkeypatch.setenv("FABRIC_HOME", str(profile_home))
    client = _client()
    first_archive = _zip_bytes(
        {
            "DESIGN.md": "# Acme",
            "tokens/colors.json": '{"brand":"#123456"}',
            "preview/index.html": "<html></html>",
        }
    )

    imported = client.post(
        "/api/design-systems/import",
        files={"file": ("Acme UI.zip", first_archive, "application/zip")},
        data={"name": "Acme UI"},
    )

    assert imported.status_code == 200
    payload = imported.json()
    system = payload["system"]
    assert payload["deduplicated"] is False
    assert system["name"] == "Acme UI"
    assert system["generation"] == 1
    assert system["activeRevisionInfo"]["originalFilename"] == "Acme UI.zip"
    assert system["activeRevisionInfo"]["entrypoints"] == {
        "designMd": "DESIGN.md",
        "html": ["preview/index.html"],
        "tokenFiles": ["tokens/colors.json"],
    }
    assert Path(system["contentPath"]).is_relative_to(profile_home)
    assert "fabric-design-system-upload-" not in system["contentPath"]

    listed = client.get("/api/design-systems")
    assert listed.status_code == 200
    assert listed.json() == {"systems": [system]}

    duplicate = client.post(
        "/api/design-systems/import",
        files={"file": ("renamed.zip", first_archive, "application/zip")},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["deduplicated"] is True
    assert duplicate.json()["system"]["id"] == system["id"]

    second_archive = _zip_bytes({"DESIGN.md": "# Acme v2"})
    replaced = client.post(
        f"/api/design-systems/{system['id']}/revisions",
        files={"file": ("Acme UI v2.zip", second_archive, "application/zip")},
        data={"generation": str(system["generation"]), "name": "Acme UI"},
    )
    assert replaced.status_code == 200
    updated = replaced.json()["system"]
    assert updated["id"] == system["id"]
    assert updated["generation"] == 2
    assert updated["activeRevision"] != system["activeRevision"]

    stale = client.post(
        f"/api/design-systems/{system['id']}/revisions",
        files={"file": ("stale.zip", first_archive, "application/zip")},
        data={"generation": "1", "name": "Acme UI"},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "stale_generation"

    stale_delete = client.request(
        "DELETE",
        f"/api/design-systems/{system['id']}",
        json={"expectedGeneration": system["generation"]},
    )
    assert stale_delete.status_code == 409
    assert stale_delete.json()["detail"]["code"] == "stale_generation"

    deleted = client.request(
        "DELETE",
        f"/api/design-systems/{system['id']}",
        json={"expectedGeneration": updated["generation"]},
    )
    assert deleted.status_code == 200
    assert client.get("/api/design-systems").json() == {"systems": []}


def test_import_rejects_traversal_and_cleans_upload_staging(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path / "profile"))
    client = _client()
    archive = _zip_bytes({"../escape.txt": "no"})

    response = client.post(
        "/api/design-systems/import",
        files={"file": ("unsafe.zip", archive, "application/zip")},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_archive"
    assert not (tmp_path / "escape.txt").exists()


def test_profile_query_isolates_global_remote_imports(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    default_home = tmp_path / ".fabric"
    work_home = default_home / "profiles" / "work"
    work_home.mkdir(parents=True)
    monkeypatch.setenv("FABRIC_HOME", str(default_home))
    client = _client()

    response = client.post(
        "/api/design-systems/import?profile=work",
        files={
            "file": (
                "work.zip",
                _zip_bytes({"DESIGN.md": "# Work"}),
                "application/zip",
            )
        },
    )

    assert response.status_code == 200
    assert Path(response.json()["system"]["contentPath"]).is_relative_to(
        work_home
    )
    assert client.get("/api/design-systems?profile=work").json()["systems"]
    assert client.get("/api/design-systems").json() == {"systems": []}
