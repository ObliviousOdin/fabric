# TODOS

Organize future work under `## <Component>` headings. Within each component,
keep items sorted from P0 through P4 and use the template below.

<!--
## Component

### Title

**What:** One-line description of the work.

**Why:** The concrete problem it solves or value it unlocks.

**Context:** Enough detail to resume the work later.

**Effort:** S / M / L / XL
**Priority:** P0 / P1 / P2 / P3 / P4
**Depends on:** None
-->

> Source: the OpenClaw gap analysis at
> [`docs/roadmap/openclaw-gap-analysis-2026-07.md`](docs/roadmap/openclaw-gap-analysis-2026-07.md)
> (2026-07-18). IDs below (e.g. `P0-1`) map to that doc's improvement matrix.
> Strategic wedge: **the auditable, governed, local-first personal agent** —
> win on trust/privacy/cost/supply-chain/CJK reach; answer mobile and
> marketplace network effects cheaply; concede raw-momentum races.

## Distribution & Releases

### Signed, notarized, checksummed public desktop release (P0-1)

**What:** Stand up CI to ship notarized macOS (Developer ID), Authenticode
Windows, and Linux deb/AppImage desktop artifacts with published `SHA256SUMS`.

**Why:** Every desktop artifact today is an unsigned source-build marked
"must not be redistributed"; users hit Gatekeeper/SmartScreen. OpenClaw ships
signed everything. This is the single biggest adoption filter for a local-first
"trust us with your machine" pitch.

**Context:** `release-channels.yml` + `scripts/ci/publish_release.py` promotion
pipeline already exists but produces no public artifacts. `apps/desktop`
declares electron-builder targets as "verification targets" only. Gate Tier-1
desktop doc claims on this landing. Spec in the roadmap doc §6.

**Effort:** XL
**Priority:** P0
**Depends on:** None

### Versioned release + PyPI wheel + Homebrew bottle (P1-2)

**What:** Tag releases, build/upload a `fabric-agent` PyPI wheel (respecting the
existing extras taxonomy), convert the HEAD-only Homebrew formula to a versioned
bottle.

**Why:** Every documented install path is git-source; no pinnable version
exists, yet `recommended_update_command_for_method()` emits
`uv pip install --upgrade fabric-agent` for a wheel that doesn't exist. Blocks
reproducible/enterprise adoption.

**Effort:** L
**Priority:** P1
**Depends on:** None

### Windows-native ship reality: atomic update + ConPTY (P1-17)

**What:** Implement stage-and-swap atomic updates on Windows; finish wiring
`win_pty_bridge.py` into the `/api/pty` consumer and flip the feature-matrix
entry — or officially reposition WSL2 as the recommended path.

**Why:** Native Windows is advertised Tier-1 but delivered WSL-or-bust; updates
can strand a half-updated environment, and the embedded terminal is marked "not
supported" natively despite a working ConPTY bridge existing.

**Effort:** L
**Priority:** P1
**Depends on:** None

### Signed desktop auto-update + rollback (P1-16, P2-44)

**What:** Signed electron-updater/Tauri auto-update channel fed by versioned
releases; surface the existing `fabric update` recovery-point as one-click
rollback.

**Why:** Desktop in-app update is a source git-pull + rebuild "not ready for
production" with no rollback. An always-on agent needs a safe update path.

**Effort:** L
**Priority:** P1
**Depends on:** Signed desktop release (P0-1)

### Complete Tauri bootstrap installer for macOS/Linux (P2-45)

**What:** Finish `update.rs` for macOS/Linux (currently Windows-first, v0.0.1);
run clean-machine install/update/uninstall verification in CI before dropping
the "preview" label on Linux desktop.

**Effort:** L
**Priority:** P2
**Depends on:** None

### First-party deb/rpm/AppImage/MSI publish pipeline (P2-46)

**What:** Publish jobs turning electron-builder targets into signed released
deb/rpm/AppImage/MSI (nfpm for deb/rpm). `packaging/` currently holds only the
Homebrew formula.

**Effort:** L
**Priority:** P2
**Depends on:** Signed desktop release (P0-1)

### Reduce installer-script fragility (P2-47)

**What:** Extract the accreted workaround branches from `install.sh` (~3,142
lines) and `install.ps1` (~3,569 lines) into testable helper modules; add a CI
install-matrix (containers per distro + Windows runner) exercising the fallback
ladders.

**Why:** These scripts are the primary install channel for most platforms; a
regression breaks first-run for everyone — the highest-stakes moment.

**Effort:** L
**Priority:** P2
**Depends on:** None

## Skills & Marketplace

### Guard-scan agent-created skills by default (P0-2)

**What:** Flip `skills.guard_agent_created` to on; surface the pending-draft
approval flow via the existing `fabric skills evaluate`.

**Why:** Currently off — a prompt-injected agent can write an unscanned skill
into `~/.fabric/skills`. The guard already maps dangerous verdicts to a
retryable "ask" error, so agent-UX degradation is minimal.

**Effort:** S
**Priority:** P0
**Depends on:** None

### Wire Ecosystem Directory trust tiers into install policy (P0-3)

**What:** Emit tier + `risk_flags` from `skills-sources.json` into the unified
index at build time; have `should_allow_install` consume them (A1/A2→trusted,
B→community, C/Q→acknowledge-or-block). Replace hardcoded `TRUSTED_REPOS` with a
config-overridable list.

**Why:** The 312-source trust directory is build-time metadata the installer
never reads; runtime trust collapses to 4 hardcoded repos, so a Q-tier source
installs under the same policy as an A1 source and a compromised trusted repo
can't be revoked without a release.

**Context:** `build_skills_index.py` already reads both files. Spec in roadmap §6.

**Effort:** M
**Priority:** P0
**Depends on:** None

### Execution-time containment for community skills (P1-8)

**What:** Promote turn-scoped permission leases (`skill_permissions.py`) from
experimental to enforced-by-default for community-trust installs; skills declare
capabilities in `skill.contract.yaml`; dispatcher blocks/asks outside the lease;
add guard patterns for inline-shell `` !`cmd` `` markers.

**Why:** "Safe"-verdict community skills run with full terminal capability after
one confirm; scanning cannot catch instruction-level attacks. First credible
containment story wins security-conscious users.

**Effort:** L
**Priority:** P1
**Depends on:** None

### Reputation, popularity & reporting signals in the Hub (P1-26)

**What:** Capture per-repo stars/last-commit into the index at crawl time; render
badges in the Hub and `fabric skills search`; add `fabric skills report <id>`
filing a templated GitHub issue.

**Why:** ClawHub's install counts/stars/reporting are a primary reason users
prefer a marketplace; Fabric has no popularity or reporting signal. Stays
static-index-based — no registry backend.

**Effort:** M
**Priority:** P1
**Depends on:** None

### Continuous re-scan of installed hub skills (P2-30)

**What:** Extend the curator's inactivity-triggered maintenance to re-run the
guard scan over hub-installed skills against current patterns; downgrade a
failing skill to disabled-pending-review (never delete).

**Effort:** S
**Priority:** P2
**Depends on:** None

### Activate the dormant skill-signing pipeline (P2-31)

**What:** Stand up signing in CI for first-party content (bundled, optional,
capability packs); ship the pinned root in-repo; flip `skills.distribution.mode`
from `observe` to enforce once first-party coverage is complete.

**Why:** A full Ed25519/TUF verifier already exists in `agent/skill_
distribution.py` but is observe-only. Signed first-party distribution + a live
revocation channel would be the strongest supply-chain story in the category.

**Effort:** L
**Priority:** P2
**Depends on:** None

### Mirror the unified skills index (SPOF) (P2-32)

**What:** Publish the built index to a second static location in the same CI run;
make the index source take an ordered mirror list with failover; expand the
committed fallback cache to the full index.

**Effort:** S
**Priority:** P2
**Depends on:** None

### Ship a minimal skill eval harness (P2-33)

**What:** `fabric skills eval run <manifest>` executing data-only manifests via
the existing pure runner; feed the existing evaluate/promotion-gate path;
publish quality badges. Start with the 12 curated stacks as the corpus.

**Effort:** L
**Priority:** P2
**Depends on:** None

### Governed community submission path (P2-34)

**What:** `fabric skills submit` opening a templated PR into the directory with a
CI job running the guard scan + structural + license checks and posting the
verdict; accepted entries flow into the next index build.

**Why:** No intake path exists for outside authors; captures contribution energy
without an open registry (which caused ClawHavoc).

**Effort:** M
**Priority:** P2
**Depends on:** None

### Deterministic, approval-gated skill pipelines (P2-24)

**What:** A YAML pipeline format executed by `fabric flow run` sequencing skill
+ shell steps via `delegate_task`, halting side-effecting steps behind the
gateway approval flow, persisting resumable state. (Shared with Automation.)

**Why:** Answers OpenClaw's Lobster/OpenProse; Fabric's every multi-step path is
LLM-driven with no deterministic/resumable composition.

**Effort:** L
**Priority:** P2
**Depends on:** None

## Extensibility, MCP & APIs

### Curated, integrity-verified extension hub (P0-4)

**What:** A git-hosted, hash-verified catalog over plugins + capability packs +
skill taps + MCP entries, reusing the capability-pack compiler's canonical-JSON
+ sha256 tree hashing. `fabric plugins search/browse`; PR intake with a
mandatory guard-scan gate; no open-publish tier.

**Why:** Discovery is why users pick OpenClaw for extensibility (ClawHub: 3,200+
skills, one-command install). Curation is Fabric's differentiator post-ClawHavoc.

**Effort:** L
**Priority:** P0
**Depends on:** None

### Close the plugin install trust gap (P1-14)

**What:** Run the skills guard on plugin installs pre-activation; extend
`plugin.yaml` with declared capabilities and diff declared-vs-registered at
load; surface `allow_tool_override`/`ctx.llm` trust as install-time prompts.

**Why:** Skills get install-time scanning; plugins — unsandboxed in-process
Python — get nothing beyond env prompting. A single malicious-plugin incident
would be trust-breaking for a security-positioned project.

**Effort:** M
**Priority:** P1
**Depends on:** None

### Publish a versioned, scoped programmatic contract (P1-15)

**What:** Version the JSON-RPC handshake (N-1 compat), publish the existing
`@fabric/shared` client as the reference client, introduce scoped API tokens
(read-only/operator/admin) across `web_server`/`api_server`/WS, carve a
documented `/api/v1/` facade.

**Why:** Third parties can't build durable products on unversioned, contract-less
surfaces; the ~200-endpoint dashboard REST (19.2k-line `web_server.py`) has no
public contract and only ephemeral session-token auth. Scoped tokens would be a
lead over OpenClaw.

**Effort:** L
**Priority:** P1
**Depends on:** None

### Wire capability packs into the CLI + docs (P1-19)

**What:** `fabric packs list/install/verify/remove` over the existing
lifecycle/transaction modules; publish the two in-repo packs; one docs page.

**Why:** The capability-pack system (deterministic fail-closed compiler,
transactions, tests) is built but unreachable — no CLI verb, no docs.

**Effort:** M
**Priority:** P1
**Depends on:** None

### Plugin API version negotiation (P2-35)

**What:** `PLUGIN_API_VERSION` constant + `api_version` in `plugin.yaml`;
hard-fail on major mismatch, warn on minor; reject unknown hook/middleware names
(fail-closed with an escape hatch).

**Effort:** S
**Priority:** P2
**Depends on:** None

### Make mcp_serve a live, approval-capable bridge (P2-36)

**What:** When the gateway is running, connect `mcp_serve`'s EventBridge to the
TUI-gateway JSON-RPC so `permissions_respond` resolves real approvals and events
push instead of poll; keep the SQLite poller as the gateway-down fallback; make
truncation limits per-call params.

**Why:** The headline "drive Fabric from Claude Code/Cursor" surface is a 200ms
SQLite poller whose approvals only mutate an in-memory record — it hits a wall
exactly when the agent asks for approval.

**Effort:** M
**Priority:** P2
**Depends on:** None

### Bound hook latency (P2-37)

**What:** Per-hook timeout budgets (config default + per-entry override);
dispatch pure-observer hooks to a background queue; keep decision hooks
synchronous but time-bounded. Must not touch the `pre_llm_call` user-message
injection path (prompt caching).

**Effort:** M
**Priority:** P2
**Depends on:** None

### Grow the MCP catalog + unbind intake from releases (P2-38)

**What:** Curate 20–30 high-demand servers as manifest entries with the existing
security review as the intake bar; support a remote hash-verified index so
entries ship without a Fabric release. Market the OSV/IOC screening.

**Why:** 3 catalog entries sit atop a 5.6k-line client with unique OSV/IOC
security screening; the content is the gap, not the machinery.

**Effort:** M
**Priority:** P2
**Depends on:** None

### Cross-ecosystem import (P3-22)

**What:** `fabric import claude-code` / `codex` mapping `.claude/skills`, hooks
config, and `.mcp.json` into `~/.fabric` equivalents with a dry-run report and
per-item consent.

**Effort:** M
**Priority:** P3
**Depends on:** None

### Consolidate the six plugin-discovery loaders (P3-23)

**What:** Extract one discovery/priority core (source ordering, override policy,
enable-gating) consumed by all category registries; make discovery an explicit
init call with the import-time hook retained as a back-compat shim.

**Effort:** M
**Priority:** P3
**Depends on:** None

## Model, Provider & Cost

### Kill or ship the phantom smart_model_routing config (P0-6)

**What:** Delete `smart_model_routing` from AGENTS.md's config list and stop
writing it in setup, or mark it explicitly "reserved, not implemented"; add a
doctor warning when a user config contains a non-empty section.

**Why:** Named in AGENTS.md and force-disabled by blank-slate setup but has zero
runtime consumers — a documented feature that does nothing, in the exact
dimension (routing/cost) where OpenClaw ships working routers.

**Effort:** S
**Priority:** P0
**Depends on:** None

### Dollar-denominated spend caps (P1-3)

**What:** A budget guard over the existing `CostResult` stream: per-session and
per-day USD caps in `config.yaml`, pause-with-grace-turn, conservative when cost
is estimated, subscription routes exempt; `fabric budget` + `/usage`.

**Why:** Fabric computes cost with provenance but nothing enforces a limit;
iteration budgets bound calls, not dollars. Cost is OpenClaw's loudest
criticism — this is the one hole in Fabric's strongest positioning asset.

**Effort:** M
**Priority:** P1
**Depends on:** None

### Day-zero frontier-model support process (P1-13)

**What:** Externalize the quirk tables (reasoning-mandatory lists,
thinking-prefix heuristics, max-token caps) from plugin code into versioned data
files refreshable from models.dev; add a doctor check for models hitting
heuristic defaults; record model adds in CHANGELOG.

**Why:** Per-provider correctness depends on hardcoded model-name substring
allowlists that rot; new frontier releases can 400/mis-price until someone edits
lists. Users pick the assistant that runs the newest model on day one.

**Effort:** M
**Priority:** P1
**Depends on:** None

### Client-side smart routing, opt-in and cache-safe (P2-14)

**What:** An opt-in plugin/virtual-provider (MoA-facade style) that classifies at
cache-safe boundaries only (conversation start, per-aux-task) and never swaps the
main model mid-conversation. Reuse `auxiliary_client` overrides + models.dev
pricing.

**Effort:** L
**Priority:** P2
**Depends on:** None

### Verify then ship the bundled models.dev snapshot (P2-15)

**What:** Confirm whether `agent/models_dev.py` already ships a bundled
offline-first snapshot (verification suggests it does); if not, add it as the
final fallback + a `fabric models refresh` command and a doctor staleness
warning. If present, downgrade to a docstring/doctor fix.

**Effort:** S
**Priority:** P2
**Depends on:** None

### Unify the dual provider registries; make OAuth providers pluggable (P2-16)

**What:** Migrate the five special-cased providers into
`plugins/model-providers/`; extend `ProviderProfile` with a declarative OAuth
descriptor so `PROVIDER_REGISTRY` is generated from profiles; lift the
api_key-only restriction on `CANONICAL_PROVIDERS` auto-injection.

**Why:** Two hand-synced registries and OAuth providers needing core edits
contradict Fabric's own "every backend is a plugin" claim. Shrinks core over
time.

**Effort:** L
**Priority:** P2
**Depends on:** None

### Runtime prompt-cache guard (P2-17)

**What:** Hash the cached prefix each turn in `agent/prompt_caching.py`; on
unexpected mutation, log a cache-invalidation event with the offending path,
surface a counter in `/usage` and `/insights`; lint new slash commands toward
deferred invalidation.

**Why:** Cache discipline — Fabric's biggest cost lead — is enforced only by
convention/review; one bad plugin silently converts a ~75% input-cost reduction
into full price with no signal.

**Effort:** M
**Priority:** P2
**Depends on:** None

### Make air_gapped fail loudly (P2-18)

**What:** Make selecting `air_gapped` a hard config error (pointing to
`local_ai`) until a real process-wide network boundary exists; document the
distinction. Longer term, deliver the boundary at the OS/firewall edge.

**Effort:** S
**Priority:** P2
**Depends on:** None

### Decompose auxiliary_client.py (P3-5 partial)

**What:** Extract pool/key selection, provider quirk detection, the resolution
chain, and client construction from the 8,847-line `agent/auxiliary_client.py`
into separate modules with characterization tests first.

**Why:** The hottest cost path and highest change-risk file; every aux LLM task
traverses it. Sequence before routing/budget work piles more logic in.

**Effort:** L
**Priority:** P3
**Depends on:** None

## Memory & Context

### Finish R2-MEM-03 memory-identity scope enforcement (P0-5)

**What:** Land the remaining `agent/memory_scope.py` steps — scope persistence in
`fabric_state.py`, CAS-guarded provider dispatch, gateway wiring — before
expanding any external-memory surface. Add a two-gateway-user integration test
asserting zero cross-scope recall.

**Why:** `memory_scope.py` is a pure contract whose docstring admits enforcement
isn't landed. Fabric's whole edge here is privacy rigor; a cross-user external-
memory leak would erase it (OpenClaw's `dmScope:'main'` is the cautionary case).

**Effort:** M
**Priority:** P0
**Depends on:** None

### In-core semantic recall without breaking the narrow core (P1-20)

**What:** (1) Promote the embedding-free holographic provider to the recommended
default for capable hardware; (2) ship an optional embedding-augmented recall
layer for `session_search` as a service-gated tool/plugin; (3) evaluate a
QMD-style local sidecar as a standalone plugin. Do not add vector storage to
`fabric_state.py`.

**Why:** Fabric's only zero-config long-term recall is keyword FTS5; paraphrase
recall needs an external provider. "It just remembers semantically" is
OpenClaw's headline — but its semantic search also isn't zero-config, so Fabric
can compete via holographic.

**Effort:** L
**Priority:** P1
**Depends on:** None

### Pre-compression durable-memory flush for the builtin store (P1-23)

**What:** Before `compress_context` runs, a bounded aux-model pass (reuse the
background-review digest + memory-only tool whitelist) stages durable-fact
writes to the builtin store via the existing write-approval flow, tagged
`[auto-precompress]`. Cap one per compaction cycle.

**Why:** OpenClaw's default-on pre-compaction flush means compaction can't erase
critical context; Fabric's `on_pre_compress` only extracts to external providers
under consent — the builtin store gets no pre-compaction capture.

**Effort:** M
**Priority:** P1
**Depends on:** None

### Context introspection commands (P2-8)

**What:** A `/context` CLI command (+ `fabric sessions context <id>`) reporting
system-prompt size, frozen memory snapshot size, tool-schema footprint, per-turn
recall usage, and compactable tail; optional per-reply token footer. Read-only,
zero cache impact.

**Why:** Answers OpenClaw's `/context`/`/usage`, and turns Fabric's cache-first
architecture into a demonstrable number next to OpenClaw's ~15–20k-token per-turn
bootstrap tax.

**Effort:** S
**Priority:** P2
**Depends on:** None

### Overflow-recovery compaction (P2-9)

**What:** In the conversation loop's API-error handling, detect provider
context-length error shapes (`request_too_large`, "context length exceeded"),
route once into `compress_context`, then retry. Cap one recovery per turn.

**Effort:** M
**Priority:** P2
**Depends on:** None

### Bounded runtime memory-provider health probe (P2-10)

**What:** `fabric memory probe` (or `memory status --live`): a time-bounded
provider round-trip (write canary → recall → delete) on the serialized
background worker, reporting per-capability pass/fail.

**Why:** The docs concede health is "unknown until a bounded runtime probe
exists"; five of eight providers declare mostly-unknown capabilities. Silent
failure of external memory is a trust issue.

**Effort:** S
**Priority:** P2
**Depends on:** None

### Visibility/override for quarantined memory (P2-11)

**What:** `fabric memory quarantine list|show|allow <id>` — list blocked entries
with the matched pattern; allowlist a specific entry (hash-pinned). Surface a
one-line notice when a snapshot contains blocked entries. Default fail-closed
unchanged.

**Effort:** S
**Priority:** P2
**Depends on:** None

### fabric memory import (OpenClaw / Claude Code / Codex) (P2-12)

**What:** A CLI command + skill parsing OpenClaw workspace files (MEMORY.md,
`memory/YYYY-MM-DD.md`, USER.md) and Claude Code CLAUDE.md, running an aux-model
consolidation to Fabric's char budgets, staging via write-approval.

**Why:** OpenClaw shipped Codex/Claude memory import as a switching-cost play;
the highest-friction step for a switcher is abandoning accumulated memory. Aimed
at OpenClaw's context-bloat backlash moment.

**Effort:** S
**Priority:** P2
**Depends on:** None

### Turn on filesystem checkpoints by default (P2-13)

**What:** Flip `checkpoints.enabled` to on with the existing conservative caps
(20 snapshots / 500 MB / 10 MB per file), or prompt once at the first file-
mutating tool use.

**Why:** Checkpoints + `/rollback` are a capability OpenClaw entirely lacks, but
ship disabled — an off-by-default differentiator is a marketing claim, not a
moat. The v2 shared-object store already removed the disk-bloat objection.

**Effort:** S
**Priority:** P2
**Depends on:** None

### Session retention & pruning policy (P3-11)

**What:** `fabric sessions cleanup --dry-run|--enforce` + config keys (retention
days, max DB bytes) reusing the lineage model to prune whole trees safely; run
opportunistically at session end on the background worker.

**Effort:** S
**Priority:** P3
**Depends on:** None

### Ship one context engine or cut the surface (P3-13)

**What:** Either ship one concrete alternative engine (e.g. a flush-first or
aggressive tool-output-pruning engine) as the reference consumer, or remove the
`plugins/context_engine/` discovery directory and scrub the non-existent `lcm`
references.

**Effort:** M
**Priority:** P3
**Depends on:** None

## Automation & Orchestration

### Proactive Heartbeat (P1-4)

**What:** A `HEARTBEAT.md` tasks file + `fabric heartbeat` command driving one
recurring cron job attached to the main session (reuse the scheduler,
`attach_to_session`, `context_from`). Inject only due tasks; short-circuit the
model call when nothing is due.

**Why:** OpenClaw's marquee assistant behavior is self-initiated main-session
check-ins; Fabric has only reactive cron. A defining personal-agent feature.

**Effort:** M
**Priority:** P1
**Depends on:** None

### Durable background delegations + unified flow record (P1-21)

**What:** An opt-in durable path routing long background work onto the existing
kanban board (crash-recovering with claim TTLs), and/or a lightweight mirrored
flow-record giving a detached run a restart-surviving status handle. Keep the
ephemeral daemon path for short fan-outs.

**Why:** Background `delegate_task` is ephemeral — `/stop` or process exit loses
results; OpenClaw's Task Flow survives restart. Fabric's durability is split
(durable kanban vs non-durable delegate) with no unified handle.

**Effort:** M
**Priority:** P1
**Depends on:** None

### Cron failure retry/backoff (P2-25)

**What:** Optional per-job retry with a bounded attempt count and backoff in the
cron scheduler (config-gated), complementing existing fallback-model and
one-shot claim recovery. Conservative default.

**Effort:** S
**Priority:** P2
**Depends on:** None

### First-class wake / event-injection primitive (P2-26)

**What:** A `fabric wake` CLI + gateway RPC injecting an arbitrary message into a
running/target session immediately, reusing the cache-safe completion-queue
re-entry rail (fresh idle turn, never a mid-context splice).

**Effort:** S
**Priority:** P2
**Depends on:** None

### External HTTP spawn API backed by kanban (P2-27)

**What:** An authenticated, service-gated HTTP endpoint that enqueues a task onto
the kanban board and returns a handle for polling; the existing dispatcher spawns
isolated detached workers. Off by default, behind auth.

**Why:** Neither product ships an external spawn API (OpenClaw's is an unshipped
request), but Fabric already owns the hard part — a durable crash-recovering
worker substrate. A lead-extension.

**Effort:** L
**Priority:** P2
**Depends on:** None

### Productized Automations surface (P3-14)

**What:** An Automations view over the cron store (stat cards, jobs table,
Active/Paused, Run-now via `trigger_job`, starter templates) on the existing
web/desktop server. Reuse existing cron APIs.

**Effort:** M
**Priority:** P3
**Depends on:** None

## Channels & Gateway

### Signal full-tier parity + fix docs matrix (P1-22)

**What:** Hand-fix the docs matrix (Signal streaming ✅ → —), then implement
edit-based streaming (`edit_message` on signal-cli), reaction lifecycle markers,
and the numbered-option fallback for clarify/approve; add a real per-platform
test suite.

**Why:** Fabric's privacy-conscious target audience overlaps Signal's, yet Signal
is one of Fabric's thinnest adapters (3 test files, no `edit_message`), and the
docs matrix falsely claims streaming — which a switching OpenClaw user hits
immediately.

**Effort:** M
**Priority:** P1
**Depends on:** None

### Deterministic multi-agent routing config (P1-24)

**What:** Generalize Discord's per-channel prompt/skill binding into a
`config.yaml` bindings section evaluated in gateway dispatch (peer > group >
channel-account > platform > default), mapping matches to profile + prompt/skill
sets and session-key scopes. Defer broadcast fan-out.

**Why:** OpenClaw's headline gateway feature is deterministic per-message agent
selection; Fabric multiplexes one agent core. Users wanting different
personas/agents per group/contact pick OpenClaw for this alone.

**Effort:** L
**Priority:** P1
**Depends on:** None

### Publish a channel threat model + extend inbound-injection defenses (P2-1)

**What:** Document the untrusted-input pipe (fake `[System Message]`, link
previews, media filenames, group-injected mentions); extend the existing
provenance tagging (`gateway/session.py` `_format_untrusted_prompt_value`) with
regression tests for known OpenClaw attack shapes; run the security-review skill
over `gateway/platforms/` and publish results.

**Why:** Security is OpenClaw's dominant channel criticism (WhatsApp-to-RCE,
link-preview exfiltration, ClawJacked, fake-system-message). Fabric's primitives
are stronger; the gap is a published, tested, marketed defense. (Provenance
tagging partly exists — extend, don't rebuild.)

**Effort:** M
**Priority:** P2
**Depends on:** None

### Generate the channel capability matrix from code (P2-2)

**What:** Add a capability-introspection method to `BasePlatformAdapter`
(converging on the relay `CapabilityDescriptor` schema) and a CI script that
regenerates the docs matrix and fails on drift.

**Why:** The matrix drifts both ways (Telegram reactions marked —, Signal
streaming marked ✅, photon/simplex rows missing) — the single most
trust-damaging docs artifact for a 29-channel product.

**Effort:** M
**Priority:** P2
**Depends on:** None

### Universal buttonless fallback for clarify/approval/model-picker (P2-3)

**What:** A numbered-option protocol in the `BasePlatformAdapter` default stubs
("1) … 2) …", accept a bare-number/reaction reply bound to the pending
interaction). One base-class change lifts ~20 adapters; native-button adapters
keep their overrides.

**Effort:** M
**Priority:** P2
**Depends on:** None

### Zero-config web chat surface (P2-4)

**What:** `fabric webui` CLI + skill that bootstraps a local Open WebUI container
preconfigured against `api_server`, or a minimal single-page webchat plugin over
`/v1/runs` SSE + approval endpoints.

**Effort:** M
**Priority:** P2
**Depends on:** None

### Finish gateway/run.py decomposition + enforce the dual-guard contract (P2-28)

**What:** Extract session dispatch and Discord voice STT next (following
authz_mixin/slash_commands); replace the documented dual message-guard pitfall
with a single guard-bypass registration API + a test asserting every control
command passes both guards during an active turn.

**Why:** `run.py` is ~21.8k lines; the dual-guard pitfall is a recurring bug
source (OpenClaw shipped the identical "Signal stop controls unresponsive
mid-turn" class).

**Effort:** L
**Priority:** P2
**Depends on:** None

### Per-platform adapter contract test harness (P2-29)

**What:** One parametrized contract suite derived from `BasePlatformAdapter`
(chunking, busy-queue debounce, media caching, retry classification, authz
fail-closed, guard bypass) that every registered adapter must pass; reorganize
tests into `tests/gateway/platforms/<name>/` and enforce a per-adapter minimum.

**Effort:** M
**Priority:** P2
**Depends on:** None

### Graduate the relay connector (P3-1)

**What:** Validate the relay by porting two Class-1 adapters (Slack, Mattermost)
to run behind it in CI, freeze `contract_version 1`, publish a connector SDK
guide, decouple scale-to-zero from Fly-specific assumptions.

**Effort:** L
**Priority:** P3
**Depends on:** None

### Telephony voice-call channel (P3-2)

**What:** A voice-call platform plugin on Twilio programmable voice reusing the
existing STT/TTS pipeline and SMS webhook signature validation; add realtime
inbound + inbound-call policies + per-number persona routing.

**Effort:** L
**Priority:** P3
**Depends on:** None

## Surfaces & UX

### Installable PWA + Web Push — the mobile answer (P1-1)

**What:** Add a manifest + service worker to `web/`; Web Push (VAPID) over the
existing dashboard auth with the ntfy adapter as fallback; `getUserMedia`
push-to-talk mic + camera capture into the existing voice/vision pipeline.
Document "Fabric on your phone = PWA over Tailscale."

**Why:** Fabric has no mobile surface; OpenClaw ships native apps + a PWA. "Does
it have a phone app?" is the first mainstream question. Web edge only — no core,
no prompt-cache impact. Answers the VO camera/voice gaps simultaneously.

**Effort:** M
**Priority:** P1
**Depends on:** None

### Close the dual-chat-implementation parity trap (P1-18)

**What:** Make the shared slash registry (`fabric_cli/commands.py`) the single
machine-readable contract exposed over JSON-RPC; render the desktop palette from
it with server-side curation flags; add a CI conformance test diffing
TUI-visible vs desktop-visible commands/approval prompts.

**Why:** Desktop keeps its own React chat/slash pipeline separate from the Ink
TUI; AGENTS.md documents a real silent-drop regression from client-side
curation. Every new slash command/approval has a second place to break.

**Effort:** M
**Priority:** P1
**Depends on:** None

### Replace or gate placeholder Workspace routes (P2-5)

**What:** (1) Gate placeholder routes (Memory/Approvals/Activity/Work Board)
behind a "show upcoming features" toggle, default off; (2) prioritize Approvals
and Activity as read-only projections of TUI/gateway events, reusing the passive-
rail projection pattern.

**Effort:** M
**Priority:** P2
**Depends on:** None

### Wake word + realtime browser/desktop voice (P2-6)

**What:** (1) A realtime-voice plugin for the web dashboard + Electron desktop
using provider WebRTC sessions; (2) a desktop/companion wake-word listener as a
service-gated feature publishing a wake event over `/api/ws`. Core request path
untouched.

**Effort:** L
**Priority:** P2
**Depends on:** None

### Harden and press the IDE/ACP lead (P2-7)

**What:** Back the ACP session manager with Fabric's session persistence so
list/load/resume survive restarts; publish a thin VS Code extension wrapping the
ACP client config; make "works in Zed/VS Code/JetBrains out of the box" a top-3
positioning message.

**Why:** IDE integration is Fabric's cleanest structural win (OpenClaw has no
first-party IDE extension), but ACP sessions are process-local.

**Effort:** M
**Priority:** P2
**Depends on:** None

### Native Windows dashboard chat without WSL (P2-7b → tracked with P1-17)

**What:** Complete the pywinpty/ConPTY path so `fabric --tui` runs in the
`/api/pty` bridge natively on Windows; if blocked, fall the Windows dashboard
chat tab back to the desktop app's chat transport instead of a dead-end banner.

**Effort:** M
**Priority:** P2
**Depends on:** None

### Unify the default terminal surface (P3-3)

**What:** Make `fabric` auto-select the TUI when Node ≥ 20 is present (with
one-time consent for the bundle install), fall back to classic CLI otherwise;
pre-build/vendor the TUI bundle in release artifacts; fold `[web,pty]` extras
into the default install or self-install interactively.

**Effort:** M
**Priority:** P3
**Depends on:** None

### Device node answer (P3-4)

**What:** Build "device nodes" as plugins exposing service-gated tools (not core
tools): a headless companion node (Linux/Termux daemon reusing DM-pairing +
`/api/ws`) offering notifications and camera-capture as individually-approvable
gated tools. Ship the fail-closed security model first and market the contrast
with OpenClaw's node-layer CVE history.

**Effort:** XL
**Priority:** P3
**Depends on:** None

### Decompose the god-file surface backends (P3-5)

**What:** Extract along the seams other gaps need: REST/API clusters out of
`web_server.py` (~19.2k LOC), session/approval logic out of `tui_gateway/
server.py` (~15.8k), subcommand clusters out of `cli.py` (~16.3k). Incremental
per-feature; add module-size lint.

**Effort:** L
**Priority:** P3
**Depends on:** None

### Companion overlay: fix event-stream stealing (P4-2)

**What:** Make companion attachment a fan-out subscriber on the visual/event
socket (as Agent Live View does) instead of an exclusive rebind; add it to
`docs_sync.py`; document the X11/Wayland capability matrix.

**Effort:** S
**Priority:** P4
**Depends on:** None

### Coding-session interop (P4-3)

**What:** `fabric sessions external` reading local Claude Code/Codex session
stores read-only and offering to resume them in a terminal via existing PTY
infra, resume commands allowlisted like ACP approvals. Ship as a plugin.

**Effort:** M
**Priority:** P4
**Depends on:** None

## Security & Trust

### Security-posture linter in fabric doctor (P1-5)

**What:** Extend `fabric doctor` with a "security posture" section enumerating
break-glass flags (`GATEWAY_ALLOW_ALL_USERS`, `*_ALLOW_ALL_USERS`, 0.0.0.0 bind,
always-authorized HomeAssistant/Webhook, loopback dashboard) from live config,
printing a loud warning on non-loopback-without-auth. Optional 24h-gated startup
banner.

**Why:** These flags are easy to misconfigure into public exposure — precisely
the root cause of OpenClaw's mass-exposure disaster. OpenClaw answers with
`openclaw security audit`; Fabric has none. Turns OpenClaw's headline failure
into a Fabric strength.

**Effort:** M
**Priority:** P1
**Depends on:** None

### Add the supply-chain-audit CI gate (P1-6)

**What:** Add the CI workflow that `CONTRIBUTING.md` references but doesn't
exist: `pip-audit`/OSV over the resolved venv on manifest changes and on a
schedule (reuse `security_audit.py`'s OSV path); add dependabot/renovate for
SHA-pinned Actions. Or delete the dangling references if on-demand-only is
intended.

**Why:** Documenting a CI control that is absent is a credibility break for a
project whose entire competitive story is supply-chain discipline.

**Effort:** M
**Priority:** P1
**Depends on:** None

### Runtime advisory refresh + scheduled OSV audit (P1-25)

**What:** Keep the startup scanner denylist-based and cache-safe, but let the
curated advisory catalog refresh from a signed remote feed on an opt-in schedule
(CLI + cron skill), and offer an opt-in scheduled OSV audit (same on-demand code
path via cron).

**Why:** `security_advisories.py` holds exactly one entry; a novel worm not
hand-added is invisible at startup, with no scheduled catch-all.

**Effort:** M
**Priority:** P1
**Depends on:** None

### External secret-manager seam (P2-19)

**What:** A secret-provider seam resolving references by ID at startup
(fail-fast), with built-in file/exec/env resolvers in a service-gated tool, and
Vault/1Password/Bitwarden as optional plugins.

**Why:** Fabric is `.env`-secrets-only (plaintext at rest); OpenClaw has SecretRef
+ Vault/1Password/Bitwarden. A concrete adoption blocker for security-conscious
operators.

**Effort:** L
**Priority:** P2
**Depends on:** None

### tirith fail-open visibility + native obfuscation fallback (P2-20)

**What:** Surface tirith availability in `fabric doctor` and warn when it's
unavailable (so fail-open is never silent); add a small native, binary-
independent obfuscation/pipe-to-interpreter fallback heuristic in the approval
path (works on Windows / when the binary is missing). Consider fail-closed for
the highest-risk command classes.

**Why:** `tirith_fail_open` defaults True with no Windows binary — best-effort
and silently off on some hosts. OpenClaw added a pre-allowlist obfuscation gate.

**Effort:** M
**Priority:** P2
**Depends on:** None

### Authz/ownership regression test matrix (P2-21)

**What:** A property/regression suite over every gateway adapter asserting
default-deny for unknown senders, no channel/allowlist path elevating a
non-owner to owner/admin, and adapter-own-policy honored only when a genuine
allowlist. Encode OpenClaw's `senderIsOwner` and channel-allowlist-owner cases
as named regressions.

**Effort:** M
**Priority:** P2
**Depends on:** None

### Close SSRF DNS-rebinding TOCTOU + document SDK egress bypass (P2-22)

**What:** Resolve the hostname once, validate the resolved IP, connect to that
pinned IP (reject mismatches) wherever the HTTP client allows a custom
resolver/connector; document the residual Firecrawl/Tavily vendor-side redirect
risk in security docs.

**Effort:** M
**Priority:** P2
**Depends on:** None

### Setup-time posture prompt: sandboxed backend for untrusted input (P2-23)

**What:** When a gateway or untrusted-input surface is enabled at setup, steer
the operator toward a sandboxed backend (ideally `docker --network=none`) and
warn if they remain on the local backend. Reuse the existing docker air-gap
plumbing.

**Why:** The default terminal backend runs LLM-emitted commands on the host, so
the out-of-the-box gateway posture is explicitly unsupported for untrusted input
— the safe path is not the default path.

**Effort:** M
**Priority:** P2
**Depends on:** None

### Independent third-party security audit (P2-49)

**What:** Commission or solicit an independent security review (or a public
red-team/bug-bounty matching the stated no-payout stance) and publish results;
complete the hermes→fabric rename in security-critical code to remove provenance
ambiguity.

**Why:** A self-described mature posture with zero outside validation is a trust
asymmetry; OpenClaw has (involuntary) external scrutiny from many firms.

**Effort:** L
**Priority:** P2
**Depends on:** None

### Publish-time skills-index scanning (P3-16)

**What:** Run the existing `skills_guard` THREAT_PATTERNS scan inside the
skills-index CI as a publish-time gate, rejecting/flagging bundles that fail the
community policy before they land in the index.

**Effort:** S
**Priority:** P3
**Depends on:** None

### Mobile/operator approval flow (P3-17)

**What:** Extend the gateway approval path into a mobile-friendly operator-
approval flow resolving on the operator's device and routing results back to the
originating channel/DM. Preserve the hardline blocklist as an un-approvable
floor.

**Effort:** M
**Priority:** P3
**Depends on:** None

## Voice, Vision & Media

### Realtime speech-to-speech path (P2-39)

**What:** A realtime voice path as a service-gated tool/plugin (OpenAI Realtime /
Gemini Live) the existing voice mode can opt into; keep the classic STT→chat→TTS
chain as the default/offline path. Gate behind the voice extra + a credential.

**Effort:** L
**Priority:** P2
**Depends on:** None

### Barge-in in live voice mode (P2-40)

**What:** Keep VAD monitoring the mic during TTS playback and cancel/abort the
current TTS stream on confident speech, in the CLI/TUI and Discord voice loops.
Runtime-only, no tool-schema change.

**Effort:** M
**Priority:** P2
**Depends on:** None

### Camera / webcam capture (P3-8)

**What:** An optional skill (`official/media/camera`) + `fabric camera snap|clip`
wrapping platform capture tools (imagesnap/AVFoundation, ffmpeg/v4l2,
DirectShow), handing files into the existing vision pipeline. (Overlaps the PWA
`getUserMedia` path in P1-1.)

**Effort:** M
**Priority:** P3
**Depends on:** None

### Extend the media-generation lead (P3-9)

**What:** Add a local ComfyUI backend as an image/video-gen provider plugin
(reuse the creative-comfyui skill) for fully-offline generation; expose an
audio/music backend via the AudioCraft skill/plugin.

**Effort:** M
**Priority:** P3
**Depends on:** None

### Low-latency voice providers: Deepgram STT + Aura TTS (P4-5)

**What:** Register Deepgram (nova-3 STT) and Aura (TTS, ~90ms TTFB) via the
existing command/plugin provider registries. Strengthens the realtime + barge-in
work.

**Effort:** S
**Priority:** P4
**Depends on:** None

## Community, Docs & Sustainability

### Counter-position on trust/governance (P1-9)

**What:** Make security/governance the top-of-funnel message: rewrite
`migrate-from-openclaw.md` around a concrete threat/governance comparison (skill
trust tiers, prompt-footprint audit, release provenance, local-first boundary);
add a "Security & governance" docs landing page linking the existing audit
scripts as evidence; surface trust tier per source in the Ecosystem Directory.

**Why:** Fabric loses every raw-momentum metric but owns OpenClaw's dominant risk
narrative. Not making "the auditable, governed, local-first alternative" the
headline leaves adopters with no articulated reason to choose Fabric.

**Effort:** M
**Priority:** P1
**Depends on:** None

### First-party community channel (P1-10)

**What:** Enable GitHub Discussions as the community home (plugins/skills
category); wire it into the docs footer "Community" section; make the AGENTS.md
`#plugins-skills-and-skins` references point to a real URL (or a Discord/Matrix
invite) — do not ship the reference before the destination exists.

**Effort:** S
**Priority:** P1
**Depends on:** None

### Bus-factor + first-contribution on-ramp (P1-11)

**What:** A short "Your first contribution" quickstart front-loading the 10% of
rules that matter; curated good-first-issue/help-wanted labels; a lightweight
governance/succession note (who can merge, what if the maintainer is
unavailable). Keep the deep rubric as reference, not the entry gate.

**Why:** Single maintainer, bus-factor of one; the contributor-facing governance
is 73 KB AGENTS.md + 51 KB CONTRIBUTING.md — a high barrier to a first PR.

**Effort:** L
**Priority:** P1
**Depends on:** None

### Observable release cadence + per-release credit (P1-12)

**What:** Actually cut and tag releases through the existing `release-channels.yml`
pipeline; publish a versioned docs releases index; auto-generate notes from
CHANGELOG; credit contributors per release once they appear.

**Why:** CHANGELOG documents one shipped release with no git tags, so external
observers can't see the project ships regularly or is alive.

**Effort:** M
**Priority:** P1
**Depends on:** None

### Fix the stale test count + run the suite in CI (P1-7)

**What:** (1) Replace the hardcoded "~17k tests / ~900 files (May 2026)" in
AGENTS.md (actual: 2,143 files / ~39.7k functions) with an audit-script-emitted
value; (2) run pytest in CI as a sharded nightly/full job separate from the fast
PR gate.

**Why:** The flagship quality metric is inaccurate, and the giant suite never
runs in CI — there is no green "tests pass" signal for adopters. In a
machine-enforced-accuracy brand, both are outsized credibility costs. Reliability
is currently an open risk, not a strength.

**Effort:** M
**Priority:** P1
**Depends on:** None

### Implement or reframe the triage sweeper (P2-41)

**What:** Either implement the AGENTS.md-described triage sweeper as a scheduled
GitHub Actions workflow, or reframe the text as explicitly aspirational until it
ships; extend an audit script to flag documented automations with no
corresponding workflow.

**Effort:** M
**Priority:** P2
**Depends on:** None

### Status badges for staged/planned features (P2-42)

**What:** A consistent status badge/admonition ("Status: planned/staged") on any
docs page documenting unshipped functionality, plus a single "What ships today
vs planned" page. Enforce via the docs-contract mechanism.

**Effort:** S
**Priority:** P2
**Depends on:** None

### Publish a granular public roadmap (P2-43)

**What:** Surface this analysis + a GitHub Projects board/milestones; keep
`TODOS.md` populated (this file) as the in-repo record.

**Effort:** S
**Priority:** P2
**Depends on:** None

### Align the versioning scheme (P3-24)

**What:** Pick one scheme repo-wide — CalVer aligns with the release pipeline and
mirrors OpenClaw's `vYYYY.M.N`; update `pyproject.toml` (currently semver 0.21.0)
and add an audit check so the package version and release tag can't diverge.

**Effort:** S
**Priority:** P3
**Depends on:** None

### Opt-in adoption signal (P3-25)

**What:** A privacy-respecting, opt-in adoption signal (anonymous off-by-default
install ping, or a curated public adopters/showcase page users add themselves to
via PR). Never an always-on core behavior.

**Effort:** M
**Priority:** P3
**Depends on:** None

## Cross-Cutting Program Risks

### Run the test suite in CI (✚-1 / P1-7)

**What:** See "Fix the stale test count + run the suite in CI" above. Tracked
here as a program-level reliability risk: the ~39.7k-function suite never
executes in `public-ci.yml`.

**Effort:** M
**Priority:** P1
**Depends on:** None

### Performance / latency / concurrency benchmark harness (✚-2)

**What:** A load/throughput/profiling harness measuring TTFT, tokens/sec, gateway
concurrency ceilings, SQLite-WAL contention under many parallel sessions/cron
jobs, cold-start, and holographic-FTS5-vs-embedding recall under load.

**Why:** A "local-first Pi/Jetson" pitch lives or dies on latency and concurrency;
the only number cited today is a static ~70 MiB footprint.

**Effort:** L
**Priority:** P2
**Depends on:** None

### Agent-quality / task-success eval harness (✚-3)

**What:** Golden-transcript regression tests + a task-success/tool-use-accuracy
eval gating releases (no `evals/` directory exists today).

**Why:** A personal agent's value is output quality, not adapter count; nothing
measures whether the agent completes tasks well or regresses when
prompts/models/toolsets change.

**Effort:** L
**Priority:** P2
**Depends on:** None

### i18n depth vs the multilingual-channel claim (✚-4)

**What:** Extend `agent/i18n.py` beyond CLI approval prompts + a few slash
replies so agent output, tool results, and command descriptions can localize;
audit the 16 locale files; assess web/desktop UI i18n.

**Why:** CJK/enterprise channel breadth (WeCom/DingTalk/Feishu/Weixin/Yuanbao/QQ)
is marketed as a lead, but the product barely localizes for those markets.

**Effort:** L
**Priority:** P3
**Depends on:** None

### Accessibility (a11y) across surfaces (✚-5)

**What:** Screen-reader support, keyboard navigation, WCAG/contrast, focus
management, and captions across TUI, Electron desktop, web dashboard, and the
PWA. Add ARIA roles/alt text and an a11y lint/test.

**Effort:** L
**Priority:** P3
**Depends on:** None

### Upstream-fork drift & CVE-backport process (✚-6)

**What:** Track the `hermes-agent` upstream as a remote; document a process to
diff divergence and backport upstream security fixes; record a divergence
measure.

**Why:** Only `origin` is tracked with squash-imported history, so Fabric can
silently miss upstream vulnerability fixes.

**Effort:** M
**Priority:** P2
**Depends on:** None

### Licensing / trademark / IP exposure review (✚-7)

**What:** Audit competitor marks (`openclaw`/`clawdbot`/`moltbot`) and the
`fabric claw migrate` verb — separate internal identifiers from user-facing
branding; verify bundled-skill license provenance and THIRD_PARTY_NOTICES
completeness against the actual dependency tree.

**Effort:** M
**Priority:** P2
**Depends on:** None

### Sustainability / funding thesis (✚-8)

**What:** Add `FUNDING.yml`, evaluate sponsors/donations and/or a hosted or
commercial tier. Nearly every P1/P2 item (registry hosting, mobile, audit,
always-on security) needs sustained funding a single unpaid maintainer can't
supply against a foundation-backed incumbent.

**Effort:** M
**Priority:** P2
**Depends on:** None

### Data portability / export / backup / DR (✚-10)

**What:** Export-out CLI verbs, portable session/memory schemas, documented
backup/restore and disaster-recovery for the SQLite stores; anti-lock-in
guarantees.

**Why:** Migration *in* is covered, but recoverability and portability are core
trust properties for a local-first tool holding all personal data.

**Effort:** M
**Priority:** P2
**Depends on:** None

### Observability / opt-in telemetry / support pipeline (✚-11)

**What:** Structured turn-level tracing (opt-in), privacy-respecting crash
reporting, and an issue-triage pipeline, so a single maintainer has field signal
on what breaks (compounds bus-factor).

**Effort:** L
**Priority:** P3
**Depends on:** None

### Enterprise compliance / multi-user RBAC / data-residency (✚-12)

**What:** Assess and, if an enterprise angle is intended, add multi-user RBAC,
tenant isolation beyond per-profile secrets, tamper-evident audit-log retention,
and SOC2/GDPR/DPA posture.

**Effort:** L
**Priority:** P3
**Depends on:** None

## Completed

No completed items yet.
