#!/usr/bin/env python3
"""Cross-platform GitHub issue helper for the fabric-contribute skill."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Sequence

from fabric_cli.github_account import fetch_github_user, resolve_github_token

API_BASE = "https://api.github.com"
REPO = "ObliviousOdin/fabric"
TIMEOUT_SECONDS = 20


def _request(
    method: str,
    path: str,
    token: str,
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{API_BASE}{path}",
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "FabricAgent/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            body = {"message": raw.decode("utf-8", errors="replace")}
        return exc.code, body
    except OSError as exc:
        raise RuntimeError(f"GitHub request failed: {exc}") from exc


def search_issues(query: str, token: str) -> list[dict[str, Any]]:
    scoped_query = f"{query} repo:{REPO} is:issue"
    encoded = urllib.parse.urlencode({"q": scoped_query, "per_page": 10})
    status, body = _request("GET", f"/search/issues?{encoded}", token, None)
    if status != 200:
        raise RuntimeError(body.get("message", f"GitHub search failed with HTTP {status}"))
    return body.get("items", [])


def create_issue(title: str, body: str, token: str, *, label: str = "") -> str:
    status, response = _request(
        "POST",
        f"/repos/{REPO}/issues",
        token,
        {"title": title, "body": body},
    )
    if status != 201:
        raise RuntimeError(response.get("message", f"Issue creation failed with HTTP {status}"))

    issue_url = response.get("html_url", "")
    issue_number = response.get("number")
    if not issue_url or not issue_number:
        raise RuntimeError("GitHub created an issue but returned no URL or number")

    if label:
        try:
            _request(
                "POST",
                f"/repos/{REPO}/issues/{issue_number}/labels",
                token,
                {"labels": [label]},
            )
        except RuntimeError:
            pass
    return issue_url


def _require_token() -> tuple[str, str]:
    token, source = resolve_github_token()
    if not token:
        raise RuntimeError("GitHub is not authenticated; run 'fabric setup github'")
    return token, source


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("status", help="show the selected GitHub account")

    search = commands.add_parser("search", help="search Fabric issues")
    search.add_argument("query")

    create = commands.add_parser("create", help="create one confirmed Fabric issue")
    create.add_argument("--title", required=True)
    create.add_argument("--body-file", required=True, type=Path)
    create.add_argument("--label", choices=("bug", "enhancement"), default="")
    create.add_argument(
        "--confirmed",
        action="store_true",
        help="assert that the user approved this exact title and body",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "create" and not args.confirmed:
        parser.error("create requires --confirmed after explicit user approval")

    try:
        token, source = _require_token()
        if args.command == "status":
            user = fetch_github_user(token)
            if not user or not user.get("login"):
                raise RuntimeError("GitHub rejected the selected credential")
            print(f"Authenticated as {user['login']} ({source})")
            return 0

        if args.command == "search":
            for issue in search_issues(args.query, token):
                print(f"#{issue.get('number')}\t{issue.get('title', '')}\t{issue.get('html_url', '')}")
            return 0

        body = args.body_file.read_text(encoding="utf-8")
        print(create_issue(args.title, body, token, label=args.label))
        return 0
    except (OSError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
