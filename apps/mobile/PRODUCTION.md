# Fabric Mobile production goal

## Goal

Ship first-class Fabric clients for iOS and Android that let an authenticated
user safely continue work with a remote Fabric gateway from a phone. The apps
must preserve the authoritative conversation, survive normal mobile lifecycle
changes, recover blocked approvals and questions, and meet native platform
security, accessibility, reliability, and release requirements.

The mobile apps are remote clients. Fabric's Python runtime, tools, files,
browser automation, cron jobs, memory, and session database remain on the
gateway host.

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

## Threat model

An authenticated mobile client can cause the gateway host to execute commands,
read files, and expose screen content. A gateway credential is therefore
machine-control-equivalent.

Required controls:

- Prefer Tailscale, WireGuard, or an SSH tunnel as the network boundary.
- Require HTTPS/WSS for non-local production endpoints.
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
- Swift and Kotlin contract tests cover history hydration, in-flight restore,
  whole-turn replay filtering, stable session identity, unpersisted
  completion warnings, and pending-interaction recovery.
- Disconnect/reconnect during streaming, tool execution, approval, and
  clarification preserves chronology without duplicate or fabricated rows.

### Security

- iOS tokens use Keychain with a documented accessibility class.
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
6. **Post-v1 capability** — OAuth system-browser flow, attachments/voice,
   opt-in APNs/FCM notifications, and only then broader background behavior.

## Current status

The repository contains a packaged PWA and working native vertical slices, not
a signed store release. Shared protocol, PWA, Android, and iOS simulator checks
run in CI; `fabric mobile` is the documented gateway/pairing entry point.
Physical-device acceptance, protected signing, store assets/automation, and
publication remain open production gates. Passing a simulator build alone does
not advance the support tier or justify a store release.
