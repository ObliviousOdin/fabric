---
sidebar_position: 1
title: "Fabric Quickstart"
description: "Install Fabric, connect one model route, and complete a real first task in four steps."
---

# Fabric Quickstart

Get from a fresh machine to a working Fabric session with one profile and one
model route. You can add memory providers, skills, desktop apps, and messaging
surfaces after the core path works.

## 1. Install Fabric

On macOS, Linux, or WSL:

```bash
curl -fsSL https://raw.githubusercontent.com/ObliviousOdin/fabric/main/scripts/install.sh | bash
```

The installer creates Fabric's managed environment, installs its dependencies,
seeds the bundled skills, adds `fabric` to `~/.local/bin`, and opens the setup
wizard. If your shell cannot find the command, reload it and confirm the install:

```bash
source ~/.zshrc  # use ~/.bashrc for Bash
fabric version
```

The installer downloads Python dependencies and requires network access. Use
only the installer and release assets published by
[`ObliviousOdin/fabric`](https://github.com/ObliviousOdin/fabric); official
desktop packages appear on that repository's release page with checksums and
platform signatures. For containers, use the [Docker guide](/user-guide/docker).

## 2. Choose one profile and keep using it

The default profile is the simplest choice for one personal environment. It
lives under `~/.fabric/`, and you can continue without a profile flag.

Create a named profile when you need isolated credentials, sessions, memory,
skills, and settings:

```bash
fabric profile create work
fabric -p work status
```

Named profiles live under `~/.fabric/profiles/<name>/`. In the rest of this
guide, `-p work` means the named profile above. Omit it everywhere if you chose
the default profile. Do not switch between the two during setup; a login or
model selection belongs only to the profile where you completed it.

## 3. Connect one model route

Open the model setup and choose just one route:

```bash
fabric -p work model
```

| Route | Setup or selection | What to know |
|---|---|---|
| ChatGPT subscription | `fabric -p work auth account openai-codex personal` | Scan the device QR or open its link; this profile-owned sign-in is separate from OpenAI API billing |
| xAI/Grok subscription | `fabric -p work auth account xai-oauth personal` | Scan the device QR or open its link; browser approval and model entitlement are separate checks |
| Fabric-managed request | `fabric -p work auth account openai-codex request --device-label "work fabric"` | Records a durable local request; it does not send email, provision an account, or make the route ready |
| Local Ollama | `fabric -p work ollama pull MODEL`, then choose **Ollama (Local)** in `fabric -p work model` | Keyless local inference; distinct from Ollama Cloud |
| API key or compatible endpoint | Choose it in `fabric -p work model` | Secrets belong in the profile auth store or `.env`; behavior belongs in `config.yaml` |

For a subscription route, finish the browser ceremony for the same profile. You
may open the verification page in another trusted browser when the provider's
device-code flow allows it, but never send a device code, OAuth session ID,
token, or API key through email or chat. The complete account contracts are in the
[ChatGPT subscription guide](/guides/chatgpt-codex-subscription) and
[xAI/Grok OAuth guide](/guides/xai-grok-oauth).

For a local route, follow [Use a Local Ollama Model with
Fabric](/guides/local-ollama-setup) for model sizing, context, and network-policy
details.

## 4. Verify the route and complete a real task

Check the effective provider and model for the same profile:

```bash
fabric -p work status --deep
```

Then start Fabric:

```bash
fabric -p work
```

Ask for a small, observable task, such as reading a non-secret file and
summarizing it. Your first setup is complete when:

- the reported provider and model match the profile you intended;
- the model returns a response without an authentication, entitlement, or
  context error; and
- any requested tool call runs only after the expected approval.

A saved token, populated model picker, or successful HTTP connection alone is
not end-to-end proof. Confirm that the model can answer and the approved tool
can complete the task.

## After your first success

Once the four-step path works, add one capability at a time so failures remain
easy to isolate.

### Connect web, voice, or private remote access

Each optional setup surface is independently rerunnable:

```bash
fabric -p work setup tools       # Web providers, browser automation, and more
fabric -p work setup tts         # Cloud voices or local Piper/NeuTTS/KittenTTS
fabric -p work setup tailscale   # Enroll this machine through Tailscale's QR login
```

Firecrawl offers its official browser connection first and a manual API-key
fallback. Choosing **Automatic (recommended)** leaves Web resolution unpinned,
so Fabric can use an available configured provider or its keyless fallback;
self-hosted Firecrawl is never selected just because you pressed Enter.

Tailscale setup is opt-in and delegates enrollment to the installed official
Tailscale client. Fabric does not store a Tailscale auth key or enable SSH,
routes, exit nodes, Serve, or Funnel. If the client is not installed, setup
shows the official platform install link and leaves the machine unchanged.

Piper remains local and works on CPU. Setup enables its CUDA path only when the
installed ONNX Runtime explicitly reports `CUDAExecutionProvider`; it does not
replace ONNX Runtime or install GPU drivers.

### Inspect memory

Fabric includes profile-local, human-readable memory and can load one external
memory adapter. Inspect the current state before configuring an adapter:

```bash
fabric -p work memory status
fabric -p work memory setup  # only when you want an external adapter
```

`eligible` means a future session may attempt initialization; it does not mean
the provider is currently healthy. Recalled external content is bounded,
provider-labeled, threat-scanned, and treated as untrusted data. See the
[memory guide](/user-guide/features/memory) and
[memory-provider guide](/user-guide/features/memory-providers) for lifecycle
and provider-specific limits.

### Inspect and add skills

Skills load on demand rather than adding every workflow to every request:

```bash
fabric -p work skills list --enabled-only
fabric -p work skills audit
fabric -p work skills search kubernetes
```

Registry installation changes the profile and uses the network. Inspect the
exact source and scan result before approving it:

```bash
fabric -p work skills inspect SOURCE/SKILL
fabric -p work skills install SOURCE/SKILL
```

Compound Engineering and Product Design skills are available as individual,
reviewable skills. Fabric does not currently provide a supported transactional
`fabric packs apply` workflow, so do not copy pack source directories into a
profile and treat that as an installation.

### Open another interface

The supported interfaces use the same profile-scoped agent core:

```bash
fabric -p work --tui       # terminal UI
fabric -p work desktop     # source-built native desktop app
fabric -p work dashboard   # local web dashboard
fabric -p work gateway setup
```

Prove the CLI task before adding a messaging platform or always-on service.
Verify pairing and allowlist policy for a gateway. A dashboard bound beyond
loopback requires an authentication provider; keep that boundary in place.

### Tighten local-model network policy

Local inference and an air-gapped process are different guarantees. After
configuring Ollama, use `local_ai` to keep participating model and external
memory routes on approved local addresses:

```yaml title="~/.fabric/profiles/work/config.yaml"
security:
  egress_mode: local_ai
  local_ai_allowed_cidrs: []
```

Loopback needs no CIDR entry. This policy covers primary, auxiliary, fallback,
delegation, Mixture-of-Agents, and external-memory routes. It does not block
arbitrary terminal commands, web/browser tools, MCP servers, plugins,
messaging, installs, updates, or an explicit OAuth ceremony. `air_gapped` is
reserved but unavailable and fails closed rather than claiming whole-process
isolation.

### Run deeper checks and back up the profile

Use read-oriented checks before applying a repair:

```bash
fabric -p work doctor
fabric -p work config check
fabric -p work logs errors -n 100
fabric -p work backup
```

Use [Repair and diagnostics](/getting-started/repair) before a mutation such
as `doctor --fix`, config migration, memory reset, or profile import.

Required copyright and attribution notices are preserved in
[`LICENSE`](https://github.com/ObliviousOdin/fabric/blob/main/LICENSE) and
[`NOTICE`](https://github.com/ObliviousOdin/fabric/blob/main/NOTICE).
