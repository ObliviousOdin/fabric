import { describe, expect, it } from "vitest";

import manifest from "../../mobile/contracts/fabric-voice-v1/voice-manifest.json";
import phoneAudioChat from "../../mobile/contracts/fabric-voice-v1/phone-audio-chat.json";
import phoneAudioMalformed from "../../mobile/contracts/fabric-voice-v1/phone-audio-malformed.json";
import phoneAudioVoiceNote from "../../mobile/contracts/fabric-voice-v1/phone-audio-voice-note.json";
import transcriptionAdditive from "../../mobile/contracts/fabric-voice-v1/transcription-additive-future.json";
import transcriptionCompleted from "../../mobile/contracts/fabric-voice-v1/transcription-completed.json";
import transcriptionFailed from "../../mobile/contracts/fabric-voice-v1/transcription-failed.json";
import transcriptionIncompatible from "../../mobile/contracts/fabric-voice-v1/transcription-incompatible.json";
import transcriptionMalformed from "../../mobile/contracts/fabric-voice-v1/transcription-malformed.json";
import { parsePhoneAudio, parseTranscriptionResult } from "./voice-contract";

const fixtures: Record<string, unknown> = {
  "phone-audio-chat.json": phoneAudioChat,
  "phone-audio-malformed.json": phoneAudioMalformed,
  "phone-audio-voice-note.json": phoneAudioVoiceNote,
  "transcription-additive-future.json": transcriptionAdditive,
  "transcription-completed.json": transcriptionCompleted,
  "transcription-failed.json": transcriptionFailed,
  "transcription-incompatible.json": transcriptionIncompatible,
  "transcription-malformed.json": transcriptionMalformed,
};

describe("canonical fabric voice fixture corpus", () => {
  it("loads every manifest case through the matching parser", () => {
    expect(manifest).toMatchObject({
      name: "fabric.voice.fixture-manifest",
      version: 1,
    });
    for (const fixtureCase of manifest.cases) {
      const fixture = fixtures[fixtureCase.file];
      expect(fixture, fixtureCase.file).toBeDefined();
      const result =
        fixtureCase.kind === "phone_audio"
          ? parsePhoneAudio(fixture)
          : parseTranscriptionResult(fixture);
      expect(result.kind, fixtureCase.id).toBe(fixtureCase.expected);
    }
    expect(Object.keys(fixtures)).toHaveLength(manifest.cases.length);
  });

  it("normalizes additive transcription metadata without rejecting v1", () => {
    const parsed = parseTranscriptionResult(transcriptionAdditive);
    expect(parsed.kind).toBe("verified");
    if (parsed.kind !== "verified") throw new Error("fixture was not verified");
    expect(parsed.value.text).toBe("Additive metadata remains compatible.");
    expect(parsed.value.segments).toEqual([]);
  });

  it("keeps phone capture ownership and mode explicit", () => {
    const parsed = parsePhoneAudio(phoneAudioVoiceNote);
    expect(parsed.kind).toBe("verified");
    if (parsed.kind !== "verified") throw new Error("fixture was not verified");
    expect(parsed.value).toMatchObject({
      contract: "fabric.phone_audio",
      mode: "voice_note",
      mime_type: "audio/mp4",
    });
  });
});
