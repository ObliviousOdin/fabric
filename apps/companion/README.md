# Fabric Companion

**An always-on-top desktop pet for Fabric** — a native overlay (Rust +
[Bevy](https://bevy.org) 0.19) that renders your installed
[petdex](https://github.com/crafter-station/petdex)-style pet above every
window and animates it with what your agent is doing right now: thinking,
running tools, waiting on you, celebrating a finished turn, or slumping when
something fails. In between, it loafs and strolls along the bottom of the
overlay with the same roaming character as the desktop app's floating pet.

This is **phase 1** of the companion: a display-only surface. Like every pet
surface in Fabric, it adds no model tool, mutates no prompt, and never writes
runtime state — it renders the same `~/.fabric/pets/` store and the same
activity semantics as the CLI, TUI, and Electron desktop.

```
┌──────────────────────────────────────────────────────────────┐
│ fabric backend (fabric serve / fabric dashboard)             │
│   └── /api/ws  JSON-RPC ── message/tool/reasoning events     │
└──────────────┬───────────────────────────────────────────────┘
               │ tokio-tungstenite thread → crossbeam channel
┌──────────────▼───────────────────────────────────────────────┐
│ fabric-companion (Bevy)                                      │
│   ActivityTracker ─ derive_pet_state ─ atlas row ─ sprite    │
│   RoamLoop (idle only) ─ position/facing                     │
└──────────────────────────────────────────────────────────────┘
```

## Try it

```bash
cd apps/companion
cargo run --release            # demo mode: procedural pet + scripted turns
```

With no connection flags the companion runs a built-in demo: a procedurally
generated placeholder blob (Fabric brand colors, full Codex atlas contract)
replays a scripted turn — greet, think, run tools, wait for input, celebrate,
fail — with roaming in between. If you have a pet installed
(`fabric pets install <slug>`), it is used automatically; the blob is the
zero-assets fallback.

## Mirror a real agent

Three ways to connect, in increasing order of ceremony:

```bash
# 1. Spawn a private backend (the same thing the Electron app does):
cargo run --release -- --spawn --prompt "say hi"

# 2. Attach to a running `fabric dashboard` (default port 9119):
cargo run --release -- --url ws://127.0.0.1:9119/api/ws --token <TOKEN>

# 3. Same, but resume an existing stored session:
cargo run --release -- --url ... --token <TOKEN> --resume-recent
```

- `--spawn` runs `fabric serve --host 127.0.0.1 --port 0` with a pinned
  session token (passed through the backend's legacy-compatibility
  `HERMES_DASHBOARD_SESSION_TOKEN` environment variable, the same handshake
  the Electron desktop uses) and reads the announced port from its stdout.
- For `--url`, the token is the per-process dashboard session token. The
  dashboard injects it into its served page; you can also pin your own by
  exporting that same variable before starting the backend. The flag falls
  back to `$FABRIC_COMPANION_TOKEN`.
- **Session semantics**: by default the companion creates its *own* session
  (safe). `--session <id>` / `--resume-recent` re-bind an existing session's
  event stream to the companion — the backend routes each session's events to
  one transport, so another attached surface (desktop, dashboard) stops
  receiving them. That trade-off is yours to make; the flags exist because
  watching *your* session is the point.

## What the pet does

The activity → animation mapping is the same priority ladder every Fabric
surface uses (`agent/pet/state.py`, mirrored here and conformance-tested —
see below):

| Signal | State | Row shown |
| --- | --- | --- |
| turn failed | `failed` | failed |
| turn completed | `jump` (2.2 s beat) | jumping |
| session bound | `wave` (greeting) | waving |
| blocked on you (clarify/approval) | `waiting` | waiting |
| tool executing | `run` | running (in place) |
| model thinking | `review` | review |
| turn in flight | `run` | running (in place) |
| otherwise | `idle` | idle (+ roaming) |

Roaming (idle only) ports the desktop's loop: exponential dwell (~4.2 s mean),
62 % chance per beat to keep loafing, strolls of at least 45 % of the floor
span biased toward open space, walk speed foot-synced to 0.8 body-widths per
animation loop, and a gravity drop-in on launch. Directional
`running-right`/`running-left` rows are used when the sheet has them
(mirrored fallbacks otherwise), and at rest the pet always faces inward.

## Configuration

The companion reads the same config every other surface writes — no new
files:

- `~/.fabric/pets/<slug>/` — pet store (`pet.json` + `spritesheet.webp|png`).
- First-party packages under `agent/pet/assets/` (notably `fabric-mascot`)
  when no usable profile package exists for the configured slug.
- `~/.fabric/config.yaml` → `display.pet.slug` and `display.pet.scale`
  (0.1–3.0, default 0.33).
- `FABRIC_HOME` env var relocates the state directory (legacy fallbacks
  honored like `fabric_constants.get_fabric_home`).
- `FABRIC_BUNDLED_PETS` optionally points at an alternate bundled-assets root.

CLI flags override config: `--pet <slug>`, `--scale`, `--no-roam`,
`--width/--height/--position`, `--floor-offset` (keep the floor above a
taskbar), `--interactive` (disable click-through), `--demo`. Run with
`--help` for everything.

## Platform notes (winit 0.30 via Bevy 0.19)

| Capability | Windows | macOS | X11 | Wayland |
| --- | --- | --- | --- | --- |
| transparent window | ✅ | ✅ (PostMultiplied alpha) | ✅ (needs compositor) | ✅ |
| always-on-top | ✅ | ✅ | ✅ | ❌ (compositor-managed) |
| click-through | ✅ | ✅ | ❌ | ✅ |
| skip taskbar/dock | ✅ | ➖ (needs LSUIElement) | ➖ | ➖ |
| programmatic position | ✅ | ✅ | ✅ | ❌ |

The overlay works everywhere; the degradations are per-capability (e.g. on
X11 the window is interactive since hit-test passthrough is unsupported).

## Architecture

Two crates, deliberately split:

- **`crates/companion-core`** (`fabric-companion-core`) — engine-agnostic
  logic: the `derive_pet_state` priority ladder, atlas taxonomy + blank-trim
  frame counting, the read-only pet store + config readers, the `/api/ws`
  frame parsing + `ActivityTracker` fold, and the roam state machine. No
  Bevy dependency; unit-tested with deterministic clocks and RNG.
- **`crates/companion-app`** (`fabric-companion` binary) — the Bevy shell:
  window/overlay setup, texture atlas + frame clock, the tokio WebSocket
  bridge thread, the demo feed, and `--spawn` backend bootstrap.

### Conformance vectors

`agent/pet/state.py` is the canonical activity→state implementation, with
mirrors in TypeScript (desktop) and Rust (here).
`conformance/derive_pet_state.json` enumerates **all 128 combinations** of
the seven input signals with the canonical result; it is asserted by
`tests/agent/test_pet_state_vectors.py` (Python) and
`crates/companion-core/tests/conformance.rs` (Rust), so a priority-ladder
change that forgets a mirror fails loudly instead of drifting.

### Event → activity wiring (desktop parity)

`reasoning.delta`/`reasoning.available` → thinking; `tool.start` → tool
running; `message.complete` → 2.2 s celebrate beat (single shared flash
timer, clears stale error beats); `error` → 1.6 s failed beat;
`clarify.request`/`approval.request`/`sudo.request`/`secret.request` →
waiting until answered or the turn ends; steady flags only count mid-turn so
an interrupted turn can't pin RUN/REVIEW.

## Roadmap

1. ✅ **State mirror** — this scaffold.
2. **Speech bubble + approvals** — status quips over the pet; surface
   `approval.request` as a click-to-answer card (the protocol responses
   `approval.respond` etc. are already modeled in core).
3. **Input surface** — click-to-chat popover (`prompt.submit`), drag
   repositioning (`RoamLoop::place` is ready), global summon hotkey,
   push-to-talk voice via the backend's transcription/TTS providers.
4. **Richer embodiment** — star-shower celebrate particles, egg hatch for
   `pet.generate`, one pet per subagent, monitor-aware multi-window roaming.

## Development

```bash
cargo test                 # core logic + conformance vectors
cargo clippy --workspace
cargo run -- --demo        # zero-config visual check
# Python side of the shared vectors:
scripts/run_tests.sh tests/agent/test_pet_state_vectors.py -q   # from repo root
```

Linux builds need `libwayland-dev` and `libxkbcommon-dev` (plus a Vulkan- or
GL-capable driver at runtime).
