#!/usr/bin/env python3
"""Fail closed when a public Fabric snapshot exposes private brand context.

The audit uses only the Python standard library so it can run before project
dependencies are installed.  It scans the filesystem rather than Git's index;
that is important for release worktrees assembled before the first public
commit.
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_REPOSITORY = "https://github.com/ObliviousOdin/fabric"
CANONICAL_RAW = "https://raw.githubusercontent.com/ObliviousOdin/fabric/main"
CANONICAL_REMOTE_RE = re.compile(
    r"^(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)"
    r"ObliviousOdin/fabric(?:\.git)?/?$",
    re.IGNORECASE,
)
MAX_TEXT_BYTES = 8 * 1024 * 1024

SKIP_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        ".docusaurus",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "coverage",
        "dist",
        "node_modules",
        "release",
        "target",
        "venv",
        "web_dist",
    }
)

LEGAL_ATTRIBUTION_FILES = frozenset(
    {"AUTHORS.md", "LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md"}
)

DOCUMENT_SUFFIXES = frozenset(
    {".example", ".json", ".md", ".mdx", ".rst", ".toml", ".txt", ".yaml", ".yml"}
)
SOURCE_SUFFIXES = frozenset(
    {".cjs", ".cmd", ".js", ".jsx", ".mjs", ".ps1", ".py", ".rs", ".sh", ".ts", ".tsx"}
)
HASH_COMMENT_SOURCE_SUFFIXES = frozenset({".ps1", ".sh"})

# These files necessarily contain the forbidden patterns they enforce. Tests
# live under ``tests/`` and are already excluded by ``_is_test_path``.
AUDIT_IMPLEMENTATION_FILES = frozenset(
    {"scripts/fabric-brand-audit.py", "scripts/public-release-audit.py"}
)

_PRIVATE_BRAND = "ra" + "bot"
_PRIVATE_OWNER = _PRIVATE_BRAND + "inc"
_PERSONAL_NAME = "ch" + "anna"

GLOBAL_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "private-brand",
        re.compile(_PRIVATE_BRAND, re.IGNORECASE),
        "private brand token, domain, path, environment variable, or app id",
    ),
    (
        "distribution-origin",
        re.compile(
            r"white\s*[-_]?\s*label(?:l?ed|l?ing|s)?|"
            r"hard\s*[-_]?\s*fork|private\s*[-_]?\s*fork",
            re.IGNORECASE,
        ),
        "private distribution/origin language",
    ),
    (
        "personal-email",
        re.compile(rf"\b{_PERSONAL_NAME}(?:\+[^@\s]+)?@", re.IGNORECASE),
        "personal email address",
    ),
    (
        "personal-workspace",
        re.compile(
            rf"/Users/{re.escape(_PRIVATE_BRAND)}-channa-mac\b|"
            rf"/Users/[^/\s]+/Documents/workspace/{re.escape(_PRIVATE_OWNER)}\b|"
            r"fabric-(?:source-integration|public)(?:/|\b)",
            re.IGNORECASE,
        ),
        "private local workspace path",
    ),
    (
        "private-topology",
        re.compile(r"(?:^|[/\\])\.rstack(?:[/\\]|$)", re.IGNORECASE),
        "private tooling topology",
    ),
)

LEGACY_REPOSITORY_RE = re.compile(
    r"(?:github\.com|raw\.githubusercontent\.com)/NousResearch/"
    r"(?:hermes-agent|fabric-agent)(?:\.git)?|"
    r"github:NousResearch/(?:hermes-agent|fabric-agent)|"
    r"git@github\.com:NousResearch/(?:hermes-agent|fabric-agent)(?:\.git)?|"
    r"fabric-agent\.nousresearch\.com|"
    r"github\.com/ObliviousOdin/fabric-[A-Za-z0-9_.-]+",
    re.IGNORECASE,
)

# Historical citations are the only public exception to the legacy repository
# ban. Keep this deliberately exact: repository roots, docs, releases, support
# links, non-numeric issue paths, and every other upstream route must fail.
HISTORICAL_PROVENANCE_URL_RE = re.compile(
    r"https://github\.com/NousResearch/hermes-agent/(?:issues|pull)/[0-9]+"
    r"(?=$|[\s\]\[(){}<>\"'`,.;:!?#])",
    re.IGNORECASE,
)

LEGACY_PRODUCT_RE = re.compile(
    r"\bHermes\s+(?:Agent|Desktop|CLI|TUI|Gateway|Console|Dashboard|app|"
    r"application|session|installation|setup|config(?:uration)?|profile|home|"
    r"runtime|tool(?:s)?|skill(?:s)?|command|backend|frontend|service|process|"
    r"repository|repo|docs?|documentation)\b|"
    r"\b(?:install|start|run|use|launch|restart|configure|open|update|"
    r"uninstall)\s+Hermes\b|"
    r"\bHermes\s+(?:is|ships|runs|supports|loads|uses|provides|includes|"
    r"stores|reads|writes|creates|can|will|should|must)\b",
    re.IGNORECASE,
)

# Catch labels such as ``Hermes Chat`` and a bare product name in structured
# metadata. Keep this case-sensitive so lowercase protocol/package identifiers
# remain available for backwards compatibility.
LEGACY_STANDALONE_PRODUCT_RE = re.compile(r"\bHermes\b")

# Model families, required upstream provenance, and explicitly named
# compatibility identifiers are not product-brand leaks.
ALLOWED_LEGACY_PRODUCT_INTRINSIC_RE = re.compile(
    r"\bHermes(?:[- ]?(?:2|3|4)(?:\.\d+)?(?:-[0-9]+[Bb])?|Bench)\b|"
    r"\bHermes\s+(?:models?|model family|parser|compatibility|protocol|schema|"
    r"header|cookie|identifier|entry[ -]?point|adaptation|port)\b|"
    r"\bX-Hermes-[A-Za-z0-9-]+\b"
)
ALLOWED_LEGACY_PRODUCT_DOCUMENT_CONTEXT_RE = re.compile(
    r"\b(?:legacy|compatibility|backward-compatible|upstream|original|modified "
    r"software from)\s+Hermes\b|"
    r"\bHermes(?:\.app|\.exe|-Setup\.exe)\b"
)

# Compatibility annotations are intentionally narrow and source-only. They
# may suppress a bare historical identifier/path constant, never a sentence,
# command, User-Agent, or other rendered customer copy. The marker must be on
# the same or immediately preceding source line and include a justification.
SOURCE_COMPATIBILITY_ANNOTATION_RE = re.compile(
    r"(?:#|//|/\*|\*)\s*public-release-audit:\s*allow-legacy-compat\s+--\s+\S",
    re.IGNORECASE,
)
SOURCE_COMPATIBILITY_LITERAL_RE = re.compile(
    r"(?:"
    r"\.hermes|~[/\\]\.hermes(?:[/\\][A-Za-z0-9_.-]+)*|"
    r"%LOCALAPPDATA%[/\\]+hermes(?:[/\\][A-Za-z0-9_.-]+)*|"
    r"hermes-agent|hermes|Hermes(?:\.app|\.exe|-Setup\.exe)?|"
    r"HERMES_[A-Z0-9_]+|X-Hermes-[A-Za-z0-9-]+|"
    r"hermes(?:\.[A-Za-z0-9_-]+)+"
    r")"
)
QUOTED_SOURCE_LITERAL_RE = re.compile(
    r"(?P<quote>[\"'`])(?P<value>(?:\\.|(?!\1).)*?)(?P=quote)"
)
NON_PYTHON_RENDERED_CONTEXT_RE = re.compile(
    r"\b(?:echo|print(?:ln)?|console\.[A-Za-z_]+|log(?:ger)?\.[A-Za-z_]+|"
    r"panic|throw|return|send|respond|title|description|message|status|"
    r"user-agent)\b",
    re.IGNORECASE,
)

LEGACY_INLINE_COMMAND_RE = re.compile(
    r"`hermes(?=`|\s)(?:[^`\n]*)`",
    re.IGNORECASE,
)

LEGACY_COMMAND_LINE_RE = re.compile(
    r"^[ \t]*(?:[$>]\s*)?hermes(?=\s|$)",
    re.IGNORECASE,
)

LEGACY_SOURCE_COMMAND_RE = re.compile(
    r"(?<![A-Za-z0-9_./-])hermes(?=\s+(?:--?[A-Za-z0-9]|[A-Za-z][\w-]*))"
)
LEGACY_SHEBANG_RE = re.compile(
    r"^#![^\n]*(?:[/\s])hermes(?=\s|$)",
    re.IGNORECASE,
)
LEGACY_HOME_GUIDANCE_RE = re.compile(
    r"~[/\\]\.hermes\b|(?<![A-Za-z0-9_.-])\.hermes(?=$|[/\\])|"
    r"%LOCALAPPDATA%[/\\]+hermes\b|\bHERMES_HOME\b"
)
LEGACY_SOURCE_HOME_RE = re.compile(
    r"~[/\\]\.hermes\b|(?<![A-Za-z0-9_.-])\.hermes(?=$|[/\\])|"
    r"%LOCALAPPDATA%[/\\]+hermes\b"
)
EXPLICIT_COMPATIBILITY_CONTEXT_RE = re.compile(
    r"\b(?:legacy|compatibility|backward-compatible|migrat(?:e|ion)|rollback|"
    r"old install|older install)\b",
    re.IGNORECASE,
)
LEGACY_OUTBOUND_IDENTITY_RE = re.compile(
    r"(?:HermesAgent|Hermes-Agent|hermes-dashboard)(?=[/ (]|$)|"
    r"User-Agent.{0,120}(?:HermesAgent|Hermes-Agent|[\"']Hermes[\"'])|"
    r"X-BILLING-INVOKE-ORIGIN.{0,80}HermesAgent",
    re.IGNORECASE,
)

FENCED_BLOCK_RE = re.compile(r"(?ms)^```[^\n]*\n(.*?)^```")

PERSONAL_DOC_PATH_RE = re.compile(r"(?<![A-Za-z0-9:])/(?:Users)/([^/\s`\"')]+)")
PUBLIC_PATH_PLACEHOLDERS = frozenset(
    {
        "...",
        "<user>",
        "<username>",
        "<you>",
        "alice",
        "bob",
        "example",
        "me",
        "test",
        "user",
        "x",
    }
)

PROJECT_TOPOLOGY_RE = re.compile(
    r"\bfabric-(?:engine|public|source-integration)\b", re.IGNORECASE
)

CANONICAL_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    ".github/workflows/public-ci.yml": (
        "permissions:\n  contents: read",
        "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683",
        "persist-credentials: false",
        "python3 scripts/public-release-audit.py",
    ),
    ".github/workflows/desktop-packaging.yml": (
        "name: Desktop packaging verification",
        "permissions:\n  contents: read",
        "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd",
        "actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020",
        "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
        "--publish never",
        'CSC_IDENTITY_AUTO_DISCOVERY: "false"',
        "productName must be Fabric",
    ),
    ".github/workflows/docs-pages.yml": (
        "name: Publish documentation",
        "contents: read",
        "pages: write",
        "id-token: write",
        "persist-credentials: false",
        "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd",
        "actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020",
        "actions/configure-pages@983d7736d9b0ae728b81ab479565c72886d7745b",
        "actions/upload-pages-artifact@56afc609e74202658d3ffba0e8f6dda462b719fa",
        "actions/deploy-pages@d6db90164ac5ed86f2b6aed7e0febac5b3c0c03e",
    ),
    "LICENSE": (
        "MIT License",
        "Copyright (c) 2025 Nous Research",
        "Copyright (c) 2026 ObliviousOdin and Fabric contributors",
    ),
    "NOTICE": (
        "Fabric includes modified software from Hermes Agent by Nous Research.",
        "preserved in the root LICENSE file",
    ),
    "THIRD_PARTY_NOTICES.md": (
        "# Third-Party Notices",
        "include the root `LICENSE`, root `NOTICE`",
    ),
    "README.md": (CANONICAL_REPOSITORY, CANONICAL_RAW),
    "apps/desktop/branding/fabric.json": (
        CANONICAL_REPOSITORY,
        '"productName": "Fabric"',
        '"vendorName": "Fabric"',
        '"appId": "io.github.obliviousodin.fabric"',
    ),
    "package.json": (CANONICAL_REPOSITORY,),
    "scripts/install.sh": (CANONICAL_REPOSITORY, CANONICAL_RAW),
    "scripts/install.ps1": (CANONICAL_REPOSITORY, CANONICAL_RAW),
    "scripts/install.cmd": (CANONICAL_RAW,),
    "website/docusaurus.config.ts": (
        CANONICAL_REPOSITORY,
        "organizationName: 'ObliviousOdin'",
        "projectName: 'fabric'",
    ),
}

EXPECTED_PUBLIC_WORKFLOWS = frozenset(
    {"desktop-packaging.yml", "docs-pages.yml", "public-ci.yml"}
)
PRIVATE_REPOSITORY_PREFIXES = (
    ".hermes/",
    ".plans/",
    ".rstack/",
    "docs/decisions/",
    "docs/plans/",
    "docs/superpowers/",
    "parity/",
    "tests-parity/",
)
UNSAFE_WORKFLOW_RE = re.compile(
    r"\bpull_request_target\s*:|\bworkflow_run\s*:|\bsecrets\s*\.",
    re.IGNORECASE,
)
WORKFLOW_WRITE_PERMISSION_RE = re.compile(
    r"(?m)^\s*([a-z-]+)\s*:\s*write\s*$", re.IGNORECASE
)
ALLOWED_WRITE_PERMISSIONS = {
    "docs-pages.yml": frozenset({"id-token", "pages"}),
}
WORKFLOW_USES_RE = re.compile(r"(?m)^\s*(?:-\s*)?uses:\s*([^\s#]+)")
PINNED_ACTION_RE = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
UNSAFE_PUBLISH_RE = re.compile(
    r"\b(?:npm|pnpm|yarn)\s+publish\b|\bgh\s+release\b|"
    r"--publish(?:[ =]+)(?!never(?:\s|$))[^\s]+|"
    r"(?:softprops/action-gh-release|actions/create-release|release-drafter)/",
    re.IGNORECASE,
)


@dataclass(frozen=True, order=True)
class Issue:
    rule: str
    path: str
    line: int
    message: str

    def render(self) -> str:
        location = self.path if self.line <= 0 else f"{self.path}:{self.line}"
        return f"{location}: [{self.rule}] {self.message}"


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def iter_repository_entries(root: Path) -> Iterator[Path]:
    """Yield files and symlinks without following links or generated trees."""

    for directory, names, filenames in os.walk(root, followlinks=False):
        names[:] = sorted(name for name in names if name not in SKIP_DIRECTORY_NAMES)
        base = Path(directory)
        for name in names:
            path = base / name
            if path.is_symlink():
                yield path
        for filename in sorted(filenames):
            yield base / filename


def _read_text(path: Path) -> str | None:
    if path.is_symlink():
        return os.readlink(path)
    try:
        if path.stat().st_size > MAX_TEXT_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _line_number(text: str, start: int) -> int:
    return text.count("\n", 0, start) + 1


def _is_test_path(relative: str) -> bool:
    parts = Path(relative).parts
    return "tests" in parts or any(part.endswith(".test.ts") or part.endswith(".test.tsx") for part in parts)


def _is_legal_attribution_path(relative: str) -> bool:
    name = Path(relative).name.lower()
    return (
        relative in LEGAL_ATTRIBUTION_FILES
        or "/licenses/" in f"/{relative.lower()}"
        or name.startswith(("attribution", "authors", "license", "notice"))
    )


def _is_customer_document(relative: str) -> bool:
    path = Path(relative)
    if path.suffix.lower() not in DOCUMENT_SUFFIXES:
        return False
    if (
        _is_test_path(relative)
        or _is_legal_attribution_path(relative)
        or relative.startswith(".github/workflows/")
    ):
        return False
    return True


def _is_customer_source(relative: str) -> bool:
    path = Path(relative)
    if (
        path.suffix.lower() not in SOURCE_SUFFIXES
        or _is_test_path(relative)
        or relative in AUDIT_IMPLEMENTATION_FILES
    ):
        return False
    return True


def _has_explicit_compatibility_context(text: str, start: int, end: int) -> bool:
    window = text[max(0, start - 100) : min(len(text), end + 140)]
    return bool(EXPLICIT_COMPATIBILITY_CONTEXT_RE.search(window))


def _legacy_product_matches(
    text: str, *, allow_document_context: bool = True
) -> Iterator[re.Match[str]]:
    """Yield legacy product references, excluding models/provenance/compat."""

    seen: set[tuple[int, int]] = set()
    for pattern in (LEGACY_PRODUCT_RE, LEGACY_STANDALONE_PRODUCT_RE):
        for match in pattern.finditer(text):
            key = (match.start(), match.end())
            if key in seen:
                continue
            seen.add(key)
            token = LEGACY_STANDALONE_PRODUCT_RE.search(match.group(0))
            token_start = match.start() + (token.start() if token else 0)
            token_end = match.start() + (token.end() if token else len(match.group(0)))
            window_start = max(0, token_start - 100)
            window = text[window_start : min(len(text), token_end + 140)]
            allowed_patterns = [ALLOWED_LEGACY_PRODUCT_INTRINSIC_RE]
            if allow_document_context:
                allowed_patterns.append(ALLOWED_LEGACY_PRODUCT_DOCUMENT_CONTEXT_RE)
            if any(
                window_start + allowed.start() <= token_start
                and window_start + allowed.end() >= token_end
                for allowed_pattern in allowed_patterns
                for allowed in allowed_pattern.finditer(window)
            ):
                continue
            yield match


def _has_source_compatibility_annotation(
    source_lines: list[str], line_number: int
) -> bool:
    """Return whether a justified compatibility marker is immediately adjacent."""

    if line_number < 1:
        return False
    start = max(0, line_number - 2)
    end = min(len(source_lines), line_number)
    return any(
        SOURCE_COMPATIBILITY_ANNOTATION_RE.search(source_lines[index])
        for index in range(start, end)
    )


def _is_annotated_compatibility_literal(
    value: str, source_lines: list[str], line_number: int
) -> bool:
    """Allow only a bare compatibility identifier with an adjacent marker."""

    return bool(
        SOURCE_COMPATIBILITY_LITERAL_RE.fullmatch(value)
        and _has_source_compatibility_annotation(source_lines, line_number)
    )


def _python_literal_is_static_compatibility(
    node: ast.Constant,
    parents: dict[ast.AST, ast.AST],
    source_lines: list[str],
) -> bool:
    """Reject annotations on strings that are directly rendered or returned."""

    line_number = getattr(node, "lineno", 0)
    source_line = (
        source_lines[line_number - 1]
        if 0 < line_number <= len(source_lines)
        else ""
    )
    if LEGACY_OUTBOUND_IDENTITY_RE.search(source_line):
        return False

    current: ast.AST = node
    while current in parents:
        current = parents[current]
        if isinstance(
            current,
            (
                ast.Call,
                ast.FormattedValue,
                ast.JoinedStr,
                ast.Raise,
                ast.Return,
                ast.Yield,
                ast.YieldFrom,
            ),
        ):
            return False
        if isinstance(current, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            return True
    return False


def _source_line_match_is_annotated_compatibility(
    line: str,
    match: re.Match[str],
    source_lines: list[str],
    line_number: int,
) -> bool:
    """Apply the same narrow annotation rule to non-Python source lines."""

    if not _has_source_compatibility_annotation(source_lines, line_number):
        return False
    if NON_PYTHON_RENDERED_CONTEXT_RE.search(line):
        return False
    for literal in QUOTED_SOURCE_LITERAL_RE.finditer(line):
        if (
            literal.start("value") <= match.start()
            and literal.end("value") >= match.end()
            and SOURCE_COMPATIBILITY_LITERAL_RE.fullmatch(literal.group("value"))
        ):
            return True
    return False


def _document_command_matches(text: str) -> Iterator[tuple[int, str]]:
    """Yield offsets for legacy commands that are actually formatted as code."""

    for match in LEGACY_INLINE_COMMAND_RE.finditer(text):
        yield match.start(), match.group(0)
    for block in FENCED_BLOCK_RE.finditer(text):
        block_text = block.group(1)
        offset = block.start(1)
        for line in block_text.splitlines(keepends=True):
            match = LEGACY_COMMAND_LINE_RE.search(line)
            if match:
                yield offset + match.start(), match.group(0)
            offset += len(line)


def _python_docstring_ids(tree: ast.AST) -> set[int]:
    docstrings: set[int] = set()
    for owner in ast.walk(tree):
        if not isinstance(owner, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not owner.body:
            continue
        first = owner.body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            docstrings.add(id(first.value))
    return docstrings


def _customer_source_identity_matches(
    relative: str, text: str
) -> Iterator[tuple[int, str]]:
    """Yield likely emitted legacy product strings, excluding code commentary."""

    if relative.endswith(".py"):
        try:
            tree = ast.parse(text, filename=relative)
        except SyntaxError:
            return
        docstrings = _python_docstring_ids(tree)
        parents = {
            child: parent
            for parent in ast.walk(tree)
            for child in ast.iter_child_nodes(parent)
        }
        source_lines = text.splitlines()
        for node in ast.walk(tree):
            if (
                not isinstance(node, ast.Constant)
                or not isinstance(node.value, str)
                or id(node) in docstrings
            ):
                continue
            line_number = getattr(node, "lineno", 1)
            if (
                _is_annotated_compatibility_literal(
                    node.value, source_lines, line_number
                )
                and _python_literal_is_static_compatibility(
                    node, parents, source_lines
                )
            ):
                continue
            matches = list(
                _legacy_product_matches(
                    node.value, allow_document_context=False
                )
            )
            matches.extend(LEGACY_SOURCE_COMMAND_RE.finditer(node.value))
            matches.extend(LEGACY_OUTBOUND_IDENTITY_RE.finditer(node.value))
            matches.extend(LEGACY_SOURCE_HOME_RE.finditer(node.value))
            for match in matches:
                yield line_number, match.group(0)
        return

    source_lines = text.splitlines()
    hash_comments = Path(relative).suffix.lower() in HASH_COMMENT_SOURCE_SUFFIXES
    in_block_comment = False
    for line_number, line in enumerate(source_lines, start=1):
        stripped = line.lstrip()
        if in_block_comment:
            if "*/" in stripped:
                in_block_comment = False
            continue
        if stripped.startswith("/*"):
            if "*/" not in stripped[2:]:
                in_block_comment = True
            continue
        if stripped.startswith(("//", "*")):
            continue
        is_shebang = hash_comments and stripped.startswith("#!")
        if hash_comments and stripped.startswith("#") and not is_shebang:
            continue
        if not is_shebang and not any(quote in line for quote in ('"', "'", "`")):
            continue
        matches = list(
            _legacy_product_matches(line, allow_document_context=False)
        )
        matches.extend(LEGACY_SOURCE_COMMAND_RE.finditer(line))
        matches.extend(LEGACY_OUTBOUND_IDENTITY_RE.finditer(line))
        matches.extend(LEGACY_SOURCE_HOME_RE.finditer(line))
        if is_shebang:
            matches.extend(LEGACY_SHEBANG_RE.finditer(stripped))
        for match in matches:
            if _source_line_match_is_annotated_compatibility(
                line, match, source_lines, line_number
            ):
                continue
            yield line_number, match.group(0)


def _audit_workflow_safety(relative: str, text: str) -> list[Issue]:
    issues: list[Issue] = []
    for match in UNSAFE_WORKFLOW_RE.finditer(text):
        issues.append(
            Issue(
                "workflow-surface",
                relative,
                _line_number(text, match.start()),
                "unsafe trigger, write permission, or secret reference",
            )
        )
    allowed_writes = ALLOWED_WRITE_PERMISSIONS.get(Path(relative).name, frozenset())
    for match in WORKFLOW_WRITE_PERMISSION_RE.finditer(text):
        permission = match.group(1).lower()
        if permission in allowed_writes:
            continue
        issues.append(
            Issue(
                "workflow-surface",
                relative,
                _line_number(text, match.start()),
                f"workflow requests disallowed {permission}: write permission",
            )
        )
    for match in UNSAFE_PUBLISH_RE.finditer(text):
        issues.append(
            Issue(
                "workflow-surface",
                relative,
                _line_number(text, match.start()),
                "public verification workflow may publish a release/package",
            )
        )

    checkout_count = 0
    for match in WORKFLOW_USES_RE.finditer(text):
        target = match.group(1)
        if target.startswith(("./", "docker://")):
            continue
        if not PINNED_ACTION_RE.fullmatch(target):
            issues.append(
                Issue(
                    "workflow-surface",
                    relative,
                    _line_number(text, match.start()),
                    f"external action is not pinned to a full commit SHA: {target}",
                )
            )
        if target.startswith("actions/checkout@"):
            checkout_count += 1

    persist_disabled_count = len(
        re.findall(r"(?m)^\s*persist-credentials:\s*false\s*$", text)
    )
    if persist_disabled_count < checkout_count:
        issues.append(
            Issue(
                "workflow-surface",
                relative,
                0,
                "every checkout step must set persist-credentials: false",
            )
        )
    return issues


def audit_repository(root: Path = ROOT) -> list[Issue]:
    issues: list[Issue] = []

    for path in iter_repository_entries(root):
        relative = _relative(path, root)

        if relative.startswith(PRIVATE_REPOSITORY_PREFIXES):
            issues.append(
                Issue(
                    "private-topology",
                    relative,
                    0,
                    "private planning/comparison artifact is not part of the public snapshot",
                )
            )

        for rule, pattern, message in GLOBAL_PATTERNS:
            match = pattern.search(relative)
            if match:
                issues.append(Issue(rule, relative, 0, f"{message} in path"))

        text = _read_text(path)
        if text is None:
            continue

        for rule, pattern, message in GLOBAL_PATTERNS:
            for match in pattern.finditer(text):
                issues.append(
                    Issue(rule, relative, _line_number(text, match.start()), message)
                )

        if (
            _is_test_path(relative)
            or _is_legal_attribution_path(relative)
        ):
            continue

        provenance_spans = [
            (match.start(), match.end())
            for match in HISTORICAL_PROVENANCE_URL_RE.finditer(text)
        ]
        for match in LEGACY_REPOSITORY_RE.finditer(text):
            if any(
                start <= match.start() and end >= match.end()
                for start, end in provenance_spans
            ):
                continue
            issues.append(
                Issue(
                    "repository-route",
                    relative,
                    _line_number(text, match.start()),
                    "legacy or non-canonical Fabric repository route",
                )
            )

        if _is_customer_document(relative):
            for match in _legacy_product_matches(text):
                issues.append(
                    Issue(
                        "customer-product",
                        relative,
                        _line_number(text, match.start()),
                        "customer documentation presents the legacy product identity",
                    )
                )
            for offset, _matched_text in _document_command_matches(text):
                issues.append(
                    Issue(
                        "customer-command",
                        relative,
                        _line_number(text, offset),
                        "customer documentation invokes the legacy executable",
                    )
                )
            for match in LEGACY_HOME_GUIDANCE_RE.finditer(text):
                if _has_explicit_compatibility_context(text, match.start(), match.end()):
                    continue
                issues.append(
                    Issue(
                        "customer-home",
                        relative,
                        _line_number(text, match.start()),
                        "customer guidance uses the legacy home name; use FABRIC_HOME/~/.fabric",
                    )
                )
            for match in LEGACY_OUTBOUND_IDENTITY_RE.finditer(text):
                if any(
                    start <= match.start() and end >= match.end()
                    for start, end in provenance_spans
                ):
                    continue
                issues.append(
                    Issue(
                        "customer-outbound",
                        relative,
                        _line_number(text, match.start()),
                        "public metadata uses a legacy outbound product identifier",
                    )
                )
            for match in PERSONAL_DOC_PATH_RE.finditer(text):
                username = match.group(1)
                if username.lower() in PUBLIC_PATH_PLACEHOLDERS or username.startswith("<"):
                    continue
                issues.append(
                    Issue(
                        "personal-doc-path",
                        relative,
                        _line_number(text, match.start()),
                        "personalized macOS path; use a placeholder",
                    )
                )
            for match in PROJECT_TOPOLOGY_RE.finditer(text):
                issues.append(
                    Issue(
                        "project-topology",
                        relative,
                        _line_number(text, match.start()),
                        "old private checkout name; public examples must use 'fabric'",
                    )
                )

        if _is_customer_source(relative):
            for line_number, _matched_text in _customer_source_identity_matches(
                relative, text
            ):
                issues.append(
                    Issue(
                        "customer-source",
                        relative,
                        line_number,
                        "customer-visible source string uses legacy product identity",
                    )
                )

    for relative, required_fragments in CANONICAL_REQUIREMENTS.items():
        path = root / relative
        text = _read_text(path) if path.exists() else None
        if text is None:
            issues.append(
                Issue("canonical-metadata", relative, 0, "required public metadata file is missing")
            )
            continue
        for fragment in required_fragments:
            if fragment not in text:
                issues.append(
                    Issue(
                        "canonical-metadata",
                        relative,
                        0,
                        f"missing required public identity fragment {fragment!r}",
                    )
                )

    workflows_dir = root / ".github" / "workflows"
    if workflows_dir.is_dir():
        workflow_names = {
            path.name for path in workflows_dir.iterdir() if path.is_file()
        }
        for name in sorted(workflow_names - EXPECTED_PUBLIC_WORKFLOWS):
            issues.append(
                Issue(
                    "workflow-surface",
                    f".github/workflows/{name}",
                    0,
                    "unexpected workflow in minimal public repository",
                )
            )
        for name in sorted(workflow_names & EXPECTED_PUBLIC_WORKFLOWS):
            relative = f".github/workflows/{name}"
            workflow_text = _read_text(workflows_dir / name)
            if workflow_text is not None:
                issues.extend(_audit_workflow_safety(relative, workflow_text))

    return sorted(set(issues))


def audit_git_history(root: Path = ROOT) -> list[Issue]:
    """Reject private identity in any locally reachable commit metadata."""

    if not (root / ".git").exists():
        return []
    issues: list[Issue] = []
    for remote_kind, extra_args in (
        ("fetch", []),
        ("push", ["--push"]),
    ):
        try:
            remote = subprocess.run(
                [
                    "git",
                    "-C",
                    str(root),
                    "remote",
                    "get-url",
                    *extra_args,
                    "origin",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            issues.append(
                Issue(
                    "git-remote",
                    ".git",
                    0,
                    f"could not audit origin {remote_kind} URL ({type(exc).__name__})",
                )
            )
            continue
        if remote.returncode != 0:
            continue
        remote_url = remote.stdout.strip()
        if not CANONICAL_REMOTE_RE.fullmatch(remote_url):
            issues.append(
                Issue(
                    "git-remote",
                    ".git",
                    0,
                    f"origin {remote_kind} URL is not the canonical public repository",
                )
            )
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "log",
                "--all",
                "--format=%x1e%H%x1f%an%x1f%ae%x1f%cn%x1f%ce%x1f%B",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return issues + [
            Issue(
                "git-history",
                ".git",
                0,
                f"could not audit reachable commit metadata ({type(exc).__name__})",
            )
        ]
    if result.returncode != 0:
        return issues + [
            Issue(
                "git-history",
                ".git",
                0,
                "could not audit reachable commit metadata",
            )
        ]

    for record in result.stdout.split("\x1e"):
        if not record.strip():
            continue
        fields = record.split("\x1f", 5)
        if len(fields) != 6:
            issues.append(
                Issue("git-history", ".git", 0, "could not parse commit metadata")
            )
            continue
        commit = fields[0].strip()
        metadata = "\n".join(fields[1:])
        matched_rules = {
            rule
            for rule, pattern, _message in GLOBAL_PATTERNS
            if pattern.search(metadata)
        }
        for matched_rule in sorted(matched_rules):
            issues.append(
                Issue(
                    "git-history",
                    f"git:{commit[:12]}",
                    0,
                    f"reachable commit metadata violates {matched_rule}",
                )
            )
    return issues


def _summarize(issues: Iterable[Issue], limit: int) -> int:
    priority = {
        "git-history": 0,
        "git-remote": 0,
        "private-brand": 1,
        "personal-email": 2,
        "personal-workspace": 3,
        "distribution-origin": 4,
        "private-topology": 5,
        "workflow-surface": 6,
        "canonical-metadata": 7,
        "repository-route": 8,
        "project-topology": 9,
        "personal-doc-path": 10,
        "customer-product": 11,
        "customer-command": 12,
        "customer-source": 13,
    }
    materialized = sorted(
        set(issues),
        key=lambda issue: (
            priority.get(issue.rule, 99),
            issue.path,
            issue.line,
            issue.message,
        ),
    )
    if not materialized:
        print("public-release-audit: OK (public identity and repository routes)")
        return 0

    print(f"PUBLIC RELEASE AUDIT FAILED: {len(materialized)} issue(s)")
    counts = Counter(issue.rule for issue in materialized)
    print(
        "  rules: "
        + ", ".join(f"{rule}={count}" for rule, count in sorted(counts.items()))
    )
    for issue in materialized[:limit]:
        print(f"  - {issue.render()}")
    if len(materialized) > limit:
        print(f"  ... {len(materialized) - limit} additional issue(s) omitted")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args(argv)
    if args.limit < 1:
        parser.error("--limit must be positive")
    root = args.root.resolve()
    return _summarize(
        [*audit_repository(root), *audit_git_history(root)],
        args.limit,
    )


if __name__ == "__main__":
    raise SystemExit(main())
