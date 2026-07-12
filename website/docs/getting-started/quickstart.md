---
sidebar_position: 1
title: "Fabric Quickstart"
description: "Install Fabric, connect one model route, verify memory and skills, and run a real first task."
---

# Fabric Quickstart

This is the shortest evidence-based path from a fresh machine to a working
fabric profile. It uses the `fabric` command, stores state under `~/.fabric`, and
keeps account, model, memory, and skill choices scoped to one profile.

:::caution Verify downloads
Use the installer and release assets published by
[`ObliviousOdin/fabric`](https://github.com/ObliviousOdin/fabric). Desktop
packages are official only when they appear on the repository's release page
with the expected checksums and platform signature.
:::

## 1. Install Fabric

On macOS, Linux, or WSL:

```bash
curl -fsSL https://raw.githubusercontent.com/ObliviousOdin/fabric/main/scripts/install.sh | bash
```

The installer creates the managed virtual environment, installs dependencies,
seeds bundled skills, exposes `fabric` through `~/.local/bin`, and starts the
setup wizard.

Reload the shell if `fabric` is not found, then verify the entry point:

```bash
source ~/.zshrc  # use ~/.bashrc for Bash
fabric version
```

The install downloads Python dependencies and is not an offline operation. See
the [Docker guide](/user-guide/docker) for container deployment.

## 2. Choose the profile that owns the setup

Use the default profile for a single personal environment, or create a named
profile to isolate its credentials, sessions, memory, skills, and settings:

```bash
fabric profile create work
```

Put `-p work` immediately after `fabric` for every command that should operate on
that profile:

```bash
fabric -p work status
```

The default profile lives under `~/.fabric/`; named profiles live under
`~/.fabric/profiles/<name>/`. Keep the flag consistent during setup so a successful
login or model selection cannot be mistaken for another profile's state.

## 3. Connect exactly one model route

Start with one route and prove it works before adding fallback, delegation, a
gateway, or automation:

```bash
fabric -p work model
```

Choose the path that matches who owns the account and where inference runs:

| Route | Setup | Important boundary |
|---|---|---|
| ChatGPT subscription | `fabric -p work auth account openai-codex personal` | Profile-owned device-code sign-in; separate from OpenAI API billing |
| xAI/Grok subscription | `fabric -p work auth account xai-oauth personal` | Browser approval does not itself prove model entitlement |
| Fabric-managed request | `fabric -p work auth account openai-codex request --device-label "work fabric"` | Durable local request and unverified email handoff; no automatic provisioning |
| Local Ollama | `fabric -p work ollama pull MODEL`, then `fabric -p work model` → **Ollama (Local)** | First-class keyless native provider, distinct from Ollama Cloud |
| API key or compatible endpoint | `fabric -p work model` | Credentials belong in the private profile auth store or `.env`; behavioral settings belong in `config.yaml` |

For ChatGPT or xAI, **My account** runs the local device-code ceremony. The separate
**Fabric-managed** CLI, dashboard, and desktop lanes record a durable profile-local
request and prepare the same server-owned non-secret handoff. They do not email a
code, send mail, prove delivery, provision an account, or make the route ready. Full
request status, cancellation, and operator transitions remain CLI-first.
Never send a device code, OAuth session ID, token, or API key by email or chat.

Use the dedicated guides for the complete account contracts:

- [ChatGPT subscription: personal and Fabric-managed paths](/guides/chatgpt-codex-subscription)
- [xAI/Grok OAuth: personal and Fabric-managed paths](/guides/xai-grok-oauth)

## 4. Optional: keep participating AI work local with Ollama

Local inference and air-gapped operation are different claims. To use Ollama,
follow [Use a Local Ollama Model with Fabric](/guides/local-ollama-setup) and
set the profile's egress mode to `local_ai` after configuring the endpoint:

```yaml title="~/.fabric/profiles/work/config.yaml"
security:
  egress_mode: local_ai
  local_ai_allowed_cidrs: []
```

Loopback needs no CIDR entry. The `local_ai` policy keeps participating primary,
auxiliary, fallback, delegation, and Mixture-of-Agents routes on approved local
addresses and disables external memory adapters. It does not block arbitrary
terminal commands, web/browser tools, MCP servers, plugins, messaging, installs,
updates, or an explicit OAuth ceremony.

`air_gapped` is reserved but unavailable until Fabric has verified a whole-process
network boundary. Selecting it blocks runtime startup; it does not silently claim
that the machine is isolated.

## 5. Verify authentication, route readiness, and a real task

Authentication and runtime readiness are separate. Inspect both before opening a
long session:

```bash
fabric -p work status --deep
fabric -p work doctor
```

Then start a normal conversation:

```bash
fabric -p work
```

Ask for a small, observable task such as reading a non-secret file and summarizing
it. A complete first verification has all of these properties:

- the selected provider and model match the intended profile;
- the model returns a response without an auth, entitlement, or context error;
- a requested tool call succeeds only after the expected approval; and
- `fabric -p work status --deep` still reports the intended effective route.

Do not treat a saved token, a populated model picker, or an HTTP connection alone
as end-to-end proof.

## 6. Inspect memory before enabling an external provider

Fabric includes profile-local human-readable memory and can load one external
memory adapter. Inspect the current tiers and selected adapter without initializing
a provider:

```bash
fabric -p work memory status
```

To configure an external adapter deliberately:

```bash
fabric -p work memory setup
```

The status vocabulary distinguishes installed, configured, eligible, active, and
healthy. `eligible` means a later session may attempt initialization; it is not a
live-health claim. Recalled external content is treated as untrusted data, bounded,
provider-labeled, threat-scanned, and kept out of the cached system prompt.

Current limitations remain explicit: external-write consent, a durable capture
outbox, revision-safe edit/delete, portable export/import, and verified remote
erasure are later memory milestones. The [memory guide](/user-guide/features/memory)
documents the built-in stores and [memory-provider guide](/user-guide/features/memory-providers)
describes adapter-specific capability differences.

## 7. Inspect and add skills safely

Skills are on-demand instruction packages. Their full bodies load only when a task
selects them, which avoids placing every workflow into each request.

```bash
fabric -p work skills list --enabled-only
fabric -p work skills audit
fabric -p work skills search kubernetes
```

Installing from a registry is a networked, mutating operation. Inspect the exact
identifier and scan result before approving it:

```bash
fabric -p work skills inspect SOURCE/SKILL
fabric -p work skills install SOURCE/SKILL
```

Fabric-authored Compound Engineering and Product Design router/member sources exist
and their catalog/planner tests pass, but the transactional pack apply command is
not released yet. Journaled apply, rollback/recovery, signed provenance, surface
parity, and distribution evidence must pass before this guide can tell users to run
`fabric packs apply`. Until then, use individually installed and reviewed skills;
do not copy pack source directories into a profile and call that a supported
installation.

## 8. Choose a user interface or messaging surface

All supported surfaces use the same profile-scoped agent core:

```bash
fabric -p work --tui       # terminal UI
fabric -p work desktop     # source-built native desktop app
fabric -p work dashboard   # local web dashboard, loopback by default
fabric -p work gateway setup
```

Configure one surface at a time. Prove the CLI task first, then connect a messaging
platform and verify its allowlist/pairing policy before installing an always-on
gateway service. A non-loopback dashboard bind requires an authentication provider;
do not weaken that boundary for convenience. A desktop package is a public Fabric
release only when it appears under `ObliviousOdin/fabric` with the required
platform signature and checksums; the source-build command does not make that claim.

## 9. Back up and know the recovery path

Create a profile-aware backup before a large configuration or skill change:

```bash
fabric -p work backup
```

When something fails, start with read-oriented diagnostics:

```bash
fabric -p work status --deep
fabric -p work config check
fabric -p work doctor
fabric -p work logs errors -n 100
```

Use [Diagnose and Repair Fabric](/getting-started/repair) before running a
mutation such as `doctor --fix`, config migration, memory reset, or profile import.

## What is ready now

| Capability | Current state |
|---|---|
| Hosted/API/custom model onboarding | Available through `fabric model` |
| ChatGPT and xAI personal OAuth | Profile-owned CLI, legacy auth, and model-picker paths available; cross-surface ownership-state adapters pending |
| Organization-managed provider request | Durable local intent; configure and operate any provisioning service separately |
| Local Ollama | First-class native CLI, desktop, and web setup plus verified foreground pull |
| `local_ai` policy | Enforced for participating AI and external-memory routes |
| Whole-process `air_gapped` mode | Unavailable and fail-closed |
| Built-in memory and external recall safety | Available |
| External-memory lifecycle/data controls | Partial; later R2 milestone |
| Individual skills | Available with inspection and security scanning |
| Compound Engineering/Product Design packs | Authored and validated; transactional installation not shipped |

Required copyright and attribution notices are preserved in
[`LICENSE`](https://github.com/ObliviousOdin/fabric/blob/main/LICENSE) and
[`NOTICE`](https://github.com/ObliviousOdin/fabric/blob/main/NOTICE).
