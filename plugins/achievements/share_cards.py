"""Strict, portable share cards for the local/manual leaderboard."""

from __future__ import annotations

import json
import math
import unicodedata
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence

from .catalog import CATEGORIES, MILESTONES, MILESTONES_BY_ID, TOTAL_POINTS
from .store import utc_now


SHARE_CARD_SCHEMA_VERSION = 1
MAX_SHARE_CARD_BYTES = 16 * 1024
MAX_DISPLAY_NAME_CHARS = 40
MAX_HIGHLIGHT_IDS = 5

_REQUIRED_FIELDS = frozenset(
    {
        "schema_version",
        "card_id",
        "display_name",
        "generated_at",
        "score",
        "earned_count",
        "category_totals",
    }
)
_OPTIONAL_FIELDS = frozenset({"achievement_ids"})


class ShareCardValidationError(ValueError):
    """A share card failed its bounded public schema."""


def _strict_int(value: object, *, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        # Explicit finite check gives a stable rejection for NaN/Infinity even
        # when a caller passes a Python object instead of encoded JSON.
        if isinstance(value, float) and not math.isfinite(value):
            raise ShareCardValidationError(f"{field} must be finite")
        raise ShareCardValidationError(f"{field} must be an integer")
    if value < minimum or value > maximum:
        raise ShareCardValidationError(f"{field} is out of bounds")
    return value


def sanitize_display_name(value: object) -> str:
    if not isinstance(value, str):
        raise ShareCardValidationError("display_name must be a string")
    normalized = unicodedata.normalize("NFKC", value)
    cleaned = "".join(
        " " if unicodedata.category(character).startswith("C") else character
        for character in normalized
    )
    cleaned = " ".join(cleaned.split())
    if not cleaned or len(cleaned) > MAX_DISPLAY_NAME_CHARS:
        raise ShareCardValidationError("display_name must contain 1 to 40 characters")
    return cleaned


def _canonical_uuid(value: object) -> str:
    if not isinstance(value, str):
        raise ShareCardValidationError("card_id must be a UUID string")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ShareCardValidationError("card_id must be a valid UUID") from exc
    canonical = str(parsed)
    if value.lower() != canonical:
        raise ShareCardValidationError("card_id must use canonical UUID form")
    return canonical


def _canonical_timestamp(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ShareCardValidationError("generated_at must be an ISO timestamp")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ShareCardValidationError("generated_at must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ShareCardValidationError("generated_at must include a timezone")
    if parsed.year < 2000 or parsed.year > 2100:
        raise ShareCardValidationError("generated_at is out of bounds")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_size(value: Mapping[str, Any]) -> int:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ShareCardValidationError("share card must be valid JSON") from exc
    return len(encoded)


def _pairs_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ShareCardValidationError(f"duplicate key: {key}")
        result[key] = value
    return result


def parse_share_card(raw: bytes | str | Mapping[str, Any]) -> dict[str, Any]:
    """Parse and validate a card, enforcing the byte cap before JSON decode."""
    if isinstance(raw, bytes):
        encoded = raw
        if len(encoded) > MAX_SHARE_CARD_BYTES:
            raise ShareCardValidationError("share card exceeds 16 KiB")
        try:
            text = encoded.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ShareCardValidationError("share card must be UTF-8 JSON") from exc
        try:
            value = json.loads(
                text,
                object_pairs_hook=_pairs_without_duplicates,
                parse_constant=lambda constant: (_ for _ in ()).throw(
                    ShareCardValidationError(f"non-finite JSON value: {constant}")
                ),
            )
        except json.JSONDecodeError as exc:
            raise ShareCardValidationError("share card must be valid JSON") from exc
    elif isinstance(raw, str):
        return parse_share_card(raw.encode("utf-8"))
    elif isinstance(raw, Mapping):
        value = dict(raw)
        if _json_size(value) > MAX_SHARE_CARD_BYTES:
            raise ShareCardValidationError("share card exceeds 16 KiB")
    else:
        raise ShareCardValidationError("share card must be a JSON object")
    if not isinstance(value, dict):
        raise ShareCardValidationError("share card must be a JSON object")
    return validate_share_card(value)


def validate_share_card(value: Mapping[str, Any]) -> dict[str, Any]:
    keys = frozenset(value.keys())
    missing = _REQUIRED_FIELDS - keys
    unknown = keys - _REQUIRED_FIELDS - _OPTIONAL_FIELDS
    if missing:
        raise ShareCardValidationError(
            "share card is missing required fields: " + ", ".join(sorted(missing))
        )
    if unknown:
        raise ShareCardValidationError(
            "share card has unknown fields: " + ", ".join(sorted(map(str, unknown)))
        )
    schema_version = _strict_int(
        value.get("schema_version"),
        field="schema_version",
        minimum=SHARE_CARD_SCHEMA_VERSION,
        maximum=SHARE_CARD_SCHEMA_VERSION,
    )
    score = _strict_int(
        value.get("score"), field="score", minimum=0, maximum=TOTAL_POINTS
    )
    earned_count = _strict_int(
        value.get("earned_count"),
        field="earned_count",
        minimum=0,
        maximum=len(MILESTONES),
    )
    if earned_count == 0 and score != 0:
        raise ShareCardValidationError("zero earned_count requires a zero score")
    if earned_count > 0 and not (10 * earned_count <= score <= 50 * earned_count):
        raise ShareCardValidationError("score is inconsistent with earned_count")

    raw_totals = value.get("category_totals")
    if not isinstance(raw_totals, Mapping):
        raise ShareCardValidationError("category_totals must be an object")
    if len(raw_totals) > len(CATEGORIES):
        raise ShareCardValidationError("category_totals has too many keys")
    category_totals: dict[str, int] = {}
    for raw_key, raw_total in raw_totals.items():
        if not isinstance(raw_key, str) or raw_key not in CATEGORIES:
            raise ShareCardValidationError("category_totals contains an unknown category")
        category_totals[raw_key] = _strict_int(
            raw_total,
            field=f"category_totals.{raw_key}",
            minimum=0,
            maximum=TOTAL_POINTS,
        )
    if sum(category_totals.values()) != score:
        raise ShareCardValidationError("category_totals must add up to score")

    card: dict[str, Any] = {
        "schema_version": schema_version,
        "card_id": _canonical_uuid(value.get("card_id")),
        "display_name": sanitize_display_name(value.get("display_name")),
        "generated_at": _canonical_timestamp(value.get("generated_at")),
        "score": score,
        "earned_count": earned_count,
        "category_totals": category_totals,
    }

    if "achievement_ids" in value:
        raw_ids = value.get("achievement_ids")
        if not isinstance(raw_ids, list):
            raise ShareCardValidationError("achievement_ids must be a list")
        if len(raw_ids) > MAX_HIGHLIGHT_IDS:
            raise ShareCardValidationError("achievement_ids may contain at most 5 ids")
        if any(not isinstance(item, str) for item in raw_ids):
            raise ShareCardValidationError("achievement_ids must contain strings")
        if len(set(raw_ids)) != len(raw_ids):
            raise ShareCardValidationError("achievement_ids must be unique")
        if any(item not in MILESTONES_BY_ID for item in raw_ids):
            raise ShareCardValidationError("achievement_ids contains an unknown catalog id")
        if len(raw_ids) > earned_count:
            raise ShareCardValidationError("achievement_ids exceeds earned_count")
        card["achievement_ids"] = list(raw_ids)

    if _json_size(card) > MAX_SHARE_CARD_BYTES:
        raise ShareCardValidationError("share card exceeds 16 KiB")
    return card


def _earned_ids_from_summary(summary: Mapping[str, Any]) -> list[str]:
    earned: list[str] = []
    tracks = summary.get("tracks")
    if not isinstance(tracks, list):
        return earned
    for track in tracks:
        if not isinstance(track, Mapping):
            continue
        milestones = track.get("milestones")
        if not isinstance(milestones, list):
            continue
        for milestone in milestones:
            if (
                isinstance(milestone, Mapping)
                and milestone.get("earned") is True
                and isinstance(milestone.get("id"), str)
                and milestone["id"] in MILESTONES_BY_ID
            ):
                earned.append(str(milestone["id"]))
    return earned


def create_share_card(
    summary: Mapping[str, Any],
    *,
    card_id: str,
    display_name: object,
    achievement_ids: Optional[Sequence[str]] = None,
) -> dict[str, Any]:
    """Create a validated card from earned milestones in a summary."""
    earned_ids = _earned_ids_from_summary(summary)
    earned_set = set(earned_ids)
    if achievement_ids is None:
        highlights = sorted(
            earned_ids,
            key=lambda item: (-MILESTONES_BY_ID[item].points, item),
        )[:MAX_HIGHLIGHT_IDS]
    else:
        highlights = list(achievement_ids)
        if len(highlights) > MAX_HIGHLIGHT_IDS:
            raise ShareCardValidationError("achievement_ids may contain at most 5 ids")
        if any(not isinstance(item, str) for item in highlights):
            raise ShareCardValidationError("achievement_ids must contain strings")
        if len(set(highlights)) != len(highlights):
            raise ShareCardValidationError("achievement_ids must be unique")
        if any(item not in earned_set for item in highlights):
            raise ShareCardValidationError("achievement_ids must already be earned")

    category_totals = {category: 0 for category in CATEGORIES}
    score = 0
    for achievement_id in earned_ids:
        milestone = MILESTONES_BY_ID[achievement_id]
        score += milestone.points
        category_totals[milestone.category] += milestone.points
    card: dict[str, Any] = {
        "schema_version": SHARE_CARD_SCHEMA_VERSION,
        "card_id": card_id,
        "display_name": display_name,
        "generated_at": utc_now(),
        "score": score,
        "earned_count": len(earned_ids),
        "category_totals": category_totals,
    }
    if highlights:
        card["achievement_ids"] = highlights
    return validate_share_card(card)


def serialize_share_card(card: Mapping[str, Any]) -> str:
    validated = validate_share_card(card)
    return json.dumps(
        validated,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


__all__ = [
    "MAX_DISPLAY_NAME_CHARS",
    "MAX_HIGHLIGHT_IDS",
    "MAX_SHARE_CARD_BYTES",
    "SHARE_CARD_SCHEMA_VERSION",
    "ShareCardValidationError",
    "create_share_card",
    "parse_share_card",
    "sanitize_display_name",
    "serialize_share_card",
    "validate_share_card",
]
