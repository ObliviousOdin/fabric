# Fabric Watch — macOS verification handoff

This branch carries the full W-relay implementation from
[`../WATCH.md`](../WATCH.md) (slices **W0 scaffold + W2 quick notes + W3 pet
surfaces**, client side), authored in a Linux environment that cannot run
XcodeGen or compile Swift. This file is the §7.4 `AGENT_GUARDRAILS.md` HANDOFF
block for the next (macOS) session; keep it current on every push.

## HANDOFF

- **State:** blocked — needs a macOS session to regenerate + build + test.
- **Done:**
  - `project.yml`: `FabricWatch` (watchOS 10 companion app, embedded in the
    iOS app) + `FabricWatchWidgets` (WidgetKit extension, accessory
    complications + Smart Stack) + `FabricWatch` scheme.
  - Shared wire contract `Fabric/WatchBridge/WatchRelayContract.swift`
    (context/note/reply/voice/sprite codecs, queue policy, frame layout math,
    pose vocabulary, widget snapshot) — compiled into the iOS app, watch app,
    and widget so validation cannot drift.
  - iPhone relay `Fabric/WatchBridge/WatchRelay.swift`: `WCSession` lifecycle,
    deduplicated context publishing, once-per-revision sprite `transferFile`,
    note delivery through the **gated** `session.create` + `prompt.submit`
    path (one note = one goal session), and honest `unavailable` replies that
    keep undelivered notes on the watch.
  - Phone voice-note pending store + Apple Speech file transcription
    (`WatchVoiceNoteStore.swift`), bounded by the same TTL/cap as the watch
    queue, drained on foreground, cleared by full local reset.
  - Watch app (`FabricWatch/`): pet home screen (relayed spritesheet renderer
    with always-on dimming + pose-symbol fallback), `TextFieldLink` dictation
    notes, AAC voice-note recorder (2-minute cap), bounded persisted note
    queue, honest per-hop status line, attention row for `waiting`.
  - Widget extension (`FabricWatchWidgets/`): circular / corner / inline /
    rectangular pet-glance complications reading the shared app-group
    snapshot; reloads are app-driven and deduplicated.
  - Integration edits: `FabricMobileApp` (+`watchRelayBridge`), `ChatView`
    (pet-state `onChange` relay), `AppModel.resetLocalAppData` (voice-note
    store cleanup).
  - `FabricTests/WatchRelayContractTests.swift` — codec round-trips,
    fail-closed validation, queue policy, sprite frame math, pose invariants.
  - `tests/scripts/test_ios_project_generation.py` — release rendering now
    asserts the watch/widget/companion/app-group identities rewrite together.
- **Verified (on Linux):**
  - `python3 tests/scripts/test_ios_project_generation.py` — 15/15 pass
    against the real `ci_post_clone.sh` with the new manifest.
  - `project.yml` parses; target/dependency/scheme shape checked.
- **Not verified (requires this handoff):**
  - **All Swift compiles.** Nothing Swift was compiled — no toolchain here.
  - **XcodeGen accepts the watch target shape** (watchOS `application`
    embedded via iOS-app dependency; widget embedded via watch-app
    dependency). If the embed phase lands wrong, fix in `project.yml`, never
    by editing the generated project.
  - The committed `FabricMobile.xcodeproj` is **intentionally behind
    `project.yml`** on this branch. Regeneration on a Mac closes the gap.
  - Simulator behavior: relay round-trip, sprite transfer, dictation,
    recording, complication rendering.
- **Remaining (ordered):**
  1. On a Mac: `sh apps/mobile/ios/scripts/mac-watch-handoff.sh` — regenerates
     the project, re-runs the generation tests, builds the watch scheme, runs
     `FabricTests`. Commit the regenerated `FabricMobile.xcodeproj` plus the
     generated `FabricWatch/Info.plist`, `FabricWatch/FabricWatch.entitlements`,
     `FabricWatchWidgets/Info.plist`,
     `FabricWatchWidgets/FabricWatchWidgets.entitlements` on this branch.
  2. Fix whatever the compiler finds (the Swift was written blind; expect
     small breakage, not design breakage) and re-run the script until green.
  3. Paired-simulator smoke: iPhone + watch simulators — pair, connect a
     gateway on the phone, confirm context/sprite arrive, send a dictated
     note, confirm a new session appears; record a voice note, confirm
     transcription + submission on foreground.
  4. Coordinate the `mobile.yml` change (shared surface, §2.1) — proposed
     diff below.
  5. Register the app group (value in `project.yml`) in the signing team's
     account before any device/TestFlight build; simulator builds don't
     need it.
  6. Physical-device pass per `WATCH.md` §7 before calling any slice shipped.
- **Risks / land-mines:**
  - Do **not** merge before step 1 lands: iOS CI runs only on `main`
    (§4.2) — a green PR here proves nothing about the native build, and the
    generation diff check on `main` will fail while the committed project
    lags the manifest.
  - The release bundle-ID rewrite depends on every watch identity being
    **prefix-derived** from `io.github.obliviousodin.fabric.mobile` (the
    generation tests pin this). Never introduce a watch bundle ID that isn't.
  - `WatchRelay` publishes chat pet state only while a chat surface is on
    screen; the watch falls back to steady idle otherwise. That is designed
    degradation, not a bug (single-brain rule in `WATCH.md` §2).
  - Notifications on the wrist arrive via iPhone mirroring once Loop 8
    (`push.register_device`) ships — nothing watch-side to build for W1.
- **Zone(s) touched:** Mobile — iOS (`apps/mobile/ios/**`) and its generation
  test. No shared surfaces edited; the `mobile.yml` change below is proposed,
  not applied.

## Proposed `mobile.yml` change (do not apply without §2.1 coordination)

In the `ios` job, after the existing generation step:

```yaml
      - name: Verify committed project matches the generator
        run: |
          git diff --exit-code -- \
            FabricMobile.xcodeproj \
            Fabric/Info.plist \
            FabricWatch/Info.plist \
            FabricWatch/FabricWatch.entitlements \
            FabricWatchWidgets/Info.plist \
            FabricWatchWidgets/FabricWatchWidgets.entitlements

      - name: Build watch app (simulator)
        run: |
          xcodebuild build \
            -project FabricMobile.xcodeproj \
            -scheme FabricWatch \
            -destination "generic/platform=watchOS Simulator" \
            CODE_SIGNING_ALLOWED=NO
```

(Adjust the first block to match however the existing diff check is phrased
in the job — extend its path list rather than duplicating it.)
