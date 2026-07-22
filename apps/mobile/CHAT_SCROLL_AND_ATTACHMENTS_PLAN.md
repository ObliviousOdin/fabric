# Fabric Mobile — plan: chat scroll preservation (#90) & chat attachments (#89)

This is the implementation plan for the two iOS issues filed on 2026-07-22:

- **#90 — Preserve user scroll position during streaming responses** *(client-only,
  one file; **implemented in the PR that carries this plan**).*
- **#89 — Support screenshot, photo, and file attachments in chat** *(large,
  server-touching, shared-surface; **this document is the plan, not the code**).*

It is written against the loop protocol in [`UPGRADE_PLAN.md`](UPGRADE_PLAN.md),
the gap map in [`JOURNEYS.md`](JOURNEYS.md), the spine in
[`ARCHITECTURE.md`](ARCHITECTURE.md), the phase contract in
[`ROADMAP.md`](ROADMAP.md), and the cross-agent contract in
[`../../AGENT_GUARDRAILS.md`](../../AGENT_GUARDRAILS.md). Line numbers are current
at authoring time and are anchors, not guarantees.

---

## 0. The one constraint that shapes everything: iOS gets no PR signal

Per `AGENT_GUARDRAILS.md` §4.2 and `UPGRADE_PLAN.md` §2, the entire iOS validation
chain — XcodeGen regeneration, the `pbxproj`/`Info.plist` byte-check,
`test_ios_project_generation.py`, `xcodebuild test`, the Release build, and the
metadata/privacy audit — runs **only** in the `ios` job of
`.github/workflows/mobile.yml`, which is **skipped on pull requests** and runs on
push to `main`. So:

- The authoritative gate for any Swift change is a **local macOS build loop**
  (`xcodegen` 2.46.0 pinned + `xcodebuild test` on a simulator). The push-to-`main`
  `ios` job is a **tripwire**, not a safety net.
- iOS changes must be **correct-by-construction**, and a green PR (with `ios`
  skipped, `android` + `web` green) is **not** proof the native build works.

Both issues below are scoped and sequenced with that in mind: #90 concentrates
its logic in a pure, unit-testable value type so the untestable-here SwiftUI
wiring is thin; #89 is decomposed so its riskiest pieces (contracts, transport)
land as small loops whose proof does **not** depend on the PR-skipped `ios` job.

---

## 1. Issue #90 — Preserve scroll position during streaming *(delivered here)*

### 1.1 Root cause (grounded)

The transcript owns scrolling in `apps/mobile/ios/Fabric/Features/Chat/ChatView.swift`,
in `TranscriptView`. There are exactly two auto-scroll call sites, both
**unconditional**:

1. `onChange(of: messages)` → `proxy.scrollTo(lastId, anchor: .bottom)` — runs on
   every mutation of the `messages` array. Each `message.delta` re-assigns the
   streaming row in place (`ChatViewModel.foldIntoStreamingAssistant`), so this
   fires on **every token** and snaps a reading user back to the bottom.
2. The completed row's rich-layout follow-up: `onRichLayoutReady` →
   `proxy.scrollTo(message.id, anchor: .bottom)`, fired once a completed row's
   cached Markdown document has a measured height
   (`RichTranscriptHeightPreferenceKey`).

There was **no** bottom-detection, no follow state, and no "jump to latest"
control anywhere in the app (verified by a full scan for
`scrollTo`/`ScrollViewReader`/`scrollPosition`/`defaultScrollAnchor`).

> The issue body cites "around lines 514–517"; that was stale. The live logic is
> in `TranscriptView` (the `onChange`/`onRichLayoutReady` sites noted above).

### 1.2 Design

A pure, `Equatable` **`TranscriptFollowState`** owns the decision of whether to
chase the newest token. It is extracted from the view so every transition is
deterministically unit-tested without a live scroll view (the same seam the repo
already uses for `AssistantTurnReducer` and `ChatPresentationCache`). The view
feeds it measured geometry and explicit reader intent:

| Signal | Source in the view | Effect on state |
| --- | --- | --- |
| Transcript grew (delta / complete / new row) | `onChange(of: messages)` | `transcriptDidGrow(newUserTurn:)` → scroll only while following; a **fresh user turn always re-engages**; growth while disengaged is remembered as "pending below" |
| Completed row rich relayout | `onRichLayoutReady` | `richLayoutReadyShouldScroll()` → follows **only** when engaged |
| Reader dragged the transcript | `.simultaneousGesture(DragGesture)` | `readerDidDrag(distanceFromBottom:)` → disengages when pulled past the tolerance (explicit, **timing-free**) |
| Viewport settled at a measured distance | `GeometryReader` preferences (content maxY vs. viewport height) | `viewportDidSettle(distanceFromBottom:)` → **re-engages at the bottom only; never disengages**, so streaming growth below a scrolled-up reader can't flip follow back on |
| "Jump to latest" tapped | overlay button | `jumpToLatest()` → re-engage + scroll |

Key invariants that make it robust without a fragile heuristic:

- **Disengage is driven by an explicit drag**, never by content growth or a
  delay. During active streaming the transcript grows constantly; only a real
  user drag past `bottomTolerance` (24 pt) stops follow.
- **Re-engage is driven by geometry** (distance ≤ tolerance) — reached either by
  the user scrolling back to the bottom or by our own snap — so momentum flicks
  resolve correctly and content growth never re-arms follow.
- **`showsJumpToLatest == !isFollowing && hasPendingContentBelow`**, matching the
  acceptance criterion "away from the bottom **and** newer content exists".
- iOS 17.0 deployment target ⇒ no iOS-18 `onScrollGeometryChange`; the
  content-maxY-vs-viewport-height `GeometryReader` pattern is used instead.

### 1.3 What changed

- `apps/mobile/ios/Fabric/Features/Chat/ChatView.swift` — replaced `TranscriptView`
  with the follow-gated version; added `TranscriptFollowState`, two
  `PreferenceKey`s, and a `JumpToLatestButton` (44-pt target, VoiceOver
  label/hint). **No public API change** (`TranscriptView(messages:)` is
  unchanged, so the `#if DEBUG` fixture and the existing hosted scroll test still
  compile against it).
- `apps/mobile/ios/FabricTests/ChatExperienceTests.swift` — added 9 unit tests
  for `TranscriptFollowState` covering: engaged-by-default, manual disengage +
  delta hold, tolerance boundary, rich-layout gating, return-to-bottom
  re-engage, growth-drift-never-re-engages, jump-to-latest, new-user-turn
  re-engage, and affordance visibility.

**No new files, no `project.yml` change** — deliberately. XcodeGen enumerates
each source file into the committed `pbxproj`; adding a file would force a
regeneration (and `xcodegen` is not available off a Mac). Editing existing
tracked files leaves the generated project byte-identical, so the `main`
`pbxproj` byte-check stays green.

### 1.4 Acceptance-criteria mapping

| #90 acceptance criterion | Where satisfied |
| --- | --- |
| Scroll up mid-stream and keep reading; deltas don't move the viewport | `readerDidDrag` disengages; `transcriptDidGrow` returns `.hold` when disengaged |
| Still follows the bottom smoothly when not scrolled away | `transcriptDidGrow` returns `.scrollToLatest` while following |
| Manual up-scroll disengages without a fragile timing heuristic | `DragGesture` + explicit tolerance; no delay/timer |
| Accessible "Jump to latest" appears when away + newer content exists | `showsJumpToLatest` + `JumpToLatestButton` (label + hint + 44-pt) |
| Tapping it scrolls to newest and resumes follow | `jumpToLatest()` + animated `scrollTo` |
| Rich Markdown relayout doesn't steal position when disengaged | `richLayoutReadyShouldScroll()` gate |
| Sending a new user message returns to the latest turn | `newUserTurn` branch in `transcriptDidGrow` (detected via the newest `.user` message id) |
| Dynamic Type / VoiceOver / reconnect / rotation | geometry recomputes on layout; button is a real accessible `Button`; follow defaults engaged on (re)mount |
| Automated tests cover follow / disengage / deltas / rich completion / resumption | `ChatExperienceTests` (see §1.3) |

### 1.5 Verification status (honest)

- **Verified (reasoning + Linux-runnable):** the pure-state logic is proven by
  the new XCTest cases; the existing hosted scroll test
  (`ResumeHistoryTests.testCompletingTallRichReplyKeepsTranscriptAtBottomAfterRelayout`)
  exercises a fresh, engaged, never-dragged transcript, for which the new code is
  behaviourally identical to the old unconditional scroll (follow defaults
  engaged, `viewportDidSettle` never disengages, the untouched `DragGesture`
  cannot fire) — so it should stay green.
- **NOT verified here:** `xcodebuild test` and the on-device gestural/VoiceOver
  behaviour — this environment is Linux with no Xcode, and the `ios` job is
  PR-skipped. Requires the local macOS loop before merge (§0). The
  `GeometryReader`/`DragGesture`/`ScrollViewReader` wiring in particular must be
  exercised on a simulator + physical device.

---

## 2. Issue #89 — Attachments in chat *(plan only)*

### 2.1 Current state (grounded)

The **outbound `files` capability is fully declared and gated on every layer,
but has no client consumer**:

- Swift: `GatewayAPI.swift` — `gatewayFeatureMethods["files"] = ["image.attach_bytes",
  "pdf.attach", "file.attach"]`; feature/method negotiation via
  `GatewayCapabilityNegotiation.supportsGatewayFeature(_:)` /
  `supportsGatewayMethod(_:)`.
- Shared TS spine: `apps/shared/src/gateway-capabilities.ts` —
  `GATEWAY_FEATURE_METHODS.files = ["image.attach_bytes", "pdf.attach",
  "file.attach"]` (mirrored in the Android `GatewayApi.kt`).
- Wire contracts: `apps/mobile/contracts/gateway-feature-registry-v1.json` and the
  `gateway-capabilities-*.json` corpus already carry the `files` family and its
  three methods.
- **No consumer:** the composer (`ChatComposerBar` in `ChatView.swift`) is
  text-only; the send path `ChatViewModel.send` → `submitPrompt` →
  `GatewayAPI.submitPrompt` emits `prompt.submit` with `["session_id", "text"]`
  only; there is **no** blob/upload/resumable/multipart client anywhere in the
  app (only inbound Live-View screenshot decoding exists).

Docs that frame this work: `ROADMAP.md` FMB-P2 ("Photo/file attachments with
resumable upload and explicit remote destination"); `JOURNEYS.md` §8
(`attachment-delivery` gap — "gated in the client … but has **no consumer**") and
the cross-cutting "**one blob-transfer + Quick Look client**"; `ARCHITECTURE.md`
§7 ("Gated blob transfer + Quick Look") and Appendix A ("`files` (outbound) …
gated, no UI yet").

### 2.2 Why #89 cannot be one PR (and cannot land beside #90)

- It is **server-touching**: the three `*.attach*` methods advertise intent, but
  there is **no defined transport** for the bytes and **no defined shape** for
  associating an uploaded blob with a `prompt.submit` turn. That transport +
  attach-to-turn contract must be ratified **before** any client code, and it is
  a **shared-surface** change (`apps/shared/**`, `apps/mobile/contracts/**`) that
  per `AGENT_GUARDRAILS.md` §2.1 must be **serialized and coordinated**, landing
  as its own PR that other agents rebase onto.
- It spans four zones (contracts, shared TS, Swift client, Swift UI) and would be
  unreviewable as a single diff — violating "one task → one branch → one PR"
  (§0.3) and the loop-granularity rule (`UPGRADE_PLAN.md` §1).
- Its acceptance requires a **physical-iPhone / TestFlight** pass (issue #89's own
  final criterion) — unreachable from this environment.

It therefore maps onto the existing backlog as **breadth over the shared
blob-transfer substrate** (`UPGRADE_PLAN.md` Loop 9), delivered as the loop
sequence below. FMB-P2 is its phase home.

### 2.3 Proposed loop decomposition

Each loop is an independently shippable PR that passes every release gate on its
own. **Proposed** method/field names are marked as such; they are ratified in
Loop A, not assumed here.

#### Loop A — Blob-transfer + attach wire contract *(schema; shared surface; coordinate first)*

Define, as canonical JSON fixtures in `apps/mobile/contracts/` mirrored by
`apps/shared/src` (TS) and the Swift/Kotlin capability mirrors:

- A **resumable blob-transfer** transport (proposed: a begin/append/commit or
  offset-chunked shape with a server-issued transfer id, a content hash, a size
  ceiling, a TTL, and a resume-offset query) — reusing the `UpstreamAdapter`/
  size-limit patterns the desktop side already models rather than inventing a
  chat-only path (issue #89 design note).
- The **attach-to-turn** shape: how a committed blob's identity + `filename` +
  media type + byte size rides alongside the optional prompt text on the existing
  `prompt.submit` turn (proposed: an `attachments: [...]` field), and how the
  three advertised methods (`image.attach_bytes`, `pdf.attach`, `file.attach`)
  select the path per type.
- Capability governance: add the transport's feature key to
  `gateway-feature-registry-v1.json` and extend the `gateway-capabilities-*`
  corpus (v1 / families / contradiction / incompatible / malformed) so
  negotiation stays additive-optional and fail-closed.

**Exit:** the new fixtures parse and assert compatible in **Swift + TS + Kotlin**;
negotiation tests prove the transport key is additive-optional and that a gateway
lacking it (or lacking any of the three attach methods) fails closed with
`-32601` as the only legacy path. No live gateway advertises it yet.
**Note:** new `FabricTests` fixtures need a `buildPhase: resources` entry in
`project.yml` (the tests target does **not** glob `../contracts`).

#### Loop B — Swift blob-transfer client *(client-only; no UI)*

A `BlobTransferClient` over `JsonRpcGatewayClient` implementing the Loop A
transport: chunked/resumable upload with progress, cancellation, and bounded
retry; strict client-side validation (type allow-list from the advertised
methods, size ceiling, dimension checks reusing the `ImageIO` guards already in
`decodeScreenCapture`); **no credentials embedded in any URL**; temp-file cleanup;
and no attachment bytes in logs (mirror `ChatPresentationSafety` redaction).

**Exit:** unit + contract-parity tests (same bytes as the TS reference) for
begin/append/commit, resume-after-interruption, cancel, retry, oversize/wrong-type
rejection, and hash mismatch. No UI, no live advertisement.

#### Loop C — Composer attachment UI *(client-only)*

Add an attachment control beside `ChatComposerBar` (gated on
`supportsGatewayFeature("files")` **and** the specific advertised method — control
**and** handler both gate, per the fail-closed invariant). Offer **Take Photo**
(camera; `NSCameraUsageDescription` already declared in `project.yml`), **Photo
Library** (`PhotosPicker`), and **Files** (`fileImporter`). Show removable preview
chips; surface type/size limits and a denied-permission recovery path; begin
upload only on explicit submit; show progress / cancel / failure / resumable
retry. Wire the committed blob(s) + optional prompt into a single turn via Loop B.

**Exit:** picker-state, validation, gating, and permission-denied unit tests; the
full state matrix (light/dark, AX XXXL, small device) screenshots; VoiceOver +
44-pt checks. `PrivacyInfo.xcprivacy` updated if a new accessed-API category is
introduced (the generation test asserts required categories).

#### Loop D — Transcript rendering + resume + open/share *(client-only)*

Render sent attachments as transcript rows (image preview / file card) with a
native open/share action (the planned **Quick Look** client, `ARCHITECTURE.md`
§7); keep attachment identity associated with the message across reconnect and
session resume (extend `SessionTranscriptMessage`/restore + the presentation
cache, keeping the cache presentation-only and file-protected).

**Exit:** rendering + resume/reconnect-identity + Quick Look tests; attachment
metadata (filename, media type, size) reaches the agent turn; cache stays
bounded/redacted/file-protected.

### 2.4 Sequencing, dependencies, fail-closed posture

```
Loop A (contract + capability governance)  ──►  Loop B (Swift transfer client)
        │  shared surface: coordinate first          │
        └───────────────────────────────────────────┴──►  Loop C (composer UI)  ──►  Loop D (render + resume + Quick Look)
```

- Depends on **Loop 0** (capability-manifest governance, already on `main` via
  #81) for `supportsGatewayFeature`.
- Every loop preserves the fail-closed contract: **no capability advertised the
  server lacks; control and handler both gate; capability state is
  connection-scoped, never persisted; Durable Work stays dark.**
- The blob-transfer substrate is the same one JOURNEYS' §12 (`fs.read`) and the
  inbound-artifact fetch (`artifact.list`/`artifact.fetch`) will reuse — build it
  as the shared client, not a chat-only transport.

### 2.5 Open questions for the human/gateway owner (escalate per §8)

These are **design-intent + shared-surface** decisions that an automated agent
must not guess:

1. **Transport shape** for the blob bytes — the three `*.attach*` methods only
   name intent. Is the resumable transport chunked JSON-RPC, a side HTTP
   endpoint, or WebSocket binary frames? This is a gateway contract decision.
2. **Attach-to-turn shape** — does an attachment ride on `prompt.submit`
   (proposed `attachments`) or a dedicated pre-turn method? Affects idempotency
   and the "delivery unconfirmed" handling already in `ChatViewModel`.
3. **Limits** — max size / count / accepted media types and the server's
   authoritative enforcement vs. client pre-checks.
4. **Whether the gateway will implement any of this now** — Loops B–D are inert
   until a gateway advertises the transport; confirm this is wanted before
   spending the client build.

Until #1–#4 are answered by the gateway owner, Loop A cannot be finalized, so #89
**stops at this plan** — which is the correct, guardrail-honoring outcome.

---

## 3. Verification reality for this PR

- **Runnable here (Linux):** `python3 tests/scripts/test_ios_project_generation.py`
  (project-generation contract; unaffected — no file-set/`project.yml` change),
  `python3 scripts/commit_identity_audit.py --range origin/main..HEAD`.
- **NOT runnable here:** `xcodegen generate` + `xcodebuild test` + the
  `pbxproj`/`Info.plist` byte-check + on-device smoke — all in the PR-skipped
  `ios` job (§0). The #90 Swift change must be run through the local macOS loop
  before merge; the push-to-`main` `ios` job is the tripwire.
