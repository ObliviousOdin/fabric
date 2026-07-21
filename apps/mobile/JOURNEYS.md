# Fabric Mobile — user journeys vs. current implementation

This is the honest gap map: the 14 canonical end-to-end journeys for the
official app (the native companion that turns an iPhone/iPad into a secure
**node** for a self-hosted Fabric gateway), each mapped to what the code
actually does today, with file evidence and severity-rated gaps.

It is the input to the loop-driven [`UPGRADE_PLAN.md`](UPGRADE_PLAN.md); the
architecture that closes these gaps is in [`ARCHITECTURE.md`](ARCHITECTURE.md).
State is assessed against `apps/mobile/ios` at the branch head (through PR #77,
rebased onto `main` including #78/#80).

**Legend:** ✅ shipped · ◐ partial · ○ absent. Evidence cites the owning Swift
file/symbol.

## Summary

| # | Journey | State | Biggest gap | Severity | Target loop |
| --- | --- | --- | --- | --- | --- |
| 1 | Discovery & installation | ◐ | No "do you already have a Gateway?" branch | medium | 1 |
| 2 | First launch, permissions & onboarding | ○ | No progressive-consent broker for device sensors | **critical** | 1 / 5 |
| 3 | Pairing (critical activation) | ◐ | Unreachable gateway dies with a raw error; enrollment is a dead end | **critical** | 1 / 5 |
| 4 | Daily text chat & session management | ◐ | Live reasoning discarded; no rich file/artifact rendering | high | 3 |
| 5 | Voice / Talk mode | ○ | No phone-side audio transport | high | 9 |
| 6 | Approvals & human-in-the-loop | ◐ | Approval card has no context, expiry, free-text, or cross-surface | high | 5 / 8 |
| 7 | Device capability invocation | ○ | No `node.invoke` transport (the peak differentiator) | **critical** | 5 / 6 |
| 8 | Content sharing (share sheet) | ○ | No share extension | high | 9 |
| 9 | Offline continuity | ○ | Offline sends are dropped; no offline-readable transcript | high | 4 |
| 10 | Multi-gateway management | ✅ | Simultaneous live sockets (parked) | medium | 9 |
| 11 | Apple Watch companion | ○ | No Watch target | high | 9 |
| 12 | Workspace / files inspection | ○ | No read-only files surface | high | 9 |
| 13 | Settings, permissions & offboarding | ◐ | Forget-Gateway purge is incomplete; no settings surface | high | 2 |
| 14 | Error recovery & reconnection | ◐ | No diagnostics; gated re-auth can't recover an expired cookie | medium | 2 |

The two biggest facts behind this table: **the drop-off risk is concentrated in
pairing (Journey 3)** and **the delight peak the whole product is missing is
device-capability invocation (Journey 7)** — today the app is a strong remote
*text* client but not yet a *node*.

---

## 1. Discovery & installation — ◐

Get the app installed and opened for the first time.

- ✅ QR-first entry exists once inside: **Scan pairing QR** is the top section of
  `AddGatewayView`, manual URL/token/password below.
- ○ **No discovery branch.** A cold launch lands directly in an empty server
  list (`GatewayListView`) whose only guidance is a one-line footer. There is no
  branch distinguishing a user who already runs `fabric serve` from one who has
  no gateway yet — the app assumes a gateway exists and shows a credential form
  for a server the user may not have. *(medium — `no-gateway-branching`)*
- Not yet a public App Store listing; store messaging must set the "needs a
  Gateway" expectation before install.

## 2. First launch, permissions & onboarding — ○

Understand the app and grant necessary, least-privilege access.

- ✅ Camera permission is correctly declared and scoped **to QR scanning only**
  (`Info.plist` `NSCameraUsageDescription`, `project.yml`). It is the *only*
  device-sensor permission the app declares.
- ✅ The reusable fail-closed gate infrastructure that every permission surface
  should build on already exists (`AppModel.supportsGatewayMethod`,
  `GatewayCapabilityNegotiation`).
- ○ **No first-run explainer / phone-is-a-node mental model.** Nothing teaches
  that the app is a thin client, that execution/state stay on the host, that
  active work survives a phone disconnect but a gateway restart interrupts it, or
  that a gateway credential is root-equivalent. *(high — `no-first-run-explainer`)*
- ◐ **Cold camera prompt, dead-end recovery.** The prompt fires the moment
  `QRScannerView` builds an `AVCaptureSession` — no rationale, no
  `authorizationStatus` pre-check; a denied camera shows a static label with no
  Open-Settings deep link and no manual-entry fallback. *(medium —
  `camera-priming-and-recovery`)*
- ○ **No progressive-consent broker.** There is no `node.*` family, no
  capability-request handling, no just-in-time consent for a sensor an agent
  asks for. The "ask only when needed" surface does not exist. *(critical —
  `progressive-consent-broker`)*
- ○ No Notifications or Microphone consent (the stated least-privilege default),
  because neither push nor phone audio exists yet.

## 3. Pairing (critical activation path) — ◐

Connect the phone to the gateway as a secure node in < 2–3 minutes.

- ✅ QR pairing (`PairingURI`, `QRScannerView`), token and gated password/TOTP
  connect paths, per-connect ticket mint, and a saved-server library are shipped
  and hardened (PR #71).
- ✅ Pairing v2 `enrollment` handle is recognized and **fails closed** today
  (`AppModel.receivePairingURL` → `.unsupportedEnrollment`).
- ○ **No reachability diagnosis.** A scanned-but-unreachable gateway dies with a
  raw error rather than "you're not on the tailnet / wrong network / host
  offline". *(critical — `route-diagnosis`)*
- ○ **Enrollment is a dead end.** The v2 handle has no `enroll → pending-approval
  → active` loop, so the "choose Full/Limited, approve on Gateway" journey can't
  complete. *(critical — `device-enrollment-loop`)*
- ○ **No Full vs Limited scope** at pairing; **no OAuth browser sign-in** for
  hosted gateways; **no guided Tailscale** setup / tailnet-membership detection;
  **thin QR UX** (no torch, reticle, permission-denied state, manual fallback).
  *(high)*
- ◐ TLS trust-on-first-use for private-CA gateways and an activation funnel to
  defend the < 3 min target are absent. *(medium)*

## 4. Daily text chat & session management — ◐

Seamless continuity of conversation and context.

- ✅ Streaming responses, steering, interruption, slash commands, background
  tasks, process control, and a **searchable, pinnable** session library (PRs
  #72, #74, #75) are shipped; rich assistant transcript rendering landed in #74.
- ○ **Live reasoning is discarded** — `thinking.delta` is not surfaced as a
  collapsible per-turn block. *(high — `reasoning-live-hidden`)*
- ○ **Tool activity collapses** to one ephemeral status line instead of
  persistent per-tool cards. *(high — `tool-activity-cards`)*
- ○ **No generated file / image / PDF presentation** — the inbound artifact fetch
  contract does not exist client-side. *(high — `generated-files-pdf-image`)*
- ○ **No model switch or reasoning-effort control** mid-session. *(high)*
- ◐ Markdown fidelity gaps: GFM tables render as raw pipe text, diffs lack
  add/remove coloring, no math, no code syntax highlighting. *(medium/low)*
- ○ No **Listen/TTS** affordance; no **session rename/archive**. *(medium/low)*

## 5. Voice / Talk mode — ○

Natural hands-free voice conversation.

- ○ **No phone-side audio.** `voice.record`/`voice.tts` use the *gateway host*
  mic/speakers by design (documented in `GatewayAPI.swift`), so there is no Talk
  Mode, push-to-talk, realtime levels, or background audio on the phone. Needs a
  new phone-audio transport contract and one `AVAudioSession` owner shared with
  Listen/TTS. *(high — `phone-voice-transport`)*
- Always-listening voice-wake is deferred until a scoped model exists. *(low)*

## 6. Approvals & human-in-the-loop — ◐

Stay in control of agent actions — the core trust mechanism.

- ✅ Approve/deny works today: `approval.request` renders and
  `ChatViewModel.respondToApproval` resolves the exact `request_id` with a
  receipt echo; clarify/sudo/secret prompts resolve too.
- ◐ **Approval card is thin.** It omits the summary/context and has **no expiry
  countdown**, and `respondToApproval` **hardcodes `once`/`deny`** (ChatViewModel.swift:758–767)
  — no free-text deny reason, no session/always/scoped choice. *(high)*
- ○ **Invisible outside the open chat.** No attention badge on Home/Sessions, no
  deep link, no "answered elsewhere" reconciliation. *(medium —
  `approval-cross-surface`; hard-depends on the push backbone)*

## 7. Device capability invocation — ○  (peak differentiator)

Let the agent use the phone's sensors — its eyes, ears, and location.

- ◐ The only "capability" today is read-only: `computer.screenshot` mirrors the
  **gateway host** screen (`LiveViewSheet`), not the phone's sensors.
- ○ **No `node.invoke` transport, consent engine, or grant model** — the phone
  cannot be addressed as a node at all. *(critical — `node-invoke-framework`)*
- ○ No `camera.capture` ("Take a photo for me" — the intended first magic
  moment), `photo.pick`, `location.oneshot`, phone `screen.snapshot`,
  `canvas.render`, `health.summary`, or `contacts/calendar.read`. *(high/medium)*
- ○ No user-visible ledger of what the phone captured and sent. *(high —
  `node-invocation-ledger`; reconciled into the server-authoritative Trust
  Center audit stream)*

## 8. Content sharing (share sheet) — ○

Inject external text, links, images, or media into a session.

- ○ **No Share Sheet extension** and no App Group staging store. *(high —
  `share-extension`)* The outbound-attach `files` capability is already gated in
  the client (`image.attach_bytes`/`pdf.attach`/`file.attach`) but has **no
  consumer**. *(medium — `attachment-delivery`)*

## 9. Offline continuity — ○

Remain useful without a perfect network.

- ✅ Foreground reconnect performs an authoritative `session.resume` before
  mutation controls return (`AppModel`, PR #73) — the socket-lifecycle half of
  resilience is solid.
- ○ **Offline sends are dropped** — no bounded, expiring outbound queue that
  flushes in order on reconnect. *(high — `outbound-queue`)*
- ○ **No offline-readable transcript** — last-known history is not cached for
  reading while disconnected. *(high — `transcript-cache`)*
- Both must honor `PRODUCTION.md`'s ban on blind offline queues / auto-retry of
  side-effecting RPCs — flush only definitely-unsent messages via gated
  `prompt.submit`, and route true side effects through idempotent Durable Work.

## 10. Multi-gateway management — ✅

Switch environments cleanly.

- ✅ Saved-server library with per-server credentials/TLS mode, one-tap token
  reconnect, silent gated reconnect, and disconnect-then-switch is shipped
  (`GatewayStore`, `AppModel`).
- ○ **Simultaneous live sockets** (a client-per-gateway registry) are a
  deliberate parked XL item. *(medium — `simultaneous-connections`)* Thin
  library management (rename/reorder/last-seen) is a small follow-up. *(low)*

## 11. Apple Watch companion — ○

Glanceable and wrist control for voice turns, approvals, status.

- ○ **No Watch target.** Relay-via-iPhone (default) and an optional direct
  `wss://` mode are unbuilt. *(high — `apple-watch-companion`; depends on the
  approval + push + audio substrate)*

## 12. Workspace / files inspection — ○

Transparency into agent state.

- ○ **No read-only Files surface** — no directory browse, syntax-highlighted
  text/image preview, or Share export. Needs `fs.list`/`fs.read` and reuses the
  shared blob-transfer + Quick Look client. *(high — `files-workspace-inspection`)*

## 13. Settings, permissions management & offboarding — ◐

Change needs, or leave cleanly and completely.

- ✅ "Forget Gateway" exists and removes the server + Keychain token
  (`AppModel.removeGateway`, `GatewayStore.remove`).
- ◐ **Purge is incomplete** — gated cookies are not cleared and there is no
  verified full local reset. *(high — `forget-gateway-purge-incomplete`)*
- ○ **No Settings screen** or permission-management surface — which is also the
  home the Trust Center and consent center need. *(medium —
  `no-settings-permission-surface`)*

## 14. Error recovery & reconnection — ◐

Recover from network drops, stuck approvals, and connection failures.

- ✅ Auto-reconnect with exponential backoff and generation-guarded attempts is
  shipped (`AppModel.scheduleReconnect`, capped, foreground-gated).
- ◐ **Gated auto-reconnect can't recover an expired cookie** — it retries a
  ticket mint that will fail rather than prompting a graceful re-auth. *(medium —
  `gated-reconnect-no-reauth`)*
- ○ **No diagnostics / persistent status chip / clear-cache** recovery surface.
  *(medium)* Backoff has a hard 4-attempt cap and no jitter/cause distinction.
  *(low)*

---

## Cross-cutting gaps (span journeys — designed once, in `ARCHITECTURE.md`)

These are not owned by any single journey and, if left per-cluster, would
fragment the whole program:

- **Capability-manifest governance** — one rule for how `gateway.capabilities`
  grows to advertise `node.*`, `trust.*`, `grant.*`, `push.*`, `fs.*`,
  `artifact.*`, `session.rename/archive`, and phone audio. *(critical, master
  dependency)*
- **Background/suspended lifecycle** — a `node.invoke`/approval/Talk turn that
  arrives while the app is asleep needs silent-push-to-wake + `BGTask` + a
  foreground-return handshake. *(high)*
- **One consent + grant + audit subsystem** — the "progressive-consent broker",
  the "`node.invoke` consent engine", and the Trust Center grants/ledger are the
  same module. *(critical)*
- **Unified typed-error taxonomy** — `unsupported` / `denied` / `transient` /
  `needs-reauth`, extending `-32601` and `5040`. *(high)*
- **One blob-transfer + Quick Look client** — inbound artifacts, share staging,
  and `fs.read`. **One `AVAudioSession` owner** — Listen/TTS and Talk Mode. *(high)*
- **Privacy-manifest matrix, localization, and accessibility** as standing
  constraints on every new surface, not afterthoughts. *(high)*
- **Per-gateway scoping** of grants/ledger even with one live socket, so
  switching servers never shows another gateway's grants. *(medium)*
- **One deep-link router + a Live Activity** for the running goal / needs-
  attention. *(medium)*
