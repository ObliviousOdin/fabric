"""Turn-scoped runtime permission leases for governed Fabric skills.

The model tool schema and system prompt are intentionally absent from this
module.  A successful ``skill_view`` activation records the verified skill
contract in a bounded, process-local registry keyed by the current turn.  The
existing dispatcher can then ask for a closed allow/block/approve decision
before executing a tool.

This is a capability guard, not a shell parser.  File and URL checks are
enforced only for tool arguments whose semantics are structurally known.  Raw
terminal commands, arbitrary Python passed to ``execute_code``, browser actions
that can navigate indirectly, and provider-owned tools expose stable
observation-gap codes instead of being misrepresented as fully inspected.

Privacy boundary: leases are volatile and bounded.  Decisions and observation
snapshots contain only canonical skill/tool names, contract digests, counters,
and stable codes.  Tool arguments, prompts, URL values, secret values, and
invoked file paths are never copied into a decision, log, or persistent store.
"""

from __future__ import annotations

import hashlib
import ipaddress
import os
import re
import tempfile
import threading
import time
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from pathlib import Path, PureWindowsPath
from typing import Any, Literal
from urllib.parse import urlsplit


OBSERVE = "observe"
ENFORCE_LEARNED = "enforce_learned"
ENFORCE_ALL = "enforce_all"
PERMISSION_MODES = frozenset({OBSERVE, ENFORCE_LEARNED, ENFORCE_ALL})

_MAX_ACTIVE_TURNS = 256
_MAX_LEASES_PER_TURN = 16
_MAX_STAGED_SCOPES = 256
_TURN_TTL_SECONDS = 4 * 60 * 60
_MAX_SCOPE_ID_BYTES = 1024

_ACCESS_BITS = {"read": 1, "write": 2, "read_write": 3}
_LANE_ORDER = {
    "standard": 1,
    "elevated": 2,
    "approval_required": 3,
    "restricted": 4,
    "unknown": 5,
}
_OPAQUE_EFFECT_TOOLSETS = frozenset(
    {
        "browser",
        "code_execution",
        "context_engine",
        "delegation",
        "memory",
        "skills",
        "terminal",
        "web",
    }
)
_FILE_TOOL_ACCESS = {
    "read_file": ("path", "read"),
    "search_files": ("path", "read"),
    "write_file": ("path", "write"),
}
_PATCH_HEADER_RE = re.compile(
    r"^\*\*\*\s+(?:Update|Add|Delete)\s+File:\s*(.+)$", re.MULTILINE
)
_PATCH_MOVE_RE = re.compile(
    r"^\*\*\*\s+Move\s+File:\s*(.+?)\s*->\s*(.+)$", re.MULTILINE
)
_BROWSER_STATEFUL_TOOLS = frozenset(
    {
        "browser_back",
        "browser_click",
        "browser_press",
        "browser_scroll",
        "browser_type",
    }
)


@dataclass(frozen=True)
class PermissionSettings:
    """Runtime rollout settings resolved from ``config.yaml``."""

    mode: str = OBSERVE


@dataclass(frozen=True)
class SkillActivationDecision:
    """Closed result of attempting to establish one permission lease."""

    action: Literal["activated", "observed", "blocked"]
    code: str
    mode: str
    contract_status: str
    provenance: str
    lane: str

    @property
    def allowed(self) -> bool:
        return self.action != "blocked"


@dataclass(frozen=True)
class SkillPermissionDecision:
    """Privacy-safe dispatcher decision for one tool attempt."""

    action: Literal["allow", "block", "approve"]
    code: str
    mode: str
    effective_lane: str
    observations: tuple[str, ...] = ()
    approval_key: str | None = None
    active_skill_count: int = 0
    enforced_skill_count: int = 0

    @property
    def blocked(self) -> bool:
        return self.action == "block"

    @property
    def approval_required(self) -> bool:
        return self.action == "approve"


@dataclass
class _SkillLease:
    lease_id: str
    skill_name: str
    contract_digest: str | None
    contract_status: str
    provenance: str
    lane: str
    mode: str
    enforced: bool
    toolsets: frozenset[str]
    file_access: dict[str, int]
    network: dict[str, frozenset[str]]
    approvals: frozenset[str]
    prohibitions: frozenset[str]
    declares_secrets: bool
    context_token_limit: int | None
    wall_seconds_limit: int | None
    tool_call_limit: int | None
    activated_at: float
    workspace_root: Path
    skill_root: Path
    temp_root: Path
    tool_calls_used: int = 0


@dataclass
class _TurnLeases:
    turn_id: str
    task_id: str | None
    session_id: str | None
    created_at: float
    updated_at: float
    leases: OrderedDict[str, _SkillLease] = field(default_factory=OrderedDict)
    observations: set[str] = field(default_factory=set)


@dataclass
class _StagedLeases:
    updated_at: float
    leases: OrderedDict[str, _SkillLease] = field(default_factory=OrderedDict)
    observations: set[str] = field(default_factory=set)


@dataclass
class _EvictedTurn:
    turn_id: str
    task_id: str | None
    session_id: str | None
    updated_at: float
    mode: str
    lane: str
    enforced: bool


_REGISTRY_LOCK = threading.RLock()
_TURN_LEASES: OrderedDict[str, _TurnLeases] = OrderedDict()
_PENDING_TURN_LEASES: OrderedDict[str, _StagedLeases] = OrderedDict()
_SESSION_LEASE_TEMPLATES: OrderedDict[str, _StagedLeases] = OrderedDict()
_EVICTED_TURNS: OrderedDict[str, _EvictedTurn] = OrderedDict()
_CURRENT_PERMISSION_TURNS: ContextVar[tuple[str, ...]] = ContextVar(
    "fabric_skill_permission_turns", default=()
)


def load_permission_settings(
    config: Mapping[str, Any] | None = None,
) -> PermissionSettings:
    """Resolve the staged rollout mode, defaulting malformed values safely."""

    if config is None:
        try:
            from fabric_cli.config import load_config_readonly

            config = load_config_readonly()
        except Exception:
            config = {}
    skills = config.get("skills") if isinstance(config, Mapping) else None
    raw = skills.get("permissions") if isinstance(skills, Mapping) else None
    raw = raw if isinstance(raw, Mapping) else {}
    mode = raw.get("mode", OBSERVE)
    if not isinstance(mode, str) or mode not in PERMISSION_MODES:
        mode = OBSERVE
    return PermissionSettings(mode=mode)


def _prepare_skill_permission_lease(
    *,
    skill_dir: Path,
    canonical_name: str,
    workspace_root: Path | None,
    config: Mapping[str, Any] | None,
) -> tuple[SkillActivationDecision, _SkillLease | None]:
    """Validate one contract and materialize authority without registering it."""

    settings = load_permission_settings(config)
    safe_name = _canonical_public_name(canonical_name)
    provenance = _classify_provenance(Path(skill_dir), safe_name)
    enforced = _provenance_is_enforced(settings.mode, provenance)

    try:
        from agent.skill_contract import validate_skill_directory

        validation = validate_skill_directory(Path(skill_dir))
        status = validation.status
        contract = validation.contract if status == "verified" else None
        contract_digest = validation.digest if status == "verified" else None
    except Exception:
        status = "invalid"
        contract = None
        contract_digest = None

    lane = derive_skill_risk_lane(contract, status)
    if enforced and status != "verified":
        return (
            SkillActivationDecision(
                "blocked",
                "contract_not_verified",
                settings.mode,
                status,
                provenance,
                lane,
            ),
            None,
        )

    try:
        lease = _lease_from_contract(
            skill_dir=Path(skill_dir),
            skill_name=safe_name,
            contract=contract,
            contract_digest=contract_digest,
            contract_status=status,
            provenance=provenance,
            lane=lane,
            mode=settings.mode,
            enforced=enforced,
            workspace_root=workspace_root,
        )
    except Exception:
        return (
            SkillActivationDecision(
                "blocked" if enforced else "observed",
                "lease_root_unsafe",
                settings.mode,
                "invalid" if enforced else status,
                provenance,
                "unknown" if enforced else lane,
            ),
            None,
        )

    return (
        SkillActivationDecision(
            "activated" if enforced else "observed",
            "lease_active" if enforced else "lease_observing",
            settings.mode,
            status,
            provenance,
            lane,
        ),
        lease,
    )


def _resolve_task_workspace_root(scope_id: str | None) -> Path | None:
    """Resolve the workspace root the file tools resolve relative paths against.

    A skill's ``workspace`` file grant authorizes relative ``write_file`` /
    ``patch`` / ``search_files`` paths, but those tools resolve the same relative
    paths against the task's authoritative workspace root (a registered
    TUI/Desktop/ACP workspace, or the live terminal cwd), which can differ from
    the Python process cwd. Binding the lease to that same anchor keeps an
    enforced ``workspace`` grant aligned with where paths actually land, instead
    of authorizing/denying against an unrelated process cwd. Returns ``None`` when
    no anchor is known, so ``_lease_from_contract`` keeps its process-cwd default.
    """

    if not scope_id:
        return None
    try:
        from tools.file_tools import _authoritative_workspace_root

        anchor = _authoritative_workspace_root(str(scope_id))
    except Exception:
        return None
    return Path(anchor) if anchor else None


def activate_skill_permission_lease(
    *,
    skill_dir: Path,
    canonical_name: str,
    turn_id: str | None,
    task_id: str | None = None,
    session_id: str | None = None,
    workspace_root: Path | None = None,
    config: Mapping[str, Any] | None = None,
) -> SkillActivationDecision:
    """Validate *skill_dir* and establish its bounded turn-scoped lease.

    Invalid and legacy skills stay loadable in ``observe`` mode.  In either
    enforcement mode they fail closed only when their provenance belongs to
    that mode's enforced population.
    """

    if workspace_root is None:
        workspace_root = _resolve_task_workspace_root(task_id or session_id)
    decision, lease = _prepare_skill_permission_lease(
        skill_dir=skill_dir,
        canonical_name=canonical_name,
        workspace_root=workspace_root,
        config=config,
    )
    if lease is None:
        return decision

    normalized_turn = _bounded_scope_id(turn_id)
    if normalized_turn is None:
        return replace(
            decision,
            action="blocked" if lease.enforced else "observed",
            code="turn_id_required" if lease.enforced else "turn_id_missing",
        )

    now = time.monotonic()
    with _REGISTRY_LOCK:
        _cleanup_locked(now)
        state = _TURN_LEASES.get(normalized_turn)
        if state is None:
            _EVICTED_TURNS.pop(normalized_turn, None)
            state = _TurnLeases(
                turn_id=normalized_turn,
                task_id=_bounded_scope_id(task_id),
                session_id=_bounded_scope_id(session_id),
                created_at=now,
                updated_at=now,
            )
            _TURN_LEASES[normalized_turn] = state
        if lease.lease_id not in state.leases:
            if len(state.leases) >= _MAX_LEASES_PER_TURN:
                state.observations.add("lease_capacity_exceeded")
                return replace(
                    decision,
                    action="blocked" if lease.enforced else "observed",
                    code="lease_capacity_exceeded",
                )
            state.leases[lease.lease_id] = lease
            state.observations.update(_declaration_observation_codes(lease))
        state.updated_at = now
        _TURN_LEASES.move_to_end(normalized_turn)
        _enforce_registry_bound_locked()

    return decision


def stage_skill_permission_lease(
    *,
    skill_dir: Path,
    canonical_name: str,
    scope_id: str | None,
    session_wide: bool = False,
    workspace_root: Path | None = None,
    config: Mapping[str, Any] | None = None,
) -> SkillActivationDecision:
    """Stage a pre-turn slash/bundle/preload activation for later binding.

    Slash expansion happens before ``build_turn_context`` creates a turn id.
    The caller already has a session/task scope, so this function validates the
    same lease immediately, keeps it in a bounded volatile queue, and lets the
    turn prologue bind it to the concrete id.  Session-wide preloads are copied
    into every later turn; ordinary slash/bundle activations are consumed once.
    """

    if workspace_root is None:
        workspace_root = _resolve_task_workspace_root(scope_id)
    decision, lease = _prepare_skill_permission_lease(
        skill_dir=skill_dir,
        canonical_name=canonical_name,
        workspace_root=workspace_root,
        config=config,
    )
    if lease is None:
        return decision
    normalized_scope = _bounded_scope_id(scope_id)
    if normalized_scope is None:
        return replace(
            decision,
            action="blocked" if lease.enforced else "observed",
            code="scope_id_required" if lease.enforced else "scope_id_missing",
        )

    now = time.monotonic()
    with _REGISTRY_LOCK:
        _cleanup_staged_locked(now)
        registry = (
            _SESSION_LEASE_TEMPLATES if session_wide else _PENDING_TURN_LEASES
        )
        staged = registry.get(normalized_scope)
        if staged is None:
            if len(registry) >= _MAX_STAGED_SCOPES:
                return replace(
                    decision,
                    action="blocked" if decision.action == "activated" else "observed",
                    code="staged_registry_capacity_exceeded",
                )
            staged = _StagedLeases(updated_at=now)
            registry[normalized_scope] = staged
        if lease.lease_id not in staged.leases:
            if len(staged.leases) >= _MAX_LEASES_PER_TURN:
                return replace(
                    decision,
                    action="blocked" if lease.enforced else "observed",
                    code="lease_capacity_exceeded",
                )
            staged.leases[lease.lease_id] = replace(lease, tool_calls_used=0)
        staged.observations.update(_declaration_observation_codes(lease))
        staged.updated_at = now
        registry.move_to_end(normalized_scope)
    return replace(
        decision,
        code="session_lease_staged" if session_wide else "turn_lease_staged",
    )


def bind_staged_skill_permission_leases(
    *,
    turn_id: str,
    task_id: str | None = None,
    session_id: str | None = None,
) -> int:
    """Bind staged slash/preload leases to *turn_id* and return their count."""

    normalized_turn = _bounded_scope_id(turn_id)
    if normalized_turn is None:
        return 0
    current_stack = _CURRENT_PERMISSION_TURNS.get()
    if not current_stack or current_stack[-1] != normalized_turn:
        _CURRENT_PERMISSION_TURNS.set((*current_stack, normalized_turn))
    scopes = []
    for raw in (session_id, task_id):
        normalized = _bounded_scope_id(raw)
        if normalized is not None and normalized not in scopes:
            scopes.append(normalized)
    if not scopes:
        return 0

    now = time.monotonic()
    with _REGISTRY_LOCK:
        _cleanup_locked(now)
        _cleanup_staged_locked(now)
        collected: OrderedDict[str, _SkillLease] = OrderedDict()
        observations: set[str] = set()
        for scope in scopes:
            template = _SESSION_LEASE_TEMPLATES.get(scope)
            if template is not None:
                for lease_id, lease in template.leases.items():
                    collected.setdefault(
                        lease_id,
                        replace(lease, tool_calls_used=0, activated_at=now),
                    )
                observations.update(template.observations)
                template.updated_at = now
                _SESSION_LEASE_TEMPLATES.move_to_end(scope)
            pending = _PENDING_TURN_LEASES.pop(scope, None)
            if pending is not None:
                for lease_id, lease in pending.leases.items():
                    collected.setdefault(
                        lease_id,
                        replace(lease, tool_calls_used=0, activated_at=now),
                    )
                observations.update(pending.observations)
        if not collected:
            return 0

        state = _TURN_LEASES.get(normalized_turn)
        existing_ids = set(state.leases) if state is not None else set()
        incoming_count = sum(
            lease_id not in existing_ids for lease_id in collected
        )
        if len(existing_ids) + incoming_count > _MAX_LEASES_PER_TURN:
            if any(lease.enforced for lease in collected.values()):
                raise RuntimeError("skill permission lease capacity exceeded")
        if state is None:
            _EVICTED_TURNS.pop(normalized_turn, None)
            state = _TurnLeases(
                turn_id=normalized_turn,
                task_id=_bounded_scope_id(task_id),
                session_id=_bounded_scope_id(session_id),
                created_at=now,
                updated_at=now,
            )
            _TURN_LEASES[normalized_turn] = state
        bound = 0
        for lease_id, lease in collected.items():
            if lease_id in state.leases:
                continue
            if len(state.leases) >= _MAX_LEASES_PER_TURN:
                state.observations.add("lease_capacity_exceeded")
                break
            state.leases[lease_id] = lease
            bound += 1
        state.observations.update(observations)
        state.updated_at = now
        _TURN_LEASES.move_to_end(normalized_turn)
        _enforce_registry_bound_locked()
        return bound


def discard_staged_skill_permission_leases(
    scope_id: str | None, *, include_session_template: bool = False
) -> None:
    """Discard pre-turn authority when its invocation will not start a turn."""

    normalized = _bounded_scope_id(scope_id)
    if normalized is None:
        return
    with _REGISTRY_LOCK:
        _PENDING_TURN_LEASES.pop(normalized, None)
        if include_session_template:
            _SESSION_LEASE_TEMPLATES.pop(normalized, None)


def evaluate_skill_tool_call(
    *,
    tool_name: str,
    function_args: Mapping[str, Any] | None,
    turn_id: str | None,
    task_id: str | None = None,
    session_id: str | None = None,
    toolset: str | None = None,
) -> SkillPermissionDecision:
    """Atomically reserve budget and decide one tool attempt.

    The returned object is deliberately argument-free.  Concurrent calls for
    the same turn share the same lock, so a one-call remaining budget cannot be
    consumed twice.
    """

    args = function_args if isinstance(function_args, Mapping) else {}
    now = time.monotonic()
    with _REGISTRY_LOCK:
        _cleanup_locked(now)
        state = _find_turn_locked(turn_id, task_id, session_id)
        if state is None or not state.leases:
            evicted = _find_evicted_turn_locked(turn_id, task_id, session_id)
            if evicted is not None:
                action: Literal["allow", "block"] = (
                    "block" if evicted.enforced else "allow"
                )
                return SkillPermissionDecision(
                    action,
                    "lease_registry_evicted",
                    evicted.mode,
                    evicted.lane,
                    ("lease_registry_evicted",),
                    enforced_skill_count=1 if evicted.enforced else 0,
                )
            return SkillPermissionDecision(
                "allow", "no_active_skill_lease", OBSERVE, "unknown"
            )

        state.updated_at = now
        _TURN_LEASES.move_to_end(state.turn_id)
        all_leases = list(state.leases.values())
        verified = [lease for lease in all_leases if lease.contract_status == "verified"]
        enforced = [lease for lease in verified if lease.enforced]
        mode = _effective_mode(all_leases)
        lane = _effective_lane(all_leases)

        # Attempts consume the declared budget whether they eventually run or
        # are denied.  This prevents a retry loop from bypassing the turn cap.
        exhausted = any(
            lease.tool_call_limit is not None
            and lease.tool_calls_used >= lease.tool_call_limit
            for lease in enforced
        )
        observed_exhausted = any(
            lease.tool_call_limit is not None
            and lease.tool_calls_used >= lease.tool_call_limit
            for lease in verified
        )
        wall_exhausted = any(
            lease.wall_seconds_limit is not None
            and now - lease.activated_at >= lease.wall_seconds_limit
            for lease in enforced
        )
        observed_wall_exhausted = any(
            lease.wall_seconds_limit is not None
            and now - lease.activated_at >= lease.wall_seconds_limit
            for lease in verified
        )
        for lease in verified:
            if lease.tool_call_limit is None:
                continue
            lease.tool_calls_used = min(
                lease.tool_calls_used + 1, lease.tool_call_limit + 1
            )

        observed = set(_observation_gaps(tool_name, args, toolset))
        simulated = _evaluate_group(
            verified,
            tool_name=tool_name,
            args=args,
            toolset=toolset,
            budget_exhausted=observed_exhausted,
            wall_budget_exhausted=observed_wall_exhausted,
        )
        if simulated[1] != "permission_allowed":
            observed.add(simulated[1])

        if not enforced:
            if any(lease.contract_status != "verified" for lease in all_leases):
                observed.add("contract_unverified_observed")
            state.observations.update(observed)
            return SkillPermissionDecision(
                "allow",
                "observed_only",
                mode,
                lane,
                tuple(sorted(observed)),
                active_skill_count=len(all_leases),
                enforced_skill_count=0,
            )

        action, code = _evaluate_group(
            enforced,
            tool_name=tool_name,
            args=args,
            toolset=toolset,
            budget_exhausted=exhausted,
            wall_budget_exhausted=wall_exhausted,
        )
        state.observations.update(observed)
        if action == "approve":
            approval_key = _approval_key(enforced, tool_name)
        else:
            approval_key = None
        return SkillPermissionDecision(
            action,
            code,
            mode,
            lane,
            tuple(sorted(observed)),
            approval_key=approval_key,
            active_skill_count=len(all_leases),
            enforced_skill_count=len(enforced),
        )


def authorize_skill_tool_call(
    *,
    tool_name: str,
    function_args: Mapping[str, Any] | None,
    turn_id: str | None,
    task_id: str | None = None,
    session_id: str | None = None,
    toolset: str | None = None,
) -> dict[str, Any] | None:
    """Apply one lease decision and the existing approval gate.

    Returns an argument-free denial payload or ``None`` when execution may
    continue. This shared adapter keeps registry and direct agent-tool routes
    behavior-identical without adding a model tool.
    """

    context_turn = get_current_permission_turn_id()
    effective_turn = context_turn or turn_id
    try:
        decision = evaluate_skill_tool_call(
            tool_name=tool_name,
            function_args=function_args,
            turn_id=effective_turn,
            task_id=task_id,
            session_id=session_id,
            toolset=toolset,
        )
    except Exception:
        try:
            mode = load_permission_settings().mode
        except Exception:
            mode = ENFORCE_ALL
        if mode == OBSERVE:
            return None
        return {
            "error": (
                "Skill permission policy denied this tool because its "
                "enforcement decision could not be evaluated."
            ),
            "permission_code": "policy_evaluation_failed",
        }

    if decision.blocked:
        return {
            "error": permission_denial_message(tool_name, decision.code),
            "permission_code": decision.code,
        }
    if not decision.approval_required:
        return None

    try:
        from tools.approval import request_tool_approval

        approval_result = request_tool_approval(
            tool_name,
            (
                "An active verified skill contract requires approval "
                f"for tool '{_canonical_public_name(tool_name)}'."
            ),
            rule_key=decision.approval_key or "",
        )
    except Exception:
        approval_result = {"approved": False}
    if isinstance(approval_result, Mapping) and approval_result.get("approved"):
        return None
    return {
        "error": permission_denial_message(tool_name, "approval_denied"),
        "permission_code": "approval_denied",
    }


def permission_denial_message(tool_name: str, code: str) -> str:
    """Return a stable, argument-free message safe for model/user context."""

    safe_tool = _canonical_public_name(tool_name)
    safe_code = code if re.fullmatch(r"[a-z0-9_]+", code or "") else "policy_denied"
    return f"Skill permission policy denied tool '{safe_tool}' ({safe_code})."


def skill_activation_denial_payload(
    canonical_name: str, decision: SkillActivationDecision
) -> dict[str, Any]:
    """Return a safe tool-result payload for a blocked skill activation."""

    return {
        "success": False,
        "error": (
            f"Skill '{_canonical_public_name(canonical_name)}' was not activated "
            f"by runtime permission policy ({decision.code})."
        ),
        "permission_code": decision.code,
        "contract_status": decision.contract_status,
        "provenance": decision.provenance,
    }


def get_turn_permission_snapshot(turn_id: str) -> dict[str, Any] | None:
    """Return a privacy-safe diagnostic snapshot (never raw roots/arguments)."""

    normalized = _bounded_scope_id(turn_id)
    if normalized is None:
        return None
    with _REGISTRY_LOCK:
        _cleanup_locked(time.monotonic())
        state = _TURN_LEASES.get(normalized)
        if state is None:
            return None
        leases = [
            {
                "skill": lease.skill_name,
                "contract_digest": lease.contract_digest,
                "contract_status": lease.contract_status,
                "provenance": lease.provenance,
                "lane": lease.lane,
                "mode": lease.mode,
                "enforced": lease.enforced,
                "tool_calls_used": lease.tool_calls_used,
                "tool_call_limit": lease.tool_call_limit,
                "context_token_limit": lease.context_token_limit,
                "wall_seconds_limit": lease.wall_seconds_limit,
            }
            for lease in state.leases.values()
        ]
        return {
            "turn": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
            "leases": leases,
            "observations": sorted(state.observations),
        }


def clear_turn_permission_leases(turn_id: str) -> None:
    """Hard-drop one turn's volatile leases (manual/test helper)."""

    normalized = _bounded_scope_id(turn_id)
    if normalized is None:
        return
    with _REGISTRY_LOCK:
        _TURN_LEASES.pop(normalized, None)
        _EVICTED_TURNS.pop(normalized, None)


def get_current_permission_turn_id() -> str | None:
    """Return the concrete turn at the top of this execution context."""

    stack = _CURRENT_PERMISSION_TURNS.get()
    return stack[-1] if stack else None


def finalize_current_turn_permission_leases() -> str | None:
    """Pop and clear this context's concrete turn, including nested turns."""

    stack = _CURRENT_PERMISSION_TURNS.get()
    if not stack:
        return None
    turn_id = stack[-1]
    _CURRENT_PERMISSION_TURNS.set(stack[:-1])
    with _REGISTRY_LOCK:
        state = _TURN_LEASES.pop(turn_id, None)
        if state is not None:
            _remember_evicted_turn_locked(state)
    return turn_id


def _clear_permission_leases_for_tests() -> None:
    with _REGISTRY_LOCK:
        _TURN_LEASES.clear()
        _PENDING_TURN_LEASES.clear()
        _SESSION_LEASE_TEMPLATES.clear()
        _EVICTED_TURNS.clear()
        _CURRENT_PERMISSION_TURNS.set(())


def _lease_from_contract(
    *,
    skill_dir: Path,
    skill_name: str,
    contract: Mapping[str, Any] | None,
    contract_digest: str | None,
    contract_status: str,
    provenance: str,
    lane: str,
    mode: str,
    enforced: bool,
    workspace_root: Path | None,
) -> _SkillLease:
    resolved_skill = _resolve_root(skill_dir)
    resolved_workspace = _resolve_root(workspace_root or Path.cwd())
    resolved_temp = _resolve_root(Path(tempfile.gettempdir()))
    permissions = contract.get("permissions") if isinstance(contract, Mapping) else {}
    permissions = permissions if isinstance(permissions, Mapping) else {}
    actions = permissions.get("actions")
    actions = actions if isinstance(actions, Mapping) else {}

    file_access: dict[str, int] = {}
    raw_files = permissions.get("files")
    if isinstance(raw_files, Sequence) and not isinstance(raw_files, (str, bytes)):
        for item in raw_files:
            if not isinstance(item, Mapping):
                continue
            scope = item.get("scope")
            access = item.get("access")
            if scope in {"workspace", "skill", "temp"} and access in _ACCESS_BITS:
                file_access[str(scope)] = _ACCESS_BITS[str(access)]

    network: dict[str, frozenset[str]] = {}
    raw_network = permissions.get("network")
    if isinstance(raw_network, Sequence) and not isinstance(raw_network, (str, bytes)):
        for item in raw_network:
            if not isinstance(item, Mapping):
                continue
            host = item.get("host")
            methods = item.get("methods")
            if isinstance(host, str) and isinstance(methods, list):
                network[host] = frozenset(
                    method for method in methods if isinstance(method, str)
                )

    toolsets = _string_frozenset(permissions.get("toolsets_required"))
    approvals = _string_frozenset(actions.get("approval_required"))
    prohibitions = _string_frozenset(actions.get("prohibited"))
    budgets = contract.get("budgets") if isinstance(contract, Mapping) else {}
    budgets = budgets if isinstance(budgets, Mapping) else {}
    raw_limit = budgets.get("tool_calls")
    tool_call_limit = raw_limit if type(raw_limit) is int and raw_limit >= 0 else None
    raw_context_limit = budgets.get("context_tokens")
    context_token_limit = (
        raw_context_limit
        if type(raw_context_limit) is int and raw_context_limit >= 0
        else None
    )
    raw_wall_limit = budgets.get("wall_seconds")
    wall_seconds_limit = (
        raw_wall_limit
        if type(raw_wall_limit) is int and raw_wall_limit >= 0
        else None
    )
    lease_material = "\0".join(
        (
            skill_name,
            contract_digest or contract_status,
            hashlib.sha256(str(resolved_skill).encode("utf-8")).hexdigest(),
        )
    )
    return _SkillLease(
        lease_id=hashlib.sha256(lease_material.encode("utf-8")).hexdigest(),
        skill_name=skill_name,
        contract_digest=contract_digest,
        contract_status=contract_status,
        provenance=provenance,
        lane=lane,
        mode=mode,
        enforced=enforced,
        toolsets=toolsets,
        file_access=file_access,
        network=network,
        approvals=approvals,
        prohibitions=prohibitions,
        declares_secrets=bool(permissions.get("secrets")),
        context_token_limit=context_token_limit,
        wall_seconds_limit=wall_seconds_limit,
        tool_call_limit=tool_call_limit,
        activated_at=time.monotonic(),
        workspace_root=resolved_workspace,
        skill_root=resolved_skill,
        temp_root=resolved_temp,
    )


def _declaration_observation_codes(lease: _SkillLease) -> set[str]:
    """Return stable codes for declarations that cannot map to core tools."""

    observations = set()
    if lease.context_token_limit is not None:
        observations.add("context_token_budget_uninspectable")
    if lease.declares_secrets:
        observations.add("secret_usage_uninspectable")
    try:
        from tools.registry import registry

        known_tools = set(registry.get_all_tool_names())
    except Exception:
        observations.add("tool_catalog_unavailable")
        return observations
    if any(
        action not in known_tools
        for action in lease.approvals | lease.prohibitions
    ):
        observations.add("semantic_action_declarations_uninspectable")
    return observations


def _evaluate_group(
    leases: Sequence[_SkillLease],
    *,
    tool_name: str,
    args: Mapping[str, Any],
    toolset: str | None,
    budget_exhausted: bool,
    wall_budget_exhausted: bool,
) -> tuple[Literal["allow", "block", "approve"], str]:
    if not leases:
        return "allow", "permission_allowed"

    # Explicit prohibitions are absolute and precede every other decision,
    # including an approval declaration for the same tool.
    if any(tool_name in lease.prohibitions for lease in leases):
        return "block", "action_prohibited"
    if budget_exhausted:
        return "block", "tool_budget_exhausted"
    if wall_budget_exhausted:
        return "block", "wall_budget_exhausted"

    allowed_toolsets = set().union(*(lease.toolsets for lease in leases))
    if not toolset:
        return "block", "toolset_unknown"
    if toolset not in allowed_toolsets:
        return "block", "toolset_not_declared"

    file_decision = _evaluate_file_access(leases, tool_name, args)
    if file_decision is not None:
        return "block", file_decision

    network_decision = _evaluate_network_access(leases, tool_name, args)
    if network_decision is not None:
        return "block", network_decision

    if any(tool_name in lease.approvals for lease in leases):
        return "approve", "approval_required"
    return "allow", "permission_allowed"


def _evaluate_file_access(
    leases: Sequence[_SkillLease], tool_name: str, args: Mapping[str, Any]
) -> str | None:
    targets: list[tuple[Any, str]] = []
    if tool_name in _FILE_TOOL_ACCESS:
        key, access = _FILE_TOOL_ACCESS[tool_name]
        default_path = "." if tool_name == "search_files" else None
        targets.append((args.get(key, default_path), access))
    elif tool_name == "patch":
        mode = args.get("mode") or "replace"
        if mode == "replace":
            targets.append((args.get("path"), "write"))
        elif mode == "patch":
            body = args.get("patch")
            if not isinstance(body, str) or not body:
                return "file_target_uninspectable"
            found = [match.group(1).strip() for match in _PATCH_HEADER_RE.finditer(body)]
            for match in _PATCH_MOVE_RE.finditer(body):
                found.extend((match.group(1).strip(), match.group(2).strip()))
            if not found:
                return "file_target_uninspectable"
            targets.extend((path, "write") for path in found)
        else:
            return "file_target_uninspectable"
    else:
        return None

    for raw_path, access in targets:
        if not isinstance(raw_path, str) or not raw_path.strip():
            return "file_target_uninspectable"
        if not _path_allowed(leases, raw_path, access):
            return "file_scope_not_declared"
    return None


def _path_allowed(
    leases: Sequence[_SkillLease], raw_path: str, access: str
) -> bool:
    required = _ACCESS_BITS[access]
    if PureWindowsPath(raw_path).drive and os.name != "nt":
        return False
    first_workspace = leases[0].workspace_root
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = first_workspace / candidate
    try:
        resolved = candidate.resolve(strict=False)
    except (OSError, RuntimeError):
        return False

    # Active skill roots are the most specific authority.  A broad workspace
    # write declaration cannot silently turn the read-only ``skill`` scope into
    # permission to rewrite a loaded skill (or a sibling stacked skill).
    matching_skill = [
        lease for lease in leases if _is_relative_to(resolved, lease.skill_root)
    ]
    if matching_skill:
        return any(
            lease.file_access.get("skill", 0) & required == required
            for lease in matching_skill
        )

    matching_workspace = [
        lease for lease in leases if _is_relative_to(resolved, lease.workspace_root)
    ]
    matching_temp = [
        lease for lease in leases if _is_relative_to(resolved, lease.temp_root)
    ]
    workspace_depth = max(
        (len(lease.workspace_root.parts) for lease in matching_workspace), default=-1
    )
    temp_depth = max(
        (len(lease.temp_root.parts) for lease in matching_temp), default=-1
    )
    if workspace_depth >= temp_depth and matching_workspace:
        return any(
            lease.file_access.get("workspace", 0) & required == required
            for lease in matching_workspace
            if len(lease.workspace_root.parts) == workspace_depth
        )
    if matching_temp:
        return any(
            lease.file_access.get("temp", 0) & required == required
            for lease in matching_temp
            if len(lease.temp_root.parts) == temp_depth
        )
    return False


def _evaluate_network_access(
    leases: Sequence[_SkillLease], tool_name: str, args: Mapping[str, Any]
) -> str | None:
    requests: list[tuple[str, str]] = []
    if tool_name == "web_extract":
        urls = args.get("urls")
        if not isinstance(urls, list) or not urls:
            return "network_target_uninspectable"
        requests.extend((url, "GET") for url in urls if isinstance(url, str))
        if len(requests) != len(urls):
            return "network_target_uninspectable"
    elif tool_name == "browser_navigate":
        url = args.get("url")
        if not isinstance(url, str) or not url:
            return "network_target_uninspectable"
        requests.append((url, "GET"))
    else:
        return None

    allowed: dict[str, set[str]] = {}
    for lease in leases:
        for host, methods in lease.network.items():
            allowed.setdefault(host, set()).update(methods)
    for raw_url, method in requests:
        authority = _canonical_url_authority(raw_url)
        if authority is None or method not in allowed.get(authority, set()):
            return "network_target_not_declared"
    return None


def _canonical_url_authority(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (TypeError, ValueError):
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    host = parsed.hostname
    if host is None or host != host.lower():
        return None
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        labels = host.split(".")
        if any(
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
            for label in labels
        ):
            return None
        canonical_host = host
    else:
        if str(address) != host:
            return None
        canonical_host = f"[{host}]" if address.version == 6 else host
    return f"{canonical_host}:{port}" if port is not None else canonical_host


def _observation_gaps(
    tool_name: str, args: Mapping[str, Any], toolset: str | None
) -> tuple[str, ...]:
    del args  # The gap classification never retains or renders arguments.
    gaps: set[str] = set()
    if tool_name == "terminal":
        gaps.update(
            {
                "terminal_file_effects_uninspectable",
                "terminal_network_uninspectable",
            }
        )
    elif tool_name == "execute_code":
        gaps.update(
            {"code_file_effects_uninspectable", "code_network_uninspectable"}
        )
    elif tool_name == "web_search":
        gaps.add("network_target_uninspectable")
    elif tool_name in _BROWSER_STATEFUL_TOOLS:
        gaps.add("browser_network_effect_uninspectable")
    elif tool_name == "browser_cdp":
        gaps.add("browser_cdp_semantics_uninspectable")
    if tool_name == "delegate_task":
        gaps.add("delegated_effects_uninspectable")
    if tool_name == "skill_manage":
        gaps.add("skill_mutation_scope_uninspectable")
    if toolset in {"context_engine", "memory"}:
        gaps.add("provider_effects_uninspectable")
    return tuple(sorted(gaps))


def _approval_key(leases: Sequence[_SkillLease], tool_name: str) -> str:
    material = "\0".join(
        sorted(
            f"{lease.skill_name}:{lease.contract_digest or lease.contract_status}"
            for lease in leases
        )
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]
    return f"skill_permissions:{digest}:{_canonical_public_name(tool_name)}"


def derive_skill_risk_lane(
    contract: Mapping[str, Any] | None, status: str
) -> str:
    """Return the shared runtime and receipt risk lane for a skill contract."""

    if status != "verified" or not isinstance(contract, Mapping):
        return "unknown"
    permissions = contract.get("permissions")
    if not isinstance(permissions, Mapping):
        return "unknown"
    actions = permissions.get("actions")
    actions = actions if isinstance(actions, Mapping) else {}
    if actions.get("prohibited"):
        return "restricted"
    if actions.get("approval_required"):
        return "approval_required"
    files = permissions.get("files")
    has_write = isinstance(files, list) and any(
        isinstance(item, Mapping) and item.get("access") in {"write", "read_write"}
        for item in files
    )
    toolsets = permissions.get("toolsets_required")
    has_opaque_effect_toolset = isinstance(toolsets, list) and any(
        item in _OPAQUE_EFFECT_TOOLSETS for item in toolsets
    )
    if (
        has_write
        or has_opaque_effect_toolset
        or permissions.get("network")
        or permissions.get("secrets")
    ):
        return "elevated"
    return "standard"


def _classify_provenance(skill_dir: Path, skill_name: str) -> str:
    if ":" in skill_name:
        return "plugin"
    try:
        from agent.skill_utils import is_external_skill_path

        if is_external_skill_path(skill_dir):
            return "external"
    except Exception:
        pass
    try:
        from tools.skill_usage import is_bundled, is_hub_installed

        if is_hub_installed(skill_name):
            return "hub"
        if is_bundled(skill_name):
            return "bundled"
    except Exception:
        return "unknown"
    try:
        from fabric_constants import get_fabric_home

        active_root = (get_fabric_home() / "skills").resolve()
        resolved = skill_dir.resolve()
        if _is_relative_to(resolved, active_root):
            return "learned"
        return "external"
    except Exception:
        return "unknown"


def _provenance_is_enforced(mode: str, provenance: str) -> bool:
    if mode == ENFORCE_ALL:
        return True
    if mode == ENFORCE_LEARNED:
        # Unknown local provenance cannot be proven distribution-owned, so the
        # learned rollout treats it conservatively as part of the enforced lane.
        return provenance in {"learned", "unknown"}
    return False


def _find_turn_locked(
    turn_id: str | None, task_id: str | None, session_id: str | None
) -> _TurnLeases | None:
    normalized_turn = _bounded_scope_id(turn_id)
    if normalized_turn is not None:
        return _TURN_LEASES.get(normalized_turn)

    # Nested execute_code tool calls historically propagate task_id but not the
    # outer turn id.  Reuse a lease only when that reduced scope identifies one
    # active turn unambiguously; ambiguity fails safe by returning no match.
    normalized_task = _bounded_scope_id(task_id)
    normalized_session = _bounded_scope_id(session_id)
    if normalized_task is None:
        return None
    candidates = [
        state
        for state in _TURN_LEASES.values()
        if state.task_id == normalized_task
        and (normalized_session is None or state.session_id == normalized_session)
    ]
    return candidates[0] if len(candidates) == 1 else None


def _find_evicted_turn_locked(
    turn_id: str | None, task_id: str | None, session_id: str | None
) -> _EvictedTurn | None:
    normalized_turn = _bounded_scope_id(turn_id)
    if normalized_turn is not None:
        return _EVICTED_TURNS.get(normalized_turn)

    normalized_task = _bounded_scope_id(task_id)
    normalized_session = _bounded_scope_id(session_id)
    if normalized_task is None:
        return None
    candidates = [
        state
        for state in _EVICTED_TURNS.values()
        if state.task_id == normalized_task
        and (normalized_session is None or state.session_id == normalized_session)
    ]
    return candidates[0] if len(candidates) == 1 else None


def _effective_mode(leases: Sequence[_SkillLease]) -> str:
    if any(lease.mode == ENFORCE_ALL for lease in leases):
        return ENFORCE_ALL
    if any(lease.mode == ENFORCE_LEARNED for lease in leases):
        return ENFORCE_LEARNED
    return OBSERVE


def _effective_lane(leases: Sequence[_SkillLease]) -> str:
    if not leases:
        return "unknown"
    return max(
        (lease.lane for lease in leases),
        key=lambda lane: _LANE_ORDER.get(lane, 0),
    )


def _resolve_root(path: Path) -> Path:
    candidate = Path(path)
    if not candidate.exists() or not candidate.is_dir():
        raise ValueError("lease root is unavailable")
    return candidate.resolve(strict=True)


def _is_relative_to(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _string_frozenset(value: Any) -> frozenset[str]:
    if not isinstance(value, list):
        return frozenset()
    return frozenset(item for item in value if isinstance(item, str) and item)


def _bounded_scope_id(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError:
        return None
    return value if size <= _MAX_SCOPE_ID_BYTES else None


def _canonical_public_name(value: Any) -> str:
    candidate = str(value or "unknown").strip()
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", candidate):
        return candidate
    return "unknown"


def _cleanup_locked(now: float) -> None:
    expired = [
        turn_id
        for turn_id, state in _TURN_LEASES.items()
        if now - state.updated_at > _TURN_TTL_SECONDS
    ]
    for turn_id in expired:
        state = _TURN_LEASES.pop(turn_id, None)
        if state is not None:
            _remember_evicted_turn_locked(state)
    expired_evictions = [
        turn_id
        for turn_id, state in _EVICTED_TURNS.items()
        if now - state.updated_at > _TURN_TTL_SECONDS
    ]
    for turn_id in expired_evictions:
        _EVICTED_TURNS.pop(turn_id, None)
    _enforce_registry_bound_locked()


def _cleanup_staged_locked(now: float) -> None:
    for registry in (_PENDING_TURN_LEASES, _SESSION_LEASE_TEMPLATES):
        expired = [
            scope
            for scope, staged in registry.items()
            if now - staged.updated_at > _TURN_TTL_SECONDS
        ]
        for scope in expired:
            registry.pop(scope, None)


def _enforce_registry_bound_locked() -> None:
    while len(_TURN_LEASES) > _MAX_ACTIVE_TURNS:
        _, state = _TURN_LEASES.popitem(last=False)
        _remember_evicted_turn_locked(state)


def _remember_evicted_turn_locked(state: _TurnLeases) -> None:
    leases = list(state.leases.values())
    _EVICTED_TURNS[state.turn_id] = _EvictedTurn(
        turn_id=state.turn_id,
        task_id=state.task_id,
        session_id=state.session_id,
        updated_at=time.monotonic(),
        mode=_effective_mode(leases),
        lane=_effective_lane(leases),
        enforced=any(
            lease.enforced and lease.contract_status == "verified"
            for lease in leases
        ),
    )
    _EVICTED_TURNS.move_to_end(state.turn_id)
    while len(_EVICTED_TURNS) > _MAX_ACTIVE_TURNS:
        _EVICTED_TURNS.popitem(last=False)


__all__ = [
    "ENFORCE_ALL",
    "ENFORCE_LEARNED",
    "OBSERVE",
    "PERMISSION_MODES",
    "PermissionSettings",
    "SkillActivationDecision",
    "SkillPermissionDecision",
    "activate_skill_permission_lease",
    "authorize_skill_tool_call",
    "bind_staged_skill_permission_leases",
    "clear_turn_permission_leases",
    "discard_staged_skill_permission_leases",
    "derive_skill_risk_lane",
    "evaluate_skill_tool_call",
    "finalize_current_turn_permission_leases",
    "get_current_permission_turn_id",
    "get_turn_permission_snapshot",
    "load_permission_settings",
    "permission_denial_message",
    "skill_activation_denial_payload",
    "stage_skill_permission_lease",
]
