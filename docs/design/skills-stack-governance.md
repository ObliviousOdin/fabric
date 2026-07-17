# Fabric Skills Stack Governance

Status: active implementation contract
Last updated: 2026-07-14

## Goal

Upgrade Fabric's skills stack from a collection of reusable instructions into a
governed, self-improving capability system. A capability must be discoverable,
minimally loaded, permission-bounded, source-aware, independently testable,
outcome-measured, versioned, and reversible.

The implementation order is intentional:

1. selection accuracy;
2. outcome quality;
3. safety and provenance;
4. reversibility;
5. learning quality;
6. efficiency;
7. catalog breadth.

Adding more skills before the first six properties are measurable increases
routing noise and persistent risk without proving user value.

## Existing foundation

Fabric already has most of the supply-chain substrate this work needs:

- a session-stable, progressively disclosed skill index;
- cache-safe slash-command and explicit skill activation;
- profile-scoped skill storage and mutation locks;
- quarantined Hub downloads, static scanning, tree digests, provenance, and
  transactional promotion;
- write-approval staging;
- Curator snapshots, archive, restore, and rollback;
- deterministic capability-pack compilation and journaled transactions.

These mechanisms must be generalized. A parallel registry or a new core model
tool would duplicate surface and violate Fabric's narrow-waist architecture.

## Gaps to close

The P0 gaps are:

- no single versioned contract for triggers, outputs, permissions, sources,
  budgets, outcomes, or evaluations;
- background-learned changes can reach the active skill tree by default;
- scanning and write approval for agent-created skills are opt-in;
- no standard trigger-negative, output, safety, or no-skill baseline evals;
- skill usage is counted, but task outcomes are not measured;
- runtime permissions are inherited from the session rather than leased to an
  active skill;
- the public `metadata.fabric` authoring contract and legacy
  `metadata.fabric` runtime readers have diverged;
- every active skill name and description is placed in the cached prompt, which
  will not scale to a substantially larger catalog.

## Canonical skill contract

`SKILL.md` remains Agent Skills-compatible and keeps the hot-path frontmatter
small. Fabric governance metadata lives beside it in `skill.contract.yaml`.

```yaml
schema_version: 1
identity:
  name: github-pr-workflow
  version: 1.2.0
  owner: fabric
  license: Apache-2.0
compatibility:
  fabric: ">=0.19,<1"
  hosts: [fabric]
  models: ["*"]
  platforms: [linux, macos, windows]
routing:
  triggers: ["open or update a pull request"]
  non_triggers: ["review code without publishing"]
  requires: []
  conflicts: []
  precedence: 50
interface:
  inputs: [{name: request, type: text, required: true}]
  outputs: [{name: pull_request_receipt, type: object}]
permissions:
  toolsets_required: [terminal, file]
  files: [{scope: workspace, access: read_write}]
  network: [{host: github.com, methods: [GET, POST, PATCH]}]
  secrets: [GITHUB_TOKEN]
  actions:
    reversible: [create_branch]
    approval_required: [push, create_pull_request, merge]
    prohibited: [force_push]
sources:
  - url: https://docs.github.com/
    retrieved_at: "2026-07-14"
    ttl_days: 30
budgets:
  context_tokens: 8000
  wall_seconds: 900
  tool_calls: 40
outcomes:
  primary: pull_request_created_or_updated
  guardrails: [tests_not_regressed, no_unapproved_merge]
evals:
  suite: evals/cases.yaml
limitations: []
```

Legacy third-party skills without a contract remain loadable during migration,
but are reported as `legacy_unverified`. First-party, learned, updated Hub, and
capability-pack skills progressively move to required contracts.

Schema v1 rejects unknown keys so policy-looking fields cannot be silently
ignored. File authority is limited to the closed `workspace`, `skill`, and
`temp` scopes (`skill` is read-only); network authority uses exact canonical
hosts and a closed set of uppercase HTTP methods; source URLs require HTTPS
except for loopback development; secret declarations use environment-variable
names. These declarations do not grant authority by themselves.

Source freshness is evaluated locally against an injectable UTC reference
time; validation never performs network I/O. Date-only retrieval values mean
midnight UTC, timestamps require an explicit offset, and a five-minute future
skew is allowed for clock drift. Impossible or farther-future values are
invalid. Expired TTLs emit the stable non-fatal `source_expired` finding so an
installed skill remains usable, but promotion must treat that finding as a
blocker. `ttl_days: 0` expires at the retrieval instant.

`metadata.fabric` is canonical inside `SKILL.md`. Readers accept
`metadata.fabric` as a legacy fallback until the shipped corpus and external
ecosystem have migrated. When both exist, canonical Fabric values win and
legacy values fill only missing keys.

## Governed lifecycle

All skill sources converge on one lifecycle:

```text
draft -> scanned -> evaluated -> awaiting_approval -> active
                                                    -> rejected
active -> superseded | revoked | archived -> rollback
```

Candidate bytes are immutable after scanning. Scan, evaluation, approval, and
promotion all bind to the same contract and tree digests. A failed or unavailable
gate leaves the current active version untouched.

Background review and `/learn` create drafts. They never mutate the active tree
directly. Promotion requires:

- a valid contract;
- a passing security scan;
- passing deterministic evaluations;
- no undeclared permission expansion;
- explicit approval for any permission expansion or sensitive action;
- an exact rollback pointer to the previous active digest.

## Evaluation contract

Every governed skill carries `evals/cases.yaml` with at least:

- positive trigger cases;
- negative trigger cases;
- output-contract cases;
- expected and forbidden tool-use cases;
- approval and safety behavior;
- regression fixtures.

Deterministic checks run on every touched skill in CI. Model-based trials run
multiple times, record variance, and compare against a no-skill baseline. A
skill is valuable only when it improves the primary outcome without regressing
its guardrails.

The deterministic runner now requires every executable baseline to declare a
unique `baseline_for` link to a non-baseline case with byte-equivalent input and
the same effective trial count. It accepts only a closed observation record
(`selected`, output, tool names, approval names, and finite 0–1 outcome score),
applies exact assertions, enforces per-case and suite thresholds, reports
population variance, and computes paired per-trial lift. It does not invoke a
provider or trust executable manifest hooks. Unpaired legacy baselines remain
valid with a migration warning but cannot produce a passing run.

## Runtime permissions and receipts

Loading a governed skill establishes a bounded, process-local permission lease
for the active turn. Explicit slash commands and bundles are validated and
staged before the turn ID exists, then consumed by the turn prologue; session
preloads are re-bound to each turn with a fresh tool-call budget. Main-document
`skill_view` loads bind immediately. Support-file reads do not create authority.
The registry is thread-safe, limited to 256 active turns and 16 leases per turn,
and expires inactive entries after four hours. Bounded tombstones make an
evicted enforced turn deny rather than degrade to “no lease.” It is never
persisted. A ContextVar stack tracks the concrete turn across nested/threaded
execution, and the outer `AIAgent.run_conversation` forwarder clears that exact
lease in `finally`, covering normal, early-return, adapter, and exception paths.
Finalized enforced turns become bounded deny tombstones, so a detached timed-out
worker cannot regain authority through a late nested dispatch.

The rollout is configured in `config.yaml`; no environment variable is read:

```yaml
skills:
  permissions:
    mode: observe # observe | enforce_learned | enforce_all
```

`observe` is the compatibility default: it evaluates verified declarations and
records only stable diagnostic codes without blocking. `enforce_learned`
enforces learned and unknown-provenance skills while observing bundled, Hub,
plugin, and external skills. `enforce_all` enforces every provenance. Legacy or
invalid contracts remain loadable in `observe`; they fail closed when their
provenance belongs to the configured enforcement population. A policy failure
or pre-turn binding failure also fails closed in either enforcement mode.

The lease guard runs in the existing dispatcher after request middleware and
before plugin or registry dispatch. It does not add a model tool, mutate a tool
schema, or rebuild the system prompt. Contract toolsets form the allowlist for
stacked skills. Approval declarations union across the stack and use Fabric's
existing approval gate; exact tool prohibitions are evaluated first and always
win. Every attempted tool call consumes the declared budget atomically, so
concurrent retries cannot overspend a one-call remainder. Wall-clock budgets
are checked before dispatch. Context-token budgets are retained for inspection
but currently emit `context_token_budget_uninspectable`, because the dispatcher
cannot attribute shared conversation tokens to one stacked skill without
mutating prompt accounting.

File checks understand `read_file`, `search_files`, `write_file`, and both patch
modes. Relative paths resolve under the workspace. Resolved containment enforces
the closed `workspace`, `skill`, and `temp` scopes, rejects traversal and symlink
escape, and keeps active skill roots read-only even when nested under a writable
workspace. Network checks understand exact URL targets for `web_extract` and
`browser_navigate`; the canonical host (including an explicit port) and HTTP
method must be declared.

Risk lanes are derived by one shared pure classifier used by both enforcement
snapshots and receipts:

- `standard`: structurally inspectable read-only/local declarations;
- `elevated`: writable files, network, secrets, or an opaque-effect toolset
  (`browser`, `code_execution`, `context_engine`, `delegation`, `memory`,
  `skills`, `terminal`, or `web`);
- `approval_required`: at least one declared approval action;
- `restricted`: at least one prohibited action;
- `unknown`: an unverified contract.

The effective stacked lane is the most restrictive lane. It is exposed through
the privacy-safe in-process snapshot together with contract digests, provenance,
mode, enforcement state, and budget counters. Snapshots hash the turn ID and
never contain prompts, tool arguments, URL values, secrets, or invoked paths.

This is a capability guard, not a shell parser. `terminal` and `execute_code`
file/network effects, `web_search` backend targets, indirect browser navigation,
CDP semantics, delegated subagent effects, provider memory/context-engine
effects, skill-manager mutations, and semantic action names that are not
registered tools cannot yet be structurally inspected; those cases emit stable
observation-gap codes instead of claiming coverage. Secret declarations raise
the lane and emit a gap, but are not a proof of which environment variables an
arbitrary implementation reads. Fabric-owned direct agent routes use the same
guard as registry tools; any third-party path that bypasses both dispatch seams
remains outside this boundary. Existing tool sandboxing and approval boundaries
remain authoritative; a lease never expands the ambient authority they grant.

Execution receipts are privacy-safe by default and contain no prompt content:

- selected skill, version, and digest;
- routing reason;
- API, tool, token, cost, and approval counts (never tool arguments);
- duration and budget class;
- completion and evaluation result;
- active and rollback digests.

Receipts support completion coverage, explicitly labeled routing precision,
outcome lift, failure analysis, cost, latency, security findings, and rollback
observability.

The Phase 3 local substrate stores a closed-schema, bounded JSONL journal at
`~/.fabric/skills/.governance/skill-receipts.jsonl` (profile-relative). It is
enabled by default and bounded with `skills.receipts.enabled`, `max_bytes`, and
`max_files` in `config.yaml`; there is no environment-variable or outbound
telemetry path. Files are locked, rotated, non-symlink regular files with mode
`0600`. Session, task, and turn identifiers are stored only as HMAC-bound local
references. Unknown fields and arbitrary text are rejected, so prompts,
responses, tool arguments, file contents, error strings, and secrets have no
valid receipt representation.

Slash, stack, bundle, scheduled-job, and main `skill_view` activation paths
record selection receipts without changing the prompt or model tool schema. A
bounded metadata-keyed LRU avoids re-hashing an unchanged skill tree; metadata
changes invalidate the entry and the descriptor-safe tree digest is recomputed.
Pre-turn activations bind to the exact concrete turn at its prologue. Session
preloads deliberately remain templates and are not falsely attributed to an
arbitrary first turn.

The outer `AIAgent.run_conversation` forwarder automatically finalizes every
activation actually correlated to that turn, including completion state,
duration, API/tool counts, token/cache/reasoning deltas, and cost in integer
micro-USD. It uses ContextVar turn identity rather than a session/task guess,
and the no-skills path does not import the receipt module. This automatic layer
does **not** infer business outcome truth or routing relevance from assistant
prose. Callers with explicit evidence use `record_outcome` for declared outcome
and guardrail keys. Aggregation therefore reports completion coverage separately
from routing precision; routing precision remains `null` until an explicit
`routing_relevant` boolean label exists.

## Prompt-cache and narrow-waist invariants

- The system prompt is byte-stable for the life of a conversation.
- Contract, scan, eval, and lock metadata never enter the system prompt.
- Full skill content remains on-demand user/tool context.
- Skill install, promotion, rollback, and reload never rewrite prior messages.
- Approved promotion and rollback defer shared skill-index invalidation until
  the next system-prompt build by default. Explicit `--now` activation clears
  the shared index immediately but still does not rewrite an existing agent's
  frozen system prompt.
- Tool schemas stay fixed for the session; skills do not register dynamic core
  tools.
- Governance capability is exposed through the existing `fabric skills` CLI,
  existing skill tools, and internal guards.
- Every governed mutation is profile-scoped, locked, digest-bound, journaled,
  and recoverable. Promotion revalidates the exact active tree after snapshot,
  after journal publication, and inside the approved replay callback before
  mutation ownership begins, preserving an out-of-band edit as a conflict.

## Delivery sequence

### Phase 1: contract and inventory

- ship the parser and `fabric skills validate`;
- repair the canonical/legacy metadata boundary;
- report missing contracts without blocking legacy external skills;
- add contracts to first-party skills in reviewed batches;
- add contract and prompt-cost checks to CI.

### Phase 2: evaluation and quarantined learning

- standardize deterministic eval artifacts;
- route background review and `/learn` into drafts;
- always scan learned candidates;
- block permission-expanding auto-promotion;
- atomically promote only passing, approved candidates.

### Phase 3: runtime governance and outcomes

- enforce permission leases in existing guards;
- record privacy-safe execution receipts;
- measure completion coverage, explicitly labeled routing precision, outcome
  lift, cost, and latency;
- add risk-sized process lanes and human-sovereignty policies.

### Phase 4: bounded routing and distribution

- replace unbounded prompt exposure with a stable taxonomy and deterministic
  on-demand ranking;
- publish signed, versioned registry entries and revocation data;
- add cross-host conformance fixtures;
- stage rollout through `observe`, `enforce_learned`, and `enforce_all` modes.

The bounded router is now implemented. Catalogs with at most 32 skills retain
the inline metadata index; larger catalogs render only top-level category
counts and use `skills_list(query=...)` for a deterministic maximum of 8
candidates (hard cap 20). Verified trigger declarations receive a bounded
boost, matching non-triggers veto selection, unrelated precedence cannot create
a result, and invalid/legacy contracts receive no trigger authority. The CI
footprint check now measures the same hybrid representation; the 72-skill
bundled catalog renders to 372 variable bytes rather than 7,762.

## Acceptance conditions

- Draft creation, evaluation, promotion, and reload do not change cached system
  prompt bytes in an active conversation.
- Background review cannot directly create or modify an active skill.
- Invalid contracts, critical findings, failed evals, changed digests, or missing
  approvals preserve the previous active version.
- Permission expansion cannot auto-promote.
- Rollback restores exact prior bytes and lock state after restart.
- Hub, Curator, and learned-skill mutations serialize safely.
- Legacy external skills remain readable but never receive verified status.
- No new core model tool appears in schema snapshots.
- A promoted skill demonstrates outcome lift over its no-skill baseline without
  exceeding declared safety or efficiency guardrails.
