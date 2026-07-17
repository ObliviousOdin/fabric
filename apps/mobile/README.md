# Fabric Mobile (iOS + Android)

Native mobile clients for [Fabric](../../README.md): SwiftUI on iOS and
Jetpack Compose on Android. Both connect to a running Fabric backend
(`fabric serve`) over the same JSON-RPC/WebSocket contract the desktop app
uses — no new server surface is required.

> **Status: scaffold.** This directory contains the architecture decision
> record, the protocol clients, and a working chat vertical slice for each
> platform. Neither app has shipped through CI or the release contract yet,
> and the code has not been compiled on a macOS/Android toolchain from this
> checkout. Treat it as the reviewed starting point for the mobile track,
> not a released surface.

## Why the runtime stays off the phone

The Fabric engine is a Python runtime that spawns subprocesses (terminal
tools, browser automation, git, cron) and holds long-lived state under
`~/.fabric`. iOS forbids spawning child processes and reclaims background
daemons aggressively; Android permits more but the tested Termux path
(`docs: getting-started/termux`) already covers "engine on the phone" as a
Tier 2/3 experimental CLI experience.

The desktop app solved the same problem in a way mobile can reuse directly:
the Electron shell is a **thin client**. It launches a headless backend
(`fabric serve --host 127.0.0.1 --port 0`, see
`apps/desktop/electron/backend-command.ts`) and talks to it exclusively
through a WebSocket JSON-RPC channel (`apps/shared/src/json-rpc-gateway.ts`).
Crucially, the desktop **already supports remote backends**
(`apps/desktop/electron/connection-config.ts`): the same UI connects to a
`fabric serve` running on another machine over http(s), authenticated with
either a session token or an OAuth-gated ticket.

A mobile app is therefore the desktop's remote-gateway mode with a
phone-native UI:

```
┌─────────────┐  wss://…/api/ws?token=…   ┌──────────────────────────┐
│ iOS/Android  │ ─────────────────────────▶ │ fabric serve             │
│ native client│  JSON-RPC 2.0 + events    │ (home machine, server,   │
└─────────────┘ ◀───────────────────────── │  or hosted gateway)      │
                                           └──────────────────────────┘
```

Reachability is the user's choice: LAN, Tailscale/WireGuard, an SSH tunnel,
or a hosted gateway behind HTTPS + OAuth.

## The wire contract (already shipped by the backend)

Everything below exists today in `fabric_cli/web_server.py` and
`tui_gateway/server.py`; the mobile clients are pure consumers.

| Surface | Endpoint | Notes |
| --- | --- | --- |
| Liveness/probe | `GET /api/status` | Public. `auth_required: true` marks a gated gateway (`authModeFromStatus` in the desktop). |
| RPC channel | `WS /api/ws?token=…` or `?ticket=…` | JSON-RPC 2.0 requests + `method: "event"` frames. Token mode uses the dashboard session token; gated mode mints a single-use ticket at `POST /api/auth/ws-ticket`. |
| REST auth header | `X-Fabric-Session-Token` | For token-mode REST calls. |
| Sign-in options | `GET /api/auth/providers` | Gated only: `{providers: [{name, display_name, supports_password}]}`. |
| Password login | `POST /auth/password-login` | Gated only: `{provider, username, password}` → session cookies (`hermes_session_at`/`_rt`). |

Two auth modes, decided by the server's bind (June 2026 hardening):

- **Token** — loopback binds (`127.0.0.1`, incl. behind an SSH/`tailscale
  serve` tunnel): the ephemeral session token authenticates REST and the
  `?token=` WS upgrade.
- **Gated** — any non-loopback bind (a Tailscale IP, `0.0.0.0`): the token
  path is rejected outright. Clients sign in against a configured auth
  provider (e.g. the bundled password provider), carry the session cookies,
  and mint a single-use 30s `?ticket=` for every WS connect. Both apps
  implement this flow; OAuth-provider sign-in is still roadmap.

RPC methods the v1 slice uses (of ~120 registered in
`tui_gateway/server.py`):

- `session.create` — params `{cols, source: "mobile", cwd?, profile?, model?, provider?, reasoning_effort?, fast?}` → `{session_id, stored_session_id, info}`
- `session.resume` — `{session_id, cols, profile?}`
- `session.list` — → `{sessions: [{id, title, preview, started_at, message_count, source}]}`
- `session.active_list` — live in-memory gateway sessions with runtime status (`working`/`waiting`/`starting`/`idle`)
- `prompt.submit` — `{session_id, text}`
- `prompt.background` — `{session_id, text}` → detached task; result returns as a `background.complete` event
- `session.steer` — `{session_id, text}` → inject a mid-turn note without interrupting (`AIAgent.steer`)
- `session.interrupt` — `{session_id}`
- `slash.exec` / `commands.catalog` — the TUI's slash-command dispatch surface and its registry-backed catalog
- `process.list` / `process.kill` — session-owned background processes (preview servers, watchers)
- `approval.respond` — `{session_id, choice: "allow"|"deny", all?: bool}`
- `clarify.respond` / `sudo.respond` / `secret.respond` — `{request_id, answer|password|value}`, unblocking the agent's blocking prompts

Streaming events consumed (`GatewayEventName` in
`apps/shared/src/json-rpc-gateway.ts` is the canonical list):
`gateway.ready`, `session.info`, `message.start`, `message.delta`
(`payload.text`), `message.complete`, `thinking.delta`, `status.update`
(`payload.{kind,text}`), `tool.start` / `tool.progress` / `tool.complete`,
`approval.request` (command pre-redacted server-side), `clarify.request`
(`{question, choices, request_id}`), `sudo.request` / `secret.request`
(`{prompt?, request_id}`), `background.complete` (`{task_id, text}`),
`error`.

## Decision record: why fully native (and what was rejected)

| Option | Verdict | Reasoning |
| --- | --- | --- |
| **SwiftUI + Jetpack Compose (chosen)** | ✅ | Best platform integration for what a Fabric client actually needs next: push notifications for approvals/turn-completion, share extensions ("send this page/file to Fabric"), widgets, background socket handling, App Store-clean review posture. The protocol layer is small (~400 lines of TS) so porting it twice is cheap; it is ported 1:1 in `FabricKit` (Swift) and `core/` (Kotlin) with the same state machine and timeouts. |
| React Native / Expo | ◻ viable fallback | Reuses `apps/shared` verbatim and the team's React knowledge (desktop renderer, web dashboard). Rejected for v1 because the explicit product ask was native, and the desktop renderer's component tree is Electron-coupled enough (IPC preload, window chrome, xterm) that real UI reuse is lower than it looks. If team velocity on two native codebases becomes the bottleneck, this is the escape hatch — the wire contract is identical. |
| Capacitor wrap of `web/` dashboard | ❌ | The dashboard chat is a PTY/xterm surface around `fabric --tui` (`web/README.md`), which is hostile to touch UX; violates the "no simulated surfaces" dashboard rule and would not pass native review quality bars. |
| Kotlin Multiplatform shared core | ❌ for now | Attractive later (one protocol/client core, two native UIs) but adds a toolchain the repo doesn't have. Revisit if the two protocol ports drift. |

## What's in this scaffold

```
apps/mobile/
├── README.md            ← this file (assessment + decision record)
├── ios/                 ← SwiftUI app, XcodeGen project manifest
│   ├── project.yml
│   └── Fabric/
│       ├── App/         ← app entry, root navigation model
│       ├── Core/        ← FabricKit: JSON-RPC client, typed API, keychain store
│       └── Features/    ← Connect, Sessions, Chat screens
└── android/             ← Jetpack Compose app, Gradle Kotlin DSL
    └── app/src/main/kotlin/io/github/obliviousodin/fabric/mobile/
        ├── core/        ← JSON-RPC client (OkHttp), typed API, settings store
        └── ui/          ← Connect, Sessions, Chat screens
```

The v1 vertical slice on both platforms:

1. **Connect** — enter gateway URL + session token, probe `GET /api/status`,
   persist credentials (iOS Keychain; Android app-private prefs, Keystore
   encryption tracked as follow-up).
2. **Sessions** — `session.list` to resume or start new, plus an
   **Active now** monitor (`session.active_list`) showing live runtime
   status with interrupt control per session.
3. **Chat** — `session.create`/`session.resume` → `prompt.submit` → live
   streamed transcript (`message.delta`), status/tool activity line,
   interrupt, and approval prompts (`approval.request` → `approval.respond`).

Plus the dispatch/remote-control surface the TUI composer has, driven from
the same chat screen:

- **Slash commands** — a draft starting with `/` routes to `slash.exec`;
  a searchable command picker (`commands.catalog`) inserts commands with
  their registry descriptions (core commands, quick commands, skills).
- **Steering** — while a turn is running the composer sends
  `session.steer` notes instead of new prompts, without interrupting.
- **Background tasks** — "Run draft in background" (`prompt.background`);
  completion lands in the transcript via `background.complete`.
- **Blocking prompts** — `clarify.request` choices render as buttons,
  `sudo.request`/`secret.request` get a secure entry field; all resolve
  through their `*.respond` RPCs so an agent blocked on a question can be
  unblocked from the phone.
- **Process control** — per-session background processes (`process.list`)
  with output tails and kill (`process.kill`).

## Pairing (QR) and connecting over Tailscale

`fabric serve --qr` prints a `fabric://pair` QR (contract in
`fabric_cli/mobile_pairing.py`); both apps scan it from the connect screen.
Gated binds emit a URL-only QR — credentials never ride in the QR — and the
app follows up with the username/password form. Ungated (loopback/tunnel)
binds embed the session token, so scanning connects with zero typing.

**Phone and machine on the same tailnet** — two supported shapes:

1. **Direct bind to the tailnet address** (username/password on the phone):

   ```bash
   # one-time: configure the bundled password provider
   #   dashboard.basic_auth.username + password_hash in config.yaml
   #   (hash with: python -c "from plugins.dashboard_auth.basic import hash_password; print(hash_password('your-password'))")
   fabric serve --host <tailscale-ip> --port 9119 --qr
   ```

   The QR carries the URL; the phone asks for the username/password. The
   auth gate refuses to bind publicly without a provider, so this is
   fail-closed by construction.

2. **Loopback bind fronted by `tailscale serve`** (token QR, zero typing,
   TLS from the tailnet cert):

   ```bash
   tailscale serve --bg 9119        # https://<machine>.<tailnet>.ts.net → 127.0.0.1:9119
   fabric serve --host 127.0.0.1 --port 9119 --qr --qr-url https://<machine>.<tailnet>.ts.net
   ```

   Traffic reaches the gateway from loopback, so token auth applies and the
   QR embeds the token. Treat that QR like a password.

## Build & run

Both apps need a reachable backend — see the pairing section above for the
Tailscale shapes. The plain-LAN equivalent of shape 1:

```bash
fabric serve --host 0.0.0.0 --port 9119 --qr   # requires a configured auth provider
```

In token mode the session token is what the dashboard/desktop use; the
served value is injected into the dashboard index page
(`window.__HERMES_SESSION_TOKEN__`, see
`apps/desktop/electron/dashboard-token.ts`).

### iOS (macOS + Xcode 16 required)

```bash
brew install xcodegen
cd apps/mobile/ios
xcodegen generate        # produces FabricMobile.xcodeproj from project.yml
open FabricMobile.xcodeproj
```

Run the `Fabric` scheme on an iOS 17+ simulator or device. No third-party
dependencies — Foundation `URLSessionWebSocketTask` + SwiftUI only.

### Android (Android Studio Ladybug+ or CLI)

```bash
cd apps/mobile/android
gradle wrapper --gradle-version 8.9   # first time only; wrapper jar is not committed
./gradlew :app:assembleDebug
```

Or open `apps/mobile/android/` in Android Studio. minSdk 26, targetSdk 35.
Dependencies: Compose (BOM), OkHttp, kotlinx-serialization.

## Roadmap after the slice

1. ~~**QR pairing**~~ — done: `fabric serve --qr` + in-app scanners
   (`fabric_cli/mobile_pairing.py`; `PairingURI.swift` / `PairingUri.kt`).
2. ~~**Password (gated) gateway auth**~~ — done: providers discovery,
   `POST /auth/password-login` cookie session, per-connect
   `POST /api/auth/ws-ticket` mint. Remaining from this line: **OAuth
   provider sign-in** via system browser (`ASWebAuthenticationSession` /
   Custom Tabs) for hosted gateways, and automatic ticket re-mint inside a
   reconnect loop (today a drop returns to the connect screen; the cookie
   session usually survives so reconnect is one tap, no password).
3. **Push notifications** — APNs/FCM for `approval.request` and turn
   completion while backgrounded; requires a small gateway-side notifier
   (new server work — the only item here that is).
4. **Attachments & voice** — `image.attach_bytes`, `voice.*` methods already
   exist server-side; wire camera roll + mic.
5. **Reconnect/resilience** — background socket teardown is normal on
   mobile; add resume-on-foreground with `session.history` replay.
6. **Release contract** — signing, store metadata, and a
   `platform-support.md` tier entry before any public build.
