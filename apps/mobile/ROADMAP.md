# Fabric Mobile parity roadmap

This roadmap turns Fabric Mobile from a protocol-complete development client
into a goal-driven product that first reaches, then exceeds, the current Claude
Mobile, Claude Code, Cowork, and Dispatch experience. It is a release contract:
each phase must be installable through internal TestFlight, carry an exact
change log and test script, and be verified on a physical iPhone before the next
phase starts.

The competitive baseline was refreshed on 2026-07-20 from Anthropic's public
product and support documentation. Re-check it at the start of every minor
version; product names and availability change faster than protocol contracts.

**Execution overlay.** The FMB-P0…P4 phases below define *what "shipped" means*.
The post-v1 capability program — turning the phone into a bidirectional **node**
the agent can reach through (camera, location, screen, health) rather than a
remote text box — is executed as small, independently shippable **loops** in
[`UPGRADE_PLAN.md`](UPGRADE_PLAN.md), against the journey-by-journey gap map in
[`JOURNEYS.md`](JOURNEYS.md) and the shared-spine architecture in
[`ARCHITECTURE.md`](ARCHITECTURE.md). The loops build FMB-P2…P4 scope; every one
of them satisfies the cross-phase gates in this file.

## Product model

Fabric should not make people choose among separate Chat, Code, Cowork, and
Dispatch products. A user gives Fabric one goal. Fabric shows where it will run,
what it is doing, when it needs attention, what it produced, and the evidence
that the outcome is complete. Chat remains available, but the durable object is
the goal rather than a scrolling transcript.

Every mobile goal has the same visible lifecycle:

1. **Goal** — the outcome, execution location, inputs, and safety mode.
2. **Plan** — a reviewable approach and any parallel workstreams.
3. **Run** — live progress, tools, agents, steering, and interruption.
4. **Attention** — approvals or questions tied to the exact current action.
5. **Outcome** — summary, files, code changes, tests, links, and next action.

## Release phases

### FMB-P0 — Reproducible beta foundation (`0.1.x`)

Purpose: make each TestFlight upload traceable to clean, reviewed source before
adding more product surface.

Acceptance:

- Xcode Cloud discovers an executable post-clone hook beside the selected Xcode
  project, and that hook generates the project from a clean checkout without
  modifying the tracked manifest. Release generation also rejects untracked or
  ignored files beneath the recursive app source root so the embedded revision
  describes every packaged Swift/resource input.
- The App Store bundle identifier is supplied explicitly by the protected
  release environment, never by a manual edit to the generated project.
- Every upload receives a unique positive build number from Xcode Cloud or an
  explicit local release value.
- GitHub CI executes the same project-generation script as Xcode Cloud and
  derives metadata assertions from the manifest rather than hard-coding them.
- Every release archive embeds the exact clean Git commit as
  `FabricSourceRevision`; it matches the merged `main` SHA recorded alongside
  the version/build, tester notes, test results, archive result, and internal
  TestFlight result in `IOS_RELEASES.md`.
- A physical-iPhone smoke pass covers launch, pairing, connect, session resume,
  prompt streaming, approval response, background/foreground recovery, and
  disconnect.

### FMB-P1 — Product foundation (`0.2.x`)

Purpose: replace the server-admin mental model with a premium, QR-first Fabric
home and make existing capability visible.

Scope:

- Branded launch/home surface based on the selected visual direction.
- Primary **Scan pairing QR** onboarding; manual URL and credentials live under
  Advanced setup.
- Human-readable secure-connection, Mac-online, connecting, offline, expired-
  auth, and recovery states.
- One obvious goal composer plus running and recent work.
- Existing sessions, steering, approvals, background work, commands, processes,
  and live view become discoverable without an overflow-menu scavenger hunt.
- Deterministic light/dark/running/typed-enabled/loading/empty/error/offline screenshot fixtures,
  Dynamic Type checks, VoiceOver navigation checks, and 44-point targets.

Exit evidence:

- Screenshot comparison against the selected source direction at the same
  simulator viewport.
- Swift tests plus a physical-device QR and reconnect pass.
- Internal TestFlight tester notes name every changed state and recovery path.

### FMB-P2 — Claude Mobile control parity (`0.3.x`)

Purpose: make the phone a complete daily client rather than a remote text box.

Scope:

- Searchable, named, pinnable sessions and project grouping.
- Rich Markdown, code, diff, image, PDF, and generated-file presentation.
- Photo/file attachments with resumable upload and explicit remote destination.
- Push notifications for completion and action-required events, with redacted
  lock-screen copy and exact in-app deep links.
- Polished streaming/tool summaries, reconnection, offline handling, downloads,
  and share-sheet input.
- Voice dispatch and camera-to-goal capture where the device contract is clear.

### FMB-P3 — Code, Cowork, and Dispatch parity (`0.4.x`)

Purpose: expose long-running autonomous work and coding workflows as first-
class mobile goals.

Scope:

- Goal-to-plan review, execution timeline, subagent/workstream status, steering,
  pause, and cancellation.
- Persistent Dispatch inbox with summary-first outcome cards linked to detailed
  runs.
- Files, artifacts, projects, schedules, recurring routines, and deep links.
- Repository/worktree, branch, commit, pull request, CI, review, merge, deploy,
  and rollback status for coding goals.
- Manual and automatic approval modes with non-bypassable destructive-action
  gates.

### FMB-P4 — Better than Claude (`0.5.x`)

Purpose: lead on transparent multi-agent execution rather than cloning another
chat product.

Scope:

- One unified mission-control model across general, code, browser, computer-use,
  and specialist work.
- Local-first agent mesh with explicit execution location, cross-provider model
  routing, scoped device enrollment, revocation, and optional cloud workers.
- Proof-of-work ledger: plan, agents, tool actions, changed files, checkpoints,
  tests, approvals, artifacts, costs, and final evidence.
- Multi-agent orchestration from mobile: split workstreams, dependencies,
  budgets, compare outcomes, redirect one branch, and merge the winner.
- Release cockpit from goal through tests, review, commit, CI, TestFlight,
  feedback, and rollback.
- Reusable goal recipes that preserve safety and verification contracts.

## Cross-phase gates

No phase is complete because a simulator build launches. Every release needs:

- protocol, unit, and integration checks appropriate to the changed scope;
- same-state light/dark screenshots and comparison against the chosen source;
- Dynamic Type, VoiceOver, contrast, long-content, and touch-target checks;
- a physical-iPhone smoke pass;
- a clean branch, coherent commits, reviewed PR, green required checks, and a
  merge to the protected base branch;
- an archive whose packaged `FabricSourceRevision` matches the exact merged
  SHA, a unique build number, internal TestFlight processing, and tester
  confirmation;
- an honest entry in `IOS_RELEASES.md`, including known gaps and rollback path.

## Current state

Release-state audit (2026-07-21): Xcode Cloud's protected `Default` workflow
targets merged `main`, the `Fabric` scheme, and
`apps/mobile/ios/FabricMobile.xcodeproj`; it supplies the protected release
bundle identifier and distributes successful archives to the internal
TestFlight `beta` group. The local signing/profile audit associates that bundle
with the configured release signing team. The physical
iPhone currently reports TestFlight build `0.2.0 (15)`. Its apparent mapping to
current `origin/main` at `c5343180` is consistent with first-parent build
history, but remains an inference until archive or workflow provenance is
captured.

| Phase | State | Evidence / next gate |
| --- | --- | --- |
| FMB-P0 | Internal TestFlight foundation verified; phase acceptance open | PR #66 merged as `00c8c2f0`; the release foundation then produced `0.2.0 (4)`, `(5)`, and `(6)` from reviewed merged source. All three archived, uploaded, processed to **Testing**, and reached the internal `beta` group. Independent signed-archive provenance extraction and the required physical-iPhone behavior smoke remain. |
| FMB-P1 | `0.2.0` internal candidates; `0.2.1` local candidate | PR #68 merged as `6c9e0341`, and the pairing-reliability slice merged through PR #71 as `9651091a`; build 6 is the last entry with an exact recorded source. The broader `0.2.1` candidate adds branded QR-first onboarding, verified/legacy-safe connection review, conversation-first Home, Home/Sessions/Settings, redacted diagnostics, rich bounded chat activity, capability-gated controls, and fail-closed recovery for upgraded saved remote-HTTP token gateways that must re-pair through trusted HTTPS or loopback. Exact-head tests, hosted checks, physical-device validation, merged-SHA packaging, archive/upload, and internal tester confirmation remain. Nothing in this row claims a shipped `0.2.1` build. |
| FMB-P2 | In progress — local client portions of loops 1–4 | The `0.2.1` candidate implements the existing-gateway activation portion of pairing reliability, the Settings/diagnostics shell, isolated per-gateway gated sessions with targeted/full-device offboarding, reasoning/tool/approval presentation, and a protected read-only last-known Chat transcript when authoritative resume fails. The complete rich document/artifact set, an outbound queue/server-authoritative offline state (the remainder of loop 4), future grant/node controls, and push/cross-surface approvals (loop 8) remain. Manifest governance is on `main`; none of these candidate changes advances the TestFlight support tier. |
| FMB-P3 | Planned — loops 0, 5–7, 9 | The bidirectional-node capability program: manifest governance, the one consent+grant+ledger substrate + node enrollment, the `node.invoke` `camera.capture` magic moment, the Trust Center, then breadth. Durable Work stays advertised only after its full client/server contract is verified end-to-end. |
| FMB-P4 | Planned | Begins after parity evidence, not feature-count claims. The mission-control, proof-of-work ledger, and multi-agent surfaces reuse the same spine (`ARCHITECTURE.md`). |
