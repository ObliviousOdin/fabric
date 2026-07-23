---
sidebar_position: 7
slug: /user-guide/mobile
title: "Mobile access"
description: "Pair the Fabric PWA or preview native clients with a secure remote Fabric gateway."
---

# Mobile access

`fabric mobile` starts Fabric's authenticated remote-execution gateway, serves
an installable PWA at `/mobile/`, and prints a pairing QR. Fabric still runs on
the gateway computer: the phone is a remote client and never executes Python,
tools, shell commands, or browser automation locally.

:::caution Preview support
The packaged PWA and gateway are available, and native simulator builds run in
CI. Native App Store/Play Store distribution, signed release artifacts, and
physical-device acceptance evidence are not yet published. Native build and
install helpers require a Fabric source checkout.
:::

## Start the mobile gateway

For a phone and computer connected to the same Tailscale tailnet, use the
private HTTPS tunnel mode:

```bash
fabric mobile --tailscale --install none
```

Before running it, install Tailscale on both devices, sign in to the same
tailnet, and confirm that the computer appears connected in `tailscale status`.
Fabric then checks Tailscale, binds only to `127.0.0.1`, configures and verifies
Tailscale Serve, and puts the machine's MagicDNS HTTPS origin in the QR. It
will not overwrite an unrelated service already mounted at the Tailscale HTTPS
root.

Keep `fabric mobile` running while the phone is connected. If the process
stops, the Tailscale URL may still exist but has no Fabric server behind it.
Restart the command and scan its new QR because each server process has a new
session token.

### Tailscale token mode versus admin-password mode

These are separate connection modes:

| Mode | Address shown on the phone | Credential |
|------|----------------------------|------------|
| `fabric mobile --tailscale` | MagicDNS `https://…ts.net` origin | The current Fabric session token is embedded in the QR. Do not enter the dashboard admin password. |
| `fabric mobile` (direct bind) | Reachable LAN/VPN `http://<host>:9119` origin | The QR contains the URL only. The phone signs in through the configured provider, such as the bundled `basic` admin username/password provider. |

To use or reset direct-mode password login, configure the provider first:

```bash
fabric dashboard auth password
fabric mobile --install none
```

Restart the mobile command after rotating the password. The default direct bind
is `0.0.0.0:9119`; Fabric requires a configured gateway authentication provider
before it exposes that non-loopback address and never falls back to an
unauthenticated public server. Direct HTTP login is intended only for a trusted
LAN or encrypted VPN. The Tailscale HTTPS token path above is recommended for
native production clients and PWA installation.

Scan the printed QR with the PWA landing page or a native Fabric client. Treat
the QR as a password when it contains a token. Pairing credentials stay in the
URL fragment, which is not sent in HTTP requests, referrers, or proxy logs.

To select a different address or an OS-assigned port:

```bash
fabric mobile --host 192.168.1.20 --port 0 --install none
```

A phone cannot reach `127.0.0.1` on the computer. Use a LAN-reachable address,
a private overlay network, or a trusted HTTPS tunnel.

## HTTPS and PWA installation

Browsers normally require HTTPS to install a PWA outside localhost.
`--tailscale` manages the recommended private tunnel automatically. For another
trusted reverse tunnel that terminates HTTPS and forwards to a loopback Fabric
server, advertise its origin explicitly:

```bash
fabric mobile \
  --host 127.0.0.1 \
  --port 9119 \
  --qr-url https://fabric.example.ts.net \
  --install none
```

`--qr-url` accepts only a root HTTP(S) origin with no user information, path,
query, or fragment. Non-loopback advertised origins must use HTTPS. Fabric
trusts only that exact origin for Host and WebSocket Origin checks; token/ticket
authentication and loopback peer restrictions still apply.

## Native preview clients

From a source checkout, `--install auto` installs and launches a debug client
only when exactly one eligible attached phone is unambiguous:

```bash
fabric mobile --install auto
```

Inspect targets without starting the server:

```bash
fabric mobile --devices
```

Select a specific Android device or physical iPhone when more than one is
attached:

```bash
fabric mobile --install android --android-serial SERIAL
fabric mobile --install ios --ios-device UDID --ios-team TEAM_ID
```

Android requires JDK 17, Android platform-tools, and the SDK. Physical iPhone
installation requires macOS, Xcode, Developer Mode/trust, and a valid Apple
Development team. Fabric does not handle signing passwords or permission
prompts. Use `--native-source PATH` when the source checkout is not the current
installation, and `--no-launch` to install without opening the pairing link.

## Authentication and credential storage

- Browser sessions use same-origin HttpOnly cookies and single-use WebSocket
  tickets. Browser bearer tokens remain in memory and are never written into
  public HTML or Cache Storage.
- Native token-mode credentials use iOS Keychain or Android Keystore-backed
  encryption.
- Passwords, TOTP codes, WebSocket tickets, and native gated-session cookies are
  process-scoped and are not persisted.
- Android release builds reject cleartext remote gateways. Native production
  endpoints require HTTPS/WSS.

For public-internet exposure, use TLS, a configured authentication provider,
rate limiting, and TOTP. A private Tailscale/WireGuard boundary is preferred.

## What reconnect restores

The clients resume the authoritative server session rather than reconstructing
one locally. Transcript history, an in-flight response, and pending approval,
clarification, sudo, or secret prompts are hydrated from the gateway. Mutating
requests are not retried automatically after an ambiguous network failure.

## Troubleshooting

- **The phone cannot connect:** verify the QR host is reachable from the phone;
  do not advertise the computer's loopback address over LAN. With
  `--tailscale`, confirm that both devices show as connected to the same
  tailnet and that the `fabric mobile` process is still running.
- **The app asks for an admin password in Tailscale mode:** that is a stale or
  direct-mode gateway entry. Remove or replace it, rerun
  `fabric mobile --tailscale --install none`, and scan the new HTTPS QR. The
  Tailscale QR uses a session token, not the dashboard admin password.
- **The admin password is rejected in direct mode:** run
  `fabric dashboard auth password`, restart `fabric mobile`, and scan its new
  URL-only QR. The bundled provider is named `basic`; a status response that
  requires auth but does not list `basic` means password setup is incomplete.
- **The PWA will not install:** use an HTTPS `--qr-url`; ordinary LAN HTTP is not
  a secure browser context.
- **A public bind is refused:** configure a password/auth provider first. This
  fail-closed behavior is intentional.
- **No native device is selected:** run `fabric mobile --devices`, then pass one
  explicit selector. Offline or unauthorized Android devices are not eligible.
- **Native sources are missing:** use the PWA, run from a source checkout, or
  pass `--native-source`.

The detailed engineering gates and current limitations live in
`apps/mobile/PRODUCTION.md` in the source repository.
