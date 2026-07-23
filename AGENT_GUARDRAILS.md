# Agent Guardrails — Multi-Agent Collaboration & Merge Discipline

**Read this before you touch anything.** It applies to every autonomous or
semi-autonomous coding agent working in this repository — Claude / Claude Code,
OpenAI Codex, Grok, Copilot, Gemini, Devin, Cursor, and any other LLM-driven
worker — whether you run solo or as one of many agents on the same repo at the
same time.

This document is the **collaboration + merge contract**. It answers: *where am I
allowed to work, how do I keep out of other agents' way, what has to be true
before my change merges, and which CI gate am I about to hit?*

It does **not** replace the deep, repo-specific engineering guidance. Two files
own that, and you must follow them too:

- [`AGENTS.md`](AGENTS.md) — architecture, contribution rubric, the Footprint
  Ladder, testing rules, and the **Known Pitfalls** list. This is the "how to
  write code that gets merged here" bible.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — setup, project structure, cross-platform
  rules, security, dependency pinning.

If this document and those disagree on a *code* question, they win. On a
*collaboration / merge / CI* question, this document wins.

---

## 0. The 60-second contract

Every agent, every task, no exceptions:

1. **Bootstrap your git identity first.** Before your first commit, run
   `bash scripts/setup-git-guardrails.sh`. Commits carry the canonical
   repository identity (`PrimeOdin <11676741+ObliviousOdin@users.noreply.github.com>`)
   — **never** an AI-tool identity (Claude, Codex, Copilot, …) as author,
   committer, or co-author, and no tool-attribution footers (§3.3).
2. **Never commit to `main`.** Work on a task branch. `main` is always green and
   always deployable.
3. **One task → one branch → one PR.** Keep the branch short-lived and the diff
   scoped to the task. Every line must trace to the request (feature PRs) or to a
   declared refactor.
4. **Stay in your lane.** Edit only the [ownership zone](#2-ownership-zones--who-works-where)
   you were assigned. Touching shared contracts (§2.1) requires explicit
   coordination.
5. **Rebase before you push, rebase before you merge.** A stale branch silently
   reverts other agents' fixes when squashed (this has actually happened — see
   §5).
6. **Green PR ≠ green `main`.** The most expensive builds (iOS, macOS/Windows
   packaging & smoke) are **cost-gated OFF on pull requests** and only run after
   merge. If you touched those surfaces, you own verifying them (§4.2).
7. **Run the real CI gate locally before you push.** Use the exact commands in
   [§6](#6-pre-flight-per-zone-run-before-you-push). "Works on my machine" is not
   a status.
8. **You do not merge your own work.** A separate reviewer/merger gate decides
   that (§3). No agent self-approves or force-merges.
9. **When intent is ambiguous, stop and ask a human.** Do not guess on design
   intent, security boundaries, or anything irreversible (§8).

If you can only remember one sentence: **stay in your assigned zone, keep `main`
green, and let the merger merge.**

---

## 1. How your specific tool should load this

Different agents look for different files. All roads lead here:

| Tool | Auto-loaded file | What it points to |
| --- | --- | --- |
| Claude / Claude Code | `CLAUDE.md` | → this file + `AGENTS.md` |
| OpenAI Codex, most "AGENTS.md-aware" agents | `AGENTS.md` (banner at top) | → this file |
| Grok, Gemini, Devin, Cursor, bespoke crews | *no fixed convention* | Paste this file (or its path) into the system prompt / repo rules before the agent starts. |

**Orchestrators:** when you spin up a worker agent of any kind, its system prompt
MUST include (or link) this file and name the worker's ownership zone. An agent
that has not read its guardrails is not ready to run.

---

## 2. Ownership zones — who works where

This is a monorepo with clearly separable surfaces. Assign each worker agent a
**zone**, and have it edit only that zone. Non-overlapping zones are what let
many agents run in parallel without stepping on each other.

The canonical source of the tree is the filesystem and `AGENTS.md` → *Project
Structure*. This table maps each zone to its **language, its CI gate, and the
command you run locally before pushing**.

| Zone | Paths (primary) | Lang | CI workflow / job | Runs on PR? |
| --- | --- | --- | --- | --- |
| **Core agent / CLI** | `run_agent.py`, `cli.py`, `agent/`, `model_tools.py`, `toolsets.py`, `fabric_cli/`, `tools/`, `gateway/`, `cron/`, `fabric_state.py`, `fabric_constants.py` | Python | `Public repository checks` → *public-release-audit* (ruff + audits); plus `scripts/run_tests.sh` | ✅ |
| **Web dashboard** | `web/` | TS/React | `Public repository checks` → *web-workspace* (typecheck, lint, test, build) | ✅ |
| **Docs site** | `website/`, `docs/`, mapped narrative docs | TS/MDX | `Public repository checks` → *documentation* (`docs_sync`, skill-doc gen, site build) | ✅ |
| **Desktop app** | `apps/desktop/`, `apps/shared/` | TS/Electron | `Desktop packaging verification` → *brand-contract* on PR; **packaging matrix (mac/win/linux) only on `main`** | ⚠️ partial |
| **Mobile — shared/PWA** | `apps/mobile-web/`, `apps/shared/` | TS | `Mobile clients` → *web* (typecheck, test, build + Python delivery tests) | ✅ |
| **Mobile — Android** | `apps/mobile/android/` | Kotlin/Gradle | `Mobile clients` → *android* (unit tests, lint, assemble debug+release) | ✅ |
| **Mobile — iOS** | `apps/mobile/ios/` | Swift/Xcode | `Mobile clients` → *ios* — **only on `main`** (macOS runners are 10× cost) | ❌ |
| **Skills / plugins** | `skills/`, `optional-skills/`, `plugins/` | Mixed | `Public repository checks` (skills-governance audit) + `docs_sync` skill metadata | ✅ |
| **Release / packaging** | `.github/workflows/`, `scripts/ci/`, `Dockerfile`, `deploy/`, `packaging/` | YAML/Py | `Fabric release channels`, `Desktop packaging`, plus release-workflow contract audit | ⚠️ partial |

> **⚠️ / ❌ in "Runs on PR?"** means the full build is **not** exercised by your
> PR. Read [§4.2 — the cost-gate trap](#42-the-cost-gate-trap-green-pr--red-main)
> before you touch those zones.

### 2.1 Shared / contract surfaces — coordinate before editing

Some files are read by *every* zone. A change here can green your PR and break
three other agents. **Do not edit these as a side effect of a zone task** —
raise it with the orchestrator/human first, land it as its own PR, then have the
other agents rebase:

- `package.json` / `package-lock.json` (root workspace manifest — mobile, web,
  desktop CI all key off it)
- `pyproject.toml` / `uv.lock` (Python deps for every Python job)
- `apps/shared/**` (imported by both desktop and mobile)
- `fabric_constants.py`, `toolsets.py`, `model_tools.py` (core contracts every
  tool and platform depends on)
- `docs/documentation-contracts.json` (the docs-impact gate reads this)
- Anything under `.github/workflows/` (the gates themselves)
- Capability/wire manifests under `capability-packs/`, mobile spine contracts

Rule of thumb: **if two agents would both want to edit it, it's a shared surface
— serialize it.**

---

## 3. Branching, isolation, and the merge gate

### 3.1 Branch and worktree isolation

- **One branch per task.** Name it for the work, not the agent:
  `feat/<area>-<slug>`, `fix/<area>-<slug>`, `chore/<area>-<slug>`. (Automated
  runners may prefix with the tool, e.g. `claude/…`, `codex/…` — that's fine, the
  `<area>` still comes next.)
- **Parallel agents use git worktrees**, not a shared checkout, so builds and
  test runs don't collide:

  ```bash
  git fetch origin main
  git worktree add ../fabric-<area>-<slug> -b feat/<area>-<slug> origin/main
  cd ../fabric-<area>-<slug>
  # work, test, commit here
  ```

- **Never `git push --force` a shared branch.** Force-with-lease is allowed
  *only* on your own task branch and *only* when you are certain no one else has
  based work on it (e.g. resetting a branch that carried only already-merged
  history).

### 3.2 The merge gate (what "done" means)

An agent's job ends at **"PR open, CI green, reviewer satisfied."** It does **not**
end at "merged." Merging is a separate gate:

1. **CI must be fully green** on the PR's head commit — every required check, not
   just the fast ones.
2. **A reviewer pass** (human or a dedicated reviewer agent) confirms the diff
   matches the request, the premise holds (`AGENTS.md` → *Before you call it a
   bug*), and no change-detector tests or dead code were added.
3. **The branch is rebased on latest `main`** immediately before merge (§5).
4. **Merge is squash**, one PR = one commit on `main`, conventional-commit
   subject (`type(scope): summary`), PR number preserved.
5. **No self-merge.** The worker that wrote the code does not merge it. A
   dedicated merger/gatekeeper (human or agent) does, sequentially, one PR at a
   time. Post-merge, other in-flight agents rebase.

If you are the merger agent: verify green CI, re-read the diff against the
stated task, check `git diff HEAD~1..HEAD` after squashing for **unexpected
deletions** (the stale-branch trap, §5), and only then merge. Never merge on a
red or stale check.

### 3.3 Commit identity & attribution (hard gate)

Commits in this repository are attributed to the **repository identity**, not
to the tool that produced them. This is enforced at three layers — local
config, committed git hooks, and CI — so it holds even when one layer is
bypassed.

**The policy** (source of truth: `scripts/commit_identity_audit.py`):

- Author and committer must be an allowlisted repository identity. Canonical
  (and only allowed author email):
  `PrimeOdin <11676741+ObliviousOdin@users.noreply.github.com>`. GitHub's
  web-flow committer (squash merges, web edits) and dependabot are also
  accepted where they naturally appear. Personal emails and private domains
  stay out of the public tree — the public-release audit enforces that too.
- **No AI-tool identity anywhere**: not as author, not as committer, not in
  `Co-Authored-By:` / `Signed-off-by:` trailers. Claude, Codex, Copilot,
  Gemini, Grok, Devin, Cursor, Aider, Windsurf, … are all rejected.
- **No tool-attribution footers** in commit messages: no
  `Generated with …` lines, no robot-emoji footers, no AI session links
  (`claude.ai/…`, `chatgpt.com/…`, `Claude-Session:` …). Plain prose that
  merely *mentions* a tool ("stop impersonating Claude Code …") is fine —
  only structured attribution is banned.
- **Agents: your harness may auto-append such trailers. Strip them.** In this
  repo the harness convention loses to the repo policy; the hooks and CI will
  reject the commit otherwise.

**Why so strict about branch commits:** PRs land as squash merges, and GitHub
**auto-appends `Co-authored-by:` trailers for every distinct author on the
branch** into the squash message. One Claude-authored commit on your branch
pollutes `main` even if every message you wrote was clean. Clean branch
commits are the only reliable input; CI is the backstop.

**The three layers:**

1. **Bootstrap** (run once per session/clone):
   `bash scripts/setup-git-guardrails.sh` — sets the canonical identity
   (repo-local), enables the committed hooks (`core.hooksPath .githooks`), and
   turns on `user.useConfigOnly`.
2. **Hooks** (committed in `.githooks/`): `pre-commit` rejects a commit whose
   *resolved* identity is not allowlisted — it checks `git var
   GIT_AUTHOR_IDENT`/`GIT_COMMITTER_IDENT`, so `--author` and `GIT_AUTHOR_*`
   overrides are caught, not just `git config`; `commit-msg` rejects forbidden
   trailers and footers before the commit exists; `pre-push` audits the actual
   outgoing commits (same code path as CI), catching anything created with
   `--no-verify`.
3. **CI** (`public-ci.yml`): audits every PR's full commit range
   (`base..head`) and every push to `main`. Nothing local is trusted; CI
   re-checks the real commit objects.

**If you inherited a dirty commit** (wrong author or forbidden trailer):

```bash
# last commit only: fix the author and edit the trailers out of the message
git commit --amend --reset-author
# several dirty commits: collapse the branch into clean commits
# (branches squash-merge anyway, so per-commit history is not preserved)
git fetch origin main && git reset --soft origin/main && git commit
# verify, then force-with-lease — allowed on your OWN task branch only
python3 scripts/commit_identity_audit.py --range origin/main..HEAD
git push --force-with-lease origin <your-task-branch>
```

---

## 4. CI reality you must know

There is **no monolithic "CI" check.** Coverage is spread across five workflows,
each with path filters and cost gates. Know which one your change triggers.

### 4.1 The workflows

| Workflow | File | Triggers on | What it gates |
| --- | --- | --- | --- |
| **Public repository checks** | `public-ci.yml` | every PR + push to `main` | Python lint (`ruff`), release/brand/identity audits, `web` typecheck+lint+test+build, docs build + `docs_sync` contracts |
| **Mobile clients** | `mobile.yml` | PR/push touching mobile paths | Android build+lint+tests (PR), iOS build+tests (**`main` only**), shared+PWA TS + Python delivery tests |
| **Desktop packaging** | `desktop-packaging.yml` | PR/push touching desktop paths | Brand contract (PR), OS packaging matrix (**`main` only**) |
| **Fabric release channels** | `release-channels.yml` | every PR + push + dispatch | Build candidate + provenance, ubuntu smoke (PR), mac/win smoke (**`main` only**), alpha/beta/production deploy |
| **Publish documentation** | `docs-pages.yml` | push to `main` (docs paths) | Builds & deploys the docs site |
| **Refresh skills index** | `skills-index.yml` | schedule (2×/day) + dispatch | Crawls skill hubs, rebuilds the index, redeploys |

### 4.2 The cost-gate trap: green PR ≠ red `main`

macOS runners bill at **10×** and Windows at **2×** Linux minutes, so the repo
deliberately **skips the expensive builds on pull requests**:

- **iOS** build + tests — skipped on PR, runs on push to `main`.
- **Desktop packaging matrix** (mac/win/linux `dist:*`) — skipped on PR, runs on
  `main`.
- **macOS + Windows package smoke** — skipped on PR (a placeholder job keeps the
  required check name green), runs on `main`.

**Consequence:** your PR can be 100% green while your change breaks the iOS build
or the Windows installer, and it will only turn red *after it lands on `main`*.

If your task touches `apps/mobile/ios/**`, `apps/desktop/**`, or packaging:

- Build that platform **locally** before you push (§6), or
- Trigger the workflow via `workflow_dispatch` on your branch and wait for green,
  and
- Flag it in the PR description so the merger knows a post-merge platform check is
  expected. **Do not treat a green PR as proof the native build works.**

### 4.3 Path filters

`mobile.yml` and `desktop-packaging.yml` only run when their paths change. If you
edited a *shared* file (e.g. root `package.json`) that those apps depend on, the
mobile/desktop jobs may not fire on your PR at all — another reason shared-surface
edits (§2.1) get their own coordinated PR and a manual platform check.

---

## 5. Guardrails distilled from real past CI/CD failures

Each of these cost the project a red build or a bad merge. They are ordered by how
often they bite an agent.

1. **Stale branch silently reverts fixes on squash-merge.**
   Squash-merging a branch that is behind `main` overwrites unrelated files with
   the branch's older copy. Always
   `git fetch origin main && git rebase origin/main` before pushing and before
   merging, and check `git diff HEAD~1..HEAD` for unexpected deletions after the
   squash. *(Documented in `AGENTS.md` → Known Pitfalls; seen in practice.)*

2. **"Works locally, fails in CI" (and the reverse).**
   Never call `pytest` directly. Use **`scripts/run_tests.sh`** — it unsets
   credential env vars, forces `TZ=UTC`, `LANG=C.UTF-8`, `PYTHONHASHSEED=0`, and
   runs each test file in its own subprocess, exactly like CI. Direct `pytest` on
   a machine with API keys and a non-UTC clock diverges from CI.

3. **Tests that write to `~/.fabric/`.**
   Tests must stay inside the temp `FABRIC_HOME` the `conftest.py` autouse fixture
   provides. Hardcoding `~/.fabric/` (or `Path.home()` without mocking it) leaks
   across the parallel suite and fails nondeterministically. Use `get_fabric_home()`
   in code, never a hardcoded path.

4. **Change-detector tests break on routine data updates.**
   Do not assert exact model-catalog contents, config version literals, or
   enumeration counts (`assert len(models) == 8`). They turn every routine model
   or skill addition into a red build. Assert *invariants/relationships* instead
   (`AGENTS.md` → *Don't write change-detector tests*). Reviewers reject these.

5. **Generated files drift from their source.**
   Several checks fail closed if a committed generated artifact is out of date:
   - `python3 scripts/docs_sync.py check` — regenerated runtime docs must match.
   - `python3 website/scripts/generate-skill-docs.py --check` — skill docs.
   - iOS: `git diff --exit-code -- FabricMobile.xcodeproj Fabric/Info.plist` after
     `ci_scripts/ci_post_clone.sh` — the committed Xcode project must match what
     the generator produces.

   Fix by **regenerating and committing the output in the same PR**, never by
   editing the generated file by hand.

6. **External-data health floors (skills index).**
   `skills-index.yml` refuses to ship a "degenerate" index and fails when a source
   drops below its `EXPECTED_FLOORS` (a real failure: `clawhub` came back with
   1744 skills against a floor of 20000). If a source is *genuinely* shrinking,
   lower the floor in `scripts/build_skills_index.py` **in the same PR** — don't
   just retry.

7. **Brand / product-identity audits fail closed.**
   `scripts/public-release-audit.py`, `scripts/fabric-brand-audit.py`, and
   `scripts/fabric_identity_audit.py` scan the whole tree. They reject:
   - Any reference to the **former product identity** or its repo slugs.
   - New `FABRIC_*`-style config tokens documented in Markdown that don't exist in
     non-doc source (`docs_sync audit`). Don't invent env-var tokens in docs.
   - Inventing Fabric names for real third-party identifiers, or vendor-positioning
     marketing copy.

   Keep new prose about **Fabric**, the agents, and generic mechanics. The public
   interface is `fabric`; state defaults to `~/.fabric`.

8. **Dependency pins + lockfiles must move together (supply-chain hardening).**
   Dependencies are hash/version-pinned and installs are `--locked`. If you change
   a dependency you must update **every** lockfile it appears in — `uv.lock`
   (`uv sync --locked` must pass), `package-lock.json` (`npm ci` must pass), and
   the Android Gradle wrapper SHA (`mobile.yml` verifies the exact
   `gradle-wrapper.jar` checksum and `8.9` distribution hash). A drifted lockfile
   fails install before any test runs. See `CONTRIBUTING.md` → *Dependency pinning
   policy*.

9. **Desktop & mobile TS is under-covered by PR CI — verify locally.**
   The desktop PR gate is only the *brand contract*; desktop `typecheck` / `lint`
   / `test:desktop` are **not** run on PRs. Run them yourself (§6) — a type error
   in `apps/desktop/` will not be caught by your PR.

10. **Don't wire in dead code without an end-to-end path.**
    Unused modules were unused for a reason. Before connecting one to a live path,
    exercise the real resolution chain (real imports, temp `FABRIC_HOME`), not
    mocks. Mock-green unit tests have hidden integration breaks that surface in CI
    or on `main`.

---

## 6. Pre-flight per zone (run before you push)

These mirror the CI jobs. Run the block(s) for the zone(s) you touched. From the
repo root, on an environment set up per `CONTRIBUTING.md`.

**Core agent / CLI / any Python zone**
```bash
ruff check .                          # lint contract (CI pins ruff; any recent ruff is fine locally)
scripts/run_tests.sh tests/<area>/    # hermetic, CI-parity; scope to what you touched
python3 scripts/public-release-audit.py
python3 scripts/fabric_identity_audit.py
python3 scripts/fabric-brand-audit.py --mode public
```

**Release / packaging (`.github/workflows/**`, `scripts/ci/**`, audit gates)** — a
shared/contract surface (§2.1); coordinate before editing:
```bash
ruff check .
scripts/run_tests.sh tests/scripts/          # audit, release-channels, desktop-asset contracts
python3 scripts/public-release-audit.py                             # workflow-surface + identity
python3 scripts/fabric_identity_audit.py
python3 scripts/fabric-brand-audit.py --mode public
python3 -m unittest discover -s tests/scripts -p 'test_*audit.py'   # exactly what public-ci runs
```
Pre-merge verification for this zone = the contract tests + audits above **plus** a
`release-channels.yml` `channel=alpha` dispatch on the branch. **`desktop-release.yml`'s
first live run is necessarily post-merge** — the workflow-dispatch API can't see a
workflow file until it is on `main`, and the `desktop-signing` environment + signing
secrets don't exist until the maintainer provisions them. Say so in the HANDOFF
"Not verified" block and babysit the first real run. Native desktop builds do **not**
run on PRs (§4.2).

**Web dashboard (`web/`)**
```bash
npm ci
npm run --prefix web typecheck
npm run --prefix web lint
npm test --prefix web -- --run
npm run --prefix web build
```

**Docs site (`website/`, `docs/`, skills)**
```bash
python3 scripts/docs_sync.py check
python3 website/scripts/generate-skill-docs.py --check
python3 scripts/docs_sync.py audit
npm ci --prefix website
npm run --prefix website typecheck
npm run --prefix website build
```

**Desktop (`apps/desktop/`, `apps/shared/`)** — CI does NOT run these on PR:
```bash
npm ci
npm run --prefix apps/desktop typecheck
npm run --prefix apps/desktop lint
npm run --prefix apps/desktop test:desktop
npm run --prefix apps/desktop dist:linux -- --publish never   # smoke the packager
```

**Mobile — shared + PWA (`apps/mobile-web/`, `apps/shared/`)**
```bash
npm ci
npm run typecheck --workspace apps/shared
npm test --workspace apps/shared -- --run
npm run typecheck --workspace apps/mobile-web
npm test --workspace apps/mobile-web -- --run
npm run build --workspace apps/mobile-web
scripts/run_tests.sh tests/work_state tests/tui_gateway -q
```

**Mobile — Android (`apps/mobile/android/`)**
```bash
cd apps/mobile/android
./gradlew --no-daemon :app:testDebugUnitTest :app:lintDebug :app:lintVitalRelease :app:assembleDebug :app:assembleRelease
```

**Mobile — iOS (`apps/mobile/ios/`)** — CI runs this only on `main`; verify on a Mac:
```bash
cd apps/mobile/ios
ci_scripts/ci_post_clone.sh
git diff --exit-code -- FabricMobile.xcodeproj Fabric/Info.plist   # committed project must match generator
python3 ../../../tests/scripts/test_ios_project_generation.py
# then xcodebuild test / build (see mobile.yml for the exact simulator invocation)
```

---

## 7. Coordination, handoff & role rotation (for parallel crews)

### 7.1 Decomposition & shared state

- **Non-overlapping decomposition first.** The orchestrator splits work so no two
  workers hold the same zone (§2) or the same shared surface (§2.1) at once.
- **Serialize shared-surface edits.** Dependency bumps, `apps/shared/**`, core
  contracts, and workflow changes land as their own PRs, merged first; other
  agents rebase after.
- **Conventional commits, one PR per logical change.** `type(scope): summary`,
  PR number in the squash subject (matches the existing history).
- **Preserve authorship of external contributors.** When building on an outside
  contributor's work, cherry-pick / rebase-merge so their credit survives —
  don't reimplement from scratch (`AGENTS.md` → *Contributor credit
  preserved*). Between this repo's own agents there is no per-tool credit:
  everything carries the repository identity (§3.3).
- **A durable multi-agent work queue already exists.** If you need shared task
  state across agents, use the built-in Kanban board (`fabric kanban`, see
  `AGENTS.md` → *Kanban*) rather than inventing an ad-hoc `MEMORY.md`. Delegation
  to subagents goes through `delegate_task` (`AGENTS.md` → *Delegation*).
- **The `.codex-audits/` directory** holds saved UI/visual audits from agent runs;
  follow that convention if you produce audit artifacts.

### 7.2 Same-surface handoff — the take-over ritual

Sometimes two agents legitimately work the same surface in sequence (agent A
went offline mid-task; a specialist takes over a stuck piece; a fresh session
resumes an old branch). The rule is **single writer per branch**: exactly one
agent owns a branch at any moment, and ownership transfers explicitly.

Taking over an in-flight branch:

1. **Announce it** — comment on the PR (or the Kanban card): "taking over from
   here." From that comment on, you own the branch; the previous agent must not
   push to it again.
2. **Read the handoff state** — the PR description's `HANDOFF` block (§7.4),
   the diff, and the last CI run. Do not trust "done" claims you can't see in
   the diff or in green checks.
3. **Sync and verify before adding work** — `git fetch origin && git rebase
   origin/main`, run the §6 pre-flight for the zone, and
   `python3 scripts/commit_identity_audit.py --range origin/main..HEAD`. If the
   inherited commits are dirty (identity/trailers), clean them now (§3.3) —
   dirt you push is dirt you own.
4. **Update the `HANDOFF` block** after every push so the next agent (or the
   human) can take over from *you* just as cheaply.

Never have two agents pushing to one branch concurrently — if the work is big
enough to want two writers, it is big enough to split into two branches with
one integrating PR.

### 7.3 Role handoffs: author → reviewer → merger → babysitter

Separate the roles; an agent can hold at most one role per PR:

- **Author** writes the change, runs the §6 pre-flight, opens the PR with a
  filled `HANDOFF` block, and stays responsive to review.
- **Reviewer** (different agent or human) verifies the premise against the
  codebase (`AGENTS.md` → *Before you call it a bug*), checks the diff against
  the stated task, hunts for change-detector tests and zone violations, and
  leaves actionable review comments. The reviewer never pushes fixes to the
  author's branch — findings go back to the author (or the reviewer formally
  takes over via §7.2).
- **Merger** is the only role that merges (§3.2): green CI + review approval +
  fresh rebase, squash, then post-merge `git diff HEAD~1..HEAD` sanity check.
- **CI babysitter** — after merge (or on a long-running PR), one agent watches
  CI: the PR checks *and* the `main` run that executes the cost-gated builds
  the PR skipped (§4.2). On failure it diagnoses, then either pushes the fix
  (if it owns the branch) or files the failure back to the author with logs.
  Watching means following through until merged/closed or explicitly relieved.

A handoff to reviewer/merger/babysitter happens **in the PR thread** ("ready
for review", "review passed, over to merger", "merged — babysitting the main
run"), so the chain of custody is auditable later.

### 7.4 The PR handoff block

Every agent-opened PR carries this block in its description (extends the
repository PR template — Summary / Verification / Documentation impact stay as
they are), kept current on every push:

```markdown
## HANDOFF
- **State:** in-progress | ready-for-review | review-passed | needs-fixes | blocked
- **Done:** what is complete, at claim level a reviewer can verify from the diff
- **Verified:** exactly which §6 pre-flight commands ran, and their results
- **Not verified:** what was NOT run (e.g. cost-gated iOS build — §4.2) and why
- **Remaining:** ordered list of what's left, smallest first
- **Risks/land-mines:** anything the next agent would step on
- **Zone(s) touched:** per §2, flag any shared-surface edits (§2.1)
```

The block is the contract between agents: the next agent trusts what's in
`Verified`, re-checks anything in `Not verified`, and starts at the top of
`Remaining`.

---

## 8. Escalate to a human — don't guess

Use the human-in-the-loop path (for Claude Code: `AskUserQuestion`; for others,
stop and surface the question) when:

- **Intent is ambiguous** — the task could be read two ways, or a reviewer comment
  has multiple interpretations.
- **You'd touch design intent** — a limitation might be *deliberate*
  (`AGENTS.md` → *Before you call it a bug*). Profiles are isolated on purpose;
  some omissions are load-bearing. Read `git log -p -S "<symbol>"` before
  "fixing" a perceived gap.
- **Security boundaries, secrets, auth, or release/publishing** are involved.
- **The change is hard to reverse or outward-facing** — deleting data, force-pushing
  shared history, publishing a release, posting externally.
- **A shared surface (§2.1) or a workflow gate needs to change.**

Taste-level "should this exist at all" calls (the *what we don't want* list in
`AGENTS.md`) are for a human maintainer, not an automated close/merge.

---

## 9. Quick reference card

```
BEFORE YOU START   read CLAUDE.md/AGENTS.md/this file · confirm your zone (§2)
                   bash scripts/setup-git-guardrails.sh   (identity + hooks, §3.3)
BRANCH             git fetch origin main → worktree → feat|fix|chore/<area>-<slug>
STAY IN LANE       edit only your zone · shared surfaces (§2.1) = coordinate
COMMIT IDENTITY    PrimeOdin <11676741+ObliviousOdin@users.noreply.github.com>
                   no AI author/committer/co-author · no Generated-with footers
                   no session links · strip harness-added trailers (§3.3)
BEFORE YOU PUSH    run the §6 block for your zone · run_tests.sh, not pytest
                   regenerate any generated files · update every lockfile you touched
                   commit_identity_audit.py --range origin/main..HEAD
REBASE             git rebase origin/main before push AND before merge (§5)
PR                 fill + maintain the HANDOFF block (§7.4)
                   CI green + reviewer OK ≠ done-by-you; you do NOT self-merge
HANDOFF            single writer per branch · take-over ritual (§7.2)
                   one role per agent per PR: author/reviewer/merger/babysitter (§7.3)
COST-GATE TRAP     iOS / macOS / Windows / desktop pkg don't run on PR (§4.2)
                   touched them? build locally or dispatch, and flag it
NEVER              commit to main · force-push shared branches · invent FABRIC_* tokens
                   reintroduce former-product identity · write change-detector tests
WHEN UNSURE        stop, ask a human (§8)
```

*Keep this file current: when a new CI gate, cost gate, or recurring failure
mode appears, add it to §4 and §5 in the same PR that introduces it.*
