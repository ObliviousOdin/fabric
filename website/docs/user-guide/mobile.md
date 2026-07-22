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

From the computer that will execute Fabric:

```bash
fabric mobile --install none
```

The default bind is `0.0.0.0:9119` so a phone on the same network can reach it.
Fabric requires a configured gateway authentication provider before it will
expose a non-loopback bind. The command can guide you through provider setup;
it never falls back to an unauthenticated public server.

For a phone and computer connected to the same Tailscale tailnet, use the
private HTTPS tunnel mode instead:

```bash
fabric mobile --tailscale --install none
```

This checks that Tailscale is connected, binds Fabric only to `127.0.0.1`,
configures and verifies Tailscale Serve, and puts the machine's MagicDNS HTTPS
origin in the QR. It will not overwrite an unrelated service already mounted
at the Tailscale HTTPS root. This is the zero-typing pairing path: the QR holds
the current Fabric session token, so treat it like a password.

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
  tailnet.
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
