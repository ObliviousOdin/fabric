---
sidebar_position: 6
title: "Connect a ChatGPT Subscription to Fabric"
description: "Connect a personal OpenAI Codex account safely, or request a Fabric-managed route without emailing device codes or credentials."
---

# Connect a ChatGPT Subscription to Fabric

Fabric uses the `openai-codex` provider for ChatGPT subscription sign-in.
It is separate from the `openai-api` provider, which uses an OpenAI API key and
API billing.

This guide covers two account-ownership paths:

- **My account** connects an OpenAI account through a local device-code flow.
- **Fabric-managed** prepares a non-secret access request for a company-managed
  workspace or credential.

:::caution Current managed-access limitation
The Fabric-managed CLI, dashboard, and desktop paths durably record a profile-local
request and prepare a server-owned email handoff.
Fabric does not send the message, provision, or connect an account automatically.
It also does not prove delivery. Full request history,
cancellation, and local-operator transitions are available through the CLI and
the explicit-admin gateway surface. A route is connected only after an authorized
administrator provisions it and Fabric passes its runtime readiness check.
:::

## Before you start

- Choose the Fabric profile that should own the connection. Credentials and model
  selection belong to that profile, not to every profile on the device.
- Have a browser available on any device where you can sign in to the intended
  OpenAI account.
- Confirm that OpenAI permits the account to use Codex. Fabric verifies the usable
  route after sign-in instead of assuming entitlement from a plan name.

## Connect your own account

### Desktop or dashboard

1. Open **Providers** and select **ChatGPT subscription (OpenAI Codex)**.
2. Choose **My account**.
3. Fabric opens the OpenAI verification page and shows a short-lived device code.
4. On the verification page, sign in to the intended account and enter the code.
5. Keep Fabric open while it polls the local, profile-bound login session.
6. Review the model Fabric selects. Change it if needed, then start chatting.

The profile that started the ceremony remains the owner of every subsequent poll,
token exchange, model lookup, model assignment, reload, and readiness check. Moving
to another profile while sign-in is in progress cannot write the connection into
that other profile.

### Command line

Run the login in the profile that should own it:

```bash
fabric -p my-profile auth account openai-codex personal
```

Omit `-p my-profile` to use the default profile. Follow the printed verification
URL and device-code instructions, then select the provider and model:

```bash
fabric -p my-profile model
```

You can add more than one personal account. Give each credential a recognizable
label through the compatible pooled-credential command and inspect the pool before
changing routing:

```bash
fabric -p my-profile auth add openai-codex --label personal
fabric -p my-profile auth list openai-codex
```

## Request Fabric-managed access

In the dashboard or desktop provider dialog, choose **Fabric-managed**, then
**Email Fabric**. Fabric creates or reuses the request in the profile that opened the
dialog, opens only the server-derived local email handoff, and best-effort records
that the handoff was attempted. Review and send the message yourself; delivery is
not verified.

For status, cancellation, or automation, use a short user-visible label with the
CLI:

```bash
fabric -p my-profile auth account openai-codex request \
  --device-label "front desk fabric"
```

Fabric creates or reuses one active request and prints a server-derived `mailto:`
handoff to `11676741+ObliviousOdin@users.noreply.github.com`. Open that URI in your local mail client and review the
message before sending it. Fabric does not open or send mail on your behalf.

After attempting the local handoff, you may record only that attempt and inspect the
durable request:

```bash
fabric -p my-profile auth account openai-codex handoff-attempted
fabric -p my-profile auth account openai-codex status
```

`handoff-attempted` is not proof that a mail app opened, the message was sent, Fabric
received it, or delivery occurred. The request remains `requested` until an
authenticated administrator or trusted local operator records a later transition.

### Messaging gateway (explicit admins only)

An administrator explicitly listed in the current platform scope's
`allow_admin_from` (DM) or `group_allow_admin_from` (group/channel) can manage
the same running profile without forwarding OAuth data into chat:

```text
/account status openai-codex
/account request openai-codex front desk fabric
/account handoff openai-codex
/account cancel openai-codex
```

On Slack, use `/fabric account ...`; the app manifest keeps this lower-frequency
surface behind the existing `/fabric` dispatcher. An unset scope-specific admin
list denies request, handoff, cancel, acknowledge, and reject actions. `status` is minimal:
it omits device labels, request references, email links, credentials, and OAuth
ceremony values. `handoff` only reoffers the server-derived email-draft link; the
gateway cannot observe a click and does not record a launch attempt.

The gateway is confined to its running Fabric profile and rejects target-profile,
personal OAuth, poll/submit/takeover, and repair commands before loading the
provider-account domain. Use CLI, Desktop, or the authenticated dashboard for
personal sign-in, and never paste the device code into chat.

The generated message contains only allowlisted non-secret context: the provider ID,
normalized device label, opaque non-authorizing request reference, and Fabric guide
link. It intentionally excludes the device code, OAuth session ID, access token,
refresh token, and API credentials.

For a managed connection, an administrator should provision an approved Business
or Enterprise route through the organization’s credential and secret-management
process. Do not repurpose the personal device-code ceremony as an approval link.

## Never email a device code

A device code authorizes the Fabric instance that requested it. Treat it like a
short-lived sign-in secret:

- enter it only on the verification URL Fabric displays;
- never forward it by email, chat, ticket, or screenshot;
- never include it in a Fabric-managed access request;
- cancel the Fabric login and start a new one if the code was exposed.

Closing or cancelling onboarding stops polling and sends a best-effort cancellation
to the profile that created the session.

## Verify the connection

Check authentication and runtime readiness separately:

```bash
fabric -p my-profile auth account openai-codex status
fabric -p my-profile auth status openai-codex
fabric -p my-profile status --deep
```

A saved credential is not, by itself, proof that a model is available. The deep
status check must resolve a usable provider/model route. Then start a normal chat
and send a small test prompt before adding fallback routing, gateways, or automation.

## Disconnect or replace the account

To remove the profile’s OpenAI Codex login state:

```bash
fabric -p my-profile auth logout openai-codex
```

For a multi-account pool, list entries and remove only the intended credential:

```bash
fabric -p my-profile auth list openai-codex
fabric -p my-profile auth remove openai-codex 2
```

Re-run `fabric auth add openai-codex` to connect a replacement account, then verify
the selected model again.

## Troubleshooting

### The browser did not open

Copy the printed verification URL into any browser. This is a device-code flow, so
it does not require an SSH callback tunnel. See [OAuth on remote hosts](/guides/oauth-over-ssh)
for the distinction between device-code and loopback-redirect providers.

### The code expired

Cancel the old flow and start a new one. Device codes are intentionally short-lived
and cannot be reused.

### Sign-in succeeded, but chat is not ready

Run `fabric status --deep`, confirm `openai-codex` is the selected provider, and use
`fabric model` to choose a currently available model. A provider-side entitlement,
revocation, or refresh failure requires a fresh `fabric auth add openai-codex` flow.

### The wrong account was connected

Log out from `openai-codex` in that Fabric profile, start a new flow, and verify the
account identity in the browser before entering the new code.

See [AI providers](/integrations/providers) for API-key, local, and other
subscription-backed alternatives.
