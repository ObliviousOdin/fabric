# Fabric Mobile — loop-driven upgrade plan

This is the execution plan for the major iOS upgrade: turning Fabric Mobile from
a protocol-complete remote **text** client into a bidirectional **node** the
agent can reach through — the phone as its eyes, ears, and location sensor —
without ever weakening the fail-closed security contract that makes the current
app trustworthy.

It is driven by two companion documents and executed as a series of small,
independently shippable **loops**:

- [`JOURNEYS.md`](JOURNEYS.md) — the 14 user journeys mapped to current code,
  with severity-rated gaps. *(What's missing.)*
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — the one spine that closes those gaps,
  with exact wire contracts and fail-closed rules. *(How it's built.)*

It overlays, and does not replace, the phase contract in [`ROADMAP.md`](ROADMAP.md)
(FMB-P0…P4) or the first-release gates in [`PRODUCTION.md`](PRODUCTION.md). The
FMB phases say *what "shipped" means*; the loops below say *what order to build
it and how each one lands safely*.

---

## 1. How this plan is executed — the loop protocol

Each loop delivers **one** vertical slice that can independently pass every
release gate. An autonomous (or human) build loop runs the same eight steps
every iteration:

0. **Sync.** `git fetch origin && git rebase origin/main` so the branch always
   sits on top of the latest `main`. Abort the iteration if the rebase touches
   the `ios` job block of `.github/workflows/mobile.yml` (resolve by keeping
   `main`'s version — see §2).
1. **Select** the next slice from the backlog (§4): the smallest vertical that
   (a) stays inside `apps/mobile/ios` (+ `apps/mobile/contracts` and
   `apps/shared` for a mirrored contract), (b) touches none of another in-flight
   PR's files, and (c) can pass all gates on its own. Prefer a slice whose proof
   does not depend on the PR-skipped iOS CI job.
2. **Build.** Implement in Swift under `Fabric/`. If new files, contract
   fixtures, or `Info.plist` keys are needed, edit **`project.yml`** (never the
   `pbxproj` or `Info.plist` by hand), then regenerate with the **pinned**
   XcodeGen 2.46.0 via `ci_scripts/ci_post_clone.sh` and commit the regenerated
   `FabricMobile.xcodeproj` + `Fabric/Info.plist` alongside the source.
3. **Verify locally** — *this is the real gate* (see §2): the regenerated
   `pbxproj`/`Info.plist` byte-match (`git diff --exit-code`);
   `tests/scripts/test_ios_project_generation.py`; `xcodebuild … test` on a
   simulator; the unsigned Release build; the metadata + PrivacyInfo audit; and
   the shared contract fixture also passing in `apps/shared` (TS) so Swift and TS
   agree. Capture light/dark + state-matrix screenshots and run the accessibility
   checklist.
4. **Gate.** Run the per-slice release-contract checklist (§3). Any red → back to
   step 2. Never proceed on partial evidence (**no simulated surfaces**).
5. **Ship.** Clean commits → PR. PR checks show `android` + `web` green and `ios`
   **skipped** — that is expected after PR #78; do not read the skip as failure
   or a reason to weaken the gate. Land after review + green required checks,
   then confirm the post-merge push-to-`main` `ios` job goes green (the tripwire).
   A red tripwire is a P0 regression on the protected branch — hotfix forward.
6. **Record.** Append an honest `IOS_RELEASES.md` entry **only** when a real
   archive/upload happened, with the merged SHA matching the packaged
   `FabricSourceRevision`; otherwise mark the slice "local candidate verified",
   never "shipped". A simulator build never advances the support tier.
7. **Capability invariant check.** No slice advertises a capability the gateway
   does not provide, and no slice flips Durable Work on. Re-assert the fail-closed
   gate in **both** the UI control and its action handler.

**Loop granularity.** A loop is one PR-sized slice, not a whole epic. The larger
epics below (the consent/grant substrate, `node.invoke`, Trust Center, push) are
each delivered as *several* loops — a contract-fixture loop, a client-model loop,
a UI loop — so no single PR is unreviewable and every merge keeps `main`
shippable.

---

## 2. Merge-safety reality (current branch and how code lands)

The capability-manifest spine (Loop 0) is now on `main` through PR #81. The
`0.2.1` branch builds only on that advertised baseline; it does not turn on
Durable Work or any future feature family.

Two consequences shape every future loop:

- **Preserve the `ios` pull-request skip in `mobile.yml`.** A product-surface
  slice has no reason to change that job guard. If a later CI-specific slice
  needs a contract-fixture path or PrivacyInfo audit line, keep the edit focused
  on that consumer and independently review the workflow diff.
- **iOS gets zero PR signal.** After `#78`, the entire iOS validation chain —
  XcodeGen regeneration, the `pbxproj`/`Info.plist` byte-check,
  `test_ios_project_generation.py`, `xcodebuild test`, the Release build, and the
  metadata/PrivacyInfo audit — runs **only** in the `ios` job, which is skipped
  on PRs and runs on push to `main`. So **the local macOS build loop is the
  authoritative gate**; the push-to-`main` `ios` job is a tripwire, not a safety
  net. iOS changes must be correct-by-construction.

**Why this plan's first artifacts were docs.** The original planning branch was
authored without a Swift/Xcode validation host, so it deliberately landed no
half-built native surface. The current `0.2.1` candidate is running on a macOS
Xcode 26.5 loop with pinned XcodeGen regeneration, simulator and Release gates,
visual evidence, and a physical-device gate. It still is not "shipped": exact
merged-SHA packaging, the post-merge `main` iOS tripwire, a fresh confirmation
that the already configured protected Xcode Cloud workflow still targets
merged `main`, archive/upload, and an internal TestFlight install remain.

**Files a code loop may touch:** `apps/mobile/ios/**`, `apps/mobile/contracts/**`,
`apps/shared/**` (for a mirrored contract), and these docs. A product loop does
not change the `ios` job guard; a CI-contract loop must declare and review that
scope explicitly.

---

## 3. Per-slice release-contract gate checklist

Distilled from `ROADMAP.md` cross-phase gates + `PRODUCTION.md`. Every loop
satisfies all of it before "done":

- [ ] **Protocol/unit/integration** for the changed scope: `FabricTests` green;
      every new RPC implemented by a client has a shared JSON contract fixture
      in `apps/mobile/contracts` (wired into `project.yml` for Swift consumers),
      and every client that implements the RPC proves parity against those same
      bytes; capability tests prove negotiation precedes session calls, `-32601`
      is the only legacy path, unknown additive fields stay compatible, and each
      control is gated by its exact advertised method.
- [ ] **Screenshots**: same-state **light and dark** fixtures vs. the chosen
      source, across the full matrix — running / typed-enabled / loading / empty
      / error / offline / permission-denied — at AX XXXL and on a small device.
- [ ] **Accessibility**: Dynamic Type reflow, VoiceOver order + announcements,
      increased contrast, Reduce Motion, ≥ 44 pt targets; long/emoji/CJK/RTL
      content does not clip controls.
- [ ] **Physical-iPhone smoke pass** on a currently-supported device.
- [ ] **Build/release**: clean checkout regenerates + tests the project; committed
      `pbxproj` + `Info.plist` byte-match XcodeGen; `test_ios_project_generation.py`
      passes; unsigned Release build + metadata + PrivacyInfo audit pass.
- [ ] **Branch hygiene**: clean branch → coherent commits → reviewed PR → green
      **required** checks (`android` + `web`; `ios` is the push-to-`main` run
      plus local macOS evidence) → merge to the protected base.
- [ ] **Archive** (only when actually releasing): packaged `FabricSourceRevision`
      == the exact merged SHA, unique build number, TestFlight processing, real
      internal-tester confirmation.
- [ ] **Honest `IOS_RELEASES.md`** entry: merged SHA, packaged revision, what
      changed, automated + device checks, archive/upload result, tester result,
      known gaps, rollback build/commit.
- [ ] **Fail-closed posture preserved**: no capability advertised the server
      lacks; UI control **and** handler both gate; capability state
      connection-scoped, never persisted; Durable Work stays dark.

---

## 4. The loop backlog

Ordered by value × confidence, honoring dependencies. Client-only loops ship
first (fast, high-confidence, no coordination); the differentiating epics come
after the substrate they share is set. "Server" means the gateway must add
methods (coordinate the manifest change first — Loop 0).

| Loop | Slice | Candidate status | Journeys | Server? | Depends on |
| --- | --- | --- | --- | --- | --- |
| **0** | Capability-manifest + typed-error governance | Complete on `main` (#81) | all | schema | — |
| **1** | Pairing reliability bundle | Partially implemented in `0.2.1` | 1, 3 | no | 0 |
| **2** | Settings shell + Forget-Gateway purge + diagnostics + gated re-auth | Implemented in `0.2.1` candidate; release gates pending | 13, 14 | no | — |
| **3** | Daily-chat rich rendering | Partially implemented in `0.2.1` | 4 | no | — |
| **4** | Offline resilience (transcript cache + outbound queue) | Partially implemented in `0.2.1` | 9 | no | — |
| **5** | Consent + grant + ledger substrate + node enrollment | Planned | 2, 3, 6, 7 | yes | 0 |
| **6** | `node.invoke` thin vertical + `camera.capture` magic moment | Planned | 7 | yes | 5 |
| **7** | Trust Center surface (audit + grants + nodes) | Planned | 2, 7, 13 | yes | 5, 2 |
| **8** | Push transport + notifications consent + cross-surface approvals | Planned | 2, 6 | yes | 5 |
| **9** | Breadth: more providers, files, Talk Mode/Listen, share ext., Watch, guided Tailscale | Planned | 5, 8, 11, 12 | mixed | 5, 6, 8 |

### Loop 0 — Capability-manifest & typed-error governance  *(schema; highest leverage)*

Pin, once, how every server-backed family is advertised so the single fail-closed
subset check does not fragment. Define the feature-key registry and typed-error
taxonomy from `ARCHITECTURE.md` §0 and §7, add the generic
`supportsGatewayFeature` gate modeled on `supportsDurableWork` (named convenience
gates arrive with their consuming loops), and land the shared contract
**fixtures** for the new feature keys (parsed, asserted compatible, but not yet
advertised by any live gateway). Cheap on the client, unblocks all server work.
**Exit:** capability-registry fixtures pass in Swift + TS + Kotlin; the future
trust/node/error corpora pass in their canonical TypeScript reference until
native consumers land; negotiation tests prove each new key is
additive-optional and fail-closed; no live manifest advertises them yet.

> **Status:** complete on `main` through PR #81. Landed TDD-verified: the governance
> registry (`gateway-feature-registry-v1.json`), the 8 new optional families +
> flag-only `scoped_grants` + `supportsGatewayFeature` in the TS reference, the
> `fabric-trust-v1` and `fabric-node-v1` fixture corpora with their TS parsers,
> and the typed-error taxonomy (all green: `apps/shared` vitest + tsc,
> `apps/mobile-web` vitest + tsc). Swift and Kotlin capability mirrors are on
> the branch; Kotlin is verified by the PR `android` job, while the regenerated
> Xcode project, 166 XCTest cases, unsigned Release build, metadata, and privacy
> audit were verified on macOS before merge.

### Loop 1 — Pairing reliability bundle  *(client-only; fastest visible win)*

The named opportunity (a) and the current critical dead-ends. Deliver
`route-diagnosis` (actionable "you're off the tailnet / wrong network / host
offline / TLS untrusted" from a real reachability probe that never substitutes
for the capability handshake), a robust QR scanner (permission-denied state,
torch, reticle, manual fallback), the first-run explainer, and the "do you
already have a Gateway?" branch. All client-only. **Exit:** a scanned-but-
unreachable gateway produces guidance, not a raw error; first-run teaches the
node model; full state matrix + accessibility captured.

> **`0.2.1` candidate status:** the existing-gateway activation slice is
> implemented: branded QR-first entry, one pre-permission rationale,
> denied/restricted recovery, reticle/torch/manual fallback, bounded route/TLS/
> auth/contract diagnosis, and a negotiation-derived connection review. Guided
> installation for a user without a Gateway and secure node enrollment are not
> implemented, so this loop is not represented as fully shipped.

### Loop 2 — Settings shell + offboarding + diagnostics  *(client-only; foundational)*

Build the Settings home that the Trust Center and consent center will live in:
server list, per-server detail/re-pair, a permission inventory, and offboarding.
Complete the Forget-Gateway purge (clear gated cookies + a verified full local
reset), add a diagnostics screen + persistent status chip + clear-cache, and make
gated reconnect prompt a graceful re-auth on an expired cookie. **Exit:** a full
local reset is verifiable; expired-cookie reconnect recovers cleanly.

> **`0.2.1` candidate status:** the Settings shell, permission inventory,
> redacted diagnostics, switch/re-pair/forget/reset confirmations, full-device
> local reset, presentation-cache recovery, persistent connection banner, and
> expired-cookie re-auth path are implemented. Each saved gateway + endpoint has
> an isolated ephemeral cookie jar; public discovery is cookie-disabled; auth
> attempts are generation-fenced; targeted Forget/disconnect invalidates only
> that gateway; and full reset invalidates all jars. Loop 2 is complete in the
> candidate source but does not count as shipped until the release gates pass.

### Loop 3 — Daily-chat rich rendering  *(client-only; most-used surface)*

Make the phone a real daily client (Journey 4): render streamed reasoning as a
collapsible per-turn Thinking block (with a VoiceOver announcement policy that
does not spam), persistent per-tool activity cards, colored unified diffs, GFM
tables, and lightweight code highlighting. No server dependency. **Exit:**
reasoning + tool history are legible and accessible; diff/table fixtures pass in
both themes.

> **`0.2.1` candidate status:** bounded/redacted reasoning and persistent tool
> cards, diff coloring, approval context/choices, and non-spamming accessibility
> announcements are implemented. GFM table layout and language-aware code
> highlighting remain, so Loop 3 remains partial.

### Loop 4 — Offline resilience  *(client-only)*

Close the dropped-send data loss (Journey 9): a file-protected, presentation-only
transcript cache and a bounded (50/session, 48 h), FIFO, definitely-unsent-only
outbound queue that flushes in order via the **gated** `prompt.submit` — never a
blind retry, per `PRODUCTION.md`. Establishes the offline contract that later
side-effecting surfaces reuse via idempotent Durable Work. **Exit:** last-known
transcript reads offline with controls disabled; queued sends flush in order and
never cross-flush across servers.

> **`0.2.1` candidate status:** Home and Chat have separate protected, bounded
> presentation caches. Chat can show the last-known transcript read-only when
> authoritative resume fails; neither cache becomes server-authoritative work
> state. There is no outbound queue, so Loop 4 remains partial.

### Loop 5 — Consent + grant + ledger substrate + node enrollment  *(server; the pivot)*

The coordinated investment everything differentiating depends on. Build the one
`ConsentGrantLedger` (JIT scoped grants, per-gateway, server-authoritative audit,
`grant.list/create/revoke` with idempotency + optimistic version) and the single
node-enrollment lifecycle (`enroll → pending-approval → active → revoke`,
Secure-Enclave device key, Full/Limited scope, OAuth browser branch). Filling the
enrollment stub also completes the Journey 3 approval loop and the Journey 6
scoped-grant menu. **Exit:** a device enrolls with a scope and appears as a
connected node; a JIT grant is minted, reviewed, and revoked; the audit stream
reconciles as one server-authoritative record.

### Loop 6 — `node.invoke` thin vertical + `camera.capture`  *(server; peak differentiator)*

The named opportunity (b) and the delight peak. A deliberately narrow vertical
over Loop 5: the `node.announce/result/reject` transport for exactly **one**
capability, a one-shot foreground consent sheet minting a temporary camera-only
grant, one required audit entry, the provider seam with a CI fake compiled out of
release, and a fail-closed gate that says "this gateway can't request your
camera" when `node_invoke` + `camera.capture` are not both advertised. This is
the forcing function that proves the substrate. **Exit:** "Take a photo for me"
works end-to-end on a device; every fail-closed rule in `ARCHITECTURE.md` §3 is
tested; nothing ships a simulated frame.

### Loop 7 — Trust Center surface  *(server; named opportunity c)*

Make the substrate visible and revocable: posture (root-equivalent even when
green), grants with one-tap revoke, connected nodes with revoke, and the audit
stream with a kill switch. Reuses Loop 5's ledger/grants + enrollment; adds
`trust.audit.list`, `node.list/revoke`. Lives in the Loop 2 shell. **Exit:** a
user can see and revoke every standing grant and connected node from the phone.

### Loop 8 — Push transport + notifications + cross-surface approvals  *(server)*

The coordinated gateway notifier: `push.register_device` lifecycle, redacted
deep-link payloads, silent-push-to-wake for background `node.invoke`/approvals,
and attention badges + deep links + "answered elsewhere" reconciliation on
Home/Sessions. Depends on enrollment (Loop 5) and the manifest (Loop 0).
**Exit:** an approval that arrives while backgrounded wakes the app to the exact
interaction; lock-screen copy is redacted; first-answer-wins holds across
surfaces.

### Loop 9 — Breadth & long tail  *(mixed)*

Once the substrate, magic moment, Trust Center, and push are proven, generalize:
the remaining `node.invoke` providers (`photo.pick`, `location.oneshot`,
`screen.snapshot`, `canvas.render`, `health.summary`, `contacts/calendar.read`),
the unified inbound-artifact/Files/`fs.read` client with Quick Look, Talk
Mode/Listen over one `AVAudioSession` owner, the Share Sheet extension, guided
Tailscale, and the Apple Watch companion. Each generalizes an existing seam, so
marginal risk is low; spread across FMB-P3/P4.

---

## 5. The first magic moment

**"Take a photo for me"** — `camera.capture` over a deliberately thin
`node.invoke` vertical (Loop 6). It is the decisive pick: a self-hosted agent
reaching *through the phone's camera* is something no pure remote-control client
does, and it viscerally teaches the phone-is-a-node model the onboarding needs.

Do **not** build the full nine-provider framework first. Scope it to exactly one
bidirectional method, a single one-shot foreground consent that mints a
temporary camera-only grant, one required audit-ledger entry, and a fail-closed
gate — that thin slice carves the minimum `ConsentGrantLedger` + `node.invoke`
transport + enrollment path, which then generalizes to every other sensor. It is
not the earliest thing that can ship, but it is the single moment worth building
the substrate for — which is exactly why the substrate (Loops 0 and 5) is
sequenced ahead of it.

---

## 6. Sequencing at a glance

```
Loop 0 (manifest) ─┬─────────────────────────────► Loop 5 (substrate + enrollment)
                   │                                   │
Loop 1 (pairing)   │   Loop 2 (settings shell)         ├─► Loop 6 (node.invoke + camera) ★ magic moment
Loop 3 (rich chat) │   Loop 4 (offline)                ├─► Loop 7 (Trust Center)   ◄── needs Loop 2 shell
   client-only, ship in parallel, no server work       ├─► Loop 8 (push + approvals)
                                                        └─► Loop 9 (breadth: providers, files, voice, share, Watch)
```

Client-only loops (1–4) ship first and keep momentum while the manifest (0) and
substrate (5) — the coordinated server work — are negotiated. Nothing
differentiating is blocked on anything except the substrate it genuinely shares,
and every loop leaves `main` shippable and the fail-closed contract intact.
