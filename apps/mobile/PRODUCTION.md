# Fabric Mobile Production Foundation

> **Scope note:** This document defines the first signed, supportable remote-chat
> release and its non-negotiable safety/reliability gates. The post-v1 mobile
> capability program builds on this foundation. Items excluded from this first
> release are deferred to named FMB slices; they are not rejected from the
> product roadmap.

## Goal

Ship first-class Fabric clients for iOS and Android that let an authenticated
user safely continue work with a remote Fabric gateway from a phone. The apps
must preserve the authoritative conversation, survive normal mobile lifecycle
changes, recover blocked approvals and questions, and meet native platform
security, accessibility, reliability, and release requirements.

The mobile apps are remote clients. Fabric's Python runtime, tools, files,
browser automation, cron jobs, memory, and session database remain on the
gateway host.

## Design adoption boundary

The supplied Fabric mobile UI kit is an audited interaction reference for this
release, not a substitute for the production contract. Connect, Sessions/Chat,
offline recovery, in-app attention, and read-only live evidence should follow
the canonical Woven Operations tokens and state grammar in `DESIGN.md`. The
broader artifact, automation, Code, share, widget, Live Activity, phone-audio,
and attachment concepts remain assigned to later post-v1 slices.

Two concept-kit patterns are prohibited in the production foundation:

- A pairing QR must not contain a reusable gateway token. It may carry an
  address and a one-time, short-lived, scope-bound enrollment credential whose
  exchange writes the resulting device secret only to Keychain/Keystore.
- Lock-screen notifications and Live Activities must not expose raw approval
  commands or apply a high-risk action directly. They are minimal, redacted
  hints that deep-link to the exact current in-app interaction for review.

Before release, Connect, Sessions, Chat, pending attention, offline recovery,
and read-only live evidence need same-state native captures in Fabric Light and
Dark, including loading, empty, error, stale/offline, and permission-denied
fixtures. Screenshot comparison complements rather than replaces Dynamic Type,
VoiceOver, TalkBack, contrast, touch-target, lifecycle, and physical-device
acceptance.

## Product boundary

### In scope for the first production release

- Native SwiftUI client for iOS 17 and newer.
- Native Jetpack Compose client for Android 8 (API 26) and newer.
- Saved-server library with QR and manual pairing.
- Token-mode and gated password/TOTP authentication.
- Keychain/Android Keystore-backed credential storage. Passwords and TOTP
  values are never persisted.
- Session list, create, authoritative resume, transcript history, streaming,
  reasoning/status, tools, steering, interruption, slash commands, and
  background tasks.
- Recovery of pending approval, clarification, sudo, and secret interactions
  after reconnect.
- Read-only computer-use live view.
- Foreground reconnect and authoritative session rehydration after the OS
  suspends or tears down the socket.
- Dark mode, Dynamic Type/font scaling, screen-reader labels, reduced-motion
  behavior, system back navigation, safe-area/window-inset handling, and
  minimum native touch targets.
- Signed release builds, CI checks, privacy metadata, operator documentation,
  and a documented support tier.

### Explicitly out of scope for the first release

- Running the Fabric agent runtime on the phone.
- Blind offline prompt queues or automatic retries of side-effecting RPCs.
- Interactive remote desktop control.
- Persisting passwords, TOTP codes, WebSocket tickets, or secrets.
- Public-internet deployment without TLS, a configured authentication
  provider, rate limiting, and TOTP.
- Claiming background push delivery until an opt-in APNs/FCM gateway contract
  exists.
- Simultaneous live sockets to multiple gateways.

## Positioning

Fabric Mobile is the native remote control for a user's own Fabric agent: the
same authoritative sessions and security boundary as desktop, adapted to the
interrupt-driven and failure-prone reality of a phone.

## Architecture

```text
SwiftUI app / Compose app
        |
        | HTTPS + WSS, JSON-RPC 2.0
        v
fabric mobile (shared fabric serve backend)
        |
        +-- authoritative session history and in-flight snapshot
        +-- model and tool execution
        +-- approvals, clarification, sudo, and secret waits
        +-- authentication and single-use WebSocket tickets
```

`session.resume` is the restoration boundary. A client installs persisted
history first, restores the in-flight turn and pending interactions, then
replays only buffered events not already covered by the snapshot's
`history_version`. Clients must not infer missing transcript content or retry
mutations after an ambiguous network failure.

The TypeScript client in `apps/shared` is the reference wire contract. Swift
and Kotlin ports must have contract tests for the same invariants. The
same-origin app in `apps/mobile-web` is a PWA fallback and browser proof; it is
not the native runtime.

`gateway.capabilities` is the connection boundary. After every authenticated
socket connect or reconnect, clients clear the previous snapshot, negotiate
the versioned contract, reject stale attempt results, and only then issue
session RPCs. Valid responses are method-authoritative. Only JSON-RPC
`-32601` enables the reviewed shipped-v1 legacy set; malformed,
incompatible, timeout, close, and other server failures fail closed for
mutations. Contract v1 also requires every client to state that execution
runs on the gateway, survives a phone disconnect but not a gateway restart,
and requires the gateway host online.

## Threat model

An authenticated mobile client can cause the gateway host to execute commands,
read files, and expose screen content. A gateway credential is therefore
machine-control-equivalent.

Required controls:

- Prefer Tailscale, WireGuard, or an SSH tunnel as the network boundary.
- Require HTTPS/WSS for non-local production endpoints.
- Permit token-mode credentials only over HTTPS or strict loopback. An upgraded
  saved remote-HTTP token gateway must fail closed before credential load or
  transport, remain visible for explicit recovery/removal, and require re-pair
  through trusted HTTPS or loopback.
- Require a configured provider on non-loopback binds; use TOTP for any public
  exposure.
- Store token-mode credentials in Keychain/Android Keystore only.
- Keep password, TOTP, WebSocket ticket, sudo response, and requested secret
  in memory only for the shortest practical lifetime.
- Redact approval commands on the server before sending them to a mobile
  client.
- Never log credentials, pairing payloads, auth cookies, tickets, sudo values,
  or requested secrets.
- Do not automatically retry session creation, prompt submission, slash
  execution, steering, approval, clarification, sudo, secret, or interrupt
  operations without server-side idempotency.
- Release builds fail closed on cleartext networking. Development-only LAN
  exceptions must not leak into store artifacts.

## Production acceptance gates

A release is production-grade only when every applicable gate is satisfied.

### Protocol and data integrity

- Backend gateway/auth contract suites pass.
- Shared TypeScript reducer and transport suites pass.
- The backend, TypeScript, Swift, and Kotlin capability parsers exercise the
  same canonical valid, incompatible, malformed, and legacy-method fixtures.
- Capability tests prove negotiation precedes session calls, stale server
  switches cannot publish old snapshots, `-32601` is the only legacy path,
  unknown additive fields remain compatible, and every existing RPC control
  is gated by its exact advertised or reviewed-legacy method.
- Swift and Kotlin contract tests cover history hydration, in-flight restore,
  whole-turn replay filtering, stable session identity, unpersisted
  completion warnings, and pending-interaction recovery.
- Disconnect/reconnect during streaming, tool execution, approval, and
  clarification preserves chronology without duplicate or fabricated rows.

### Security

- iOS tokens use Keychain with a documented accessibility class.
- iOS auto-connect, explicit reconnect, and final WebSocket construction all
  enforce the HTTPS-or-strict-loopback token boundary, including saved records
  created by an older build.
- Android tokens use Android Keystore-backed encryption; no credential appears
  in plain SharedPreferences, backups, logs, clipboard history, screenshots,
  or saved instance state.
- Release networking rejects plaintext remote gateways.
- Password/TOTP and WebSocket tickets are not persisted.
- Dependency bounds and release signing configuration are documented and
  checked.

### Reliability and lifecycle

- Foregrounding reconnects and resumes the open stored session.
- Network changes and server restarts produce recoverable UI rather than
  destructive navigation or duplicate mutations.
- All WebSocket requests time out and are cancelled on socket close.
- Large transcripts remain responsive and do not grow duplicate event
  subscriptions.
- Empty, loading, offline, expired-auth, permission-denied, and server-error
  states offer an explicit recovery action.

### Native UX and accessibility

- VoiceOver and TalkBack can complete pairing, session selection, prompt
  submission, approval, clarification, and interruption.
- iOS supports Dynamic Type, safe areas, native navigation/back gestures,
  dark mode, increased contrast, and Reduce Motion.
- Android supports font scaling, edge-to-edge insets, IME resizing, predictive
  back, dark mode, and disabled system animations.
- Touch targets are at least 44 pt on iOS and 48 dp on Android.
- Long text, emoji, CJK, and RTL content do not clip critical controls.

### Build and release

- A clean checkout can generate and test the Xcode project.
- Android builds and unit tests run through a pinned Gradle wrapper and JDK 17.
- Debug and signed release builds are separate; release enables shrinking and
  contains no debug cleartext exception.
- CI builds both native apps and runs their unit tests.
- App icons, launch assets, privacy manifests/data-safety declarations,
  versioning, signing, and store metadata are present.
- Physical-device smoke tests pass on at least one currently supported iPhone
  and one currently supported Android phone.

## Delivery phases

1. **Contract stabilization** — authoritative resume, pending interactions,
   typed transport failures, and cross-client tests.
2. **Credential and transport hardening** — Android Keystore, release-only TLS,
   auth expiry, log redaction, and safe pairing.
3. **Lifecycle resilience** — foreground reconnect, active-session restoration,
   network-change recovery, and non-retrying mutation UX.
4. **Native quality** — accessibility, adaptive layouts, long-transcript
   performance, localization resilience, and device QA.
5. **Release engineering** — pinned toolchains, CI, signing templates, privacy
   declarations, versioning, and operator/runbook documentation.
6. **Post-v1 capability** — OAuth system-browser flow, resumable phone
   attachments and a distinct phone-audio contract (never gateway-host
   `voice.*`), opt-in APNs/FCM notifications, and only then broader background
   behavior.

## Current status

The repository contains a packaged PWA and working native vertical slices. An
initial iOS development preview has been signed, uploaded, installed, and used
through internal TestFlight; it is evidence that the distribution path works,
not a claim that the production gates are complete. Shared protocol, PWA,
Android, and iOS simulator checks run in CI; `fabric mobile` is the documented
gateway/pairing entry point. The protected Xcode Cloud `Default` workflow now
targets merged `main`, supplies the protected release bundle identifier through
`FABRIC_IOS_BUNDLE_ID`, and sends successful archives to the internal
TestFlight `beta` group; the local signing/profile audit associates that bundle
with the configured release signing team. Merged-main
candidates `0.2.0 (4)`, its immutable-source repeat `0.2.0 (5)`, and the
pairing-reliability candidate `0.2.0 (6)` archived, uploaded, processed to
**Testing**, and reached that group; build 6 came from
`9651091ac45e34124184bdf1cf54a37e149c27e2`. A physical-iPhone audit on
2026-07-21 also observed the TestFlight-installed bundle as `0.2.0 (15)`, but
its apparent mapping to current `origin/main` at `c5343180` is history-based
inference until signed-archive or workflow provenance is captured. Full
physical-device acceptance, independent signed-archive inspection, store
assets, public beta delivery, and later-phase native quality gates remain open.
See
`IOS_RELEASES.md` for exact build evidence and `ROADMAP.md` for the phased parity
program. Passing a simulator build alone does not advance the support tier or
justify a store release.

FMB-002 Durable Work remains an unadvertised control-plane preview. It stores
bounded, redacted Job/Attention state in profile-private `work.db`; a phone
disconnect can recover that state, while a gateway restart interrupts rather
than replays in-process agent execution. Until every client and operations gate
is complete, the released capability manifest keeps the legacy
`prompt.background` path authoritative. Push and lock-screen actions remain
deferred to FMB-003/FMB-004, after server-derived device identity and exact
durable return-state contracts exist.
