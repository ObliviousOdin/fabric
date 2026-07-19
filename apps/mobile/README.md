# Fabric Mobile (iOS + Android)

Native mobile clients for [Fabric](../../README.md): SwiftUI on iOS and
Jetpack Compose on Android. Both connect to a running Fabric backend
(`fabric serve`) over the same JSON-RPC/WebSocket contract the desktop app
uses — no new server surface is required.

> **Status: development preview.** Both native clients compile and their unit,
> protocol, simulator, debug, and unsigned release checks run from this
> checkout. They are not store releases yet: physical-device accessibility,
> signing, privacy metadata, and hosted-CI gates in `PRODUCTION.md` still apply.

## Quick start

From a Fabric source checkout, one command discovers an attached phone,
installs the native debug app when exactly one target is unambiguous, starts
the authenticated mobile gateway, serves the PWA at `/mobile/`, and prints a
camera-friendly pairing QR:

```bash
fabric mobile
```

Useful variants:

```bash
fabric mobile --devices
fabric mobile --install ios --ios-device <UDID> --ios-team <TEAM_ID>
fabric mobile --install android --android-serial <ADB_SERIAL>
fabric mobile --install none
fabric mobile --qr-url https://<trusted-tunnel-host>
```

Native installation is source-checkout-only because released Python wheels do
not ship Xcode and Gradle source trees. The gateway, QR landing page, and PWA
are included in packaged Fabric installs. `auto` never guesses between devices;
an explicit selector is required when more than one is attached.

The default `0.0.0.0` bind is fail-closed and prompts for/configures an auth
provider. Plain LAN HTTP is useful for native development but browsers normally
require trusted HTTPS to install a PWA. Use `--qr-url` with Tailscale Serve or
another trusted HTTPS tunnel for the installable browser path.

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
- `session.resume` — `{session_id, cols, profile?}` → authoritative stored
  history, in-flight turn, `history_version`, durable `session_key`, and any
  pending approval/clarification/sudo/secret interactions
- `session.list` — → `{sessions: [{id, title, preview, started_at, message_count, source}]}`
- `session.active_list` — live in-memory gateway sessions with runtime status (`working`/`waiting`/`starting`/`idle`)
- `prompt.submit` — `{session_id, text}`
- `prompt.background` — `{session_id, text}` → detached task; result returns as a `background.complete` event
- `session.steer` — `{session_id, text}` → inject a mid-turn note without interrupting (`AIAgent.steer`)
- `session.interrupt` — `{session_id}`
- `slash.exec` / `commands.catalog` — the TUI's slash-command dispatch surface and its registry-backed catalog
- `process.list` / `process.kill` — session-owned background processes (preview servers, watchers)
- `computer.screenshot` — read-only PNG capture of the gateway host's screen (the live-view "PiP"); returns `{png_b64, width, height, mime}` or error 5040 when the host can't capture
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

0. **Servers** — a saved-gateway library. Add a server by scanning its
   pairing QR or entering the address; the app remembers each one and its
   auth mode. Token servers reconnect in one tap (auto-login from the
   stored token); gated servers reconnect silently while their cookie
   session is alive, else prompt for the password. Switching servers is
   "disconnect → pick another" — one active socket at a time (see the
   roadmap for simultaneous connections). See **Saved servers** below.
1. **Connect** — QR pairing or manual URL + token / username+password,
   probe `GET /api/status` to pick the auth mode. Tokens live in the
   Keychain (iOS) / Android Keystore-backed encrypted storage; passwords never
   persist.
2. **Sessions** — `session.list` to resume or start new, plus an
   **Active now** monitor (`session.active_list`) showing live runtime
   status with interrupt control per session. The title names the
   connected server.
3. **Chat** — `session.create`/`session.resume` → `prompt.submit` → live
   streamed transcript (`message.delta`), status/tool activity line,
   interrupt, and approval prompts (`approval.request` → `approval.respond`).
   The overflow menu also opens a **live screen view** — a read-only
   picture-in-picture of the gateway host's screen for watching a
   `computer_use` turn, polling `computer.screenshot`.

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

`fabric mobile` prints a normal browser URL whose `/mobile/pair` fragment
contains the versioned `fabric://pair` payload (contract in
`fabric_cli/mobile_pairing.py`). Phone cameras can therefore open a real landing
page, which attempts the native app and falls back to the same-origin PWA.
Fragments are never sent in HTTP requests, access logs, cookies, or referrers.
Both native apps also accept a direct `fabric://pair` scan from their connect
screens.
Gated binds emit a URL-only QR — credentials never ride in the QR — and the
app follows up with the username/password form. Ungated (loopback/tunnel)
binds embed the session token, so scanning connects with zero typing.

**Phone and machine on the same tailnet** — two supported shapes:

1. **Direct bind to the tailnet address** (username/password on the phone):

   ```bash
   # one-time: configure the bundled password provider
   #   dashboard.basic_auth.username + password_hash in config.yaml
   #   (hash with: python -c "from plugins.dashboard_auth.basic import hash_password; print(hash_password('your-password'))")
   fabric mobile --host <tailscale-ip> --port 9119 --install none
   ```

   The QR carries the URL; the phone asks for the username/password. The
   auth gate refuses to bind publicly without a provider, so this is
   fail-closed by construction.

2. **Loopback bind fronted by `tailscale serve`** (token QR, zero typing,
   TLS from the tailnet cert):

   ```bash
   tailscale serve --bg 9119        # https://<machine>.<tailnet>.ts.net → 127.0.0.1:9119
   fabric mobile --host 127.0.0.1 --port 9119 --install none \
     --qr-url https://<machine>.<tailnet>.ts.net
   ```

   Traffic reaches the gateway from loopback, so token auth applies and the
   QR embeds the token. Treat that QR like a password.

## Saved servers

The app holds a library of Fabric servers rather than a single connection.
Metadata (id, label, URL, auth mode, username) is stored locally; the
session token for a token-mode server is kept in the Keychain (iOS) /
Android Keystore-backed encrypted storage, keyed per server. Passwords are
never stored.

- **Auto-login** — a token server reconnects with no prompt from its saved
  token. A gated server reconnects silently if its in-process cookie
  session is still alive; otherwise the app asks only for the password
  (the username is remembered).
- **Switching** — one socket is active at a time. "Switch server"
  disconnects and returns to the library, where another server is one tap
  away. Truly simultaneous connections (several live sockets, a server
  switcher that keeps them all attached) are a deliberate follow-up: the
  app is built around one shared client today, and multi-client is a larger
  change tracked in the roadmap.

Stores: `GatewayStore.swift` (iOS), `core/GatewayStore.kt` (Android).

## Live screen view (computer use)

When an agent runs the `computer_use` tool, the chat overflow menu opens a
read-only live view of the gateway host's screen. It polls the gateway's
`computer.screenshot` RPC (~1.5s cadence) and renders the returned PNG; no
input is ever sent back from the phone. Hosts that can't capture
(unsupported OS, `cua-driver` not installed) return error 5040 and the view
says so instead of spinning. This is a **view**, not remote control —
driving the desktop stays with the agent, and the phone's levers are the
existing approve / steer / interrupt / prompt controls.

## Build & run

Both apps need a reachable backend — see the pairing section above for the
Tailscale shapes. The plain-LAN equivalent of shape 1 is now the default:

```bash
fabric mobile --install none   # requires or interactively configures an auth provider
```

In token mode the session token is what the dashboard/desktop use; the
served value is injected into the dashboard index page
(`window.__HERMES_SESSION_TOKEN__`, see
`apps/desktop/electron/dashboard-token.ts`).

### iOS (macOS + Xcode 16 or newer)

```bash
brew install xcodegen
cd apps/mobile/ios
xcodegen generate        # produces FabricMobile.xcodeproj from project.yml
open FabricMobile.xcodeproj
```

Run the `Fabric` scheme on an iOS 17+ simulator or device. No third-party
dependencies — Foundation `URLSessionWebSocketTask` + SwiftUI only.

CI-equivalent simulator verification:

```bash
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer \
  xcodebuild -project FabricMobile.xcodeproj -scheme Fabric \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro Max' \
  CODE_SIGNING_ALLOWED=NO test
```

### Android (Android Studio Ladybug+ or CLI)

```bash
cd apps/mobile/android
export JAVA_HOME=/path/to/jdk-17
export ANDROID_HOME="$HOME/Library/Android/sdk"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
./gradlew --no-daemon :app:testDebugUnitTest :app:assembleDebug :app:assembleRelease
```

The pinned Gradle 8.9 wrapper is committed. Or open `apps/mobile/android/` in
Android Studio. minSdk 26, targetSdk 35. Dependencies: Compose (BOM), OkHttp,
kotlinx-serialization.

## Roadmap after the slice

1. ~~**QR pairing**~~ — done: `fabric mobile` + in-app scanners
   (`fabric_cli/mobile_pairing.py`; `PairingURI.swift` / `PairingUri.kt`).
2. ~~**Password (gated) gateway auth**~~ — done: providers discovery,
   `POST /auth/password-login` cookie session, per-connect
   `POST /api/auth/ws-ticket` mint. Remaining from this line: **OAuth
   provider sign-in** via system browser (`ASWebAuthenticationSession` /
   Custom Tabs) for hosted gateways. Password-gated reconnect already mints a
   fresh one-time ticket while the cookie session remains valid.
3. ~~**Saved servers + auto-login**~~ — done: the gateway library, per-server
   token storage, one-tap token reconnect, silent gated reconnect on a live
   session. Remaining here: **simultaneous connections** — one live socket
   per server with a switcher that keeps them all attached — which needs the
   app moved off its single shared client to a client-per-gateway.
4. ~~**Computer-use live view**~~ — done (read-only screen mirror via
   `computer.screenshot`). Interactive control from the phone (tap/type
   injected into the host) is intentionally out of scope pending a
   permission model.
5. **Push notifications** — APNs/FCM for `approval.request` and turn
   completion while backgrounded; requires a small gateway-side notifier
   (new server work — the only item here that is).
6. **Attachments & voice** — `image.attach_bytes`, `voice.*` methods already
   exist server-side; wire camera roll + mic.
7. ~~**Reconnect/resilience**~~ — done: background socket teardown preserves
   gateway/chat identity; foreground reconnect performs an authoritative
   `session.resume` before mutation controls become available.
8. **Release contract** — CI definitions and unsigned release builds are in
   place; signing, store metadata, physical-device QA, and a
   `platform-support.md` tier entry before any public build.
