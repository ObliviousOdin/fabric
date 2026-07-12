---
title: "Managed Tool Routes"
description: "Configure web, image, speech, and browser backends independently with Fabric's profile-scoped tool routing."
sidebar_label: "Managed Tool Routes"
sidebar_position: 2
---

# Managed Tool Routes

Fabric keeps model inference and tool backends separate. You can use a local
model with hosted web search, a subscription model with local browser
automation, or direct API keys for every capability. Each choice belongs to the
active profile.

## Configure routes

Use the interactive tools command to inspect and change one capability at a
time:

```bash
fabric tools
fabric status --deep
```

`fabric tools` lists the supported backends for each capability. Selecting a
backend may prompt for its credential; saving the selection is not a live
provider health check. Optional plugins can add more choices without expanding
the permanent core tool schema.

## Capability map

| Capability | Direct or local options | Configuration |
|---|---|---|
| Web search and extraction | DDGS, SearXNG, Firecrawl, Tavily, Exa, Parallel, xAI | `fabric tools` → Web |
| Image generation | FAL and installed image-provider plugins | `fabric tools` → Image generation |
| Text to speech | Edge TTS, ElevenLabs, OpenAI, Mistral | `fabric tools` → Text to speech |
| Browser automation | Local browser, Browserbase, installed browser-provider plugins | `fabric tools` → Browser |

The exact list evolves with installed plugins and credentials. The interactive
picker is the source of truth for the active profile.

## Bring your own credentials

Secrets belong in the profile's private auth store or `~/.fabric/.env`.
Behavioral choices belong in `~/.fabric/config.yaml`.

Common direct-provider credentials include:

| Capability | Credential |
|---|---|
| Firecrawl | `FIRECRAWL_API_KEY` |
| Browserbase | `BROWSERBASE_API_KEY`, `BROWSERBASE_PROJECT_ID` |
| FAL image generation | `FAL_KEY` |
| ElevenLabs speech | `ELEVENLABS_API_KEY` |
| OpenAI speech | `VOICE_TOOLS_OPENAI_KEY` |
| Mistral speech | `MISTRAL_API_KEY` |

Run `fabric tools` after adding a credential to select the route without
hand-editing provider-specific YAML. Verify it with a small real call before
depending on it in scheduled or unattended work.

## Mix routes intentionally

Tool routing is per capability, not all-or-nothing. For example:

- use free local DDGS search and a direct Firecrawl key for extraction;
- keep browser automation local while routing image generation to FAL;
- use Edge TTS for local speech and ElevenLabs only for premium voices;
- keep inference on Ollama while enabling a hosted tool that the workflow
  explicitly needs.

This separation avoids an accidental vendor bundle and makes cost, privacy,
and failure boundaries visible.

## Local-AI boundary

Choosing Ollama does not automatically make the whole process offline. Web
search, cloud browsers, hosted image generation, remote memory, and speech
providers may still send data over the network.

Use the profile's `local_ai` policy to restrict participating AI and memory
routes, then inspect the result:

```bash
fabric status --deep
```

Treat whole-process air-gapping as a separate, verified network boundary.

## Troubleshooting

### A backend does not appear

1. Confirm its plugin is installed or its credential is present.
2. Run `fabric tools` again.
3. Check `fabric logs --level warning` for provider initialization failures.
4. Run a small provider-specific task to verify credentials and reachability.

### A configured backend is not used

Confirm you changed the intended profile. Tool routes are profile-scoped, so a
setting in `default` does not silently inherit into another profile.

### A hosted route fails

Use the provider's direct status page, verify the credential, and keep a local
or alternate backend configured when the workflow must degrade gracefully.

## Related guides

- [Tools](/user-guide/features/tools)
- [Provider routing](/user-guide/features/provider-routing)
- [Local Ollama](/guides/local-ollama-setup)
- [Local-AI boundary](/guides/local-ollama-setup#review-traffic-outside-the-local-ai-boundary)
- [Plugins](/user-guide/features/plugins)
