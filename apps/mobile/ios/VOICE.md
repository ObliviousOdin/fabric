# iOS native voice

Fabric's first phone-side voice implementation is deliberately native and
separate from gateway-host voice operations.

## What ships in source

- **Dictation:** the microphone button in Chat uses `SFSpeechRecognizer` and
  `AVAudioEngine`. Partial results are inserted into the composer draft. Fabric
  never sends the draft automatically; the user stops dictation, reviews or
  edits the text, then explicitly sends it.
- **Voice Mode:** the waveform button in Chat starts a hands-free conversation
  loop: listen → transcribe → send → agent works → speak the reply → listen
  again. It uses the same on-device Apple Speech capture as dictation and the
  same `AVSpeechSynthesizer` playback as read-aloud; no phone audio leaves the
  device. See **Voice Mode behavior contract** below.
- **Read aloud:** each completed assistant message exposes **Read aloud** and
  **Stop speaking**. `AVSpeechSynthesizer` reads the answer prose with an
  installed iPhone voice; technical code/diff blocks are announced but not
  spelled character by character.
- **Voice settings:** Settings → Voice lists installed system voices and offers
  a local preview. Enhanced/premium voices remain managed by iOS. Voice Mode
  replies use the same selected voice.
- **Permissions:** Microphone and Speech Recognition are requested just in time
  after the user taps Dictate or starts Voice Mode. Denied states lead to iOS
  Settings. Settings and redacted diagnostics report permission state without
  recording audio or transcript content.

The owning implementation is `Fabric/Core/DeviceVoiceController.swift`, with
Voice Mode's decision logic in `Fabric/Core/VoiceModeSession.swift` (pure,
unit-tested policy) and its surface in
`Fabric/Features/Chat/VoiceModeShell.swift`. `ChatView.swift` owns the draft
merge, prompt submission, and visible controls; Settings owns voice selection
and permission presentation.

## Voice Mode behavior contract

Voice Mode is an explicit conversational operating state, not a new transport:

- **One explicit start.** Capture begins only when the user taps the Voice
  Mode button. Opening Chat, granting permissions, or a previous session never
  starts the microphone.
- **Auto-send is scoped to Voice Mode.** A completed utterance (speech
  followed by the silence window, bounded by a maximum utterance length) is
  submitted as an ordinary prompt. Dictation keeps its never-auto-send
  contract; the two modes cannot run at once.
- **Chat stays the transcript.** Spoken prompts and replies land in the normal
  thread; the shell shows live captions of what has been heard so far, plus a
  factual state: `Listening`, `Muted`, `Finishing what you said…`, `Working…`,
  `Awaiting your approval in chat`, `Speaking`.
- **Approvals are never spoken.** A pending approval or question pauses the
  loop and points at the existing interaction UI. A spoken "yes" cannot
  approve anything, and Voice Mode refuses to submit while an approval is
  pending or the agent is busy — speech never becomes a steering note.
- **Interrupt is reliable.** Mute drops the current utterance without
  submitting; Skip stops a reply mid-sentence and resumes listening; End stops
  playback, releases the microphone, and returns to ordinary chat.
- **Failures are bounded and visible.** Capture errors restart listening at
  most `VoiceModeCapturePolicy.failureLimit` consecutive times before ending
  with visible copy. Audio interruptions, route loss, and media-services
  resets end the session with `Voice Mode ended` copy rather than continuing
  on a route the user never chose. A submitted prompt that produces no agent
  activity within the start timeout resumes listening instead of hanging.
- **Recognition is refreshed, not trusted forever.** Silent listening restarts
  the Apple Speech request before its service window can expire it, so a
  quiet room does not silently kill the session.

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
- Voice Mode owns the microphone and speaker exclusively while active:
  dictation and per-message read-aloud are unavailable until it ends;
- leaving Chat or backgrounding the app stops dictation, read-aloud, and Voice
  Mode; temporary inactivity from an iOS permission sheet does not cancel the
  first dictation attempt;
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
10. Voice Mode completes a real multi-turn spoken conversation: speak → the
    utterance auto-submits after the silence window → the reply is spoken →
    listening resumes, with captions and factual states shown throughout.
11. Voice Mode's Mute drops the current utterance without submitting, Skip
    stops a reply mid-sentence and resumes listening, and End releases the
    microphone (the indicator in the status bar goes away) and restores
    dictation and read-aloud.
12. While a Voice Mode prompt has a pending approval, the shell reads
    `Awaiting your approval in chat`, nothing is auto-submitted, and the
    approval is answerable only through the existing buttons.
13. A phone call, Siri activation, or unplugging the headset during Voice Mode
    ends it with the `Voice Mode ended` alert; no capture continues afterward.
14. VoiceOver announces Voice Mode state transitions (listening, muted,
    working, speaking, ended) and all shell controls are reachable at
    accessibility text sizes.

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
