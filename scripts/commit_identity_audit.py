#!/usr/bin/env python3
"""Fail closed when commits carry a non-canonical or AI-tool identity.

This is the single source of truth for the repository's commit-identity
policy (see AGENT_GUARDRAILS.md, "Commit identity & attribution"):

* Authors and committers must use an allowlisted repository identity
  (PrimeOdin / ObliviousOdin), the GitHub web-flow committer, or an
  allowlisted bot. AI coding tools (Claude, Codex, Copilot, ...) must
  never appear as author, committer, or co-author.
* Commit messages must not carry AI-attribution footers: Co-Authored-By /
  Signed-off-by trailers naming an AI tool or a non-allowlisted identity,
  "Generated with ..." lines, or AI session links.

Invocations:
  --range A..B        audit every commit in a range (CI: PR base..head)
  --range 000...B     lhs of all zeros audits only the head commit (push
                      events for new refs)
  --commit SHA        audit a single commit
  --message-file F    audit a commit message file (commit-msg hook)
  --check-config      audit the effective git user.name/user.email
                      (pre-commit hook, session bootstrap)
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path


CANONICAL_NAME = "PrimeOdin"
CANONICAL_EMAIL = "11676741+ObliviousOdin@users.noreply.github.com"

# Identities that may author commits in this repository. Only the canonical
# GitHub noreply identity is allowed: the public-release audit forbids
# private domains and personal emails anywhere in the public tree, and
# CONTRIBUTING.md requires maintainers to commit with the noreply identity.
ALLOWED_AUTHOR_EMAILS = frozenset((CANONICAL_EMAIL.lower(),))

# Bots that may author or commit (dependency updates).
ALLOWED_BOT_EMAILS = frozenset(
    email.lower()
    for email in ("49699333+dependabot[bot]@users.noreply.github.com",)
)

# GitHub's web-flow identity signs squash merges, reverts, and web edits.
# It is acceptable as a committer only, never as an author.
ALLOWED_COMMITTER_ONLY_EMAILS = frozenset(("noreply@github.com",))

# AI coding tools must never appear in any identity field or trailer.
_DENIED_IDENTITY_RE = re.compile(
    r"(?i)\b("
    r"claude|anthropic|codex|openai|chatgpt|gpt-\d|copilot|gemini"
    r"|grok|devin|cursor|aider|windsurf|jules"
    r")\b"
)

_TRAILER_RE = re.compile(r"(?im)^\s*(co-authored-by|signed-off-by)\s*:\s*(.+?)\s*$")
_TRAILER_EMAIL_RE = re.compile(r"<([^<>]*)>\s*$")
_GENERATED_WITH_RE = re.compile(r"(?im)^\s*(?:\W*\s*)?generated\s+(?:with|by)\b")
_SESSION_LINK_RE = re.compile(
    r"(?i)("
    r"claude\.ai/|claude\.com/claude-code|chatgpt\.com/|chat\.openai\.com/"
    r"|gemini\.google\.com/|copilot\.microsoft\.com/"
    r"|^\s*claude-session\s*:"
    r")",
    re.MULTILINE,
)
_SCISSORS_MARKER = " >8 "
_ZERO_SHA_RE = re.compile(r"^0+$")

_RECORD_SEPARATOR = "\x1e"
_FIELD_SEPARATOR = "\x00"


def _run_git(args: Sequence[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or "git failed"
        raise RuntimeError(f"git {' '.join(args)}: {detail}")
    return result.stdout


def _describe(name: str, email: str) -> str:
    return f"{name} <{email}>"


def _audit_identity_field(
    *, role: str, name: str, email: str, subject: str
) -> list[str]:
    issues: list[str] = []
    where = f"{role} {_describe(name, email)} ({subject!r})"
    lowered_email = email.lower()
    denied = _DENIED_IDENTITY_RE.search(name) or _DENIED_IDENTITY_RE.search(email)
    if denied:
        issues.append(f"{where}: AI-tool identity {denied.group(1)!r} is forbidden")
        return issues
    allowed = ALLOWED_AUTHOR_EMAILS | ALLOWED_BOT_EMAILS
    if role == "committer":
        allowed = allowed | ALLOWED_COMMITTER_ONLY_EMAILS
    if lowered_email not in allowed:
        issues.append(
            f"{where}: email is not an allowlisted repository identity; "
            f"use {_describe(CANONICAL_NAME, CANONICAL_EMAIL)} "
            "(scripts/setup-git-guardrails.sh)"
        )
    return issues


def audit_message(message: str, *, context: str = "commit message") -> list[str]:
    """Return policy violations found in one commit message body."""

    issues: list[str] = []
    for match in _TRAILER_RE.finditer(message):
        trailer_key, value = match.group(1), match.group(2)
        denied = _DENIED_IDENTITY_RE.search(value)
        if denied:
            issues.append(
                f"{context}: {trailer_key} trailer names AI tool "
                f"{denied.group(1)!r}: {value!r}"
            )
            continue
        email_match = _TRAILER_EMAIL_RE.search(value)
        email = (email_match.group(1) if email_match else "").lower()
        if email not in ALLOWED_AUTHOR_EMAILS | ALLOWED_BOT_EMAILS:
            issues.append(
                f"{context}: {trailer_key} trailer identity is not "
                f"allowlisted: {value!r}"
            )
    if _GENERATED_WITH_RE.search(message):
        issues.append(f'{context}: "Generated with/by ..." attribution is forbidden')
    session = _SESSION_LINK_RE.search(message)
    if session:
        issues.append(
            f"{context}: AI session/tool link is forbidden: {session.group(1)!r}"
        )
    if "\U0001f916" in message:
        issues.append(f"{context}: robot-emoji attribution footer is forbidden")
    return issues


def audit_commits(revisions: Sequence[str]) -> list[str]:
    """Audit author, committer, and message of the selected commits."""

    output = _run_git(
        [
            "log",
            # git expands %x00/%x1e itself; argv cannot carry raw NUL bytes.
            "--format=%H%x00%an%x00%ae%x00%cn%x00%ce%x00%s%x00%B%x1e",
            *revisions,
        ]
    )
    issues: list[str] = []
    for raw_record in output.split(_RECORD_SEPARATOR):
        record = raw_record.strip("\n")
        if not record:
            continue
        fields = record.split(_FIELD_SEPARATOR, 6)
        if len(fields) != 7:
            raise RuntimeError(f"unparseable git log record: {record[:80]!r}")
        sha, author_name, author_email = fields[0], fields[1], fields[2]
        committer_name, committer_email = fields[3], fields[4]
        subject, body = fields[5], fields[6]
        short = sha[:12]
        issues.extend(
            _audit_identity_field(
                role="author",
                name=author_name,
                email=author_email,
                subject=subject,
            )
        )
        issues.extend(
            _audit_identity_field(
                role="committer",
                name=committer_name,
                email=committer_email,
                subject=subject,
            )
        )
        issues.extend(audit_message(body, context=f"commit {short}"))
    return issues


def audit_range(range_spec: str) -> list[str]:
    """Audit a rev range; an all-zero lhs audits only the head commit."""

    base, _, head = range_spec.partition("..")
    if head and _ZERO_SHA_RE.match(base):
        return audit_commits(["-1", head.lstrip(".")])
    return audit_commits([range_spec])


def read_message_file(path: Path) -> str:
    """Read a commit message file, dropping comments and scissors content."""

    lines: list[str] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        if line.startswith("#"):
            if _SCISSORS_MARKER in line:
                break
            continue
        lines.append(line)
    return "\n".join(lines)


def audit_config() -> list[str]:
    """Audit the effective git identity for the working repository."""

    issues: list[str] = []
    for key in ("user.name", "user.email"):
        result = subprocess.run(
            ["git", "config", "--get", key],
            check=False,
            capture_output=True,
            text=True,
        )
        value = result.stdout.strip()
        if result.returncode != 0 or not value:
            issues.append(
                f"{key} is not set; run scripts/setup-git-guardrails.sh"
            )
            continue
        denied = _DENIED_IDENTITY_RE.search(value)
        if denied:
            issues.append(
                f"{key} {value!r} carries the AI-tool identity "
                f"{denied.group(1)!r}; run scripts/setup-git-guardrails.sh"
            )
        elif key == "user.email" and value.lower() not in ALLOWED_AUTHOR_EMAILS:
            issues.append(
                f"user.email {value!r} is not an allowlisted repository "
                f"identity; expected {CANONICAL_EMAIL} "
                "(scripts/setup-git-guardrails.sh)"
            )
    return issues


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--range", dest="range_spec", help="rev range A..B to audit")
    mode.add_argument("--commit", help="single commit to audit")
    mode.add_argument(
        "--message-file", type=Path, help="commit message file to audit"
    )
    mode.add_argument(
        "--check-config",
        action="store_true",
        help="audit the effective git user.name/user.email",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.check_config:
            issues = audit_config()
        elif args.message_file is not None:
            issues = audit_message(read_message_file(args.message_file))
        elif args.commit:
            issues = audit_commits(["-1", args.commit])
        else:
            issues = audit_range(args.range_spec)
    except (RuntimeError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if issues:
        print(f"COMMIT IDENTITY AUDIT FAILED: {len(issues)} issue(s)", file=sys.stderr)
        for issue in issues:
            print(f"  - {issue}", file=sys.stderr)
        print(
            "Fix: scripts/setup-git-guardrails.sh, then rewrite the offending "
            "commits (git commit --amend --reset-author, or git rebase with "
            "--reset-author) and strip the flagged message lines.",
            file=sys.stderr,
        )
        return 1
    print("Commit identity audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
