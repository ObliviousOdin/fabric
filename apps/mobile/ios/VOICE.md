# iOS native voice

Fabric's first phone-side voice implementation is deliberately native and
separate from gateway-host voice operations.

## What ships in source

- **Dictation:** the microphone button in Chat uses `SFSpeechRecognizer` and
  `AVAudioEngine`. Partial results are inserted into the composer draft. Fabric
  never sends the draft automatically; the user stops dictation, reviews or
  edits the text, then explicitly sends it.
- **Read aloud:** each completed assistant message exposes **Read aloud** and
  **Stop speaking**. `AVSpeechSynthesizer` reads the answer prose with an
  installed iPhone voice; technical code/diff blocks are announced but not
  spelled character by character.
- **Voice settings:** Settings → Voice lists installed system voices and offers
  a local preview. Enhanced/premium voices remain managed by iOS.
- **Permissions:** Microphone and Speech Recognition are requested just in time
  after the user taps Dictate. Denied states lead to iOS Settings. Settings and
  redacted diagnostics report permission state without recording audio or
  transcript content.

The owning implementation is `Fabric/Core/DeviceVoiceController.swift`.
`ChatView.swift` owns the draft merge and visible controls; Settings owns voice
selection and permission presentation.

## Processing and privacy boundary

Read-aloud audio is synthesized through iOS and is not sent to the Fabric
gateway. Dictation requires on-device recognition whenever the active Apple
Speech recognizer advertises support. When it does not, iOS may use Apple's
speech service. Raw microphone buffers are streamed only into the Apple Speech
request, are not written to disk by Fabric, and are never sent through Fabric's
JSON-RPC gateway.

The existing gateway `voice.record` / `voice.tts` behavior is intentionally not
called by the iOS app: those operations record from and play on the **gateway
host**, not the iPhone. `GatewayAPI.swift` keeps that boundary explicit.

## Audio lifecycle

There is one `DeviceVoiceController` per Chat surface:

- starting dictation stops read-aloud;
- starting read-aloud stops dictation;
- leaving Chat or backgrounding the app stops both; temporary inactivity from
  an iOS permission sheet does not cancel the first dictation attempt;
- stopping dictation removes the input tap, ends microphone input, and gives
  Apple Speech up to two seconds to return the final phrase before cancelling
  recognition and deactivating the audio session;
- Bluetooth HFP input is allowed for dictation;
- audio interruptions, route invalidation, engine reconfiguration, and media
  service resets stop the affected voice path and expose bounded recovery copy;
- user-selected TTS voice identifiers are stored in `UserDefaults`, never in
  gateway capability state.

A permission request carries a run identity. If Chat disappears while the
system prompt is open, its eventual completion cannot start a stale recording.

## Physical-iPhone release gate

A simulator build cannot prove microphone, speech-model, route, or audible TTS
behavior. Before a release can claim native voice is shipped, record all of the
following against the exact merged source revision:

1. First-use Microphone and Speech Recognition prompts appear only after
   tapping Dictate.
2. Allowed dictation produces partial text, never auto-sends, preserves text
   already in the draft, and remains editable after Stop.
3. Denied permissions show bounded recovery copy and Open Settings; restricted
   Speech Recognition shows device-policy guidance; Settings refreshes after
   returning to the app.
4. On-device recognition works for a supported locale; an unsupported or
   unavailable recognizer fails with clear copy rather than a silent control.
5. Wired, speaker, and Bluetooth headset routes behave correctly; route changes
   and interruptions stop or recover without leaving a live input tap.
6. Background/foreground and navigation away stop recording and speech.
7. Read aloud uses the selected installed voice, changes to Stop speaking while
   active, and stops when tapped or when Chat closes.
8. VoiceOver announces Start/Stop dictation and Read aloud/Stop speaking; all
   controls remain reachable at accessibility text sizes.
9. The archive contains both privacy usage descriptions and its
   `FabricSourceRevision` matches the merged commit.

Until this gate and TestFlight provenance are recorded in `IOS_RELEASES.md`,
this is implemented source—not a shipped-release claim.

## Future model-backed Talk contract

Continuous conversation, provider-hosted STT/TTS, realtime levels, and Android
voice require a new mobile audio contract. Do not route them through the
host-local gateway voice calls. A reviewed contract must define at least:

- capability and provider negotiation;
- input encoding, sample rate, channel count, duration/size limits, locale, and
  whether the request is streaming or bounded;
- partial/final transcript ordering and cancellation receipts;
- TTS voice identifiers, output encoding, chunk ordering, playback ownership,
  and cancellation;
- consent, retention, privacy disclosure, and provider/network failure states;
- idempotency and replay rules for uploads and non-idempotent stream starts.

That transport can later sit behind the same visible Chat controls while native
Apple Speech remains a capability-aware fallback.
