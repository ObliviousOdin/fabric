#!/usr/bin/env bash
# One-command git guardrail bootstrap for this checkout.
#
# Every agent session (Claude, Codex, Grok, ...) and every maintainer clone
# runs this once before committing. It:
#   1. Sets the canonical repository identity (repo-local scope).
#   2. Enables the committed .githooks (identity + message enforcement).
#   3. Blocks git from silently inventing an identity.
#   4. Verifies the result.
#
# See AGENT_GUARDRAILS.md ("Commit identity & attribution") for the policy;
# scripts/commit_identity_audit.py is the enforcement source of truth.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

python3 scripts/configure-maintainer-git-identity.py --scope local
git config --local core.hooksPath .githooks
git config --local user.useConfigOnly true

python3 scripts/commit_identity_audit.py --check-config
echo "Git guardrails installed: canonical identity + .githooks enforcement."
