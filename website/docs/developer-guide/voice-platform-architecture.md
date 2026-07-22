---
sidebar_position: 9
title: "Voice Platform Architecture"
description: "Contracts and phased roadmap for native capture, transcription, and voice-note workflows"
---

# Voice Platform Architecture

This document defines the target architecture and phased roadmap for reusable
transcription results, voice-note workflows, system-wide dictation, and
phone-owned audio. It complements the current [Voice Mode feature
reference](/user-guide/features/voice-mode) and [setup
guide](/guides/use-voice-mode-with-fabric); roadmap items below are not claims
that an unshipped feature is already available.

## Implementation Status

- Fabric already supports CLI and messaging voice modes and the Desktop chat
  microphone; the native iOS dictation/read-aloud implementation is merged.
- Native iOS voice landed in [PR #100](https://github.com/ObliviousOdin/fabric/pull/100)
  and is the phone-owned baseline for this roadmap.
- Reusable rich transcription results, Voice Notes, Android capture,
  system-wide Ask Fabric, IME integration, and App Intents remain phased work.

## Problem

Fabric can already record microphone audio in Desktop and route it through the configured speech-to-text provider. Native iOS capture is phone-owned and uses the platform speech stack. Fabric does not yet have a reusable rich transcription contract, a voice-note workflow, or a shared phone-audio result contract. AutoWhisper provides local Whisper inference, microphone capture, global hotkeys, and text injection, but needs a stable service protocol before another application can consume its runtime.

## Solution

Extract a reusable AutoWhisper runtime with a versioned, local stdio protocol, publish an AutoWhisper-owned Fabric transcription plugin that uses Fabric's existing `/api/audio/transcribe` path, and add a versioned `TranscriptionResult` plus phone-audio contract to Fabric. Build Desktop Voice Notes, opt-in system-wide Dictate and Ask Fabric modes, and native iOS/Android capture on those contracts. Keep meeting capture, diarization, wearables, widgets, and broad background recording as later layers.

## Product Modes

| Mode            | Audio owner                                | Model behavior                                | Output                                                                 |
| --------------- | ------------------------------------------ | --------------------------------------------- | ---------------------------------------------------------------------- |
| Dictate         | AutoWhisper desktop runtime                | No Fabric model call                          | Inject cleaned transcript into the focused application                 |
| Voice Note      | Fabric Desktop/mobile client               | Transcribe, then one explicit Fabric workflow | Reviewed Markdown result with summary, decisions, tasks, and follow-up |
| Ask Fabric      | AutoWhisper hotkey/action or Fabric client | One explicit Fabric conversation turn         | Fabric answer in the chosen conversation                               |
| Chat microphone | Fabric Desktop/mobile client               | Existing prompt submission behavior           | Transcript inserted into or submitted from the composer                |

The mode must be selected before recording. A transcript captured in Dictate mode must never silently become an agent request.

## Acceptance Criteria

- [ ] AutoWhisper builds a reusable runtime library and keeps the Whisper model warm across multiple requests.
- [ ] `autowhisper serve --stdio` accepts newline-delimited JSON requests on stdin, emits one JSON response per request on stdout, and sends all logs to stderr.
- [ ] `autowhisper transcribe <path> --json` returns `TranscriptionResult` v1 and supports files decodable by the bundled miniaudio decoder.
- [ ] The protocol handles `health`, `capabilities`, `transcribe_file`, and `shutdown` without opening a network listener.
- [ ] The AutoWhisper-owned Fabric plugin registers the provider name `autowhisper`, normalizes unsupported input when needed, and returns Fabric's existing `{success, transcript, provider, error?}` envelope.
- [ ] Fabric Desktop continues to call `/api/audio/transcribe`; selecting `stt.provider: autowhisper` requires no renderer-specific provider branch.
- [ ] Desktop Voice Notes supports recording, transcript review/editing, and an explicit conversion to a Markdown result containing summary, decisions, tasks, and follow-up.
- [ ] System-wide Dictate and Ask Fabric are opt-in, visibly distinct, independently configurable, and preserve existing AutoWhisper Dictate behavior by default.
- [ ] `TranscriptionResult` v1 has cross-language fixtures consumed by C++, Python, TypeScript, Swift, and Kotlin tests.
- [ ] Phone audio is captured on the phone and never represented by the existing gateway-host `voice.record` or `voice.tts` methods.
- [ ] Native iOS dictation/read-aloud is implemented, but physical-device verification and migration to the shared result contract remain.
- [ ] Android can record/transcribe in app and invoke Dictate/Ask from an IME; iOS exposes App Intents suitable for Shortcuts and the Action button.
- [ ] No audio or transcript telemetry is emitted unless a generic user-facing telemetry opt-in exists and the user explicitly enables it.
- [ ] Existing CLI, Desktop chat microphone, gateway-host voice, and AutoWhisper daemon behavior remain compatible.

## Constraints

- Do NOT add AutoWhisper as an in-tree Fabric plugin. It is a sibling product and must publish its Fabric integration from the AutoWhisper repository as a standalone installable plugin.
- Do NOT add an AutoWhisper model tool to Fabric. Speech-to-text remains an edge/provider capability and uses the existing transcription dispatcher and HTTP endpoint.
- Do NOT mutate a long-lived conversation's system prompt or tool list. Voice-note transformation is an ordinary explicit user turn/workflow.
- Do NOT expose gateway-host `voice.record` or `voice.tts` as phone microphone/speaker capabilities.
- Do NOT make Dictate mode call Fabric or any LLM.
- Do NOT enable system-wide capture, background recording, microphone persistence, or audio retention by default.
- Each implementation layer ships in a focused, independently reviewed PR; Fabric changes must not reach into AutoWhisper-owned source.
- Must support AutoWhisper on macOS, Windows, and Linux without a TCP port, firewall rule, or shared secret in the first protocol version.
- Must bound input size, duration, line size, transcript size, and request processing time at every process boundary.
- Must preserve logs on stderr and machine-readable protocol data on stdout.
- Must treat audio files and transcripts as sensitive local data and remove temporary normalized files after each call.

## Runtime Modes

| Mode                       | Behavior                                                      | Notes                                                                               |
| -------------------------- | ------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| AutoWhisper desktop daemon | Existing hotkey capture and focused-app injection             | Continues to own microphone, tray, feedback, and output injection                   |
| AutoWhisper one-shot CLI   | Loads runtime, transcribes one file, exits                    | Useful for diagnostics and command-provider fallback                                |
| AutoWhisper stdio service  | Parent-owned child process, model stays loaded                | No listener; EOF or `shutdown` tears down the runtime                               |
| Fabric Desktop windowed    | Chat microphone and Voice Notes UI available                  | Recording owned by renderer; transcription owned by backend/provider                |
| Fabric Desktop hidden/tray | AutoWhisper system-wide modes may remain active when opted in | No renderer IPC send unless a live window/client exists                             |
| Fabric backend headless    | Existing `/api/audio/transcribe` remains available            | Voice Notes may be created through an authenticated client; no microphone ownership |
| iOS foreground             | Native audio session records and transcribes                  | Native dictation/read-aloud from merged PR #100 is the baseline                     |
| iOS App Intent             | Short, explicit user-triggered capture/action                 | Must surface permission/auth failures; no indefinite background recording           |
| Android foreground         | Native recorder captures and transcribes                      | Lifecycle stops/finishes on interruption, route loss, or app teardown               |
| Android IME                | User explicitly holds/taps a mode control                     | Dictate commits text; Ask Fabric returns/inserts a bounded response                 |

For every Desktop or mobile event delivery, a missing/destroyed renderer, disconnected gateway, inactive input connection, or stale recording run is a handled no-op or explicit error—not a crash and not a delivery to a newer run.

## Technical Context

### AutoWhisper integration boundary

AutoWhisper is a separately versioned sibling product. Fabric depends only on
its published local protocol and standalone plugin, never on AutoWhisper source
paths or internal classes. The AutoWhisper-owned implementation is expected to:

1. Keep local Whisper inference and current system-wide Dictate behavior under
   AutoWhisper ownership.
2. Expose one reusable runtime that can keep a selected model warm across
   requests.
3. Offer a one-shot file-transcription command and a parent-owned stdio service
   without opening a network listener.
4. Decode supported audio into bounded 16-kHz mono samples in one shared runtime
   path rather than duplicating decoders.
5. Publish its Fabric provider as a standalone package through Fabric's general
   plugin entry point.

### Fabric today

1. `apps/desktop/src/app/chat/composer/hooks/use-mic-recorder.ts` owns browser
   microphone capture, levels, silence handling, and `MediaRecorder` cleanup.
2. `apps/desktop/src/fabric.ts` sends captured audio to the existing
   `/api/audio/transcribe` endpoint.
3. `fabric_cli/web_server.py` validates the base64 audio upload, writes a bounded
   temporary file, calls `tools.transcription_tools.transcribe_audio`, deletes
   the file, and returns the compatibility transcript envelope.
4. `agent/transcription_provider.py` defines the external provider ABC and its
   failure envelope.
5. `agent/transcription_registry.py` registers plugin providers while protecting
   built-in names.
6. `tools/transcription_tools.py` discovers and dispatches to external providers.
7. `apps/shared/src/gateway-capabilities.ts` and
   `tui_gateway/gateway_capabilities.py` deliberately exclude gateway-host
   `voice.record` and `voice.tts` from mobile capabilities.
8. `apps/mobile/ios/Fabric/Core/DeviceVoiceController.swift`, merged in PR #100,
   implements phone-side iOS dictation/read-aloud with lifecycle guards.

## Key Files

| File                                                                                               | Role                                                        |
| -------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| `agent/transcription_provider.py`                                                                  | Standalone Fabric STT provider contract                     |
| `agent/transcription_registry.py`                                                                  | External provider registration and built-in-name protection |
| `tools/transcription_tools.py`                                                                     | Provider dispatch and exception boundary                    |
| `fabric_cli/plugins.py`                                                                            | General plugin registration surface                         |
| `fabric_cli/web_server.py`                                                                         | Existing Desktop transcription endpoint                     |
| `apps/desktop/src/app/chat/composer/hooks/use-mic-recorder.ts`                                     | Shared Desktop recording primitive                          |
| `apps/desktop/src/fabric.ts`                                                                       | Existing renderer-to-backend transcription call             |
| `apps/shared/src/gateway-capabilities.ts`                                                          | Shared gateway capability-family contract                   |
| `tui_gateway/gateway_capabilities.py`                                                              | Gateway-host versus phone-audio safety boundary             |
| `apps/mobile/ios/Fabric/Core/DeviceVoiceController.swift`                                          | Native iOS capture and read-aloud lifecycle                 |
| `apps/mobile/ios/Fabric/Core/GatewayAPI.swift`                                                     | Native iOS gateway capability parser                        |
| `apps/mobile/android/app/src/main/kotlin/io/github/obliviousodin/fabric/mobile/core/GatewayApi.kt` | Native Android gateway capability parser                    |

## Data Contracts

### `TranscriptionResult` v1

```json
{
  "schema": "fabric.transcription",
  "version": 1,
  "request_id": "01J...",
  "status": "completed",
  "text": "Ship the voice note workflow.",
  "language": "en",
  "duration_ms": 1840,
  "processing_ms": 412,
  "model": "small.en",
  "provider": "autowhisper",
  "segments": [
    { "start_ms": 0, "end_ms": 1840, "text": "Ship the voice note workflow." }
  ],
  "warnings": []
}
```

`status` is one of `completed`, `no_speech`, `cancelled`, or `failed`. Failed results add `error: {code, message, retryable}` and keep `text` empty. Producers may omit optional timing/model/language fields, but must not change their types. Consumers must ignore unknown fields.

### AutoWhisper stdio request

```json
{
  "protocol": "autowhisper.local",
  "version": 1,
  "id": "req-1",
  "method": "transcribe_file",
  "params": {
    "path": "/absolute/audio.wav",
    "language": "en",
    "model": "small.en"
  }
}
```

Responses echo `id` and contain either `result` (a `TranscriptionResult`) or `error: {code, message, retryable}`. The service processes one request at a time in v1. The parent continuously drains stderr into a bounded, redacted log sink so child logging cannot block protocol progress. The parent also owns process cancellation: close stdin, wait a bounded grace period, then terminate the child process tree.

### Phone-audio result envelope

Phone capture is client-owned state, not a gateway microphone method. When a
client needs to persist or hand off the result, it uses this versioned envelope:

```json
{
  "contract": "fabric.phone_audio",
  "version": 1,
  "capture_id": "local UUID",
  "mode": "dictate|voice_note|ask_fabric|chat",
  "mime_type": "audio/mp4",
  "duration_ms": 1840,
  "result": {
    "schema": "fabric.transcription",
    "version": 1,
    "request_id": "01J...",
    "status": "completed",
    "text": "..."
  }
}
```

When remote transcription is selected, the authenticated client uploads its bounded recording to the existing backend audio endpoint. The gateway never claims it recorded phone audio.

## Design Contracts

### Lifecycle Matrix

| Transition                 | Owned state                                                    | What must happen                                                                                                     |
| -------------------------- | -------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| Off → On                   | AutoWhisper child process, stdin/stdout reader, loaded runtime | Spawn once, verify `health`, load selected model, begin accepting requests                                           |
| On → Off                   | Process, pipes, pending request, temp files                    | Reject/cancel pending work, close stdin, send/await shutdown when possible, terminate after grace, remove temp files |
| On → On (config changed)   | Model/device/language/process options                          | Drain current request, stop old process, spawn and health-check a fresh process with new config                      |
| On → On (config unchanged) | Same process and model                                         | Reuse the process and loaded model; do not reload                                                                    |

Recording controllers use the same four transitions: a changed device/locale/mode invalidates the current run ID, tears down the old tap/recorder, and starts a fresh run only after permission and state checks.

### Parameter Contracts

| Method                               | Scoping parameter   | Collection/state           | Filter/guard                                                       |
| ------------------------------------ | ------------------- | -------------------------- | ------------------------------------------------------------------ |
| `handle_response(request_id)`        | `request_id`        | pending request map        | Resolve only the exact matching pending request                    |
| `finish_capture(capture_id)`         | `capture_id`        | active capture             | Apply transcript only when IDs match                               |
| `ask_fabric(conversation_id)`        | `conversation_id`   | conversation/session store | Submit only to the explicitly selected conversation                |
| `commit_ime_text(editor_session_id)` | `editor_session_id` | active input connection    | Commit only if the connection still belongs to that editor session |

### Return Value Contracts

| Method                       | Return type           | Success means                                          | Failure means                              | Caller must                                                      |
| ---------------------------- | --------------------- | ------------------------------------------------------ | ------------------------------------------ | ---------------------------------------------------------------- |
| `Runtime::transcribe_file`   | `TranscriptionResult` | Terminal `completed` or `no_speech` result             | `failed` with stable code/message          | Never parse logs or infer status from empty text                 |
| `ProtocolHandler::handle`    | response JSON         | Exactly one response for a valid request               | Structured protocol error                  | Write one compact JSON line and flush                            |
| Fabric provider `transcribe` | Fabric STT dict       | Existing dispatcher-compatible success                 | Existing dispatcher-compatible failure     | Return the envelope; never raise across plugin boundary          |
| Voice-note generation        | Markdown result       | Complete Markdown is returned to the explicit workflow | No partial result is presented as complete | Keep the reviewed transcript and allow retry or an explicit save |

### Guard Parity

| Side effect                     | Template                                                  | Guard to preserve                                                                      |
| ------------------------------- | --------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| Transcription upload            | `fabric_cli/web_server.py`                                | Authenticated API path plus data URL, MIME, non-empty, and max-byte validation         |
| Plugin invocation               | `tools/transcription_tools.py`                            | Provider exists, reports available, and exceptions become failure envelopes            |
| Mobile capability advertisement | `apps/shared/src/gateway-capabilities.ts`                 | Feature is true iff every required method exists; absent optional family remains false |
| iOS recording completion        | `apps/mobile/ios/Fabric/Core/DeviceVoiceController.swift` | Callback run ID equals current run ID before transcript/state mutation                 |
| Desktop window delivery         | existing Electron window send sites                       | Window exists and is not destroyed before send                                         |
| Android IME commit              | active `InputConnection` template                         | Connection exists and capture/editor session IDs still match                           |

### Test Harness Requirements

| Assertion                        | Harness condition                                                                           | Negative path                                                               |
| -------------------------------- | ------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| Protocol returns a transcription | Fake transcriber returns a complete v1 result                                               | Unknown method, malformed JSON, oversized line, thrown engine error         |
| Model is reused                  | Fake/runtime factory counts one load across two requests                                    | Config change creates a new runtime exactly once                            |
| Provider returns transcript      | Fake stdio process emits matching response ID                                               | Timeout, EOF, invalid JSON, mismatched ID, nonzero exit, unavailable binary |
| Desktop creates note             | Recorder and endpoint return a reviewed transcript; workflow call returns Markdown sections | Empty/no-speech result, cancelled review, workflow failure                  |
| Phone capture applies transcript | Permission granted and callback capture ID matches                                          | Permission denied, interruption, stale callback, route loss, app teardown   |
| IME commits text                 | Active input connection matches editor session                                              | Connection replaced before completion; Ask response too large; user cancels |

## Implementation Plan

### Phase 1 — AutoWhisper reusable runtime and protocol

- [ ] Add `src/runtime/transcription_result.{h,cpp}` and strict v1 JSON serialization.
- [ ] Extract the proven miniaudio file decoder from `tools/bench/bench_main.cpp` into `src/runtime/audio_file.{h,cpp}`.
- [ ] Add `AutoWhisperRuntime`, owning one loaded `WhisperInference` and returning structured results.
- [ ] Add a pure `ProtocolHandler` plus `StdioServer`; use a fake transcriber in unit tests so protocol tests need no model.
- [ ] Add `autowhisper transcribe` and `autowhisper serve --stdio`.
- [ ] Build `autowhisper_runtime` as a reusable target and link the daemon/bench/CLI without compiling inference twice.
- [ ] Verification: `cmake -B build -DCMAKE_BUILD_TYPE=Release -DAUTOWHISPER_ENABLE_TESTS=ON && cmake --build build -j && ctest --test-dir build --output-on-failure`.

```cpp
class Transcriber {
public:
    virtual ~Transcriber() = default;
    virtual TranscriptionResult transcribe_file(
        const std::string& path,
        const TranscriptionOptions& options
    ) = 0;
};

int StdioServer::run(std::istream& input, std::ostream& output) {
    for (std::string line; std::getline(input, line);) {
        output << handler_.handle_line(line).dump() << '\n' << std::flush;
        if (handler_.shutdown_requested()) return 0;
    }
    return 0;
}
```

### Phase 2 — AutoWhisper-owned Fabric provider

- [ ] Publish `integrations/fabric/autowhisper_fabric` as a standalone package with `fabric_agent.plugins` entry point.
- [ ] Register `AutoWhisperTranscriptionProvider` through `ctx.register_transcription_provider(...)`.
- [ ] Own one synchronized stdio client per Fabric process, restart it on config change or broken pipe, and clean up on process exit.
- [ ] Normalize non-decodable input to a bounded 16-kHz mono temporary WAV using an explicitly discovered `ffmpeg`, then remove it in `finally`.
- [ ] Add install/config/smoke documentation using `config.yaml`, never a non-secret `.env` toggle.
- [ ] Verification: package unit tests with a fake AutoWhisper executable plus an end-to-end Fabric import/dispatch test in a temporary `FABRIC_HOME`.

```python
class AutoWhisperTranscriptionProvider(TranscriptionProvider):
    @property
    def name(self) -> str:
        return "autowhisper"

    def transcribe(self, file_path: str, *, model=None, language=None, **extra):
        try:
            result = self._client.transcribe_file(file_path, model=model, language=language)
            return {
                "success": result["status"] in {"completed", "no_speech"},
                "transcript": result.get("text", ""),
                "provider": self.name,
                "transcription_result": result,
            }
        except Exception as exc:
            return {"success": False, "transcript": "", "provider": self.name, "error": str(exc)}
```

### Phase 3 — Fabric transcription and phone-audio contracts

- [ ] Add canonical JSON Schemas and fixtures for `fabric.transcription` v1 and `fabric.phone_audio` v1.
- [ ] Add parsers/types in shared TypeScript, Swift, and Kotlin plus backend validation tests.
- [ ] Extend `/api/audio/transcribe` additively with `result`; preserve `ok`, `transcript`, and `provider` for old clients.
- [ ] Keep phone audio out of `voice.*`; advertise only genuinely implemented upload/transcription semantics.
- [ ] Verification: shared/mobile contract tests and targeted Python endpoint/provider tests.

```typescript
export interface TranscriptionResultV1 {
  schema: "fabric.transcription";
  version: 1;
  request_id: string;
  status: "completed" | "no_speech" | "cancelled" | "failed";
  text: string;
  provider?: string;
  language?: string;
  duration_ms?: number;
  processing_ms?: number;
  model?: string;
  segments?: readonly TranscriptionSegmentV1[];
  warnings?: readonly string[];
  error?: { code: string; message: string; retryable: boolean };
}
```

### Phase 4 — Desktop Voice Notes

- [ ] Reuse `useMicRecorder`; do not fork browser microphone lifecycle code.
- [ ] Add a Voice Note route/sheet with record, transcript review/edit, discard, retry, generate, and explicit save/export actions.
- [ ] Submit one explicit Fabric workflow containing the reviewed transcript and a stable Markdown output contract.
- [ ] Keep generated Markdown in the conversation by default; save only to a user-selected destination through existing file capabilities rather than a hidden note database.
- [ ] Save audio only when the user opts in; otherwise delete it after transcription/retry lifetime ends.
- [ ] Verification: component/action tests, Desktop typecheck/lint/tests/build, macOS/Windows/Linux packaging verification.

```markdown
# Voice Note

## Summary

...

## Decisions

- ...

## Tasks

- [ ] ...

## Follow-up

- ...

## Transcript

...
```

### Phase 5 — System-wide Dictate and Ask Fabric

- [ ] Preserve current AutoWhisper hotkey as Dictate default.
- [ ] Add explicit mode configuration and a separate Ask Fabric hotkey/action.
- [ ] Route Ask Fabric through an authenticated local Fabric endpoint/CLI invocation without adding a model tool.
- [ ] Display unmistakable recording/processing mode feedback and require opt-in before background/tray availability.
- [ ] Verification: mode-state unit tests plus macOS, Windows, and Linux manual hotkey/injection smoke tests.

### Phase 6 — Native in-app iOS and Android voice

- [x] Preserve the native iOS dictation/read-aloud baseline merged in PR #100.
- [ ] Evolve iOS output from a plain transcript to the shared v1 result without weakening its run-ID and audio-session guards.
- [ ] Add Android foreground recording, permission/lifecycle handling, upload/transcription, transcript review, and the same four product modes.
- [ ] Verification: Xcode unit/UI tests on a real macOS runner plus physical-device permission/route/interruption smoke tests; Android unit/lint/debug/release builds plus device/emulator interruption tests.

### Phase 7 — Android IME and iOS App Intents

- [ ] Add an opt-in Android input method with separate Dictate and Ask Fabric controls, active-editor guards, and no transcript history by default.
- [ ] Add iOS App Intents for Start Voice Note and Ask Fabric, expose App Shortcuts, and document Action button assignment.
- [ ] Verification: Android IME instrumentation on at least two editor types; iOS Shortcuts/Action button manual tests with locked/unlocked and denied-permission paths.

### Phase 8 — Rollout and documentation

- [ ] Document local-only defaults, model download, permissions, audio retention, provider selection, and failure recovery.
- [ ] Ship each phase behind explicit user configuration until its platform verification is complete.
- [ ] Record compatibility matrix and protocol version negotiation behavior.

## UI/UX Changes

Desktop adds a dedicated Voice Note surface, not a second chat composer. The recording state always names the current mode. Transcript review is mandatory before Markdown generation by default; a later preference may enable immediate processing. Saving or exporting requires an explicit destination. Mobile uses native controls and system permission language. Dictate and Ask Fabric controls must never share an ambiguous single icon without a visible mode label.

## Migration and Rollout

1. Preserve the merged native iOS baseline while the shared contracts evolve.
2. Land the AutoWhisper runtime/protocol.
3. Publish the AutoWhisper-owned Fabric provider and validate it against released/current Fabric.
4. Land Fabric result/phone contracts as an additive compatibility PR.
5. Land Desktop Voice Notes and system-wide mode integration independently.
6. Migrate iOS to the shared result contract without regressing native lifecycle guards.
7. Land Android in-app capture before IME work.
8. Ship App Intent/IME integrations only after in-app capture is stable.

Old Fabric clients continue reading `transcript`. Old AutoWhisper behavior continues in Dictate mode. Protocol version mismatch fails closed with an actionable error and never falls back to interpreting arbitrary stdout.

## Test Plan

- [ ] AutoWhisper unit: result JSON, malformed/unknown/oversized protocol messages, correlation IDs, shutdown/EOF, decoder failures, no-speech, engine exception.
- [ ] AutoWhisper integration: two requests use one model load; one-shot and stdio outputs validate against fixtures.
- [ ] Fabric plugin unit: discovery, availability, config changes, timeout, process death/restart, cleanup, unsupported format normalization.
- [ ] Fabric backend: old and new response fields, upload bounds, provider-rich result propagation, temporary-file cleanup.
- [ ] Shared contracts: the same valid/invalid JSON fixtures pass/fail in Python, TypeScript, Swift, and Kotlin.
- [ ] Desktop: record/cancel/retry/review/edit/create note; no-speech and workflow error; window hidden/destroyed during completion.
- [ ] iOS: permissions, interruptions, route changes, stale callback, finalization timeout, foreground/background transitions.
- [ ] Android: permissions, rotation/process recreation, audio focus/route loss, stale callback, review and submit.
- [ ] Android IME: connection replacement, editor rejection, cancellation, Dictate commits only text, Ask Fabric bounded insertion.
- [ ] Security/privacy: no raw audio/transcript in logs, no retained temp file, no listener, no default background capture.

## Out of Scope

- Meeting bots, calendar joins, system-audio loopback, and unattended meeting recording.
- Speaker diarization, speaker naming, and collaborative transcript editing.
- Apple Watch, Wear OS, widgets, Live Activities, and lock-screen continuous capture.
- Broad background capture, ambient journaling, wake words, and automatic recording triggers.
- Cloud model hosting or an AutoWhisper network service.

## Open Questions

- Whether Voice Notes should store source audio when the user explicitly opts in, and what retention setting owns deletion.
- Whether Ask Fabric inserts the answer into the focused app, opens Fabric, or offers both as explicit output actions.
- Which conversation Ask Fabric targets by default: last active, a pinned voice inbox, or a per-hotkey configured session.
- Whether iOS on-device Speech remains the default phone engine while AutoWhisper-derived native runtimes mature.

None of these questions blocks the runtime, provider, result contract, or in-app capture work.

## Self-Review

- [x] Every acceptance criterion has a corresponding implementation phase.
- [x] Runtime Modes covers desktop, headless, tray, iOS, Android, IME, and App Intent execution.
- [x] Lifecycle Matrix includes off/on, teardown, changed config, and unchanged config.
- [x] Every method with a scoping identifier has an explicit filter/guard contract.
- [x] Meaningful return values have caller obligations.
- [x] High-consequence side effects reference existing guards or platform equivalents.
- [x] Test assertions identify the harness state required to reach them and negative paths.
- [x] No implementation step contains a placeholder.
- [x] Out of Scope lists adjacent layers explicitly deferred by the approved roadmap.
- [x] Key file references use stable paths rather than line-number snapshots.

## Change Governance

Each phase requires its normal engineering, security, design, and platform
review before merge. Updating this roadmap does not approve an implementation
PR or relax Fabric's plugin, prompt-caching, privacy, or mobile lifecycle
contracts.
