---
title: Mithuru Simple Mode
sidebar_position: 17
---

# Mithuru Simple Mode

Mithuru is a simplified Fabric experience for people who prefer larger controls,
shorter copy, and a voice-first path. It is available as a source preview in
Fabric Desktop and the native iOS client.

Mithuru is a presentation layer, not a second agent or account. It uses the
active Fabric profile or paired gateway, the same conversation/session state,
and the same authenticated prompt, approval, and attachment contracts as
Standard Fabric.

## Open and leave Simple Mode

- **Desktop:** select **Open Mithuru Simple Mode** in the title bar. Select
  **Standard Fabric** to return to the regular desktop chat.
- **iOS:** after pairing and completing the connected-server introduction, the
  Home tab presents Mithuru setup. Select **Standard Fabric** from Mithuru to
  use the regular Home experience; **Open Mithuru** returns to Simple Mode.

Preferences are local to the device and isolated by Fabric profile on Desktop
or by saved gateway on iOS.

## Setup

Setup asks one question at a time:

1. Sinhala, Tamil, or English (Sri Lanka)
2. Voice and text, or text only
3. Text size
4. Speech speed when voice is enabled
5. Whether a family member is helping with setup
6. Whether online speech may be used when voice is enabled and on-device
   recognition is unavailable

Text-only setup skips voice-only questions and keeps microphone and read-aloud
controls hidden. Choosing a family helper changes setup presentation only; it
does not grant access to conversations, recordings, documents, messages,
health information, or location.

## Voice and privacy

Mithuru has no wake word and never submits recognized speech automatically.
Dictation remains editable until **Send** is selected.

On iOS, Apple on-device recognition is preferred. If the selected language is
not available on device, Apple online recognition remains blocked unless the
user explicitly opted in during setup. Raw microphone buffers are not written
to disk by Fabric and are not sent through the Fabric gateway.

On Desktop, microphone audio is sent to the configured Fabric speech service
only after the same explicit online-speech choice. Otherwise the microphone
path fails closed to typing.

Read aloud uses the operating system's installed voices. Availability and
pronunciation depend on the selected language and voices installed on the
device.

## Approvals, prompts, and documents

Simple Mode does not weaken Fabric authorization:

- speech, typed “yes”, and client copy are never authorization;
- consequential tool requests still use the gateway's exact pending approval;
- the approval surface shows the gateway-provided redacted command and location
  and offers only **Allow once** or **Deny**;
- secure prompts continue to use secure entry; and
- normal input is disabled while a prompt or approval is pending.

Before a document picker opens, Mithuru explains that the file may be sent to
the paired gateway and selected AI provider. Existing capability, attachment
size/count, upload, and receipt checks remain authoritative.

## Preview and release gates

Sinhala and Tamil implementation copy must be reviewed by native-language
reviewers before it is described as release-quality localization. A public
mobile release also requires physical-iPhone testing for microphone and Speech
permissions, on-device and online recognition, installed Sinhala/Tamil voices,
VoiceOver, Dynamic Type, increased contrast, offline recovery, document import,
and the normal TestFlight provenance gates.
