"""Profile-scoped REST routes for managed design-system ZIP imports."""

from __future__ import annotations

from datetime import datetime, timezone
import functools
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from fabric_cli.design_system_library import (
    MAX_ARCHIVE_BYTES,
    ArchiveValidationError,
    DesignSystemConflictError,
    DesignSystemLibrary,
    DesignSystemNotFoundError,
    DesignSystemStorageError,
)

_UPLOAD_CHUNK_BYTES = 1024 * 1024


class DesignSystemDeleteRequest(BaseModel):
    expectedGeneration: int | None = None


def _iso_timestamp(value: Any) -> str:
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError, OSError, OverflowError):
        return "1970-01-01T00:00:00Z"


def _entrypoints(files_path: str) -> dict[str, Any]:
    root = Path(files_path)
    design_md: str | None = None
    package_json: str | None = None
    html: list[str] = []
    token_files: list[str] = []

    try:
        candidates = (path for path in root.rglob("*") if path.is_file())
        for path in candidates:
            relative = path.relative_to(root).as_posix()
            folded = relative.casefold()
            basename = path.name.casefold()
            if design_md is None and basename == "design.md":
                design_md = relative
            if package_json is None and basename == "package.json":
                package_json = relative
            if path.suffix.casefold() in {".htm", ".html"}:
                html.append(relative)
            if "token" in folded and path.suffix.casefold() in {
                ".css",
                ".json",
                ".toml",
                ".yaml",
                ".yml",
            }:
                token_files.append(relative)
    except OSError:
        return {}

    result: dict[str, Any] = {}
    if design_md is not None:
        result["designMd"] = design_md
    if package_json is not None:
        result["packageJson"] = package_json
    if html:
        result["html"] = sorted(html)
    if token_files:
        result["tokenFiles"] = sorted(token_files)
    return result


def design_system_summary(record: dict[str, Any]) -> dict[str, Any]:
    revisions = list(record.get("revisions") or [])
    generation = max(1, len(revisions))
    content_path = str(record.get("files_path") or record.get("path") or "")
    revision = str(record.get("sha256") or record.get("revision") or "")
    imported_at = revisions[-1].get("imported_at") if revisions else record.get("updated_at")
    original_filename = str(record.get("source_filename") or "design-system.zip")
    revision_manifest = str(Path(content_path).parent / "revision.json") if content_path else ""

    return {
        "schemaVersion": 1,
        "id": str(record.get("id") or ""),
        "name": str(record.get("name") or "Imported design system"),
        "description": "",
        "sourceKind": "claude-design-zip",
        "createdAt": _iso_timestamp(record.get("created_at")),
        "updatedAt": _iso_timestamp(record.get("updated_at")),
        "generation": generation,
        "activeRevision": revision,
        "activeRevisionInfo": {
            "sha256": revision,
            "importedAt": _iso_timestamp(imported_at),
            "originalFilename": original_filename,
            "archiveBytes": int(record.get("archive_size") or 0),
            "expandedBytes": int(record.get("expanded_size") or 0),
            "entryCount": int(record.get("file_count") or 0),
            "entrypoints": _entrypoints(content_path),
        },
        "contentPath": content_path,
        "revisionManifestPath": revision_manifest,
    }


def _raise_http_error(exc: Exception) -> None:
    if isinstance(exc, ArchiveValidationError):
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_archive", "message": str(exc)},
        ) from exc
    if isinstance(exc, DesignSystemConflictError):
        raise HTTPException(
            status_code=409,
            detail={"code": "stale_generation", "message": str(exc)},
        ) from exc
    if isinstance(exc, DesignSystemNotFoundError):
        raise HTTPException(
            status_code=404,
            detail={"code": "design_system_not_found", "message": "Design system not found"},
        ) from exc
    if isinstance(exc, DesignSystemStorageError):
        raise HTTPException(
            status_code=500,
            detail={"code": "design_system_storage_error", "message": str(exc)},
        ) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_request", "message": str(exc)},
        ) from exc
    raise exc


def _safe_upload_filename(value: str | None) -> str:
    filename = Path(value or "design-system.zip").name
    filename = "".join("_" if ord(char) < 32 or ord(char) == 127 else char for char in filename)
    if filename in {"", ".", ".."}:
        return "design-system.zip"
    return filename[:255]


def _library_for_profile(profile: str | None) -> DesignSystemLibrary:
    if not profile:
        return DesignSystemLibrary()

    from fabric_cli import profiles as profiles_mod

    try:
        name = profiles_mod.normalize_profile_name(profile.strip() or "default")
        profiles_mod.validate_profile_name(name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not profiles_mod.profile_exists(name):
        raise HTTPException(status_code=404, detail=f"Profile '{name}' does not exist.")
    return DesignSystemLibrary(profiles_mod.get_profile_dir(name))


def design_system_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/design-systems")
    async def list_managed_design_systems(profile: str | None = None):
        library = _library_for_profile(profile)
        try:
            records = await run_in_threadpool(library.list)
        except Exception as exc:
            _raise_http_error(exc)
            raise
        return {"systems": [design_system_summary(record) for record in records]}

    @router.get("/api/design-systems/{design_system_id}")
    async def get_managed_design_system(design_system_id: str, profile: str | None = None):
        library = _library_for_profile(profile)
        try:
            record = await run_in_threadpool(library.get, design_system_id)
        except Exception as exc:
            _raise_http_error(exc)
            raise
        if record is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "design_system_not_found", "message": "Design system not found"},
            )
        return {"system": design_system_summary(record)}

    @router.post("/api/design-systems/{design_system_id}/revisions")
    @router.post("/api/design-systems/import")
    async def import_managed_design_system(
        file: UploadFile = File(...),
        name: str | None = Form(None),
        design_system_id: str | None = None,
        replace_system_id: str | None = Form(None),
        expected_generation: int | None = Form(None),
        generation: int | None = Form(None),
        profile: str | None = None,
    ):
        library = _library_for_profile(profile)
        replace_system_id = design_system_id or replace_system_id
        expected_generation = expected_generation if expected_generation is not None else generation
        filename = _safe_upload_filename(file.filename)
        upload_directory = Path(tempfile.mkdtemp(prefix="fabric-design-system-upload-"))
        upload_directory.chmod(0o700)
        upload_path = upload_directory / filename
        total = 0

        try:
            with upload_path.open("xb") as out:
                os.chmod(upload_path, 0o600)
                while True:
                    chunk = await file.read(_UPLOAD_CHUNK_BYTES)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_ARCHIVE_BYTES:
                        raise HTTPException(
                            status_code=413,
                            detail={
                                "code": "archive_too_large",
                                "message": "Archive exceeds the import limit",
                            },
                        )
                    out.write(chunk)
                out.flush()
                os.fsync(out.fileno())

            try:
                if replace_system_id:
                    current = await run_in_threadpool(library.get, replace_system_id)
                    if current is None:
                        raise HTTPException(
                            status_code=404,
                            detail={
                                "code": "design_system_not_found",
                                "message": "Design system not found",
                            },
                        )
                    record = await run_in_threadpool(
                        functools.partial(
                            library.replace,
                            replace_system_id,
                            upload_path,
                            expected_generation=expected_generation,
                            name=name,
                        )
                    )
                    deduplicated = str(record.get("sha256")) == str(current.get("sha256"))
                else:
                    existing = await run_in_threadpool(library.list)
                    record = await run_in_threadpool(
                        functools.partial(library.import_archive, upload_path, name=name)
                    )
                    duplicate = next(
                        (item for item in existing if item.get("sha256") == record.get("sha256")),
                        None,
                    )
                    if duplicate is not None:
                        await run_in_threadpool(library.delete, str(record.get("id")))
                        record = duplicate
                    deduplicated = duplicate is not None
            except HTTPException:
                raise
            except Exception as exc:
                _raise_http_error(exc)
                raise
        finally:
            await file.close()
            shutil.rmtree(upload_directory, ignore_errors=True)

        return {
            "system": design_system_summary(record),
            "deduplicated": deduplicated,
            "warnings": [],
        }

    @router.delete("/api/design-systems/{design_system_id}")
    async def delete_managed_design_system(
        design_system_id: str,
        payload: DesignSystemDeleteRequest,
        profile: str | None = None,
    ):
        library = _library_for_profile(profile)
        try:
            deleted = await run_in_threadpool(
                functools.partial(
                    library.delete,
                    design_system_id,
                    expected_generation=payload.expectedGeneration,
                )
            )
        except HTTPException:
            raise
        except Exception as exc:
            _raise_http_error(exc)
            raise

        if not deleted:
            raise HTTPException(
                status_code=404,
                detail={"code": "design_system_not_found", "message": "Design system not found"},
            )
        return {"ok": True}

    return router
