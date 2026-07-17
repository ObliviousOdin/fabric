#!/usr/bin/env bash
# File an issue on the upstream Fabric repository (ObliviousOdin/fabric).
#
# Usage:
#   fabric-issue.sh "Issue title" /path/to/body.md [label]
#
# Auth resolution matches skills/github/github-auth/scripts/gh-env.sh:
# prefers an authenticated `gh` CLI, falls back to GITHUB_TOKEN from the
# environment or the Fabric profile's .env. Prints the created issue URL
# on success.

set -euo pipefail

OWNER_REPO="ObliviousOdin/fabric"

TITLE="${1:-}"
BODY_FILE="${2:-}"
LABEL="${3:-}"

if [ -z "$TITLE" ] || [ -z "$BODY_FILE" ] || [ ! -f "$BODY_FILE" ]; then
    echo "Usage: $0 \"Issue title\" /path/to/body.md [label]" >&2
    exit 2
fi

# --- Auth detection (same order as gh-env.sh) ---

if command -v gh &>/dev/null && gh auth status &>/dev/null 2>&1; then
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

GITHUB_TOKEN="${GITHUB_TOKEN:-}"
if [ -z "$GITHUB_TOKEN" ]; then
    _fabric_env="${FABRIC_HOME:-${HERMES_HOME:-$HOME/.fabric}}/.env"
    if [ -f "$_fabric_env" ] && grep -q "^GITHUB_TOKEN=" "$_fabric_env" 2>/dev/null; then
        GITHUB_TOKEN=$(grep "^GITHUB_TOKEN=" "$_fabric_env" | head -1 | cut -d= -f2 | tr -d '\n\r')
    fi
fi

if [ -z "$GITHUB_TOKEN" ]; then
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

RESPONSE=$(curl -s -X POST \
    -H "Authorization: token $GITHUB_TOKEN" \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/$OWNER_REPO/issues" \
    -d "$PAYLOAD")

URL=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('html_url',''))" 2>/dev/null)

if [ -n "$URL" ]; then
    echo "$URL"
else
    echo "Issue creation failed:" >&2
    echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('message','unknown error'))" >&2 2>/dev/null || echo "$RESPONSE" >&2
    exit 1
fi
