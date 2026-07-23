# Voice Mode Experience — Product and Implementation Spec

**Status:** proposal, ready to split into implementation tickets

**Primary surface:** Desktop app (macOS, Windows, Linux)

**Surface archetype:** **Command / Inspect** — a focused control surface for talking to an agent while keeping its work legible. It is not a second chat app, a decorative assistant orb, or a settings wall.

## 1. Product decision

Fabric already has the hard parts of voice interaction: browser/CLI voice loops with VAD, STT, streaming TTS, profile isolation, an Electron chat client, and a Live View that can show browser or Computer Use activity in a docked panel or native picture-in-picture (PiP) window.

What is missing is a coherent **voice experience**. Today, a user must infer the relationship between the primary microphone button, dictation, auto-speak, raw TTS/STT settings, profiles, and Live View.

### The update

Turn the desktop microphone into the **single Voice Mode entry point**. It opens one compact launcher that lets the user choose:

1. **Voice** — the voice Fabric will use for spoken replies, with a short, explicit preview.
2. **Attitude** — how Fabric should sound and collaborate, without changing permissions or safety rules.
3. **Profile** — the real Fabric profile that supplies model, SOUL, skills, memory, and credentials.
4. **Work display** — either **Chat only** or **Watch work in PiP**.

One clear `Start voice` action creates a fresh, correctly scoped voice session. During the session, the chat remains the transcript and source of truth while the user can speak, interrupt, mute, see the agent’s real state, and—when selected—watch its visible work in a PiP window.

**Product promise:** *Talk naturally, choose who Fabric is for this task, and decide how much of the work you want to see.*

---

## 2. Experience model

### 2.1 One button, not a pile of toggles

The existing primary `AudioLines` composer button becomes the one entry point for Voice Mode.

| Moment | Behavior |
| --- | --- |
| User taps the microphone | Opens the Voice Mode launcher. It never silently starts recording before the user presses `Start voice`. |
| First use or incomplete audio setup | Launcher shows the exact missing prerequisite and a `Set up voice` route. It does not expose a blank/disabled mic state with no explanation. |
| Existing setup | The last valid profile-scoped selections are preselected, so the launcher is fast rather than a recurring wizard. |
| During a conversation | The same primary control becomes the existing end-conversation control. Mute and stop-turn remain explicit. |
| Keyboard | The existing voice shortcut remains available. It opens/starts the same experience; it must not create a separate configuration path. |

Dictation (audio → editable draft) and `Read replies aloud` remain useful, but are deliberately secondary controls. Voice Mode is a conversational operating state: listen → transcribe → think/act → speak → listen.

### 2.2 Launcher layout

The launcher is a compact **Configure / Command** sheet anchored to the composer. It contains four stacked, inspectable rows—not four tabs and not a full settings page.

```text
┌──────────────────────────────────────────────────────┐
│ Voice Mode                                            │
│ Talk with Fabric while it works                       │
├──────────────────────────────────────────────────────┤
│ Voice       • Nova — warm, clear                [▸]  │
│ Attitude    • Decisive operator                  [▸]  │
│ Profile     • Engineering · model / skills       [▸]  │
│ Display     • Watch work in PiP                  [▸]  │
├──────────────────────────────────────────────────────┤
│ STT ready · TTS ready · captions always on            │
│                                             [Start voice] │
└──────────────────────────────────────────────────────┘
```

Each row opens an inline picker; the user never loses the other choices or their readiness status. The primary action is unavailable only when input transcription is unavailable. If TTS is unavailable, Fabric can still run a **captions-first** voice session, but the button must state `Start with captions` rather than imply spoken output will occur.

### 2.3 Voice

The Voice picker presents only voices that the selected profile can actually use:

- A `Profile default` option always appears first.
- Provider voices are shown with a human label, provider, language when known, and a `Preview` action.
- Preview is explicit, bounded, and uses a fixed local sentence; it never sends the user’s current chat content to a provider.
- A picker cannot expose or persist an API key, reference audio, or any credential-like field.
- A stale/unavailable selection falls back visibly to `Profile default`; it never fails silently mid-conversation.

The existing `tts.*` settings remain the source of truth for provider configuration and credentials. Voice Mode selects a supported **voice reference**, not a parallel TTS provider configuration system.

### 2.4 Attitude

`Attitude` is a small, honest behavior overlay for the new voice session. It changes tone, pacing, and collaboration style—not model access, tool access, approval policy, memory, or the profile’s safety boundary.

V1 offers a deliberately small set:

| Attitude | Spoken behavior |
| --- | --- |
| `Profile default` | Use the profile’s SOUL/personality without an additional overlay. |
| `Clear guide` | Calm, explanatory, checks shared understanding before moving on. |
| `Decisive operator` | Concise, action-led, states what it is doing and what it needs. |
| `Quiet observer` | Speaks only material updates and questions; work remains visible in chat/PiP. |

These are product-facing names, not an invitation to surface novelty personas. The launcher may list profile-configured personalities, but it must not turn a profile’s private SOUL text into a picker preview.

### 2.5 Profile

A profile is a full Fabric identity, not a cosmetic persona. The Profile picker shows:

- profile name and user-authored description;
- its configured model/provider summary;
- readiness state (`ready`, `needs model`, `needs voice setup`);
- no secret values, raw SOUL contents, or private memory snippets.

Selecting a profile always creates a **fresh session bound to that profile**. Fabric must not hot-swap profile, system prompt, tools, skills, or memory inside an existing conversation; that would blur isolation and break prompt-cache invariants.

If the user chooses a different profile from the active desktop gateway, the normal profile-switch/gateway path runs before creating the new voice session. The launcher reports progress honestly rather than pretending the profile is already live.

### 2.6 Work display

The Display picker intentionally has two choices:

| Choice | What the user sees |
| --- | --- |
| `Chat only` | A spoken conversation with persistent captions/transcript. Tool work stays in the normal thread and activity surfaces. |
| `Watch work in PiP` | Chat remains the transcript; when Fabric produces a safe visual work surface, a native PiP window opens automatically. |

`Watch work in PiP` is a presentation preference, **not** permission to use Computer Use, browser automation, terminal access, or any other tool. It never enables a toolset or requests an OS permission.

The PiP priority is:

1. **Computer Use** — show the latest allowed screenshot plus the current action and target application.
2. **Browser** — show the existing live browser stream when one is available.
3. **Coding / terminal work** — show a bounded activity view: current action, files changed, patch summary, command phase, and approval state. It is an activity monitor, not a raw terminal mirror.

When no visual work is occurring, PiP stays closed. The user should never get an empty floating window just because they selected the preference.

---

## 3. In-conversation experience

Once started, Voice Mode adds a compact voice shell above the existing composer; it does not replace the established chat thread.

```text
Engineering · Decisive operator · Watching work

   Listening        Thinking / acting        Speaking
   live level       “Updating the test…”     sentence-by-sentence TTS

[ Mute ]  [ Stop turn ]                                  [ End voice ]
```

### V1 interaction rules

- **Captions are always visible.** User transcript and agent response stay in normal chat even when everything is spoken aloud.
- **State is factual.** Use `Listening`, `Transcribing`, `Thinking`, `Awaiting approval`, `Working`, `Speaking`, and `Paused`; do not show a generic animated orb that implies work with no evidence.
- **Interrupt is reliable.** `Stop turn` ends the user’s current recording while listening. Existing cancellation/approval controls remain visible when Fabric is acting.
- **Voice changes are lightweight.** Voice and display may change for the next spoken response without changing the system prompt. Profile and attitude changes require `Start a fresh voice session`.
- **PiP controls are view controls.** Pause, dock, hide, and close control rendering only. They never pause or cancel the agent. The desktop PiP never accepts click-to-control for Computer Use in V1.
- **End is complete.** Ending Voice Mode stops playback, releases/cancels microphone capture, clears transient audio buffers, and returns to ordinary chat without deleting the transcript.

### Honest visual behavior

Current Computer Use returns action screenshots; it is not a continuous video feed. Voice Mode must label this correctly as `Latest desktop step` and update it on each eligible Computer Use capture/action. Browser work may be labelled `Live` only when the existing browser stream is actually active.

Coding PiP is new work. It must not claim a visual screen recording exists. Its purpose is to answer, at a glance: **what is Fabric doing, what changed, and is it blocked?**

---

## 4. Safety, privacy, and accessibility requirements

### 4.1 Safety

1. Audio input is untrusted user input, exactly like typed input. It does not bypass prompt-injection defenses.
2. Voice Mode never changes approval settings. A spoken “yes” is not sufficient to approve destructive shell actions, OS permissions, payments, passwords, or sensitive external actions; existing explicit approval UI remains authoritative.
3. `Watch work in PiP` never activates Computer Use and never opens a system permission dialog. Computer Use retains its normal capability checks and operator consent.
4. All display events remain allow-listed, bounded, and redacted. Raw tool arguments, raw terminal output, tokens, secrets, and arbitrary screenshots must not be copied into an activity card.
5. The profile boundary applies to every launcher lookup, TTS/STT request, profile switch, session creation, and preference save.

### 4.2 Privacy

- Do not retain microphone recordings after the transcription path completes, except where an existing user-configured provider or platform explicitly owns retention.
- Do not use transcripts as voice previews or provider-training material.
- Keep voice-selection metadata local/profile-scoped and non-secret.
- Preserve the existing redaction and size caps for Live View events. Coding/activity events need the same force-redaction before they leave the backend.

### 4.3 Accessibility

- All Voice Mode states have a screen-reader live label; the waveform is supplemental, not the status source.
- Captions remain readable while speaking and after the voice session ends.
- `Space` stop-turn behavior, mute, end, and launcher choices are keyboard reachable with visible focus states.
- Reduced-motion users receive static state labels rather than a required animated waveform.
- Every microphone, speaker, PiP, and provider error has concrete recovery copy—not icon-only failure.

---

## 5. Technical design

### 5.1 Reuse the capability Fabric already has

| Existing capability | Voice Mode use |
| --- | --- |
| `useComposerVoice` + `useVoiceConversation` | Own the browser microphone/VAD/transcribe/speak loop; expose a launcher-driven session configuration instead of adding a second loop. |
| `voice.auto_tts` + desktop voice playback | Continue as the pure read-aloud preference; Voice Mode maintains its own active conversation state. |
| Profile store and profile-scoped gateway | Resolve and switch the selected profile before session creation. |
| Existing profile descriptions/model metadata | Populate the Profile picker. |
| Live View store and native PiP bridge | Treat `Watch work in PiP` as a presentation preference and auto-open only when a visual/activity surface exists. |
| `tui_gateway.visual_events` | Continue the narrow, redacted DTO path for browser and Computer Use frames. |
| Computer Use approvals and CuaDriver checks | Remain the only source of permission to act on a desktop. |

No new core model tool is needed. This is desktop orchestration, profile/session initialization, and safe rendering at the edge.

### 5.2 New desktop modules

Create a focused `voice-experience/` cluster under `apps/desktop/src/app/chat/`:

- `voice-mode-launcher.tsx` — the one entry-point sheet and readiness state.
- `voice-mode-picker.tsx` — reusable inspectable row/picker shell.
- `voice-mode-session.ts` — session configuration, launch state machine, and profile-safe persistence.
- `voice-mode-copy.ts` — i18n-facing copy keys/fallbacks; no hard-coded user-facing strings in state logic.
- `voice-mode-launcher.test.tsx` and state-machine tests.

Keep `use-composer-voice.ts` responsible for audio conversation mechanics. It receives a resolved `VoiceSessionPlan`; it should not own profile selection, picker UI, or long-lived preference writes.

### 5.3 Data contract

Add a profile-scoped, non-secret configuration block. Exact nesting can follow the configuration schema convention, but the behavioral contract is:

```yaml
voice:
  experience:
    attitude: profile_default        # profile_default | clear_guide | decisive_operator | quiet_observer
    presentation: chat               # chat | pip
    voice_ref: profile_default       # provider-resolved opaque voice reference, never a credential
```

Rules:

- `tts.*` and `stt.*` remain canonical provider setup. `voice.experience.voice_ref` only selects from the resolved catalog.
- Settings are profile-scoped. A profile’s voice, attitude, and display preference travel with that profile.
- The desktop may retain a local non-secret `last selected profile` convenience value. It must fall back to the active profile if the named profile no longer exists or cannot be reached.
- The selected attitude is recorded in session metadata/title context for user legibility and history, but raw prompt overlays are not exposed as transcript content.

### 5.4 Bootstrap and launch protocol

Introduce one desktop-facing, profile-aware bootstrap request (JSON-RPC or existing API shape, depending on the established desktop transport) that returns only:

```ts
interface VoiceModeBootstrap {
  selectedProfile: string
  profiles: Array<{
    name: string
    description?: string
    model?: string
    provider?: string
    ready: boolean
    readinessReason?: 'needs_model' | 'needs_stt' | 'needs_tts'
  }>
  voices: Array<{
    id: string
    label: string
    provider: string
    language?: string
    previewable: boolean
    available: boolean
  }>
  attitudes: Array<{ id: string; label: string; description: string }>
  capabilities: {
    sttReady: boolean
    ttsReady: boolean
    pipSupported: boolean
    computerUseReady: boolean
  }
}
```

This response must be derived from the selected profile’s config and capabilities. It must never include keys, tokens, SOUL contents, memory, filesystem paths, or a raw config dump.

`Start voice` follows this ordering:

1. Validate the selected profile and audio readiness.
2. Switch/ensure the selected profile’s gateway only if necessary.
3. Create a **new** voice session with the resolved profile and attitude before the agent is initialized.
4. Store the display preference in desktop session state without altering prompt/tool state.
5. Start the existing voice conversation loop only after session creation succeeds.
6. Seed the selected Live View presentation preference, but do not open PiP until visual/activity work begins.

This ordering preserves strict profile isolation and the immutable system prompt/toolset contract for a live conversation.

### 5.5 PiP and activity event model

Extend Live View rather than creating a competing overlay:

- Add a session-level `preferredPresentation: 'chat' | 'pip'` that can exist before the first visual tool event.
- On eligible browser or `computer_use` events, use the existing redacted Live View event path and automatically call the existing native PiP bridge only when `preferredPresentation === 'pip'`.
- Add an `activity` Live View kind for coding work. It accepts a small, allow-listed event payload such as `{ phase, label, files_changed_count, changed_files?, command_category?, approval_state? }`.
- `changed_files` must be capped, redacted, and path-normalized; raw command text and arbitrary terminal output are out of scope.
- Prefer emitted `tool.start`, `tool.complete`, patch/write summaries, and approval events. Do not add a polling loop for the PiP.
- Preserve bounded retention and current protection against oversized image data. Pause/hide must stop retaining frames immediately.

### 5.6 Attitude resolution

Attitude is resolved before session startup using a small registry of named, reviewed overlays. It is not a freeform user string passed to the system prompt.

The resolution order is:

1. selected named attitude;
2. selected profile SOUL/personality;
3. Fabric’s normal system behavior.

A profile switch or attitude change from an active session requires a clear choice: `End and start a fresh voice session` or `Keep current session`. Do not mutate a live system prompt, toolset, or cache prefix.

---

## 6. Phased delivery

### Phase 1 — coherent desktop Voice Mode

**Goal:** one button, one launcher, one trustworthy voice conversation loop.

- Implement the launcher, profile picker, attitudes, readiness states, and Start flow.
- Add profile-scoped `voice.experience` configuration and migration-safe defaults.
- Reuse the current desktop microphone/STT/TTS loop and transcript UI.
- Make caption-first fallback and all error states explicit.
- Do not change gateway, CLI, Telegram, Discord, or voice-channel behavior.

**Acceptance:** a user can choose a configured profile, a voice, an attitude, and `Chat only`, then complete a real multi-turn voice conversation with the selected session identity displayed in chat.

### Phase 2 — PiP for work already visible

**Goal:** make `Watch work in PiP` real without inventing a new automation capability.

- Seed Live View presentation preference from Voice Mode.
- Auto-pop native PiP for eligible browser and Computer Use events.
- Keep the PiP read-only and preserve existing dock/hide/pause controls.
- Label Computer Use as step snapshots unless a true stream is present.

**Acceptance:** a voice session set to PiP opens a native window only when Fabric begins browser/Computer Use work; no PiP opens for text-only work, and no automation permission is changed.

### Phase 3 — coding/activity PiP

**Goal:** provide useful operational visibility for code and terminal work.

- Add the bounded `activity` Live View kind and safe event projection.
- Render phase, files changed, current operation, approvals, and final outcome.
- Add tests proving secrets/raw terminal bodies cannot enter the PiP event payload.

**Acceptance:** while Fabric edits code, the PiP answers what is happening and what changed without exposing a terminal mirror or claiming screen video.

### Phase 4 — optional parity work

**Goal:** decide deliberately which parts belong outside Desktop.

- CLI/TUI may adopt the same attitude/profile preflight semantics, but retain their native controls.
- Messaging platforms keep their existing per-chat auto-TTS behavior; they do not receive a desktop PiP metaphor.
- Mobile can reuse the launcher contract later, with a mobile-native work view rather than Electron’s native PiP window.

---

## 7. Non-goals

- No new core model tool.
- No automatic toolset enablement, capability grants, or approval bypasses.
- No voice-command approval for high-impact actions.
- No profile or personality mutation inside an active session.
- No raw terminal streaming, keystroke replay, secret display, or unredacted tool result in PiP.
- No claim that Computer Use is live video when only action screenshots exist.
- No redesign of current CLI, gateway voice notes, or Discord voice channels in the first desktop release.
- No voice cloning, custom voice training, or storage of user microphone recordings in V1.

---

## 8. Verification plan

### Desktop unit and component tests

- Launcher opens only from the single Voice Mode entry point and does not start recording before `Start voice`.
- Preselected values are profile-scoped; deleted/unreachable profiles fall back safely.
- A profile change causes a fresh session path; it never mutates the active session’s system prompt/toolset.
- `Chat only` never auto-opens Live View; PiP opens only after an eligible event.
- TTS/STT unavailable, preview failure, profile-switch failure, and PiP unsupported states have actionable copy.
- Keyboard, screen-reader status, reduced-motion, mute, stop-turn, and end behavior are covered.

### Backend/config tests

- Default/migration behavior for `voice.experience` is schema-safe and profile-safe.
- Bootstrap payload contains no credential, SOUL, memory, raw config, or secret-looking values.
- Attitude registry accepts only known IDs.
- Coding/activity event DTOs are bounded, allow-listed, and force-redacted.

### End-to-end checks

1. Start with a configured STT/TTS profile; select voice, attitude, and Chat only; complete two spoken turns.
2. Select a different profile; verify a fresh session is created under that profile and the prior session remains unchanged.
3. Select PiP; run a Browser or Computer Use task; verify PiP appears only with a visual event and closes/hides cleanly.
4. Run code-editing work; verify Activity PiP reports summaries without raw command output or sensitive strings.
5. Attempt a destructive action by voice; verify the existing explicit approval path still owns consent.

---

## 9. Source surface audit (current implementation)

The proposal is based on the current Fabric tree, not a hypothetical rewrite:

- Desktop voice loop: `apps/desktop/src/app/chat/composer/hooks/use-composer-voice.ts` and `use-voice-conversation.ts` already implement continuous listening, transcription, streaming spoken chunks, mute, stop-turn, and end.
- Desktop entry/control surface: `apps/desktop/src/app/chat/composer/controls.tsx` already has the primary Voice Mode button, dictation, auto-speak, and active conversation pill.
- Voice preferences/settings: `apps/desktop/src/store/voice-prefs.ts` and `apps/desktop/src/app/settings/config-settings.tsx` already persist/read raw voice configuration.
- Existing profile isolation: the desktop profile store switches the live gateway per profile; profiles carry separate config, model, skills, SOUL, memory, and credentials.
- Existing visual PiP: `apps/desktop/src/store/live-view.ts` and `app/chat/live-view/live-view-pane.tsx` already support docked and native PiP browser/desktop views with bounded state.
- Existing safe visual projection: `tui_gateway/visual_events.py` allow-lists/redacts/bounds browser and Computer Use event data; it is the model for the coding/activity projection.
- Existing Computer Use integration: `computer_use` retains its independent checks, permissions, and approval rules; Voice Mode only observes it.

## 10. Decision for implementation

Build **Phase 1 and Phase 2 as one user-facing release**: the launcher makes Voice Mode feel intentional, and the existing Live View makes `Watch work in PiP` tangible without waiting for terminal visualization. Phase 3 is a separate, safety-sensitive activity-projection effort and should not block the first release.
