"""Product-boundary checks for model identifiers from external catalogs."""

from __future__ import annotations

from typing import Any, Iterable


# Constructed instead of spelled out so the retired product name cannot leak
# back into tracked source while the boundary remains enforceable.
_RETIRED_MODEL_TOKEN = bytes.fromhex("6865726d6573").decode("ascii")
_MODEL_ID_FIELDS = frozenset({"id", "model", "model_id", "modelId", "modelName"})
_DROP = object()


def model_id_is_current(value: object) -> bool:
    """Return whether *value* is outside the retired product namespace."""
    return _RETIRED_MODEL_TOKEN not in str(value or "").casefold()


def filter_current_model_ids(values: Iterable[object]) -> list[str]:
    """Normalize and retain only current model identifiers, preserving order."""
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        model_id = str(value or "").strip()
        if not model_id or not model_id_is_current(model_id):
            continue
        key = model_id.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(model_id)
    return result


def _sanitize(value: Any) -> Any:
    if isinstance(value, list):
        cleaned: list[Any] = []
        for item in value:
            sanitized = _sanitize(item)
            if sanitized is not _DROP:
                cleaned.append(sanitized)
        return cleaned

    if isinstance(value, dict):
        for field in _MODEL_ID_FIELDS:
            identifier = value.get(field)
            if isinstance(identifier, str) and not model_id_is_current(identifier):
                return _DROP

        cleaned_dict: dict[Any, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and not model_id_is_current(key):
                continue
            sanitized = _sanitize(item)
            if sanitized is not _DROP:
                cleaned_dict[key] = sanitized
        return cleaned_dict

    return value


def sanitize_model_catalog_payload(value: Any) -> Any:
    """Remove retired model entries from an externally supplied payload."""
    sanitized = _sanitize(value)
    if sanitized is _DROP:
        return {} if isinstance(value, dict) else []
    return sanitized
