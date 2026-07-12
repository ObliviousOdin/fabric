---
sidebar_position: 16
title: "xAI Grok OAuth (SuperGrok / X Premium+)"
description: "Connect a personal SuperGrok or X Premium+ subscription to Fabric safely, without an API key or forwarding device codes."
---

# xAI Grok OAuth (SuperGrok / X Premium+)

Fabric supports xAI Grok through a browser-based OAuth device-code flow
against [accounts.x.ai](https://accounts.x.ai). You can connect either a
**SuperGrok subscription** ([grok.com](https://x.ai/grok)) or an **X Premium+**
subscription linked to the X account you use. No `XAI_API_KEY` is required for
this provider.

Sign in with the same account that owns the subscription. xAI's
[account guidance](https://docs.x.ai/grok/faq) says X Premium+ access applies to
the X-linked account, but xAI—not Fabric—decides the resulting entitlement. A
successful browser approval or saved token therefore does not prove that the
selected model or subscription route is usable; verify runtime readiness after
login.

The transport reuses the `codex_responses` adapter (xAI exposes a Responses-style endpoint), so reasoning, tool-calling, streaming, and prompt caching work without any adapter changes.

The same profile-scoped OAuth connection can also serve Fabric's direct xAI TTS,
image, video, transcription, and X Search surfaces when those capabilities are
enabled.

## Overview

| Item | Value |
|------|-------|
| Provider ID | `xai-oauth` |
| Display name | xAI Grok OAuth (SuperGrok / X Premium+) |
| Auth type | Browser OAuth 2.0 device code |
| Transport | xAI Responses API (`codex_responses`) |
| Default model | `grok-build-0.1` |
| Endpoint | `https://api.x.ai/v1` |
| Auth server | `https://accounts.x.ai` |
| Requires env var | No (`XAI_API_KEY` is **not** used for this provider) |
| Subscription | [SuperGrok](https://x.ai/grok) or [X Premium+](https://x.com/i/premium_sign_up) — see note below |

## Prerequisites

- Python 3.9+
- Fabric installed
- An active **SuperGrok** subscription on your xAI account, **or** an **X Premium+** subscription on the X account you sign in with (xAI links the subscription automatically)
- A browser available anywhere you can open the printed verification URL

:::warning xAI may restrict OAuth API access by tier
xAI's backend enforces its own allowlist on the OAuth API surface and has been seen to reject standard SuperGrok subscribers with `HTTP 403` (see issue [#26847](https://github.com/NousResearch/hermes-agent/issues/26847)) even though the in-app subscription is active. If OAuth login succeeds in the browser but inference returns 403, set `XAI_API_KEY` and switch to the API-key path (`provider: xai`) — that surface is not subject to the same gating today.
:::

## Quick Start

```bash
# Launch the provider and model picker
fabric model
# → Select "xAI Grok OAuth (SuperGrok / X Premium+)" from the provider list
# → Fabric opens or prints an accounts.x.ai verification URL
# → Enter the displayed code if prompted, then approve access in the browser
# → Pick a model (grok-build-0.1 is at the top)
# → Start chatting

fabric
```

After login, Fabric stores credentials in the selected profile's private auth
store and refreshes them before they expire. Named profiles remain isolated from
the default profile.

## Choose who owns the account

Fabric supports two ownership lanes:

- **My account** starts the profile-bound xAI device-code ceremony described in
  this guide.
- **Fabric-managed** prepares a non-secret request for an administrator-managed
  route.

:::caution Current managed-access limitation
The CLI, dashboard, and desktop now create a durable profile-local managed request
and use a server-owned email handoff. Fabric does not send the message, prove
delivery, or provision an xAI account automatically. Full request history,
cancellation, and local-operator transitions are available through the CLI and
the explicit-admin gateway surface. A connected managed route still requires an
authorized administrator and a successful runtime readiness check.
:::

In the dashboard or desktop provider dialog, choose **Fabric-managed**, then
**Email Fabric**. The request stays pinned to the profile that opened the dialog.
Review and send the prepared message yourself; delivery remains unverified.

Create or reuse one profile-local managed request with a user-visible device label:

```bash
fabric -p my-profile auth account xai-oauth request \
  --device-label "front desk fabric"
```

Fabric prints a server-derived email handoff. Open and review it in your own mail
client. If you attempt the handoff, record only that attempt and inspect the durable
status:

```bash
fabric -p my-profile auth account xai-oauth handoff-attempted
fabric -p my-profile auth account xai-oauth status
```

The attempt is not proof that a mail app opened, the message was sent, Fabric received
it, or delivery occurred.

### Messaging gateway (explicit admins only)

An administrator explicitly listed in the platform scope's `allow_admin_from`
(DM) or `group_allow_admin_from` (group/channel) can use the running gateway
profile:

```text
/account status xai-oauth
/account request xai-oauth front desk fabric
/account handoff xai-oauth
/account cancel xai-oauth
```

Use `/fabric account ...` on Slack. With no explicit scope-specific admin list,
every mutation and email handoff is denied. Status is deliberately minimal, and `handoff` only
reoffers the server-derived local email draft; it does not claim that the link
was clicked or the message was sent. The gateway rejects personal OAuth,
poll/submit/takeover, repair, and target-profile actions before importing the
provider account code. Start personal xAI sign-in through CLI, Desktop, or the
authenticated dashboard instead, and never paste a device code into chat.

The prepared request may include only the provider ID, a user-visible Fabric label,
an opaque request reference, and a Fabric guide link. It must never include an xAI
user/device code, OAuth session ID, authorization code, access token, refresh token,
API key, or dashboard token.

## Never forward the device code

The short-lived code authorizes the Fabric instance that requested it. Enter it
only at the verification URL Fabric displays. Never send it by email, chat, ticket,
or screenshot—including in a Fabric-managed access request. If it is exposed, cancel
the local ceremony and begin again.

## Logging In Manually

You can trigger a login without going through the model picker:

```bash
fabric -p my-profile auth account xai-oauth personal
# Compatible direct provider login for existing automation:
fabric -p my-profile auth add xai-oauth
```

Omit `-p my-profile` to use the default profile. Status, model selection, and logout
should use the same profile flag.

### Remote / headless sessions

On servers, containers, browser-only consoles (Cloud Shell, Codespaces, EC2
Instance Connect), or SSH sessions where Fabric cannot open a browser locally,
Fabric prints the xAI verification URL and user code. Open the URL in a browser
you trust, enter the code if prompted, and keep Fabric running while xAI approves
the login. No SSH tunnel or local callback listener is required.

```bash
fabric -p my-profile auth account xai-oauth personal --no-browser
# Open the printed verification URL in your browser.
```

The same device-code flow applies in the web dashboard and desktop app: Fabric
shows the verification URL and user code, then polls until you approve access.
The code stays on the initiating local surface; never email or forward it.

## How the Login Works

1. Fabric requests a device code from `auth.x.ai`.
2. You open the verification URL, sign in, enter the displayed code if prompted, and approve access.
3. Fabric polls xAI until approval, then saves tokens to the initiating profile.
4. Fabric refreshes the access token until you run `fabric auth logout xai-oauth`
   or revoke access in your xAI account settings.

## Checking Login Status

```bash
fabric -p my-profile auth account xai-oauth status
fabric -p my-profile auth status xai-oauth
fabric -p my-profile status --deep
```

Authentication status and runtime readiness are separate. A saved token is not proof
that xAI grants the selected subscription/model route; the deep status check must also
resolve a usable route.

## Switching Models

```bash
fabric -p my-profile model
# → Select "xAI Grok OAuth (SuperGrok / X Premium+)"
# → Pick from the model list (grok-build-0.1 is pinned to the top)
```

Or set the model directly:

```bash
fabric -p my-profile config set model.default grok-build-0.1
fabric -p my-profile config set model.provider xai-oauth
```

## Configuration Reference

After login, the selected profile's `config.yaml` will contain:

```yaml
model:
  default: grok-build-0.1
  provider: xai-oauth
  base_url: https://api.x.ai/v1
```

### Provider aliases

All of the following resolve to `xai-oauth`:

```bash
fabric --provider xai-oauth        # canonical
fabric --provider grok-oauth       # alias
fabric --provider x-ai-oauth       # alias
fabric --provider xai-grok-oauth   # alias
```

## Direct-to-xAI Tools (TTS / Image / Video / Transcription / X Search)

Once you're logged in via OAuth, every direct-to-xAI tool reuses the same bearer token automatically — there is **no separate setup** unless you'd rather use an API key.

To pick a backend for each tool:

```bash
fabric tools
# → Text-to-Speech       → "xAI TTS"
# → Image Generation     → "xAI Grok Imagine (image)"
# → Video Generation     → "xAI Grok Imagine"
# → X (Twitter) Search   → "xAI Grok OAuth (SuperGrok / X Premium+)"
```

If OAuth tokens are already stored, the picker confirms it and skips the credential prompt. If neither OAuth nor `XAI_API_KEY` is set, the picker offers a 3-choice menu: OAuth login, paste API key, or skip.

:::note Video generation is off by default
The `video_gen` toolset is disabled by default. Enable it in `fabric tools` →
`🎬 Video Generation` (press space) before the agent can call `video_generate`.
Otherwise Fabric may fall back to the bundled ComfyUI skill, which is also tagged
for video generation.
:::

:::note X search auto-enables when xAI credentials are present
The `x_search` toolset auto-enables whenever xAI credentials (a SuperGrok /
X Premium+ OAuth token or `XAI_API_KEY`) are configured. Disable it explicitly
through `fabric tools` → `🐦 X (Twitter) Search` (press space) if you do not want
that route. The tool schema remains hidden from the model when no usable xAI
credential is configured.
:::

### Models

| Tool | Model | Notes |
|------|-------|-------|
| Chat | `grok-build-0.1` | Default; auto-selected when you log in via OAuth |
| Chat | `grok-4.3` | Previous default |
| Chat | `grok-4.20-0309-reasoning` | Reasoning variant |
| Chat | `grok-4.20-0309-non-reasoning` | Non-reasoning variant |
| Chat | `grok-4.20-multi-agent-0309` | Multi-agent variant |
| Image | `grok-imagine-image` | Default; ~5–10 s |
| Image | `grok-imagine-image-quality` | Higher fidelity; ~10–20 s |
| Video | `grok-imagine-video` | Text-to-video |
| Video | `grok-imagine-video-1.5-preview` | Image-to-video; dated alias `grok-imagine-video-1.5-2026-05-30` |
| TTS | (default voice) | xAI `/v1/tts` endpoint |

The chat catalog is derived live from the on-disk `models.dev` cache; new xAI releases appear automatically once that cache refreshes. `grok-build-0.1` is always pinned to the top of the list.

## Environment Variables

| Variable | Effect |
|----------|--------|
| `XAI_BASE_URL` | Override the default `https://api.x.ai/v1` endpoint (rarely needed). |

To select xAI as the active provider, set `model.provider: xai-oauth` in
`config.yaml` (use `fabric setup` for the guided flow) or pass
`--provider xai-oauth` for one invocation.

## Troubleshooting

### Token expired — not re-logging in automatically

Fabric refreshes the token before each session and reactively on a 401. If refresh
fails with `invalid_grant` because the grant was revoked or rotated, Fabric surfaces
a typed re-authentication message instead of repeatedly retrying a dead token.

When the failure is terminal, Fabric quarantines the dead refresh chain locally so
subsequent calls skip the doomed attempt. The agent surfaces one
"re-authentication required" message until you sign in again.

**Fix:** run `fabric auth add xai-oauth` again. The quarantine clears after the
next verified exchange.

### Authorization timed out

Device-code approval has a finite expiry window. If you do not approve the login
in time, Fabric expires the local ceremony.

**Fix:** re-run `fabric auth add xai-oauth` (or `fabric model`).

### Logging in from a remote server

On SSH or container sessions Fabric prints the verification URL and user code
instead of opening a browser. Open that URL in a browser on your laptop or in a
cloud console; xAI device-code OAuth does not need an SSH port forward.

```bash
fabric auth add xai-oauth --no-browser
```

For loopback-redirect providers (Spotify, MCP servers), see [OAuth over SSH / Remote Hosts](./oauth-over-ssh.md).

### HTTP 403 after a successful login (tier / entitlement)

OAuth completed in the browser, tokens are saved, but inference or token refresh returns `HTTP 403` with a message similar to *"The caller does not have permission to execute the specified operation"*.

This is **not** necessarily a stale-token problem—re-running `fabric model` will
not change a provider-side entitlement. xAI's backend has been observed to restrict
OAuth API access by subscription tier even when the consumer subscription is active
(upstream issue [#26847](https://github.com/NousResearch/hermes-agent/issues/26847)).

**Fix:** set `XAI_API_KEY` and switch to the API-key path:

```bash
export XAI_API_KEY=xai-...
fabric config set model.provider xai
```

Or upgrade your subscription at [x.ai/grok](https://x.ai/grok) if the OAuth route is required.

### "No xAI credentials found" error at runtime

The auth store has no `xai-oauth` entry and no `XAI_API_KEY` is set. You haven't logged in yet, or the credential file was deleted.

**Fix:** run `fabric model` and select xAI Grok OAuth, or run
`fabric auth add xai-oauth`.

## Logging Out

To remove all stored xAI Grok OAuth credentials:

```bash
fabric auth logout xai-oauth
```

This clears both the singleton OAuth entry in `auth.json` and any credential-pool
rows for `xai-oauth`. Use
`fabric auth remove xai-oauth <index|id|label>` to remove only one pool entry;
run `fabric auth list xai-oauth` first to identify it.

## See Also

- [OAuth over SSH / Remote Hosts](./oauth-over-ssh.md) — SSH tunnels for loopback-redirect providers (Spotify, MCP); xAI uses device code and does not need a tunnel
- [AI Providers reference](../integrations/providers.md)
- [Environment Variables](../reference/environment-variables.md)
- [Configuration](../user-guide/configuration.md)
- [Voice & TTS](../user-guide/features/tts.md)
