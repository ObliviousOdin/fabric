#!/usr/bin/env python3
"""Shared handlers for the /memory and /skills write-approval subcommands.

Both the interactive CLI (``cli.py``) and the gateway (``gateway/run.py``) call
into this module so the pending-review UX (list / approve / reject / diff /
mode) lives in one place. Each caller owns only its surface concerns:
formatting the returned text and, for the gateway, persisting config + evicting
the cached agent on a mode change.

Every public handler returns a plain text string suitable for both a terminal
and a chat message. Skill diffs are intentionally NOT inlined here — the
``diff`` handler returns the full diff for the CLI pager, but on a messaging
platform the gateway truncates it and points the user at the dashboard / file.
"""

from __future__ import annotations

import json
from typing import List, Optional

from tools import write_approval as wa


def _fmt_state(subsystem: str) -> str:
    on = wa.write_approval_enabled(subsystem)
    return f"{subsystem}.write_approval = {'on' if on else 'off'}"


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt_pending_list(subsystem: str) -> str:
    records = wa.list_pending(subsystem)
    if not records:
        return f"No pending {subsystem} writes."
    lines = [f"Pending {subsystem} writes ({len(records)}):"]
    for r in records:
        origin = r.get("origin", "foreground")
        if origin == "background_review":
            tag = " [auto draft]"
        elif origin in {"learn_request", "learn_followup"}:
            tag = " [/learn draft]"
        else:
            tag = ""
        lines.append(f"  {r['id']}{tag}  {r.get('summary', '')}")
    where = "/{s} approve <id>".format(s=subsystem)
    if subsystem == wa.SKILLS:
        where += " [--now]"
    lines.append("")
    lines.append(f"Apply: {where}   Reject: /{subsystem} reject <id>")
    if subsystem == wa.SKILLS:
        lines.append("Review full diff: /skills diff <id>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Subcommand dispatch
# ---------------------------------------------------------------------------

def handle_pending_subcommand(
    subsystem: str,
    args: List[str],
    *,
    memory_store=None,
    set_mode_fn=None,
) -> Optional[str]:
    """Dispatch a /memory or /skills subcommand.

    Args:
        subsystem: ``memory`` or ``skills``.
        args: tokens after the slash command (e.g. ``["approve", "a1b2"]``).
        memory_store: live MemoryStore for applying approved memory writes
            (CLI passes ``self.agent._memory_store``; gateway applies against a
            freshly loaded store).
        set_mode_fn: optional callable ``(enabled: bool) -> None`` that
            persists the new write_approval boolean to config (gateway provides
            this; CLI uses its own ``save_config_value`` and passes a closure).

    Returns a text string to show the user. Returns None when the args are not
    a write-approval subcommand (caller falls through to its other handling,
    e.g. /skills search).
    """
    if subsystem not in {wa.MEMORY, wa.SKILLS}:
        return f"Unsupported pending subsystem '{subsystem}'."
    if not args:
        # Bare /memory or /skills with no sub → show pending + gate state.
        return f"{_fmt_state(subsystem)}\n\n" + _fmt_pending_list(subsystem)

    sub = args[0].lower()
    rest = args[1:]

    if sub == "pending":
        return _fmt_pending_list(subsystem)

    if sub in {"approve", "apply"}:
        return _approve(subsystem, rest, memory_store)

    if sub in {"reject", "deny", "drop"}:
        return _reject(subsystem, rest)

    if sub == "diff" and subsystem == wa.SKILLS:
        return _diff(rest)

    if sub == "evaluate" and subsystem == wa.SKILLS:
        return (
            "Evaluation observations are accepted only by the local bounded CLI. "
            "Run: fabric skills evaluate <pending-id> --observations <path> [--json]"
        )

    if sub == "rollback" and subsystem == wa.SKILLS:
        activate_now = "--now" in rest
        transaction_ids = [arg for arg in rest if arg != "--now"]
        if len(transaction_ids) != 1:
            return "Usage: /skills rollback <32-hex-transaction-id> [--now]"
        from tools.skill_manager_tool import rollback_committed_skill_transaction

        result = rollback_committed_skill_transaction(
            transaction_ids[0], activate_now=activate_now
        )
        if not result.get("success"):
            return f"Rollback refused: {result.get('error', 'unknown error')}"
        suffix = (
            " Active skill routing was refreshed immediately."
            if activate_now
            else " The restored routing will activate in the next session; use --now to refresh immediately."
        )
        return f"Rolled back skill promotion transaction {transaction_ids[0]}." + suffix

    if sub in {"approval", "mode"}:  # 'mode' kept as a back-compat alias
        return _set_approval(subsystem, rest, set_mode_fn)

    return None  # not ours — caller handles


def _resolve_one(subsystem: str, rest: List[str]):
    if not rest:
        return None, f"Usage: /{subsystem} approve|reject <id>  (or 'all')"
    return rest[0], None


def _approve(subsystem: str, rest: List[str], memory_store) -> str:
    activate_now = subsystem == wa.SKILLS and "--now" in rest
    positional = (
        [arg for arg in rest if arg != "--now"]
        if subsystem == wa.SKILLS
        else rest
    )
    target, err = _resolve_one(subsystem, positional)
    if err or target is None:
        return err or f"Usage: /{subsystem} approve <id>"

    if target.lower() != "all" and not wa.is_valid_pending_id(target):
        return (
            f"Invalid pending {subsystem} id '{target}'. Expected 32 lowercase "
            "hex characters (legacy 8-character ids are also accepted)."
        )

    records = wa.list_pending(subsystem)
    if not records and subsystem != wa.SKILLS:
        return f"No pending {subsystem} writes."
    if not records and subsystem == wa.SKILLS and target.lower() == "all":
        return "No pending skills writes."

    if target.lower() == "all":
        targets = list(records)
    else:
        rec = wa.get_pending(subsystem, target)
        if not rec:
            if subsystem == wa.SKILLS:
                from tools.skill_manager_tool import find_skill_pending_receipt

                receipt = find_skill_pending_receipt(target)
                if receipt and receipt.get("decision") == "promoted":
                    return (
                        "This reviewed skill batch was already promoted "
                        f"(transaction {receipt.get('transaction_id')})."
                    )
                if receipt and receipt.get("decision") == "rejected":
                    return "This skill draft was already rejected."
            return f"No pending {subsystem} write with id '{target}'."
        if subsystem == wa.SKILLS and rec.get("batch_id"):
            targets = [
                candidate
                for candidate in records
                if candidate.get("batch_id") == rec.get("batch_id")
            ]
        else:
            targets = [rec]

    if subsystem == wa.SKILLS:
        from tools.skill_manager_tool import apply_skill_pending_batch

        result = apply_skill_pending_batch(targets, activate_now=activate_now)
        if not result.get("success"):
            return (
                "Promoted 0 approved skill draft(s).\nFailed:\n  "
                f"{result.get('error', 'promotion failed')}\n"
                "All selected drafts were retained; no partial promotion was committed."
            )
        if result.get("already_promoted"):
            return (
                "This reviewed skill batch was already promoted "
                f"(transaction {result.get('transaction_id')})."
            )
        activation = (
            " Skill routing was refreshed immediately."
            if activate_now
            else " The promoted skill will activate in the next session; use --now to refresh immediately."
        )
        return (
            f"Promoted {result.get('applied', 0)} approved skill draft(s) "
            f"in transaction {result.get('transaction_id')}." + activation
        )

    applied, failed = 0, []
    for rec in targets:
        ok, msg = _apply_one(subsystem, rec, memory_store)
        if ok:
            wa.discard_pending(subsystem, rec["id"])
            applied += 1
        else:
            failed.append(f"{rec['id']}: {msg}")

    out = [f"Approved {applied} {subsystem} write(s)."]
    if failed:
        out.append("Failed:")
        out.extend(f"  {f}" for f in failed)
    return "\n".join(out)


def _apply_one(subsystem: str, rec, memory_store):
    payload = rec.get("payload", {})
    try:
        if subsystem == wa.MEMORY:
            if memory_store is None:
                return False, "memory store unavailable"
            from tools.memory_tool import apply_memory_pending
            result = apply_memory_pending(payload, memory_store)
            return bool(result.get("success")), result.get("error", "")
        else:
            from tools.skill_manager_tool import apply_skill_pending
            result = json.loads(
                apply_skill_pending(payload, origin=rec.get("origin"))
            )
            ok = bool(result.get("success"))
            return ok, result.get("error", "")
    except Exception as e:
        return False, str(e)


def _reject(subsystem: str, rest: List[str]) -> str:
    target, err = _resolve_one(subsystem, rest)
    if err or target is None:
        return err or f"Usage: /{subsystem} reject <id>"
    if subsystem == wa.SKILLS:
        if target.lower() != "all" and not wa.is_valid_pending_id(target):
            return (
                f"Invalid pending {subsystem} id '{target}'. Expected 32 "
                "lowercase hex characters (legacy 8-character ids are also accepted)."
            )
        from tools.skill_manager_tool import reject_skill_pending

        result = reject_skill_pending(
            None if target.lower() == "all" else target,
            reject_all=target.lower() == "all",
        )
        if not result.get("success"):
            return str(result.get("error") or "Skill draft rejection failed.")
        if result.get("already_rejected"):
            return "This skill draft batch was already rejected."
        return f"Rejected {result.get('rejected', 0)} pending skill draft action(s)."
    if target.lower() == "all":
        n = 0
        for rec in wa.list_pending(subsystem):
            if wa.discard_pending(subsystem, rec["id"]):
                n += 1
        return f"Rejected {n} pending {subsystem} write(s)."
    if not wa.is_valid_pending_id(target):
        return (
            f"Invalid pending {subsystem} id '{target}'. Expected 32 lowercase "
            "hex characters (legacy 8-character ids are also accepted)."
        )
    rec = wa.get_pending(subsystem, target)
    if rec and wa.discard_pending(subsystem, target):
        return f"Rejected pending {subsystem} write '{target}'."
    return f"No pending {subsystem} write with id '{target}'."


def _diff(rest: List[str]) -> str:
    if not rest:
        return "Usage: /skills diff <id>"
    if not wa.is_valid_pending_id(rest[0]):
        return (
            f"Invalid pending skills id '{rest[0]}'. Expected 32 lowercase hex "
            "characters (legacy 8-character ids are also accepted)."
        )
    rec = wa.get_pending(wa.SKILLS, rest[0])
    if not rec:
        return f"No pending skill write with id '{rest[0]}'."
    diff = wa.skill_pending_diff(rec)
    header = f"# Reviewed skill draft batch containing {rec['id']}\n"
    return header + "\n" + diff


def _set_approval(subsystem: str, rest: List[str], set_mode_fn) -> str:
    """Turn the approval gate on/off for a subsystem.

    ``set_mode_fn`` (when provided) persists the new boolean to config.
    """
    if not rest:
        return (f"{_fmt_state(subsystem)}\n"
                f"Set with: /{subsystem} approval <on|off>")
    arg = rest[0].strip().lower()
    truthy = {"on", "true", "yes", "1", "enable", "enabled"}
    falsey = {"off", "false", "no", "0", "disable", "disabled"}
    if arg in truthy:
        enabled = True
    elif arg in falsey:
        enabled = False
    else:
        return f"Invalid value '{arg}'. Use: on or off."
    if set_mode_fn is None:
        val = "true" if enabled else "false"
        return (f"To change the {subsystem} approval gate, run:\n"
                f"  Fabric config set {subsystem}.write_approval {val}")
    try:
        set_mode_fn(enabled)
    except Exception as e:
        return f"Failed to set {subsystem}.write_approval: {e}"
    return f"{subsystem}.write_approval set to '{'on' if enabled else 'off'}'."
