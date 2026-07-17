#!/usr/bin/env bash
# File an issue on the upstream Fabric repository (ObliviousOdin/fabric).
#
# Usage:
#   fabric-issue.sh "Issue title" /path/to/body.md [label]
#
# Auth detection is delegated to the shared github-auth helper
# (skills/github/github-auth/scripts/gh-env.sh): prefers an authenticated
# `gh` CLI, falls back to GITHUB_TOKEN from the environment or the Fabric
# profile's .env. Prints the created issue URL on success.

set -euo pipefail

OWNER_REPO="ObliviousOdin/fabric"

TITLE="${1:-}"
BODY_FILE="${2:-}"
LABEL="${3:-}"

if [ -z "$TITLE" ] || [ -z "$BODY_FILE" ] || [ ! -f "$BODY_FILE" ]; then
    echo "Usage: $0 \"Issue title\" /path/to/body.md [label]" >&2
    exit 2
fi

# --- Auth detection (shared helper; summary output silenced) ---

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# gh-env.sh probes git/gh and tolerates their failures internally, so it
# must not run under this script's errexit (e.g. `git remote` fails when
# invoked outside a repo).
set +e
# The path is resolved from SCRIPT_DIR at runtime; ShellCheck resolves source
# annotations from its invocation directory instead.
# shellcheck disable=SC1091
source "$SCRIPT_DIR/../../github-auth/scripts/gh-env.sh" >/dev/null
set -e
GH_AUTH_METHOD="${GH_AUTH_METHOD:-none}"

if [ "$GH_AUTH_METHOD" = "gh" ]; then
    ARGS=(--repo "$OWNER_REPO" --title "$TITLE" --body-file "$BODY_FILE")
    if [ -n "$LABEL" ]; then
        # Labels can require triage permission — retry without on failure.
        gh issue create "${ARGS[@]}" --label "$LABEL" 2>/dev/null \
            || gh issue create "${ARGS[@]}"
    else
        gh issue create "${ARGS[@]}"
    fi
    exit 0
fi

if [ "$GH_AUTH_METHOD" != "curl" ] || [ -z "${GITHUB_TOKEN:-}" ]; then
    echo "Not authenticated with GitHub. Run: fabric setup github" >&2
    exit 1
fi

# --- Create via REST (body JSON built with python to escape safely) ---

PAYLOAD=$(python3 - "$TITLE" "$BODY_FILE" "$LABEL" <<'PYEOF'
import json, sys
title, body_file, label = sys.argv[1], sys.argv[2], sys.argv[3]
payload = {"title": title, "body": open(body_file, encoding="utf-8").read()}
if label:
    payload["labels"] = [label]
print(json.dumps(payload))
PYEOF
)

# Guard every step below so `set -e` can't skip the failure diagnostics.
RESPONSE=$(curl -s -X POST \
    -H "Authorization: token $GITHUB_TOKEN" \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/$OWNER_REPO/issues" \
    -d "$PAYLOAD" || true)

URL=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('html_url',''))" 2>/dev/null || true)

if [ -n "$URL" ]; then
    echo "$URL"
else
    echo "Issue creation failed:" >&2
    echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('message','unknown error'))" >&2 2>/dev/null \
        || echo "${RESPONSE:-no response (network error?)}" >&2
    exit 1
fi
