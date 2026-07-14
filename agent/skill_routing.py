"""Deterministic, bounded routing for progressively disclosed skills.

The router is intentionally local and data-only.  It ranks the small metadata
surface already available for a skill and, when a verified contract is
present, its declared positive and negative triggers.  It never calls a model,
does not mutate the system prompt, and does not grant runtime authority.

Selection is a discovery aid rather than an activation mechanism: callers
still load the chosen skill through the existing ``skill_view`` path.  Keeping
those two steps separate preserves Fabric's narrow waist and prompt-cache
stability while allowing the catalog to grow beyond what should be embedded in
every conversation prefix.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.skill_contract import validate_skill_directory


MAX_ROUTING_QUERY_CHARS = 4096
DEFAULT_ROUTING_LIMIT = 8
MAX_ROUTING_LIMIT = 20
MAX_ROUTING_REASON_COUNT = 4

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_ROUTING_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "for",
        "in",
        "of",
        "on",
        "or",
        "the",
        "to",
        "with",
    }
)


@dataclass(frozen=True)
class RoutedSkill:
    """One ranked skill candidate with bounded, machine-readable reasons."""

    name: str
    description: str
    category: str | None
    score: float
    reasons: tuple[str, ...]
    contract_status: str

    def to_public_dict(self) -> dict[str, Any]:
        """Return the minimal JSON-safe result exposed by ``skills_list``."""

        result: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "routing_score": round(self.score, 3),
            "routing_reasons": list(self.reasons),
            "contract_status": self.contract_status,
        }
        return result


@dataclass(frozen=True)
class _RoutingMetadata:
    triggers: tuple[str, ...]
    non_triggers: tuple[str, ...]
    precedence: int
    status: str


def rank_skill_candidates(
    query: str,
    skills: Iterable[Mapping[str, Any]],
    *,
    limit: int = DEFAULT_ROUTING_LIMIT,
) -> tuple[RoutedSkill, ...]:
    """Rank skill metadata for *query* without model inference or side effects.

    Each skill mapping may contain ``name``, ``description``, ``category``, and
    an internal ``skill_dir``/``_skill_dir`` path.  A valid adjacent contract
    contributes declared triggers, non-triggers, and precedence.  Invalid or
    missing contracts remain discoverable through legacy metadata but never
    receive verified-trigger boosts.

    Stable tie-breaking is ``score desc, category, name``.  Zero-signal
    candidates are omitted, and a matching declared non-trigger vetoes a
    candidate.  The function reads at most one bounded contract per candidate;
    validation itself has strict size/depth/symlink limits.
    """

    normalized_query = _normalize(query)[:MAX_ROUTING_QUERY_CHARS]
    query_tokens = frozenset(_tokens(normalized_query))
    if not normalized_query or not query_tokens:
        return ()
    if type(limit) is not int:
        limit = DEFAULT_ROUTING_LIMIT
    limit = max(1, min(limit, MAX_ROUTING_LIMIT))

    routed: list[RoutedSkill] = []
    seen: set[str] = set()
    for raw in skills:
        name = str(raw.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        description = str(raw.get("description") or "").strip()
        category_value = raw.get("category")
        category = str(category_value).strip() if category_value else None
        metadata = _routing_metadata(raw)
        score, reasons, vetoed = _score_candidate(
            normalized_query,
            query_tokens,
            name=name,
            description=description,
            category=category,
            metadata=metadata,
        )
        if vetoed or score <= 0:
            continue
        routed.append(
            RoutedSkill(
                name=name,
                description=description,
                category=category,
                score=score,
                reasons=tuple(reasons[:MAX_ROUTING_REASON_COUNT]),
                contract_status=metadata.status,
            )
        )

    routed.sort(
        key=lambda item: (
            -item.score,
            item.category or "",
            item.name,
        )
    )
    return tuple(routed[:limit])


def _routing_metadata(skill: Mapping[str, Any]) -> _RoutingMetadata:
    raw_path = skill.get("skill_dir", skill.get("_skill_dir"))
    if not isinstance(raw_path, (str, Path)) or not str(raw_path).strip():
        return _RoutingMetadata((), (), 0, "legacy_unverified")
    skill_dir = Path(raw_path)
    contract_path = skill_dir / "skill.contract.yaml"
    # The migration corpus is mostly legacy. Avoid re-reading every SKILL.md
    # on each query when no contract exists; present contracts still go
    # through the complete fail-closed validator below (including symlinks).
    if not contract_path.exists() and not contract_path.is_symlink():
        return _RoutingMetadata((), (), 0, "legacy_unverified")
    try:
        validation = validate_skill_directory(skill_dir, require_contract=False)
    except Exception:
        return _RoutingMetadata((), (), 0, "invalid")
    if validation.status != "verified" or not isinstance(validation.contract, Mapping):
        return _RoutingMetadata((), (), 0, validation.status)
    routing = validation.contract.get("routing")
    if not isinstance(routing, Mapping):
        return _RoutingMetadata((), (), 0, "invalid")
    triggers = _bounded_strings(routing.get("triggers"))
    non_triggers = _bounded_strings(routing.get("non_triggers"))
    precedence = routing.get("precedence", 0)
    if type(precedence) is not int:
        precedence = 0
    return _RoutingMetadata(triggers, non_triggers, precedence, "verified")


def _score_candidate(
    query: str,
    query_tokens: frozenset[str],
    *,
    name: str,
    description: str,
    category: str | None,
    metadata: _RoutingMetadata,
) -> tuple[float, list[str], bool]:
    normalized_name = _normalize(name.replace("-", " ").replace("_", " "))
    name_tokens = frozenset(_tokens(normalized_name))
    normalized_description = _normalize(description)
    description_tokens = frozenset(_tokens(normalized_description))
    normalized_category = _normalize((category or "").replace("/", " "))
    category_tokens = frozenset(_tokens(normalized_category))

    for negative in metadata.non_triggers:
        if _strong_match(query, query_tokens, negative):
            return 0.0, ["declared_non_trigger"], True

    score = 0.0
    reasons: list[str] = []

    if normalized_name and normalized_name in query:
        score += 100.0
        reasons.append("name_phrase")
    else:
        coverage = _coverage(name_tokens, query_tokens)
        if coverage:
            score += 38.0 * coverage
            reasons.append("name_terms")

    best_trigger_score = 0.0
    best_trigger_reason = ""
    for trigger in metadata.triggers:
        normalized_trigger = _normalize(trigger)
        trigger_tokens = frozenset(_tokens(normalized_trigger))
        if not trigger_tokens:
            continue
        if normalized_trigger and normalized_trigger in query:
            candidate_score = 90.0
            candidate_reason = "declared_trigger_phrase"
        else:
            # Favour coverage of the declared trigger, but require at least
            # one material term.  Single stopword-like overlaps cannot win on
            # their own because zero-signal results are filtered below.
            coverage = _coverage(trigger_tokens, query_tokens)
            specificity = min(1.0, len(trigger_tokens) / 4.0)
            candidate_score = 62.0 * coverage * (0.75 + 0.25 * specificity)
            candidate_reason = "declared_trigger_terms"
        if candidate_score > best_trigger_score:
            best_trigger_score = candidate_score
            best_trigger_reason = candidate_reason
    if best_trigger_score > 0:
        score += best_trigger_score
        reasons.append(best_trigger_reason)

    description_overlap = _coverage(query_tokens, description_tokens)
    if description_overlap:
        score += 28.0 * description_overlap
        reasons.append("description_terms")

    category_overlap = _coverage(query_tokens, category_tokens)
    if category_overlap:
        score += 10.0 * category_overlap
        reasons.append("category_terms")

    if score > 0 and metadata.status == "verified":
        # Precedence only breaks otherwise-relevant candidates.  It cannot
        # make an unrelated skill appear and is deliberately a small factor.
        score += max(-100, min(metadata.precedence, 100)) / 100.0

    # Round here to keep ordering deterministic across Python builds and
    # avoid exposing meaningless floating-point noise in receipts/results.
    return math.floor(score * 1000.0 + 0.5) / 1000.0, reasons, False


def _strong_match(query: str, query_tokens: frozenset[str], phrase: str) -> bool:
    normalized = _normalize(phrase)
    if not normalized:
        return False
    if normalized in query:
        return True
    phrase_tokens = frozenset(_tokens(normalized))
    if len(phrase_tokens) < 2:
        return phrase_tokens == query_tokens
    return _coverage(phrase_tokens, query_tokens) >= 0.8


def _coverage(needles: frozenset[str], haystack: frozenset[str]) -> float:
    if not needles or not haystack:
        return 0.0
    return len(needles & haystack) / len(needles)


def _bounded_strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    result: list[str] = []
    for item in value[:128]:
        if isinstance(item, str) and item.strip():
            result.append(item.strip()[:512])
    return tuple(result)


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value)).casefold()
    return " ".join(_TOKEN_RE.findall(normalized))


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(
        token for token in _TOKEN_RE.findall(value) if token not in _ROUTING_STOPWORDS
    )


__all__ = [
    "DEFAULT_ROUTING_LIMIT",
    "MAX_ROUTING_LIMIT",
    "RoutedSkill",
    "rank_skill_candidates",
]
