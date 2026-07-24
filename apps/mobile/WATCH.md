# Fabric Watch — Apple Watch companion design contract

This document is the design contract for Journey 11 in
[`JOURNEYS.md`](JOURNEYS.md) (*Apple Watch companion*, executed in Loop 9 of
[`UPGRADE_PLAN.md`](UPGRADE_PLAN.md)). It answers three product questions
before any Xcode target exists:

1. Can Fabric be "the watch face"? What is actually possible on watchOS?
2. How does the Fabric pet become the identity of the wrist experience?
3. How do quick notes and notifications work against the existing gateway
   contracts?

Like the other documents in this directory it is a contract, not aspiration:
every mechanism below names the platform API or existing Fabric contract it
rides on, and §7 states exactly which gates must pass before any of it is
called shipped.

---

## 1. The watch-face question — platform reality

**watchOS does not allow third-party watch faces.** Through watchOS 26 Apple
has never opened face creation to apps; nothing on the App Store replaces the
face, and nothing here should pretend to. What the platform *does* allow gets
close enough to matter, in increasing order of engineering cost:

| Option | Mechanism | What the user sees | Cost |
| --- | --- | --- | --- |
| **Photos-face album** | Export pet artwork to a synced album; the user picks the *Photos* face | The pet as the face background, static, rotating per wrist-raise | Near zero (art export only) |
| **Complications** | WidgetKit accessory families (`accessoryCircular`, `accessoryCorner`, `accessoryInline`, `accessoryRectangular`) | A pet state frame + attention badge on the face the user already uses | Low |
| **Smart Stack widget** | WidgetKit (watchOS 10+); Live Activity mirroring (watchOS 11+) | A "goal running / attention needed" card one crown-turn from the face | Low–medium |
| **The app as wake screen** | Always-on display + the user's per-app *Return to Clock* setting | The animated pet screen stays up when the wrist raises — the de facto face | Medium (the full app) |
| **Notification long-looks** | `UNNotificationContentExtension`-style custom notification views | The pet waves on completion, slumps on failure, right in the notification | Low, after push exists |

The honest product framing: **complications + the Smart Stack are "on the
watch face"; the pet app with *Return to Clock* set to stay in-app is "as the
watch face."** Both are legitimate; neither is a literal custom face, and no
release note should claim otherwise.

Not possible, to save future spelunking: replacing or animating the face
itself, dynamic app icons, arbitrary background animation while the app is not
frontmost, and third-party faces distributed outside the Photos-face
mechanism.

---

## 2. The pet as the wrist identity

The pet is already a cross-surface Fabric contract, not a desktop skin:

- **Engine** — `agent/pet/` owns spritesheet geometry (192×208 frames, 8×9
  atlas), the per-state frame budget (6 frames, 1100 ms loop), and the single
  activity→animation decision in `agent/pet/state.py::derive_pet_state`
  (priority: `error` → `celebrate` → `just_completed` → `awaiting_input` →
  `tool_running` → `reasoning` → `busy` → `idle`).
- **Transport** — the gateway `pet.info` RPC serves the active pet's
  spritesheet payload plus per-state frame counts; the TUI and the desktop
  floating pet both consume it (`apps/desktop/src/store/pet.ts` mirrors the
  Python priority order).

The watch adds *renderers*, never a second brain:

1. **Watch app pet screen** — SwiftUI `TimelineView` steps the atlas frames at
   the engine's loop cadence; in always-on dimmed mode it degrades to a single
   static frame of the current state (per Apple's always-on update budget).
   State changes arrive over the phone relay (§5), reusing the exact
   `derive_pet_state` inputs the phone already tracks.
2. **Complication** — one frame of the current state per accessory family,
   tinted-mode-safe, plus an SF Symbol badge for `awaiting_input` (approval
   pending) and unread-completion. A complication is a glance contract: state
   frame + badge, no text soup.
3. **Notification imagery** — completion notifications attach the `wave`
   frame, failures the `failed` frame, so the pet carries outcome tone before
   a word is read.
4. **Photos-face export** — a `fabric pet` art-export path (existing sprite
   assets rendered to wallpaper-sized stills) gives the zero-code "pet watch
   face" from day one.

The spritesheet ships to the watch via `WCSession.transferFile` once per pet
revision (the payload already carries a stable `spritesheetRevision`), so the
watch never re-downloads sprites it has and never talks to petdex.dev itself.

---

## 3. Quick notes

Input on watchOS is dictation-first (system dictation and scribble via the
standard text-input flow, QWERTY on larger devices), plus raw audio capture —
which maps cleanly onto contracts Fabric already has:

- **Dictated text note** — the system text-input flow returns plain text; the
  watch relays it to the phone, which submits through the *gated*
  `prompt.submit` path exactly like a typed phone message. No new gateway
  surface.
- **Audio voice note** — `AVAudioRecorder` capture on the watch, relayed as a
  `fabric.phone_audio` v1 payload with `mode: "voice_note"`
  (`contracts/fabric-voice-v1/`). Transcription stays where it lives today:
  Apple Speech on the phone or the gateway's STT path. The Speech framework is
  not available on watchOS, so the watch never claims on-device
  transcription — it captures and relays.
- **Offline capture** — notes queue on the watch and drain through the phone's
  existing outbound rules. `PRODUCTION.md` rules out blind offline replay of
  side-effecting RPCs; the watch inherits `OutboundMessageQueue` semantics
  (bounded, definitely-unsent only, never steer notes) rather than inventing a
  second queue policy.

The core interaction budget: **raise wrist → one tap (or Double Tap on
supported hardware) → speak → done.** Anything past two taps before speech
starts is a design failure for this journey.

---

## 4. Notifications

The dependency ordering matters more than the watch code:

- **Mirroring is free.** Once Loop 8 lands the APNs push backbone on the
  iPhone app (`push.register_device`, redacted lock-screen copy, deep links —
  [`ARCHITECTURE.md`](ARCHITECTURE.md) §5), watchOS mirrors those
  notifications to the wrist automatically whenever the phone is locked and
  the watch is worn. **The first shippable watch experience is therefore Loop
  8 with zero watch-specific code.**
- **Watch-native polish comes second.** A watch app target upgrades mirrored
  notifications to custom long-looks (pet imagery, §2) and adds
  complication/Smart Stack refresh. Timely complication updates ride the same
  APNs lifecycle; background-refresh budgets alone give roughly
  four updates per hour, so "live" pet state on the face requires push.
- **Standalone watch APNs registration** (the watch as its own `push`
  device) is deliberately deferred until a direct-connection mode (§5) exists.
  Per §5 of `ARCHITECTURE.md`, no surface ever simulates a "notification
  sent" state.

Redaction rules are inherited unchanged: lock-screen and long-look copy stays
minimal and links to the exact in-app interaction; approvals never render as
one-tap high-risk applies from a notification — on the wrist that rule is
load-bearing, not cosmetic.

---

## 5. Architecture — relay first, direct later

Journey 11 already names the two transports; this contract sequences them:

- **W-relay (default): relay-via-iPhone.** The watch app is a companion
  surface of the paired phone. `WCSession.sendMessage` carries live pet state
  and note submissions when both apps are reachable; `transferUserInfo`
  queues them otherwise; `transferFile` ships spritesheets. The watch holds
  **no gateway credentials** in this mode — the phone remains the single
  authenticated client, so pairing, capability gating, Keychain custody, and
  offboarding stay exactly where they are audited today.
- **W-direct (deferred): direct connection.** A watch-initiated `wss://`
  session for phone-absent use (LTE models on the same network as the
  gateway). This requires enrolling the watch as its own node identity with
  its own Keychain-held token and its own revocation row in the Trust Center
  — i.e. it depends on the Loop 5 consent/grant substrate and is out of scope
  until that ships. Tailnet access from watchOS is not assumed; W-direct is
  honest about only working where the gateway is plainly reachable.

Everything user-visible in W-relay must degrade explicitly when the phone is
unreachable: the pet shows a disconnected pose, capture still works, queued
notes show as queued. No spinner theater.

---

## 6. Delivery plan

Each slice is independently shippable and ordered by value-per-verified-line;
W2 onward requires the W0 scaffold.

| Slice | Scope | Depends on |
| --- | --- | --- |
| **W1 — Mirrored notifications** | Loop 8 push on the iPhone app; zero watch code. Completion + attention alerts reach the wrist, redacted, deep-linking to the phone | Loop 8 |
| **W0 — Target scaffold** | `watchOS` app + widget-extension targets added to `project.yml`, regenerated project, schemes, CI wiring | macOS toolchain (§7) |
| **W2 — Quick notes** | Dictation + voice-note capture over W-relay, offline queue semantics | W0, Loop 4 queue |
| **W3 — Pet surfaces** | Animated pet screen, accessory complications, Smart Stack widget, Photos-face export | W0; push for timely complication refresh |
| **W4 — Attention on the wrist** | Approval glances with the full redaction/first-answer-wins rules from `ARCHITECTURE.md` §5 | W2, Loop 8 |

W1 before W0 is deliberate: mirrored notifications deliver the highest-value
wrist moment (the agent finished / needs you) without a single watch target,
so the expensive native scaffold is never the critical path for the first
user-visible win.

---

## 7. Verification gates — what this environment cannot do

All watch-target work sits behind the same cost gate as iOS
(`AGENT_GUARDRAILS.md` §4.2): **nothing under `apps/mobile/ios/` builds on
PRs**, and the committed `FabricMobile.xcodeproj` must byte-match what
`ci_scripts/ci_post_clone.sh` regenerates from `project.yml`. Consequences:

- **W0 requires a Mac.** Adding watch targets means editing `project.yml`,
  regenerating with the pinned XcodeGen, updating
  `tests/scripts/test_ios_project_generation.py`'s expectations, and building
  the watch scheme locally. A Linux agent must not hand-edit the project or
  push a manifest the generator has not reproduced — that is the exact
  stale-generated-file trap in `AGENT_GUARDRAILS.md` §5.
- **CI wiring is a shared surface.** Extending `mobile.yml` to build the
  watch scheme touches `.github/workflows/` and follows the coordination rule
  in `AGENT_GUARDRAILS.md` §2.1.
- **Shipping evidence is physical.** Per the cross-phase gates in
  [`ROADMAP.md`](ROADMAP.md), each slice needs the usual screenshot fixtures
  plus a worn-device pass: wrist-raise latency, always-on dimming, Double Tap
  where supported, and a real dictation round-trip. Simulator-only evidence
  does not close a slice.
