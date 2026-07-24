# Fabric Mobile — remote-access security

This document answers a direct question: **can I reach my Fabric from my
phone without Tailscale, and is that safe?** The honest answer is nuanced,
so read the threat model before you open a port.

## What a Fabric connection actually grants

A mobile (or desktop) client that authenticates to a gateway can, through
the existing RPCs:

- run shell commands on the host (`cli.exec`, `shell.exec`),
- read and capture the host screen (`computer.screenshot`), and drive
  `computer_use` turns,
- start background agent tasks, manage processes, read/write files the
  agent can reach.

**A gateway credential is root-equivalent for that machine.** Whatever
protects the login is the only thing between an attacker and full control
of the box. Design every decision below from that fact.

## Why Tailscale is the recommended default

Tailscale (or WireGuard, or an SSH tunnel) puts the gateway on a **private,
authenticated, encrypted network**. Before Fabric's own auth is even
reached, the attacker has to already be a device on your tailnet. That is
*defense in depth*: two independent barriers (network membership, then
Fabric login) instead of one.

The June 2026 hardening enforces the floor: a non-loopback bind **refuses to
start without an auth provider**, and rejects the session-token path
on the WebSocket. There is no unauthenticated public bind.

## Can I drop Tailscale and expose Fabric directly?

You *can*, but understand the trade. Exposing the gateway to the public
internet removes the network barrier and leaves **one** barrier — the
Fabric login — in front of a root-equivalent surface that anyone on Earth
can now reach and hammer. That is categorically riskier than a tailnet
bind, and **2FA does not close that gap by itself**:

- 2FA makes the *login* much harder to defeat (no password-only compromise).
- 2FA does **nothing** for a bug in the pre-auth surface — a
  vulnerability in TLS termination, the HTTP stack, or the auth code itself
  is reachable by the whole internet the moment you expose the port.
- Network isolation removes that entire class of exposure. 2FA doesn't.

So: **2FA is worth adding regardless, but it is a complement to network
isolation, not a replacement for it.** The safest posture keeps the gateway
off the public internet *and* adds 2FA.

### If you insist on public exposure, the minimum bar

1. **TLS with a real certificate** (Let's Encrypt / a reverse proxy).
   Never self-signed, never plaintext.
2. **TOTP 2FA on** (below). Password-only public exposure is not acceptable
   for a shell-granting endpoint.
3. **Rate limiting + lockout** in front of `/auth/password-login` (the
   provider has per-IP rate limiting; a reverse proxy / fail2ban adds more).
4. **A narrow path** — expose only what the app needs, ideally behind a
   reverse proxy that terminates TLS and forwards to a loopback gateway.
5. **Accept residual risk.** Even done well this is a bigger target than a
   tailnet bind. For a machine that can run arbitrary code, most people
   should not take this trade.

**Recommendation:** keep Tailscale (or an SSH tunnel / `tailscale serve`
with its automatic TLS) as the transport, and turn 2FA on as the second
factor. You get both barriers for almost no extra effort.

## Second factor: what's implemented and what isn't

### TOTP (implemented) — the "Google Authenticator" factor

A standard RFC 6238 time-based code, layered on the bundled password
provider. Zero external service, works offline, no SMS/email cost or new
attack surface. Compatible with Google Authenticator, Authy, 1Password, and
the Apple Passwords app (iCloud Keychain).

Enroll on the host:

```bash
python -c "from plugins.dashboard_auth.basic import print_totp_enrollment; print_totp_enrollment('admin')"
```

That prints a base32 secret and an `otpauth://` URI. Put the secret in
config (or the env override) and scan the URI into your authenticator:

```yaml
dashboard:
  basic_auth:
    username: admin
    password_hash: "scrypt$..."
    totp_secret: "JBSWY3DPEHPK3PXP..."   # from the command above
```

```bash
# or, without editing config:
dashboard:
  basic_auth:
    totp_secret: "JBSWY3DPEHPK3PXP..."
```

Once set, `/api/auth/providers` reports `requires_totp: true`, the mobile
sign-in form shows a 6-digit code field, and `/auth/password-login`
requires a valid code. Security properties:

- Password and code are verified together into **one generic failure** — a
  wrong password and a wrong code are indistinguishable, so the endpoint is
  not a "password was correct" oracle.
- `requires_totp` is a capability flag, not per-attempt state, so it leaks
  nothing about an individual login.
- Codes are constant-time compared; a ±30s clock-skew window is allowed;
  malformed input just fails the factor.

### SMS / email passcodes (not implemented — and mostly not recommended)

The mechanism (text/email a one-time code) is possible but weaker and
heavier than TOTP:

- **SMS** is the weakest common 2FA — SIM-swap and SS7 interception are
  real, and it needs a paid gateway (Twilio-type) plus storing your phone
  number. NIST discourages SMS as a primary factor.
- **Email** is better than SMS but ties your gateway's security to your
  email account, and needs SMTP credentials on the box (new secret, new
  attack surface).

If you want a delivered code anyway, the same
`complete_password_login(..., otp=...)` seam this TOTP work added is where a
"delivered-OTP" provider would plug in. TOTP is the better default.

### Passkeys / WebAuthn ("Apple iCloud key", Google security key) — future

Passkeys are the **strongest** option: phishing-resistant, hardware-backed,
nothing shared to steal, and exactly the "Apple iCloud key / Google auth"
model you asked about. They're also the largest build — a full WebAuthn
registration/assertion ceremony, per-origin credentials (which complicates
the multi-server / bare-IP story), and platform-authenticator integration
on both phones. It's the right long-term direction and is tracked as a
follow-up; TOTP is the pragmatic first factor that ships today.

## SSH and Remote Desktop — scope and stance

- **SSH / shell**: the agent already runs shell on the host (`cli.exec`,
  `shell.exec`, and the SSH execution environment in
  `tools/environments/ssh.py`), so "SSH capability" largely exists through
  the agent. A dedicated raw-terminal tab on the phone is deliberately **not
  added**: piping an interactive root shell to a phone is the highest-blast-
  radius surface here, and it should ride the same trust decision as public
  exposure (tailnet + 2FA), with its own explicit opt-in. Ask if you want it
  behind a setting.
- **Remote Desktop**: the read-only **live view** (`computer.screenshot`)
  ships today — you can *watch* a `computer_use` turn. Interactive control
  (injecting taps/keys into the host from the phone) is intentionally **not
  added**: it turns the phone into a remote-control for your desktop over
  the network, which needs a real permission model (per-session consent,
  visible "remote control active" state, an idle kill-switch) before it's
  safe to offer. It's a deliberate future item, not an oversight.

## Mithuru security boundary

Mithuru is a presentation layer over the existing authenticated Fabric mobile
client. It does not add a pairing scheme, credential scope, gateway RPC, model
tool, or server-side authorization rule. The existing gateway remains the
authority for capabilities, exact pending interactions, and mutation receipts.

- Spoken text is never treated as authorization. A recognized transcript stays
  editable and is submitted only after the user taps Send.
- Consequential actions use the existing `approval.request` and
  `approval.respond` flow. Mithuru offers Allow once or Deny; it does not infer
  confirmation from “yes,” silence, or background speech.
- Clarification choices return the server's exact response value. Sudo and
  secret prompts use secure entry and are not read aloud.
- On iOS, on-device Apple recognition is preferred. If it is unavailable,
  Apple online recognition is blocked unless the user explicitly opted in
  during Mithuru setup. Fabric does not write raw microphone buffers to disk or
  send them through its gateway.
- Desktop microphone audio is sent to the configured Fabric speech service only
  after the same explicit online-speech choice; otherwise the microphone path
  fails closed to typing.
- A document disclosure appears before picking a file. Existing capability,
  size/count, upload, provider, and receipt checks remain authoritative.
- Device-local Mithuru preferences are scoped by Fabric profile on desktop and
  saved gateway on iOS. The family-helper preference grants no conversation or
  data access.

Prompt wording, localized copy, and client-side presentation checks are not
security boundaries. Any future external action, reminder mutation, cloud voice
provider, caregiver access, or new mobile RPC must be implemented and reviewed
through the existing capability and authenticated gateway contracts before the
UI claims it exists.

## Summary

| You want | Do this | Safe? |
| --- | --- | --- |
| Reach Fabric from your phone | Tailscale / SSH tunnel + TOTP | ✅ recommended |
| Zero-typing pairing on a tailnet | `tailscale serve` (auto-TLS) + `--qr` | ✅ |
| Public internet exposure | TLS + TOTP + rate limit + reverse proxy | ⚠️ higher risk; usually don't |
| Public exposure, password only | — | ❌ not acceptable for a shell-granting endpoint |
| Watch a computer-use turn | Live view (shipped) | ✅ read-only |
| Drive the desktop from the phone | (not built — needs a permission model) | ⛔ pending design |
