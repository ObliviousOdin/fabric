# Claude — start here

This repository is worked on by multiple AI agents (Claude, Codex, Grok, and
others), sometimes in parallel. Before making any change, read, in order:

1. **[`AGENT_GUARDRAILS.md`](AGENT_GUARDRAILS.md)** — the cross-agent
   collaboration + merge contract. Where you're allowed to work (ownership
   zones), how to branch/PR/merge without colliding with other agents, which CI
   gate your change hits, the "green PR ≠ green `main`" cost-gate trap, and
   guardrails distilled from real past CI failures. **Read this first.**
2. **[`AGENTS.md`](AGENTS.md)** — the deep engineering reference: architecture,
   the contribution rubric, the Footprint Ladder, testing rules, and the
   **Known Pitfalls** list.
3. **[`CONTRIBUTING.md`](CONTRIBUTING.md)** — setup, project structure,
   cross-platform rules, security, and dependency pinning.

The non-negotiables (full text in `AGENT_GUARDRAILS.md` §0):

- Never commit to `main`; work on a scoped task branch, one task → one PR.
- Stay in your assigned ownership zone; coordinate before touching shared
  surfaces (root `package.json`, `uv.lock`, `apps/shared/**`, core contracts,
  `.github/workflows/**`).
- `rebase origin/main` before you push and before you merge.
- Run the exact pre-flight commands for your zone (`AGENT_GUARDRAILS.md` §6);
  use `scripts/run_tests.sh`, never bare `pytest`.
- A green PR does **not** prove the iOS / macOS / Windows / desktop-packaging
  build works — those are cost-gated off PRs and only run on `main`.
- You do not self-merge; when intent is ambiguous, stop and ask via
  `AskUserQuestion`.
