---
sidebar_position: 17
title: "OAuth on SSH and Remote Hosts"
description: "Complete Fabric device-code and loopback OAuth safely when the browser and Fabric run on different machines."
---

# OAuth on SSH and Remote Hosts

Fabric supports two browser sign-in patterns on a remote host:

- **Device code**: Fabric prints a verification URL and short-lived code. Open
  the URL in any trusted browser and enter the code. No callback tunnel is used.
- **Loopback redirect**: Fabric listens on
  `http://127.0.0.1:<port>/...`. When the browser is on your laptop and Fabric
  is on a server, use an SSH local forward or the MCP paste-back flow.

The distinction matters. A tunnel does not help a device-code flow, and sending
a device code or callback URL to another person exposes sign-in authority.

:::caution Treat ceremony values as credentials
Enter a device code only on the verification page Fabric prints. Paste an OAuth
callback URL only into the same trusted Fabric terminal that started that flow.
Never send a device code, authorization code, callback URL, session ID, or token
by email, chat, ticket, screenshot, or a Fabric-managed access request.
:::

## Choose the right path

| Connection | Browser return path | Remote-host action |
|---|---|---|
| ChatGPT subscription (`openai-codex`) | Device code | Open the printed URL anywhere; no tunnel |
| xAI Grok (`xai-oauth`) | Device code | Open the printed URL anywhere; no tunnel |
| Spotify | Loopback on port `43827` by default | Forward the exact listener port |
| OAuth MCP server | Loopback on a per-flow port | Paste the redirect back, or forward the printed port |

Run every command with the profile that should own the resulting credential.
The top-level profile flag comes before the subcommand:

```bash
fabric -p work auth add openai-codex --no-browser
fabric -p work auth add xai-oauth --no-browser
```

Keep the Fabric process running while you approve the browser prompt. A saved
credential belongs to `work`; it does not automatically appear in the default
profile or another named profile.

## Device-code providers

ChatGPT/Codex and xAI/Grok do not redirect the browser to the remote server.
Fabric prints the provider verification URL and a short-lived code:

```bash
fabric -p work auth add openai-codex --no-browser
# Or:
fabric -p work auth add xai-oauth --no-browser
```

Open the printed URL in a browser you trust, sign in to the intended account,
enter the code, and return to the terminal. If the code expires or is exposed,
cancel the ceremony and start a fresh one; do not reuse or forward it.

Verify authentication and runtime readiness separately:

```bash
fabric -p work auth status openai-codex
fabric -p work status --deep
```

Use `xai-oauth` in the status command for xAI. Browser approval proves only
that the provider accepted the ceremony; it does not prove that the account is
entitled to a selected model or that the final route is healthy.

See [Connect a ChatGPT subscription](./chatgpt-codex-subscription.md) and
[xAI Grok OAuth](./xai-grok-oauth.md) for the ownership and entitlement flows.

## Spotify through an SSH tunnel

Spotify uses a loopback callback. Its default redirect is:

```text
http://127.0.0.1:43827/spotify/callback
```

Start the local forward from a separate terminal on your laptop:

```bash
ssh -N -L 127.0.0.1:43827:127.0.0.1:43827 user@remote-host
```

Then start Spotify login on the remote host:

```bash
fabric -p work auth spotify login --no-browser
```

Open the authorization URL Fabric prints. After approval, the browser connects
to loopback on your laptop; SSH forwards that request to Fabric's listener on
the server. Keep the tunnel open until the terminal reports completion, then
stop it with Ctrl+C.

If Fabric prints a different listener port, use that exact port on both sides
of `-L`. The redirect URI registered for the Spotify application must also
match Fabric's printed URI exactly.

Verify the profile-owned result:

```bash
fabric -p work auth spotify status
```

## OAuth MCP servers {#mcp-servers}

For an OAuth-enabled MCP server, start a fresh interactive login:

```bash
fabric -p work mcp login SERVER_NAME
```

Fabric prints an authorization URL and the callback port. You can finish in one
of two ways.

### Paste the redirect back

This is usually simplest on an interactive SSH terminal:

1. Open the printed authorization URL in your local browser.
2. Approve access.
3. The final `127.0.0.1` page may fail to load because no listener exists on
   your laptop. That browser error is expected.
4. Copy the full URL from the address bar and paste it only at Fabric's
   waiting prompt.

Fabric also accepts the exact `?code=...&state=...` portion. Both forms contain
an authorization code, so do not save them in shell history, paste them into a
chat, or reuse them in another flow.

### Forward the callback port

If the terminal cannot accept paste-back, use the exact port Fabric prints:

```bash
ssh -N -L 127.0.0.1:PORT:127.0.0.1:PORT user@remote-host
```

Open the authorization URL while the tunnel is active. Do not guess or reuse a
port from an older ceremony; MCP callback ports can change between flows.

After completion, verify the MCP connection rather than relying on the consent
page alone:

```bash
fabric -p work mcp test SERVER_NAME
```

Some MCP providers require a pre-registered OAuth client instead of dynamic
client registration. If Fabric reports that the server responded but no token
was obtained, configure that provider's client ID and secret through Fabric's
MCP configuration, then rerun `fabric -p work mcp login SERVER_NAME`.

## Jump hosts, containers, tmux, and mosh

For a jump host, keep the loopback endpoints on the laptop and final Fabric
host:

```bash
ssh -N \
  -L 127.0.0.1:43827:127.0.0.1:43827 \
  -J jump-user@jump-host \
  user@final-host
```

A mosh connection does not carry SSH `-L` forwarding. Keep Fabric in tmux or
mosh if desired, but open a separate ordinary SSH connection for the tunnel.

If Fabric runs inside a container, the forwarded remote port must reach the
listener inside that container. Publish only to remote loopback, for example
`127.0.0.1:43827:43827`, and keep the container mapping private. Do not expose
an OAuth callback listener on a public interface.

## Troubleshooting

### The browser did not open

That is expected with `--no-browser` and common over SSH. Copy only the
authorization or verification URL that Fabric prints into your trusted browser.

### The callback timed out

Start a new ceremony and confirm:

- the tunnel is still running;
- both `-L` ports match the current listener;
- the browser used the current authorization URL;
- a container publishes the listener to remote loopback; and
- another local process is not already using the port.

Do not replay an old callback URL. Authorization codes and OAuth state values
are flow-specific and short-lived.

### The token went to the wrong profile or OS user

Run the command again with the exact top-level profile flag and operating-system
account used by the Fabric runtime:

```bash
fabric -p work auth status openai-codex
fabric -p work mcp list
```

Credentials written by another profile or OS user should be treated as a
different security boundary, not copied into place manually.

### Login succeeded but the feature still fails

Authentication, entitlement, tool discovery, and runtime readiness are separate
checks. Run the provider status/deep status or `fabric mcp test SERVER_NAME`,
then repair the specific failing layer. Never treat a browser success page as
proof that Fabric can complete a real task.
