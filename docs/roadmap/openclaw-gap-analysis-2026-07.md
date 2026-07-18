# Fabric ↔ OpenClaw Gap Analysis, Improvement Matrix & Roadmap

**Date:** 2026-07-18 · **Baseline:** Fabric `main` @ `016ab5c` vs OpenClaw
`v2026.7.2-beta.2` (Jul 17 2026), `v2026.7.1` stable (Jul 13), `v2026.6.11`.

**What this is.** A comprehensive, evidence-grounded comparison of Fabric
against OpenClaw — today the dominant open-source personal-AI-agent runtime —
across eleven capability dimensions, plus a prioritized improvement matrix and a
Now/Next/Later roadmap with specs for the headline initiatives. Every Fabric
claim is grounded in the repository; every OpenClaw claim is grounded in
primary sources (docs.openclaw.ai, the GitHub repo, official posts) or clearly
flagged where it could not be confirmed.

**How it was produced.** A multi-agent research pass mapped the Fabric codebase
and deep-researched OpenClaw independently for each dimension, a per-dimension
analyst compared the two, and an adversarial verifier fact-checked the
load-bearing claims. Verification tally: **76 confirmed, 11 corrected, 3
plausible, 6 refuted** across the claims checked. Corrections that change a
recommendation are folded into the gaps below and listed in
[Appendix B](#appendix-b--verification-corrections-that-changed-a-finding).

> **Read this first — how to weight the findings.** A completeness critic
> reviewed the whole analysis and surfaced three biases to correct for:
>
> 1. **Discount "plumbing moats."** Fabric's leads cluster in internal
>    engineering sophistication (ABCs, hooks, rotation strategies, snapshots)
>    that users never see; OpenClaw's leads cluster in adoption, network
>    effects, native apps, and UX. Network effects compound; private
>    architecture does not. Weight OpenClaw's advantages higher than a raw
>    feature count would suggest.
> 2. **Deduplicate shared architecture.** A handful of Fabric strengths
>    (the OpenAI-compatible API server, the prompt-cache invariant, multi-profile
>    isolation, the Skills-Guard/MCP-screen static gate, the holographic
>    memory) each show up as a "win" in 3–4 dimensions. They are counted **once**
>    in this document.
> 3. **Reliability is an open risk, not a strength.** The large pytest suite
>    (~39.7k functions) **is never run in CI** (`.github/workflows/public-ci.yml`
>    runs only lint, audit scripts, web checks, and doc contracts). Treat "mature
>    test posture" as unproven until the suite runs green in CI.

---

## 1. Executive summary

Fabric and OpenClaw are the same *kind* of product — a single long-lived agent
core multiplexed across a CLI/TUI, a messaging gateway (~28–29 channels each), a
desktop app, and a web surface, extended through skills/plugins rather than core
growth. Their stated philosophies are nearly identical ("lean core, rich
ecosystem"). They diverge on **maturity of execution** and **go-to-market**, not
on architecture.

**Where Fabric genuinely leads (deduplicated):**

- **Cost discipline as architecture.** The prompt-cache invariant (frozen
  system prompt, per-turn recall injected into a fenced, non-persisted user
  block) directly answers OpenClaw's single loudest criticism: context-bloat
  token burn (issue #67419, ~15–20k tokens re-injected per turn). This is
  Fabric's most defensible technical moat.
- **Local-first and egress control.** Real OS-level air-gap (`docker
  --network=none`), per-purpose route authorization, embedding-free semantic-ish
  memory (holographic FTS5+HRR) that runs on a 1 GB board, and a candid,
  documented single-tenant threat model (330-line `SECURITY.md`).
- **Supply-chain & skill-trust posture.** Client-side Skills Guard
  (scan→quarantine→attest), MCP save/spawn security screening, CVE-annotated
  dependency pinning, and a 312-source trust-tiered Skills Ecosystem Directory —
  a credible counter to OpenClaw's ClawHavoc history (341+ malicious ClawHub
  skills; ~135k exposed instances).
- **Channel breadth OpenClaw structurally lacks.** Official WhatsApp **Cloud
  API** path (OpenClaw is Baileys-only with documented ban risk), first-class
  IMAP/SMTP email, iMessage without a Mac (Photon), and a first-party CJK/
  enterprise suite (DingTalk, WeCom, Weixin, Yuanbao, Feishu, QQ).
- **First-party media generation and cross-platform Computer Use.** `image_generate`/
  `video_generate` are core tools (OpenClaw relies on third-party skills);
  Computer Use runs background-mode on macOS + Windows + Linux (OpenClaw is
  macOS-only, foreground-gated).
- **IDE integration via ACP.** A real ACP server (Zed registry entry, VS Code/
  JetBrains) — OpenClaw has no first-party IDE extension.

**Where OpenClaw leads (weight these heavily):**

- **Adoption & sustainability.** ~383k stars, 532 contributors credited on a
  single release, weekly-to-biweekly dated releases, a 501(c)(3) foundation
  (OpenAI/NVIDIA/Microsoft/Tencent sponsors), mainstream press, ClawCon events,
  and a derivative ecosystem. Fabric is a **single-maintainer project with a
  bus-factor of one** and no observable public release cadence.
- **Native mobile + device mesh.** Official iOS/Android/macOS apps, on-device
  wake word, realtime full-duplex Talk, camera/location/notification capture
  from paired "nodes," and an installable PWA with Web Push. Fabric has **no
  mobile surface** beyond messaging bots and responsive web.
- **Signed, mainstream distribution.** Notarized macOS DMG, Play Store + signed
  APK, App Store build, no-admin Windows installer, deb/AppImage. Fabric ships
  **only unsigned source-builds** and has **no published PyPI wheel or versioned
  release**.
- **Proactive / ambient behavior.** Heartbeat (self-initiated main-session
  check-ins), Wake events, Standing Orders/Commitments — the defining "personal
  assistant" loop Fabric lacks entirely.
- **Deterministic, resumable orchestration.** Lobster (typed pipelines with
  approval gates + resume tokens) and OpenProse. Fabric's every multi-step path
  is LLM-driven.
- **Marketplace network effects.** ClawHub (3,200+ published skills, one-command
  install, reputation signals). Fabric curates others' ecosystems but generates
  little first-party publishing activity, has no reputation/reporting signals,
  and its MCP catalog holds 3 entries.
- **Model velocity & a shipping cost-router.** Day-zero frontier-model support
  (five families in one dated release) and ClawRouter (bundled credential-broker
  gateway with dollar budget enforcement). Fabric's `smart_model_routing` config
  section has **zero runtime consumers**, and it enforces iteration budgets but
  never dollar caps.
- **Empirical security validation.** ~1,142 advisories and red-team scrutiny
  from Cisco/Kaspersky/Koi/Unit 42/CertiK — bruising, but its surviving controls
  are proven at scale. Fabric has **no independent third-party audit**.

**The strategic reading.** A single maintainer cannot out-ship a foundation-
backed, 383k-star incumbent on breadth. Fabric should stop chasing parity by
default and adopt an explicit wedge:

> **Wedge: "the auditable, governed, local-first personal agent."** Win on
> trust, privacy, cost discipline, supply-chain integrity, and CJK/enterprise
> channel reach. **Concede** the native-mobile-app and marketplace-network-
> effect races (answer them cheaply via PWA and curation, not by cloning).
> Turn OpenClaw's dominant *risk* narrative into Fabric's headline *message*.

The [build-vs-concede table](#3-strategy--build-vs-concede) makes this concrete
per gap.

---

## 2. Side-by-side capability matrix

Verdict is Fabric's position relative to OpenClaw as of 2026-07-18.
"Lead" = Fabric ahead; "Behind" = OpenClaw ahead; "Parity" = roughly equivalent.

| # | Dimension | Verdict | Fabric's edge | OpenClaw's edge |
|---|-----------|---------|---------------|-----------------|
| 1 | Messaging channels & gateway | **Parity (Fabric edge on breadth/security)** | WhatsApp Cloud API, email, CJK suite, delivery-reliability machinery, per-command authz | Multi-agent routing (bindings hierarchy), Signal depth, bundled WebChat, telephony, contributor velocity |
| 2 | Surfaces & UX (CLI/TUI/desktop/web/mobile/IDE) | **Mixed** | Ink TUI depth, single-chat web (PTY embed), ACP/IDE, skins, Live View, no surface CVEs | Native mobile apps, node mesh, PWA+push, signed installers, wake word, cloud workers |
| 3 | Model & provider support, routing, cost | **Lead on cost discipline; behind on routing product** | Prompt-cache invariant, cost provenance, credential pools, egress routing, local-first depth | ClawRouter (dollar budgets), day-zero model velocity, 67 provider pages, org-cost import |
| 4 | Skills ecosystem & marketplace | **Lead on safety; behind on network effects** | Scan→quarantine→attest, trust-tiered directory, TUF verifier, cache-preserving injection | ClawHub registry (reputation, install counts, reporting), continuous re-scan, Lobster |
| 5 | Extensibility: plugins, MCP, APIs, SDK | **Lead on security; behind on contract/ecosystem** | MCP OSV/IOC screening, host-owned plugin LLM facade, versioned middleware, ACP, webhook rigor | Versioned scoped protocol (v4), ClawHub plugin registry, third-party commercial economy |
| 6 | Memory, context & session mgmt | **Lead on cost/privacy; behind on semantic recall** | Prompt-cache economics, bounded curated memory, checkpoints/rollback, egress-gated recall | In-core hybrid BM25+vector, QMD sidecar, context introspection, memory import, Memory Wiki |
| 7 | Automation & multi-agent orchestration | **Mixed** | Per-profile cron isolation, provider-snapshot drift guard, durable kanban OS-workers | Proactive Heartbeat, Lobster/OpenProse deterministic engines, Task Flow, Wake events, retry/backoff |
| 8 | Security, privacy & trust | **Lead on posture; behind on validation** | Fail-closed defaults, env scrubbing, hardline blocklist, honest threat model | `security audit` linter, secret managers (Vault/1Pass/Bitwarden), pre-allowlist obfuscation gate, external audits |
| 9 | Deployment, install & device support | **Behind** | Broad device matrix, s6 supervised Docker, managed-toolchain installer ladder, `fabric doctor` | Signed/notarized installers, published releases, App/Play Store, cloud workers |
| 10 | Voice, vision & media | **Lead on generation/CU; behind on live voice** | Core image/video gen, cross-platform Computer Use, local zero-key voice loop, browser backends | Native mobile voice, wake word, realtime speech-to-speech, barge-in, phone plugin, camera nodes |
| 11 | Community, adoption, docs & momentum | **Behind (docs governance excepted)** | Machine-enforced docs contracts, licensing hygiene, trust-tiered directory, migration guide | 383k stars, 532 contributors/release, foundation, press, events, observable cadence |

**Net:** Fabric is technically competitive-to-ahead on **cost, privacy,
security posture, supply-chain integrity, channel breadth, media generation,
and IDE integration**, and materially behind on **adoption, native mobile,
signed distribution, proactive behavior, deterministic orchestration,
marketplace network effects, and model/routing velocity**.

---

## 3. Strategy — build vs concede

Sequencing against a single maintainer's capacity. "Extend" = a Fabric lead to
press; "Answer cheaply" = match at the edge (PWA/skill/plugin), don't clone;
"Concede" = deliberately don't chase, or answer only via positioning.

| OpenClaw strength | Decision | Rationale |
|---|---|---|
| Signed/notarized installers, published releases | **Build (P0/P1)** | Table-stakes trust for a *local-first* pitch; unsigned source-build is an adoption filter and a credibility hit. |
| Context-bloat / cost | **Extend (Fabric already wins)** | Make the prompt-cache advantage a *measured, marketed number* via `/context`. |
| Skill/plugin supply-chain trust | **Extend** | Fabric already has the machinery; turn ClawHavoc into Fabric's headline via activation + positioning. |
| Proactive Heartbeat | **Answer cheaply (P1)** | Build on existing cron + attach-to-session; no new core loop. |
| Native mobile apps | **Answer cheaply → concede native** | Ship a PWA (mic/camera/push) over the existing dashboard; defer native indefinitely. |
| Marketplace network effects (ClawHub) | **Answer cheaply, concede scale** | Curation *is* the differentiator; add reputation/reporting from the static index, don't run a registry backend. |
| ClawRouter dollar budgets | **Build the cap, answer the router cheaply** | Ship spend caps (real gap); make routing an opt-in cache-safe plugin, not core. |
| Deterministic workflow engines | **Answer cheaply (P2)** | One `fabric flow` CLI + skill over delegate/kanban; not a core tool. |
| Node mesh (camera/location/screen) | **Concede / narrow answer (P3)** | OpenClaw's largest attack surface; answer only a headless companion node via service-gated tools. |
| Cloud workers | **Watch (P4)** | Days-old beta; interim answer is `fabric serve` + Tailscale, already supported. |
| Foundation / 532 contributors / press | **Concede on raw metrics, counter-position** | Cannot be closed quickly; win the argument on trust/governance instead. |

---

## 4. Consolidated improvement matrix

Every actionable gap, deduplicated across dimensions, ranked by priority then
severity. **Sev** = user/trust impact (H/M/L). **Eff** = S/M/L/XL. **Rung** =
Footprint-Ladder placement (all respect narrow-core / prompt-cache-sacred).
Dimension key: CH channels · SU surfaces · MO models · SK skills · EX
extensibility · ME memory · AU automation · SE security · DE deployment ·
VO voice · CO community · ✚ cross-cutting (critic).

### P0 — do first (trust-breaking or blocks the wedge)

| ID | Gap | Dim | Sev | Eff | Rung |
|----|-----|-----|-----|-----|------|
| P0-1 | Signed, notarized, checksummed public desktop release (macOS Developer ID + notarize, Windows Authenticode) | DE/SU | H | XL | CI/dist |
| P0-2 | Guard-scan agent-created skills **by default** (`skills.guard_agent_created` → on) | SK | H | S | config |
| P0-3 | Wire the trust-tiered Ecosystem Directory into runtime install policy (replace 4 hardcoded `TRUSTED_REPOS`) | SK | H | M | build+guard |
| P0-4 | Curated, integrity-verified extension **hub** (plugins + packs + MCP + taps), curation-not-open-publish | EX | H | L | CLI+catalog |
| P0-5 | Finish `R2-MEM-03` memory-identity scope enforcement end-to-end (persistence + provider dispatch + gateway wiring) | ME | H | M | core (finish) |
| P0-6 | Kill or ship the phantom `smart_model_routing` config (zero runtime consumers today) | MO | H | S | docs/setup |

### P1 — next (decisive competitive points; extend leads)

| ID | Gap | Dim | Sev | Eff | Rung |
|----|-----|-----|-----|-----|------|
| P1-1 | Installable **PWA + Web Push** over the existing dashboard (the mobile answer) | SU/VO | H | M | web edge |
| P1-2 | Versioned release + **PyPI wheel** + Homebrew bottle (no pinnable version exists) | DE | H | L | packaging |
| P1-3 | **Dollar spend caps** (per-session/per-day USD budget guard over existing CostResult stream) | MO | H | M | CLI+status |
| P1-4 | Proactive **Heartbeat** (HEARTBEAT.md + `fabric heartbeat` over cron/attach-to-session) | AU | H | M | CLI+skill |
| P1-5 | Security-posture **linter** in `fabric doctor` (flag 0.0.0.0-without-auth, `*_ALLOW_ALL_USERS`, break-glass flags) | SE | H | M | CLI |
| P1-6 | Add the referenced-but-absent **supply-chain-audit CI** (pip-audit/OSV on manifest change) + dependabot | SE/✚ | H | M | CI |
| P1-7 | **Run the pytest suite in CI** (nightly/sharded) + fix the stale "~17k tests" count | CO/✚ | H | M | CI |
| P1-8 | Execution-time **containment** for community skills (promote permission leases to enforced) | SK | H | L | edge (promote) |
| P1-9 | Counter-position on **trust/governance** (rewrite migrate-from-openclaw; Security & Governance landing page) | CO | H | M | docs |
| P1-10 | First-party **community channel** (enable GitHub Discussions; fix dangling `#plugins-skills-and-skins`) | CO | H | S | infra |
| P1-11 | **Bus-factor + first-contribution on-ramp** (quickstart, good-first-issue, succession note) | CO/✚ | H | L | process |
| P1-12 | Observable **release cadence** (cut/tag releases via existing pipeline; docs releases index) | CO | M | M | CI |
| P1-13 | **Day-zero frontier-model** process (externalize quirk allowlists to versioned data) | MO | H | M | data+doctor |
| P1-14 | Close the **plugin install trust gap** (scan on install, declare capabilities in `plugin.yaml`, prompt) | EX | H | M | edge |
| P1-15 | Publish a **versioned, scoped programmatic contract** (JSON-RPC handshake version + scoped API tokens + `/api/v1`) | EX | M | L | edge+refactor |
| P1-16 | Signed desktop **auto-update** channel (depends on P0-1) | SU | H | L | dist |
| P1-17 | Windows-native **ship reality** (atomic stage-and-swap update; finish ConPTY `/api/pty`) | DE/SU | H | L | edge |
| P1-18 | Close the **dual-chat-implementation** trap (desktop React chat vs TUI drift; server-side curation + conformance CI) | SU | M | M | contract |
| P1-19 | Wire the already-built **capability packs** into the CLI + docs (`fabric packs …`) | EX | M | M | CLI |
| P1-20 | **In-core semantic recall**: promote holographic to recommended default + optional embedding layer as plugin | ME | H | L | plugin+promote |
| P1-21 | Durable **background delegations** + unified flow record (route long work onto kanban) | AU | M | M | edge |
| P1-22 | **Signal** full-tier parity (edit-based streaming, reaction lifecycle, numbered-option picker) + fix docs matrix | CH | H | M | adapter |
| P1-23 | Pre-compression **durable-memory flush** for the builtin store | ME | M | M | edge |
| P1-24 | Multi-agent **deterministic routing** config (generalize Discord per-channel bindings to a gateway bindings section) | CH | H | L | gateway config |
| P1-25 | Runtime **advisory refresh** + opt-in scheduled OSV audit (catalog has one entry) | SE | M | M | CLI+cron |
| P1-26 | Reputation / popularity / **reporting** signals in the Hub (stars/freshness badges; `fabric skills report`) | SK | H | M | index+CLI |

### P2 — soon (noticeable disadvantages / lead extensions)

| ID | Gap | Dim | Sev | Eff | Rung |
|----|-----|-----|-----|-----|------|
| P2-1 | Publish a **channel threat model** + extend inbound-injection defenses (build on existing `_format_untrusted_prompt_value`) | CH | H | M | docs+edge |
| P2-2 | Generate the **channel capability matrix from code** (adapter capability introspection + CI drift check) | CH | M | M | CLI+CI |
| P2-3 | Universal **buttonless fallback** for clarify/approval/model-picker (numbered options in base adapter) | CH | M | M | adapter |
| P2-4 | Zero-config **web chat** surface (bootstrap Open WebUI via `fabric webui` or minimal SPA plugin) | CH/SU | M | M | plugin |
| P2-5 | Replace/gate **placeholder Workspace routes**; project Approvals & Activity from TUI events | SU | M | M | web |
| P2-6 | **Wake word + realtime** browser/desktop voice ("Talk mode" answer) as plugins | SU/VO | M | L | plugin |
| P2-7 | Harden + press the **IDE/ACP lead** (persistent ACP sessions; published VS Code extension) | SU | M | M | edge+pkg |
| P2-8 | **Context introspection** commands (`/context`, per-reply usage footer) — proves the cache lead | ME | M | S | CLI |
| P2-9 | **Overflow-recovery compaction** (compact-and-retry on provider context-length errors) | ME | M | M | loop |
| P2-10 | Bounded runtime **memory-provider health probe** (`fabric memory probe`) | ME | M | S | CLI |
| P2-11 | Visibility/override for **quarantined memory** (`fabric memory quarantine list/allow`) | ME | M | S | CLI |
| P2-12 | `fabric memory import` (OpenClaw / Claude Code / Codex) — switcher on-ramp | ME | M | S | CLI+skill |
| P2-13 | Turn on **filesystem checkpoints** by default (v2 shared-object store removed the disk cost) | ME | M | S | config |
| P2-14 | Client-side **smart routing** (opt-in, cache-safe boundaries only; MoA-style virtual provider) | MO | M | L | plugin |
| P2-15 | Verify then ship the **bundled models.dev snapshot** (offline-first) — *see Appendix B, may already exist* | MO | M | S | verify+data |
| P2-16 | Unify the **dual provider registries**; make OAuth providers pluggable | MO | M | L | core-shrink |
| P2-17 | Runtime **prompt-cache guard** (detect + count cache-breaking mutations; surface in `/usage`) | MO | M | M | telemetry |
| P2-18 | Make `air_gapped` **fail loudly** until a real network boundary exists | MO | M | S | config |
| P2-19 | **External secret-manager** seam (Vault/1Password/Bitwarden as plugins; reference-by-ID) | SE | M | L | plugin |
| P2-20 | `tirith` **fail-open visibility** + native binary-independent obfuscation fallback (Windows too) | SE | M | M | edge |
| P2-21 | **Authz/ownership regression** test matrix over ~20 adapters (encode OpenClaw's `senderIsOwner` bug class) | SE | M | M | tests |
| P2-22 | Close SSRF **DNS-rebinding TOCTOU** + document third-party-SDK egress bypass | SE | M | M | code |
| P2-23 | Setup-time **posture prompt**: steer gateway/untrusted-input users to a sandboxed backend | SE | M | M | setup |
| P2-24 | **Deterministic workflow engine** (`fabric flow run` over delegate/kanban; approval gates + resume) — answers Lobster/OpenProse | AU/SK | M | L | CLI+skill |
| P2-25 | Cron **failure retry/backoff** | AU | M | S | scheduler |
| P2-26 | First-class **wake / event-injection** primitive (`fabric wake` over completion-queue rail) | AU | M | S | CLI+RPC |
| P2-27 | External **HTTP spawn API** backed by kanban (leapfrogs OpenClaw's unshipped `/api/sessions/spawn`) | AU | M | L | service-gated |
| P2-28 | Finish the **gateway/run.py decomposition** + codify the dual message-guard as an enforced contract | CH | M | L | refactor |
| P2-29 | Per-platform **adapter contract test harness** | CH | M | M | tests |
| P2-30 | Continuous **re-scan** of installed hub skills against evolving patterns | SK | M | S | curator |
| P2-31 | Activate the dormant **skill signing** pipeline for first-party content (TUF verifier exists) | SK | M | L | CI |
| P2-32 | Mirror the unified **skills index** (eliminate the discoverability SPOF) | SK | M | S | CI |
| P2-33 | Ship a minimal **skill eval harness** (`fabric skills eval run`) → quality badges | SK | M | L | CLI+skill |
| P2-34 | Governed **community submission** path (`fabric skills submit` → templated PR + CI guard scan) | SK | M | M | CLI+CI |
| P2-35 | Plugin **API version negotiation** (fail-closed; `PLUGIN_API_VERSION`) | EX | M | S | edge |
| P2-36 | Make `mcp_serve` a **live, approval-capable** bridge (connect to TUI-gateway JSON-RPC) | EX | M | M | edge |
| P2-37 | **Bound hook latency** (per-hook timeouts; async observers) | EX | M | M | edge |
| P2-38 | Grow the **MCP catalog** (3 → 20–30) + remote index unbinding intake from releases | EX | M | M | catalog |
| P2-39 | Realtime **speech-to-speech** path (OpenAI Realtime / Gemini Live) as a gated plugin | VO | M | L | plugin |
| P2-40 | **Barge-in** in live voice mode (VAD during TTS; cancel playback on speech) | VO | M | M | runtime |
| P2-41 | Implement or reframe the documented **triage sweeper** | CO | M | M | CI |
| P2-42 | **Status badges** for staged/planned features (docs-contract enforced) | CO | M | S | docs |
| P2-43 | Publish a **granular public roadmap** (this doc + `TODOS.md` + GitHub Projects) | CO | M | S | docs |
| P2-44 | Desktop signed **auto-update + rollback** UX (surface existing recovery-point) | DE | M | L | dist |
| P2-45 | Complete Tauri **bootstrap installer** for macOS/Linux (currently Windows-first, v0.0.1) | DE | M | L | packaging |
| P2-46 | First-party **deb/rpm/AppImage/MSI** publish pipeline | DE | M | L | packaging |
| P2-47 | Reduce **installer-script fragility** (extract workarounds; CI install-matrix) | DE | M | L | CI |
| P2-48 | Finish **Hermes → Fabric** rename (env ABI, Docker `/opt/hermes`, entry-point group, headers) — *one sweep, dedup across CH/EX/DE* | DE/EX/CH | M | M | compat |
| P2-49 | Independent **third-party security audit** / public red-team | SE | M | L | process |

### P3/P4 — later (polish, watch-items, long-tail)

| ID | Gap | Dim | Sev | Eff | Rung |
|----|-----|-----|-----|-----|------|
| P3-1 | Graduate the **relay connector** (freeze contract v1) → community long-tail channels | CH | M | L | edge |
| P3-2 | **Telephony** voice-call channel (Twilio programmable voice) + realtime inbound | CH/VO | L | L | plugin |
| P3-3 | Unify default **terminal surface** (auto-select TUI; vendor the bundle) | SU | L | M | UX |
| P3-4 | Device **node** answer (headless companion node; service-gated tools only) | SU/VO | M | XL | plugin |
| P3-5 | Decompose god-file **surface backends** (`cli.py`/`web_server.py`/`tui_gateway`) + `auxiliary_client.py` | SU/MO | L | L | refactor |
| P3-6 | Provider **breadth top-ups** (Groq, Cerebras) + gateway recipes | MO | L | M | plugin |
| P3-7 | Harden **fragile subscription-auth** (externalize client-version/backend URLs; doctor probes) | MO | M | M | data |
| P3-8 | **Camera capture** skill + `fabric camera snap` | VO | M | M | skill |
| P3-9 | Extend **media-gen lead** (local ComfyUI/AudioCraft backends) | VO | L | M | plugin |
| P3-10 | Read-only **memory-layer composition** (per-tool read/write annotations; composite provider) | ME | L | M | edge |
| P3-11 | **Session retention/pruning** policy (`fabric sessions cleanup`) | ME | L | S | CLI |
| P3-12 | Mid-session builtin **memory writes visible** via the per-turn fence | ME | L | S | edge |
| P3-13 | Ship one real **context engine** or cut the speculative surface | ME | L | M | decision |
| P3-14 | Productized **Automations** UI (templates, run-now, stat cards) | AU | L | M | web |
| P3-15 | Persistent sub-agent sessions / on-exit cron / named cron | AU | L | M | edge |
| P3-16 | Publish-time **skills-index scanning** (hub-side complement) | SE | L | S | CI |
| P3-17 | Mobile/operator **approval** flow (resolve on originating device) | SE | L | M | gateway |
| P3-18 | Tier-3 **CI smoke tests** (Termux/Jetson/Nix) + health badges | DE | L | M | CI |
| P3-19 | Productize the **SBC thin-client / remote-inference** profile | DE | L | M | docs+preset |
| P3-20 | Refactor security-critical **install-path god-files** (`skills_hub.py`) | SK | L | M | refactor |
| P3-21 | Contract tests + visible degradation for **third-party registry adapters** | SK | L | S | CI |
| P3-22 | Cross-ecosystem **import** (`fabric import claude-code`/`codex`) | EX | M | M | CLI+skill |
| P3-23 | Consolidate the **six plugin-discovery loaders**; kill the import side-effect | EX | L | M | refactor |
| P3-24 | Align **versioning** scheme (CalVer everywhere; pyproject says 0.21.0) | CO | L | S | cleanup |
| P3-25 | Opt-in **adoption signal** / public adopters page | CO | M | M | opt-in |
| P4-1 | Watch **cloud workers**; interim `fabric serve` + Tailscale recipe | SU | L | XL | watch |
| P4-2 | Companion overlay: fix event-stream stealing before promoting | SU | L | S | edge |
| P4-3 | Coding-session **interop** (catalog/resume Claude Code/Codex) | SU | L | M | plugin |
| P4-4 | Watch OpenClaw's **Memory Wiki** (structured claims layer) | ME | L | L | watch |
| P4-5 | Deepgram/Aura **low-latency** voice providers | VO | L | S | plugin |
| P4-6 | Surface the full **provider catalog** behind the curated default | MO | L | S | UX |
| P4-7 | Generate **ecosystem counts** from a single source of truth | SK | L | S | build |
| P4-8 | Fix the self-referential **example-plugins** pointer in AGENTS.md | EX | L | S | docs |

### Cross-cutting workstreams the dimensions missed (critic-surfaced)

These are not per-dimension gaps; they are program-level risks that touch the
whole roadmap. Grounded against the repo where noted.

| ID | Workstream | Why it matters | First check |
|----|-----------|----------------|-------------|
| ✚-1 | **Run the test suite in CI** (also P1-7) | ~39.7k test functions never execute in CI; reliability is unproven | `public-ci.yml` runs no pytest |
| ✚-2 | **Performance / latency / concurrency benchmarks** | A "local-first Pi/Jetson" pitch lives or dies on TTFT, tokens/sec, gateway concurrency, SQLite-WAL contention; only a static ~70 MiB footprint is cited | no `evals/`/bench harness found |
| ✚-3 | **Agent-quality / task-success evals** gating releases | Adapter count ≠ output quality; no golden-transcript or success-rate instrumentation | no `evals/` dir |
| ✚-4 | **i18n depth** | CJK/enterprise channel breadth is marketed, but `agent/i18n.py` localizes only CLI approval prompts + a few slash replies; agent output stays English despite 16 locale files | read `agent/i18n.py` scope |
| ✚-5 | **Accessibility (a11y)** | Screen-reader/keyboard/WCAG across TUI/desktop/web/PWA; emerging procurement requirement | grep `web/` for ARIA/alt/a11y lint |
| ✚-6 | **Upstream-fork drift / CVE backport** | Only `origin` is tracked (no `hermes-agent` upstream); squash history; no patch-sync path, so upstream fixes can be silently missed | `git remote` = origin only |
| ✚-7 | **Licensing / trademark / IP exposure** | `openclaw`/`clawdbot`/`moltbot` strings and a `fabric claw migrate` verb ship in code; bundling a competitor's personas raises mark-use/redistribution questions | audit competitor marks in user-facing vs internal identifiers |
| ✚-8 | **Sustainability / funding** | No `FUNDING.yml`, sponsors, or commercial tier; nearly every P1/P2 needs sustained funding a single unpaid maintainer can't supply | `FUNDING.yml` absent |
| ✚-9 | **Positioning / wedge strategy** | Parity-by-default loses to a 383k-star incumbent; needs an explicit "win here, concede there" (see §3) | README/index.mdx lack a stated wedge |
| ✚-10 | **Data portability / export / backup / DR** | Migration *in* is covered; export *out*, portable schemas, backup/restore/DR for the SQLite stores are unexamined — core trust for a local-first data holder | look for export/backup verbs |
| ✚-11 | **Observability / opt-in telemetry / support pipeline** | An always-on single-maintainer agent has no field signal on what breaks (compounds bus-factor) | grep for turn-level tracing |
| ✚-12 | **Enterprise compliance / multi-user RBAC / data-residency** | "Enterprise breadth" (WeCom/DingTalk/Feishu) is claimed without RBAC, tenant isolation, audit-log completeness, or SOC2/GDPR posture | assess gateway authz vs single-owner model |

---

## 5. Roadmap — Now / Next / Later

Organized into themes so a single maintainer can batch related work. Each theme
lists its matrix IDs.

### NOW (this cycle) — earn trust, stop the bleed, unlock the wedge

**Theme A · Distribution & trust foundation** — *P0-1, P1-2, P1-16, P1-17*
Signed/notarized desktop artifacts, a published PyPI wheel + versioned release,
and an atomic Windows update. This is the single biggest adoption filter and the
prerequisite for a credible "trust us with your machine" pitch. CI/packaging
work only — zero core impact.

**Theme B · Supply-chain & reliability integrity** — *P0-2, P0-3, P1-6, P1-7,
P1-8, P1-25, ✚-1*
Flip the agent-created-skill guard on, wire trust tiers into install policy, add
the missing supply-chain-audit CI, **run the pytest suite in CI**, and promote
permission leases. This converts Fabric's *claimed* security lead into a
*demonstrated* one — and closes the credibility gap where docs reference CI that
doesn't exist.

**Theme C · The wedge, made loud** — *P1-9, P1-10, P1-11, P1-12, P2-43, ✚-9*
Counter-position on trust/governance, open GitHub Discussions, lower the
first-contribution barrier, start cutting visible releases, and publish this
roadmap. Community/process work that directly attacks bus-factor-of-one.

**Theme D · Answer the headline product gaps cheaply** — *P1-1, P1-3, P1-4*
PWA + Web Push (the mobile answer), dollar spend caps (the cost-cap gap),
proactive Heartbeat (the "checks in on its own" gap). Three high-visibility
OpenClaw features answered at the edge without core growth.

**Theme E · Clean up phantom/false claims** — *P0-6, P1-22 (docs-matrix half),
P2-15 (verify), ✚-4*
Remove or ship `smart_model_routing`, fix the Signal-streaming false "✅",
verify the models.dev snapshot claim, and right-size the i18n story. Small,
mostly-docs, protects the "machine-enforced accuracy" brand.

### NEXT (following cycle) — close decisive competitive points

**Theme F · Model & cost product** — *P1-13, P2-14, P2-17, P2-18, P2-16*
Day-zero model process, opt-in cache-safe routing, the prompt-cache guard, and
provider-registry unification. Extend the cost/local-first lead.

**Theme G · Memory & context** — *P0-5 (finish), P1-20, P1-23, P2-8, P2-9,
P2-10, P2-11, P2-12, P2-13*
Land memory-scope enforcement, promote holographic semantic recall, add
`/context`, pre-compression flush, and the switcher-focused `fabric memory
import`. Turns the cache lead into a visible, marketable number and answers
OpenClaw's semantic-recall headline without a vector store in core.

**Theme H · Orchestration & automation** — *P1-21, P2-24, P2-25, P2-26, P2-27*
Durable delegations on kanban, a deterministic `fabric flow` engine, cron
retry, a wake primitive, and the HTTP spawn API. Answers Lobster/Task Flow and
leapfrogs OpenClaw's unshipped spawn API.

**Theme I · Extensibility & marketplace** — *P0-4, P1-14, P1-15, P1-19, P1-26,
P2-30..P2-38*
The curated hub, plugin install trust, the versioned contract + scoped tokens,
capability-pack CLI, and Hub reputation signals. Curation-as-differentiator.

**Theme J · Channels & surfaces polish** — *P1-18, P1-24, P2-1..P2-7, P2-28,
P2-29*
Dual-chat parity contract, gateway bindings routing, channel threat model +
code-generated capability matrix, buttonless fallbacks, Approvals/Activity
projections, ACP hardening, and the run.py decomposition.

**Theme K · Security depth** — *P2-19..P2-23, P2-49*
Secret-manager seam, tirith visibility, authz regression matrix, SSRF TOCTOU,
setup-time posture prompt, and an independent audit.

### LATER (opportunistic / watch) — long-tail, refactors, strategic bets

All P3/P4 items, the god-file refactors (P3-5, P3-20, P3-23), the device-node
answer (P3-4), telephony (P3-2), the relay graduation (P3-1), and the watch-
items (cloud workers P4-1, Memory Wiki P4-4). Plus the remaining cross-cutting
workstreams: perf benchmarks (✚-2), agent-quality evals (✚-3), a11y (✚-5),
fork-drift/CVE-backport (✚-6), IP/trademark review (✚-7), funding (✚-8), data
portability/DR (✚-10), observability (✚-11), enterprise/RBAC (✚-12).

---

## 6. Specs for the headline initiatives

Enough detail to start. Each names the concrete Fabric attach-points found in
the mapping so work can begin without re-discovery.

### Spec P0-1/P1-2/P1-16/P1-17 — Signed distribution & real releases

**Problem.** Every desktop artifact is a source-build or unsigned CI output
explicitly marked "must not be redistributed"; there is no PyPI wheel and no
versioned release, yet `recommended_update_command_for_method()` emits
`uv pip install --upgrade fabric-agent` for a wheel that doesn't exist. On
macOS users hit Gatekeeper, on Windows SmartScreen. OpenClaw ships signed
everything (confirmed: macOS auto-selects a Developer ID).

**Approach (CI/packaging only — no core, no prompt-cache impact).**
1. CI jobs: macOS notarize + Developer ID staple; Windows Authenticode; publish
   versioned GitHub Releases with `SHA256SUMS` (the `release-channels.yml` +
   `publish_release.py` promotion pipeline already exists — it just isn't
   producing public artifacts).
2. Build & upload a **PyPI wheel** for `fabric-agent` respecting the existing
   extras taxonomy in `pyproject.toml`; convert the Homebrew formula from
   HEAD-only to a versioned bottle.
3. Windows atomic **stage-and-swap** update (download to a side dir, swap on next
   launch) to kill the half-updated-environment failure; finish wiring
   `win_pty_bridge.py` into the `/api/pty` consumer and flip the feature-matrix
   entry — or officially reposition WSL2 as the recommended Windows path.
4. Once signing lands, add a signed `electron-updater`/Tauri auto-update channel
   and surface the existing `fabric update` recovery-point as a one-click
   rollback.

**Done when:** a non-developer can download a signed installer per OS, verify a
checksum, `pip install fabric-agent==<version>`, and receive a signed in-app
update with rollback. Gate "Tier-1 desktop/Windows" doc claims on this existing.

### Spec P0-2/P0-3/P1-8/P1-26 — Skill supply-chain: activate the lead

**Problem.** Fabric has best-in-class *machinery* but ships it half-armed:
`skills.guard_agent_created` is **off** (a prompt-injected agent can write an
unscanned skill), the 312-source trust directory is **build-time metadata the
installer never consults** (runtime trust collapses to 4 hardcoded repos), and
"safe"-verdict community skills run with full terminal capability. Meanwhile
`skill_permissions.py` (turn-scoped leases) exists but is experimental.

**Approach.**
1. **P0-2:** flip `guard_agent_created` → on. The guard already maps dangerous
   verdicts to a retryable "ask" error, so agent-UX degradation is minimal.
   Surface the pending-draft approval via the existing `fabric skills evaluate`.
2. **P0-3:** emit tier + `risk_flags` from `skills-sources.json` into
   `skills-index.json` at build time (`build_skills_index.py` already reads
   both); have `should_allow_install` consume them — A1/A2 → trusted, B →
   community, C/Q → explicit acknowledgment or block. Replace hardcoded
   `TRUSTED_REPOS` with a config-overridable list so a compromised source can be
   revoked without a release.
3. **P1-8:** promote permission leases to enforced-by-default for community
   trust: a skill's `skill.contract.yaml` declares needed capabilities; the
   dispatcher blocks/asks outside the lease; add guard patterns for inline-shell
   `` !`cmd` `` markers. Keep observation-gap surfaces honest (degrade to
   approve-per-use, don't fake containment). Leases record at `skill_view`
   activation → no prompt-cache impact.
4. **P1-26:** capture per-repo GitHub stars/last-commit into the index at crawl
   time; render as badges in the Hub and `fabric skills search`; add
   `fabric skills report <id>` filing a templated GitHub issue (moderation loop
   without running a registry backend).

**Done when:** an agent-written skill is scanned before it can run; a Q-tier
source cannot install under A1 policy; a community skill's scripts are lease-
gated; and users can see popularity/freshness and report bad skills.

### Spec P0-4/P1-14/P1-15/P1-19 — Curated extension hub + versioned contract

**Problem.** Discovery is why users pick OpenClaw for extensibility (ClawHub:
3,200+ skills, one-command install, reputation). Fabric's plugin install is
git-clone trust-on-install with no search, the MCP catalog has 3 entries, the
already-built **capability-pack** system is unwired (no CLI verb, no docs), and
none of Fabric's three protocols (ACP, JSON-RPC, OpenAI-compat) is versioned.
But ClawHavoc proves open-publish is a liability — so answer with **curation**.

**Approach (all edge surface).**
1. **P0-4:** a git-hosted, hash-verified catalog index over plugins + capability
   packs + skill taps + MCP entries, reusing the capability-pack compiler's
   canonical-JSON + sha256 tree hashing as the integrity layer. `fabric plugins
   search/browse`; intake via PR with a mandatory guard-scan gate; no open-
   publish tier — curation *is* the differentiator and the marketing message.
2. **P1-19:** wire `fabric packs list/install/verify/remove` to the existing
   lifecycle/transaction modules; publish the two in-repo packs as first catalog
   entries; one docs page. (Verified: the machinery exists, no CLI verb does.)
3. **P1-14:** run the skills guard on **plugin** installs (plugins are unsandboxed
   in-process Python and today get nothing); extend `plugin.yaml` with declared
   capabilities and diff declared-vs-registered at load; surface `allow_tool_
   override`/`ctx.llm` trust as install-time prompts.
4. **P1-15:** version the JSON-RPC handshake (N-1 compat), publish the existing
   `@fabric/shared` `JsonRpcGatewayClient` as the reference client, introduce
   scoped API tokens (read-only/operator/admin) honored across `web_server`,
   `api_server`, and the WS, and carve a documented `/api/v1/` facade (also
   serves the god-file goal).

**Done when:** `fabric plugins search` and `fabric packs install` work against a
hash-verified curated index; plugin installs are scanned + declared; and a third
party can build on a versioned contract with a scoped token.

### Spec P1-1 — Installable PWA + Web Push (the mobile answer)

**Problem.** Fabric has no mobile surface; OpenClaw ships native iOS/Android +
an installable PWA with VAPID Web Push. The dashboard is *already* responsive
(`useBelowBreakpoint(1024)`, stacked sheets) but has no manifest/service worker
(verified). "Does it have a phone app?" is the first mainstream question.

**Approach (web edge only — no core, no prompt-cache impact).** Add a manifest +
service worker to `web/`; add Web Push with VAPID over the existing dashboard
auth (ntfy adapter as the documented fallback). Use `getUserMedia` for
push-to-talk mic and camera capture streaming into the existing voice/vision
pipeline (answers VO camera/voice gaps at once). Document "Fabric on your phone =
PWA over Tailscale" as a first-class guide. Reconcile the cross-dimension mobile
contradiction explicitly: **messaging channels are the async mobile story; the
PWA is the interactive one; native is deferred/conceded.**

**Done when:** a user installs Fabric to their phone home screen, receives a push
approval, and talks/shows-camera to the agent — with zero native app.

### Spec P1-3 — Dollar spend caps (budget enforcement)

**Problem.** Fabric computes per-session `estimated_cost_usd` with provenance but
**nothing enforces a limit** — iteration budgets bound calls, not dollars.
ClawRouter does pre-request reservation against monthly budgets, and cost is
OpenClaw's loudest criticism, so this is the one hole in Fabric's strongest
positioning asset.

**Approach (CLI + status, no core tool).** A budget guard consuming the existing
`CostResult` stream (`agent/usage_pricing.py`, `agent/turn_finalizer.py`):
per-session and per-day USD caps in `config.yaml` (`agent.budget`), pause-with-
grace-turn semantics mirroring `iteration_budget`'s grace call, conservative
enforcement when `cost_status` is estimated/unknown, `included` subscription
routes exempt. Surface via `fabric budget` + `/usage`. Optional follow-on:
admin-key (OpenAI/Anthropic org cost) reconciliation to convert estimates to
actuals.

**Done when:** an agent pauses at a configured USD ceiling instead of running
unbounded, and `fabric budget` reports spend vs cap.

### Spec P1-4 — Proactive Heartbeat (ambient check-ins)

**Problem.** OpenClaw's marquee assistant behavior is the Heartbeat: periodic
main-session turns driven by a `HEARTBEAT.md` tasks block that short-circuits
the model call when nothing is due. Fabric has only reactive cron and liveness
tickers — no proactive loop.

**Approach (Footprint Ladder: CLI + skill, no new core loop).** A `HEARTBEAT.md`
tasks file + a `fabric heartbeat` command that drives one recurring cron job
attached to the main session (reuse the existing scheduler, `attach_to_session`,
and `context_from`). Inject only due tasks; short-circuit the model call when
nothing is due (protects spend *and* the prompt cache). No mid-context splice —
results re-enter via the existing cache-safe fresh-idle-turn rail.

**Done when:** Fabric, on its own schedule, batches due tasks into the user's
main conversation and stays silent (and free) when nothing is due.

### Spec P1-5/P1-6/P1-7 — Prove the security & reliability posture

**Problem.** Three credibility gaps for a security-positioned product:
(a) Fabric ships break-glass fail-open flags (`GATEWAY_ALLOW_ALL_USERS`,
`0.0.0.0` bind, always-authorized HomeAssistant/Webhook, loopback dashboard
skipping auth) with no linter — the *exact* misconfig class that mass-exposed
OpenClaw; (b) `SECURITY.md`/`CONTRIBUTING.md` reference a `supply-chain-audit.yml`
that **does not exist** (verified: only CONTRIBUTING names it; the workflow is
absent); (c) the ~39.7k-function pytest suite **never runs in CI**.

**Approach.**
1. **P1-5:** extend `fabric doctor` with a "security posture" section
   enumerating the break-glass flags from live config and printing a loud
   warning on non-loopback-without-auth or any `*_ALLOW_ALL_USERS`. Optional
   24h-gated startup banner (like the advisory scanner, so prompt caching is
   untouched).
2. **P1-6:** add the missing CI workflow running `pip-audit`/OSV over the
   resolved venv on `pyproject.toml`/`lazy_deps.py` changes and on a schedule
   (reuse `security_audit.py`'s OSV path); add dependabot/renovate for SHA-pinned
   Actions. If on-demand-only is truly intended, delete the dangling doc
   references instead.
3. **P1-7:** run pytest in CI as a sharded nightly/full job separate from the
   fast PR gate; replace the hardcoded "~17k tests" in AGENTS.md with an
   audit-script-emitted count so it can't drift again.

**Done when:** a misconfigured exposure flag warns loudly; every dependency
change is CVE-scanned in CI; and there is a green "tests pass" signal adopters
can trust.

---

## 7. Confidence, caveats & method

- **Coverage.** 11 dimensions × (Fabric repo map + OpenClaw web research) →
  per-dimension comparison → adversarial verification → completeness critique.
  22 side-maps, 11 comparisons, 12 verification passes, 1 critic.
- **Verification.** 76 confirmed / 11 corrected / 3 plausible / 6 refuted on the
  sampled load-bearing claims. Material corrections are in Appendix B.
- **Known data caveat.** The *Deployment* comparison's OpenClaw input arrived as
  a placeholder in one run; its **Fabric-side** findings are verified against the
  repo, and its **OpenClaw-side** facts (signed installers, published releases)
  are cross-sourced from the Surfaces and Community dimensions and independently
  confirmed (Developer ID). Treat Deployment's Fabric weaknesses as solid and its
  head-to-head framing as reconciled, not raw.
- **OpenClaw naming.** OpenClaw was previously "Clawdbot"/"Moltbot"; component
  names referenced here (ClawRouter, ClawHub, Lobster/OpenProse, Heartbeat,
  Talk/Voice Wake, nodes, cloud workers, ClawHavoc) are from primary sources
  dated through 2026-07-17.
- **This is a strategy artifact, not published product docs.** It lives in
  `docs/` (internal), mirrors into `TODOS.md`, and should feed a GitHub
  Projects board.

---

## Appendix A — per-dimension detail pointers

Each dimension's full `fabric_ahead` / `openclaw_ahead` / `parity` lists and
per-gap `key_claims` were produced during analysis. The gaps are consolidated in
§4; the leads/parity are summarized in §1–§2. For any gap, the underlying
verifiable claims (tagged `[fabric]`/`[openclaw]`) are the falsifiable basis —
re-check those before acting if a recommendation looks expensive.

## Appendix B — verification corrections that changed a finding

Folded into §4/§6; recorded here for auditability.

1. **Inbound injection defenses are not zero.** Fabric already renders inbound
   channel metadata as untrusted via `gateway/session.py`
   `_format_untrusted_prompt_value`, and has `gateway/response_filters.py` +
   `_sanitize_gateway_final_response`. → P2-1 is *extend + document existing
   provenance tagging*, not build-from-scratch.
2. **A skill artifact-signature verifier already exists.** `agent/skill_
   distribution.py` implements a full Ed25519, TUF-style verifier
   (root→timestamp→snapshot→targets, sha256 tree/contract/eval binding). → the
   skill-signing gap (P2-31) is *activation of a dormant verifier*, not absence.
3. **The models.dev bundled snapshot may already exist.** Verification reports a
   `bundled-snapshot → disk cache → network → 60-min refresh` chain in
   `agent/models_dev.py`, contradicting the mapped "no bundled step." → P2-15 is
   **verify-first**; if present, downgrade to a docstring/doctor fix.
4. **`supply-chain-audit.yml` reference is narrower than mapped.** Only
   `CONTRIBUTING.md` (not `SECURITY.md` §4) names the workflow; the workflow is
   still absent. → P1-6 unchanged; wording corrected.
5. **OpenClaw signing posture is knowable and known.** OpenClaw's macOS app
   auto-selects a Developer ID — so P0-1 is a *confirmed competitive loss*, not
   "unknown."
6. **ClawHub scale confirmed.** ~3,200+ published skills with searchable
   publish/install — the marketplace network-effect gap (P0-4, P1-26) is real.
