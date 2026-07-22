# Fabric Mobile — user journeys vs. current implementation

This is the honest gap map: the 14 canonical end-to-end journeys for the
official app (the native companion that turns an iPhone/iPad into a secure
**node** for a self-hosted Fabric gateway), each mapped to what the code
actually does today, with file evidence and severity-rated gaps.

It is the input to the loop-driven [`UPGRADE_PLAN.md`](UPGRADE_PLAN.md); the
architecture that closes these gaps is in [`ARCHITECTURE.md`](ARCHITECTURE.md).
State is assessed against the `0.2.1` candidate source at this branch head,
based on `main` after the capability-governance merge (#81). This is a code gap
map, not a TestFlight release claim; archive/device/tester evidence lives in
[`IOS_RELEASES.md`](IOS_RELEASES.md).

**Legend:** ✅ implemented in current source · ◐ partial · ○ absent. Evidence
cites the owning Swift file/symbol.

## Summary

| # | Journey | State | Biggest gap | Severity | Target loop |
| --- | --- | --- | --- | --- | --- |
| 1 | Discovery & installation | ◐ | No guided path for someone without a running Gateway | medium | 1 |
| 2 | First launch, permissions & onboarding | ◐ | No progressive-consent broker for device sensors | **critical** | 5 |
| 3 | Pairing (critical activation) | ◐ | Device enrollment/OAuth/private-CA trust are still absent | **critical** | 5 / 9 |
| 4 | Daily text chat & session management | ◐ | No generated file/artifact or model-control surface | high | 3 / 9 |
| 5 | Voice / Talk mode | ◐ | Native dictation/read-aloud exist; no continuous Talk transport | high | 9 |
| 6 | Approvals & human-in-the-loop | ◐ | No expiry, free-text denial, or cross-surface attention | high | 5 / 8 |
| 7 | Device capability invocation | ○ | No `node.invoke` transport (the peak differentiator) | **critical** | 5 / 6 |
| 8 | Content sharing (share sheet) | ○ | No share extension | high | 9 |
| 9 | Offline continuity | ◐ | No outbound queue or server-authoritative offline state | high | 4 |
| 10 | Multi-gateway management | ✅ | Simultaneous live sockets (parked) | medium | 9 |
| 11 | Apple Watch companion | ○ | No Watch target | high | 9 |
| 12 | Workspace / files inspection | ○ | No read-only files surface | high | 9 |
| 13 | Settings, permissions & offboarding | ◐ | Future grant/node controls wait for advertised families | high | 7 |
| 14 | Error recovery & reconnection | ◐ | Backoff is capped and has no jitter/cause policy | medium | 2 / 4 |

The two biggest facts behind this table: **the drop-off risk is concentrated in
pairing (Journey 3)** and **the delight peak the whole product is missing is
device-capability invocation (Journey 7)** — today the app is a strong remote
*text* client but not yet a *node*.

---

## 1. Discovery & installation — ◐

Get the app installed and opened for the first time.

- ✅ A cold launch now lands on the branded scanner-led
  `FirstRunConnectView`, with one primary **Scan pairing code** path and manual
  URL/token/password fields behind **Advanced setup**. Returning users receive a
  separate saved-Fabric library (`GatewayListView`).
- ◐ **Gateway discovery is still instructional, not guided.** The scanner names
  the `fabric mobile` command, but there is no explicit install/start walkthrough
  for a person who does not yet run a Gateway. *(medium —
  `no-gateway-branching`)*
- Not yet a public App Store listing; store messaging must set the "needs a
  Gateway" expectation before install.

## 2. First launch, permissions & onboarding — ◐

Understand the app and grant necessary, least-privilege access.

- ✅ Camera permission is correctly declared and scoped **to QR scanning only**.
  Microphone and Speech Recognition are separately declared and requested only
  after the user taps Dictate in Chat (`Info.plist`, `project.yml`).
- ✅ The reusable fail-closed gate infrastructure that every permission surface
  should build on already exists (`AppModel.supportsGatewayMethod`,
  `GatewayCapabilityNegotiation`).
- ✅ `PairingScannerFlow` checks authorization before camera construction,
  presents one rationale before the system request, and gives denied,
  restricted, and unavailable states an Open-Settings action where possible
  plus an Advanced-setup fallback.
- ✅ The post-connect `ConnectedGatewayIntroView` explains only what negotiation
  proves: endpoint, gateway execution, phone-disconnect continuity, gateway-host
  dependency, and credential storage. A legacy response says those execution
  facts are unverified instead of inferring them.
- ○ **No progressive-consent broker.** There is no `node.*` family, no
  capability-request handling, no just-in-time consent for a sensor an agent
  asks for. The "ask only when needed" surface does not exist. *(critical —
  `progressive-consent-broker`)*
- ○ No Notifications consent because push does not exist yet. Native dictation
  now owns its microphone/speech consent locally and does not imply a general
  agent sensor grant.

## 3. Pairing (critical activation path) — ◐

Connect the phone to the gateway as a secure remote client in < 2–3 minutes;
secure node enrollment remains a later, separately advertised contract.

- ✅ QR pairing (`PairingURI`, `QRScannerView`), token and gated password/TOTP
  connect paths, per-connect ticket mint, and a saved-server library are shipped
  and hardened (PR #71).
- ✅ Pairing v2 `enrollment` handle is recognized and **fails closed** today
  (`AppModel.receivePairingURL` → `.unsupportedEnrollment`).
- ✅ Pairing and saved-server failures pass through `ConnectRouteDiagnosis` /
  `GatewayConnectionIssue`: offline, timeout/host, TLS, authentication, and
  contract failures receive bounded actionable copy; raw server/network text and
  credentials never enter the UI or presentation cache.
- ○ **Enrollment is a dead end.** The v2 handle has no `enroll → pending-approval
  → active` loop, so the "choose Full/Limited, approve on Gateway" journey can't
  complete. *(critical — `device-enrollment-loop`)*
- ✅ The QR path now includes a reticle, conditional torch, permission recovery,
  cancellation, and manual fallback. It still has **no Full vs Limited scope**,
  **no OAuth browser sign-in**, and **no guided Tailscale** setup or
  tailnet-membership detection. *(high)*
- ◐ TLS trust-on-first-use for private-CA gateways and an activation funnel to
  defend the < 3 min target are absent. *(medium)*

## 4. Daily text chat & session management — ◐

Seamless continuity of conversation and context.

- ✅ Streaming responses, steering, interruption, slash commands, background
  tasks, process control, and a **searchable, pinnable** session library (PRs
  #72, #74, #75) are shipped; rich assistant transcript rendering landed in #74.
- ✅ `ChatPresentationReducer` retains bounded/redacted reasoning and tool
  lifecycle parts beside the assistant turn; `ReasoningDisclosureCard` and
  `ToolActivityCard` render them persistently with stable accessibility labels.
- ○ **No generated file / image / PDF presentation** — the inbound artifact fetch
  contract does not exist client-side. *(high — `generated-files-pdf-image`)*
- ○ **No model switch or reasoning-effort control** mid-session. *(high)*
- ◐ Unified diffs now receive add/remove presentation, while GFM tables, math,
  and language-aware code syntax highlighting remain. *(medium/low)*
- ✅ Completed assistant responses have a **Read aloud / Stop speaking**
  affordance backed by an installed iPhone voice; Settings offers voice
  selection and a local preview.
- ○ No **session rename/archive**. *(medium/low)*

## 5. Voice / Talk mode — ◐

Natural hands-free voice conversation.

- ✅ Chat has explicit phone-side dictation (`SFSpeechRecognizer` +
  `AVAudioEngine`) that writes partial speech into the draft and never submits
  automatically. It prefers on-device recognition when Apple Speech advertises
  it. Read-aloud uses `AVSpeechSynthesizer`; neither path reuses gateway-host
  audio RPCs.
- ○ **No continuous Talk mode or model-backed phone-audio transport.**
  `voice.record`/`voice.tts` still use the *gateway host* mic/speakers by design
  (documented in `GatewayAPI.swift`). Realtime levels, conversation turn-taking,
  background audio, and a provider-neutral audio wire contract remain future
  work. *(high — `phone-voice-transport`)*
- Always-listening voice-wake is deferred until a scoped model exists. *(low)*

## 6. Approvals & human-in-the-loop — ◐

Stay in control of agent actions — the core trust mechanism.

- ✅ Approve/deny works today: `approval.request` renders and
  `ChatViewModel.respondToApproval` resolves the exact `request_id` with a
  receipt echo; clarify/sudo/secret prompts resolve too.
- ◐ Approval UI now presents bounded summary/command/directory context and the
  gateway's once/session/always/deny choices, disabling permanent approval with
  an explicit reason when the request forbids it. It still has no expiry
  countdown or free-text denial reason. *(high)*
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

## 9. Offline continuity — ◐

Remain useful without a perfect network.

- ✅ Foreground reconnect performs an authoritative `session.resume` before
  mutation controls return (`AppModel`, PR #73) — the socket-lifecycle half of
  resilience is solid.
- ✅ Chat retains a bounded, protected, presentation-only last-known transcript
  and can show it read-only when authoritative resume fails. The cache is never
  promoted to server state and mutation controls stay unavailable.
- ○ **Offline sends are dropped** — no bounded, expiring outbound queue that
  flushes in order on reconnect. *(high — `outbound-queue`)*
- Any future outbound queue must honor `PRODUCTION.md`'s ban on blind offline
  queues / auto-retry of side-effecting RPCs — flush only definitely-unsent
  messages via gated
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
- ✅ The connected shell now has a first-class Settings screen with connection
  and execution posture, camera/local-network inventory, client/gateway
  contract details, redacted diagnostics, re-pair/switch/forget actions, and a
  confirmed full-device local reset.
- ✅ Every saved gated gateway + normalized endpoint owns an isolated ephemeral
  cookie jar. Public discovery is cookie-disabled; fresh-password and silent-
  reconnect attempts are generation-fenced; Forget/disconnect invalidate only
  the targeted gateway; and full reset invalidates every jar before removing
  saved metadata, Keychain tokens, and device presentation state.
- ◐ Future grant/node permission controls still wait for their advertised
  families. *(high)*

## 14. Error recovery & reconnection — ◐

Recover from network drops, stuck approvals, and connection failures.

- ✅ Auto-reconnect with exponential backoff and generation-guarded attempts is
  shipped (`AppModel.scheduleReconnect`, capped, foreground-gated).
- ✅ A 401/403 ticket-mint failure now transitions to the existing gated
  `SignInSheet` instead of repeating a silent reconnect; the shell adds a
  persistent recovery banner with Retry/Servers actions.
- ✅ Settings provides a locally generated redacted diagnostic report and a
  device-only presentation-cache recovery action; neither sends data or mutates
  gateway-side work.
- ◐ Backoff still has a hard four-attempt cap and no jitter/cause distinction.
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
