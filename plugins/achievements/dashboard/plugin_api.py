"""Dashboard API for private Fabric achievements and manual share cards."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from fabric_constants import get_fabric_home
from fabric_cli.profiles import get_active_profile_name, profiles_to_serve
from plugins.achievements.engine import (
    AchievementEngine,
    PRIVACY_METADATA,
)
from plugins.achievements.share_cards import (
    MAX_SHARE_CARD_BYTES,
    ShareCardValidationError,
    create_share_card,
    parse_share_card,
    sanitize_display_name,
    validate_share_card,
)
from plugins.achievements.store import AchievementStateError, AchievementStore


router = APIRouter()


class ShareCardBody(BaseModel):
    display_name: str
    achievement_ids: Optional[list[str]] = None


class ResetBody(BaseModel):
    scope: Literal["imported_leaderboard"]
    confirm: bool


def _privacy() -> dict[str, Any]:
    return {
        key: list(value) if isinstance(value, list) else value
        for key, value in PRIVACY_METADATA.items()
    }


def _active_engine() -> AchievementEngine:
    return AchievementEngine(get_fabric_home())


def _profile_label(profile_name: str) -> str:
    if profile_name == "default":
        return "Default"
    if profile_name == "custom":
        return "Local Profile"
    return sanitize_display_name(profile_name.replace("_", " ").replace("-", " ").title())


def _profile_candidates() -> list[tuple[str, Path, bool]]:
    """List current + local Fabric profiles without exposing their paths."""
    current_home = get_fabric_home().resolve()
    current_name = get_active_profile_name()
    candidates: list[tuple[str, Path, bool]] = [
        (current_name, current_home, True)
    ]
    seen = {current_home}
    try:
        discovered = profiles_to_serve(multiplex=True)
    except Exception:
        discovered = []
    for name, raw_home in discovered:
        try:
            home = Path(raw_home).resolve()
        except OSError:
            continue
        if home in seen:
            continue
        seen.add(home)
        candidates.append((name, home, False))
    return candidates


def _local_leaderboard_entries() -> tuple[list[dict[str, Any]], int, int]:
    entries: list[dict[str, Any]] = []
    skipped = 0
    warning_count = 0
    for profile_name, home, is_current in _profile_candidates():
        try:
            if not is_current:
                # Cross-profile aggregation is strictly read-only.  A profile
                # without both existing files has no stable local row yet and
                # is skipped rather than initialised from this request.
                if not (home / "state.db").is_file():
                    skipped += 1
                    continue
                store = AchievementStore(home, read_only=True)
                if not store.ledger_path.is_file():
                    skipped += 1
                    continue
                engine = AchievementEngine(home, read_only=True)
                card_id = store.card_id(create=False)
                if card_id is None:
                    skipped += 1
                    continue
                display_name = store.local_display_name(
                    _profile_label(profile_name), create=False
                )
            else:
                engine = AchievementEngine(home)
                store = engine.store
                card_id = store.card_id()
                assert card_id is not None
                display_name = store.local_display_name(_profile_label(profile_name))

            # The current profile may reconcile normally.  Other profiles
            # combine their existing ledger with current aggregate evaluation
            # strictly in memory and are never written from this request.
            summary = (
                engine.refresh()
                if is_current
                else engine.summary(include_current_qualifiers=True)
            )
            warning_count += len(summary.get("warnings") or [])
            card = create_share_card(
                summary,
                card_id=card_id,
                display_name=display_name,
            )
            entries.append(
                {
                    "origin": "local_profile",
                    "is_current_profile": is_current,
                    "warning_count": len(summary.get("warnings") or []),
                    "card": card,
                }
            )
        except (AchievementStateError, OSError, ShareCardValidationError):
            skipped += 1
    return entries, skipped, warning_count


@router.get("/summary")
def get_summary() -> dict[str, Any]:
    try:
        # First-load reconciliation makes historical aggregate activity visible
        # immediately on a fresh install.  The ledger append is idempotent, and
        # the response keeps GET's summary shape (newly_earned is a refresh-only
        # response detail).
        summary = _active_engine().refresh()
        summary.pop("newly_earned", None)
        return summary
    except AchievementStateError as exc:
        raise HTTPException(status_code=500, detail="Achievement state is unavailable.") from exc


@router.post("/refresh")
def post_refresh() -> dict[str, Any]:
    try:
        return _active_engine().refresh()
    except AchievementStateError as exc:
        raise HTTPException(status_code=500, detail="Achievement state is unavailable.") from exc


@router.post("/share-card")
def post_share_card(body: ShareCardBody) -> dict[str, Any]:
    try:
        display_name = sanitize_display_name(body.display_name)
        engine = _active_engine()
        # Share is an explicit snapshot action, so evaluate and durably append
        # every currently-qualified milestone before exporting the card.
        summary = engine.refresh()
        card_id = engine.store.card_id()
        assert card_id is not None
        card = create_share_card(
            summary,
            card_id=card_id,
            display_name=display_name,
            achievement_ids=body.achievement_ids,
        )
        engine.store.set_local_display_name(display_name)
        return {"card": card, "privacy": _privacy()}
    except ShareCardValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AchievementStateError as exc:
        raise HTTPException(status_code=500, detail="Achievement state is unavailable.") from exc


@router.get("/leaderboard")
def get_leaderboard() -> dict[str, Any]:
    local_entries, skipped, warning_count = _local_leaderboard_entries()
    local_ids = {entry["card"]["card_id"] for entry in local_entries}
    entries = list(local_entries)
    invalid_imports = 0
    try:
        imported_cards = AchievementStore().list_imports()
    except AchievementStateError as exc:
        raise HTTPException(status_code=500, detail="Leaderboard state is unavailable.") from exc
    for raw_card in imported_cards:
        try:
            card = validate_share_card(raw_card)
        except ShareCardValidationError:
            invalid_imports += 1
            continue
        if card["card_id"] in local_ids:
            # A locally verifiable row always wins over a copied self-report.
            continue
        entries.append(
            {
                "origin": "self_reported_import",
                "is_current_profile": False,
                "warning_count": 0,
                "card": card,
            }
        )
    entries.sort(
        key=lambda entry: (
            -entry["card"]["score"],
            entry["card"]["display_name"].casefold(),
            entry["card"]["card_id"],
        )
    )
    return {
        "schema_version": 1,
        "entries": entries,
        "skipped_local_profiles": skipped,
        "warning_count": warning_count + invalid_imports,
        "privacy": _privacy(),
    }


@router.post("/leaderboard/import")
async def post_leaderboard_import(request: Request) -> dict[str, Any]:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_SHARE_CARD_BYTES:
                raise HTTPException(status_code=413, detail="Share card exceeds 16 KiB.")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid Content-Length.")
    # Do not fall back to ``request.body()``: a chunked request has no
    # Content-Length and would otherwise be buffered without a bound before
    # the card parser gets to enforce its 16 KiB contract.
    buffered = bytearray()
    async for chunk in request.stream():
        if len(buffered) + len(chunk) > MAX_SHARE_CARD_BYTES:
            raise HTTPException(status_code=413, detail="Share card exceeds 16 KiB.")
        buffered.extend(chunk)
    raw = bytes(buffered)
    try:
        card = parse_share_card(raw)
        store = AchievementStore()
        created = store.upsert_import(card)
        return {
            "ok": True,
            "created": created,
            "entry": {
                "origin": "self_reported_import",
                "is_current_profile": False,
                "warning_count": 0,
                "card": card,
            },
        }
    except ShareCardValidationError as exc:
        status_code = 413 if "16 KiB" in str(exc) else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except AchievementStateError as exc:
        raise HTTPException(status_code=500, detail="Leaderboard state is unavailable.") from exc


@router.delete("/leaderboard/{card_id}")
def delete_leaderboard_card(card_id: str) -> dict[str, Any]:
    # Reuse the public card validator's UUID rules without accepting a partial
    # card shape: UUID parsing here is intentionally narrow and path-safe.
    try:
        import uuid

        parsed = uuid.UUID(card_id)
        if str(parsed) != card_id.lower():
            raise ValueError
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="card_id must be a valid UUID.")
    try:
        deleted = AchievementStore().delete_import(str(parsed))
    except AchievementStateError as exc:
        raise HTTPException(status_code=500, detail="Leaderboard state is unavailable.") from exc
    return {"ok": True, "deleted": deleted}


@router.post("/reset")
def post_reset(body: ResetBody) -> dict[str, Any]:
    """Clear copied cards only; earned progress is intentionally immutable."""
    if not body.confirm:
        raise HTTPException(
            status_code=400,
            detail="confirm=true is required to reset imported leaderboard cards.",
        )
    try:
        removed = AchievementStore().reset_imports()
    except AchievementStateError as exc:
        raise HTTPException(status_code=500, detail="Leaderboard state is unavailable.") from exc
    return {
        "ok": True,
        "scope": "imported_leaderboard",
        "removed": removed,
        "progress_preserved": True,
    }


__all__ = ["router"]
