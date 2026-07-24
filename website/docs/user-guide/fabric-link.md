---
sidebar_position: 9
title: Fabric Link
description: Securely control Fabric machines from Terminal, Desktop, or iPhone without a VPN or social login.
---

# Fabric Link

Fabric Link gives a paired controller access to selected Fabric operations on
one of your machines. It is not a VPN, SSH tunnel, public Dashboard, or remote
desktop. The machine and controller both make outbound TLS WebSocket
connections to a blind relay; Fabric commands and responses are encrypted
end-to-end with MLS before the relay receives them.

You do **not** need GitHub, Google, email, OIDC, a Fabric cloud account,
Tailscale, or Cloudflare Access to authenticate the two ends. Each machine is
its own trust root. You scan or paste a one-time pairing link, compare the
short authentication string on both screens, and approve the controller
locally on that machine.

## Availability in this release

The complete controller flow is available from Fabric Terminal/CLI, Fabric
Desktop, and the Fabric iOS app. Those three surfaces can pair, dispatch
durable Work, and attach to an explicitly published exact live session.

Android and browser code currently provide native-core compatibility and
protected-state foundations only. They do not expose an end-user Fabric Link
controller flow yet. Do not substitute a public Dashboard or generic tunnel
for a paired controller while those surfaces remain gated.

## Remote Control versus Dispatch

These are intentionally different operations:

| Action | What it controls | What must stay open |
| --- | --- | --- |
| `/remote` | The exact current Terminal, TUI, or Desktop conversation | The owning conversation and Fabric process |
| Dispatch | A separate durable Work job created on the selected machine | An always-available Link service, or another active Link host process |

`/remote` does not copy a terminal chat into a new chat. It publishes the same
in-memory session, transcript, active turn, and future event stream. Inputs
from controllers enter the same serialized input queue as local input. Running
`/remote off`, closing a controller, or losing network connectivity does not
end the local conversation. Closing the owning conversation ends its live
publication.

Dispatch never writes into that conversation. It creates a new idempotent Work
job with its own ID, status, and event history.

## Security boundary

Fabric Link deliberately exposes less than Tailscale or a general tunnel:

- the Fabric machine opens no inbound internet port;
- the relay receives opaque encrypted records, not prompts or responses;
- every controller has a distinct device credential and MLS membership;
- grants are stored and enforced on each machine before JSON-RPC dispatch;
- request IDs, expiry, and replay state are committed atomically;
- revocation denies the controller locally before relay or MLS cleanup;
- the allowed methods are a reviewed Fabric list—there is no raw socket,
  shell, PTY, filesystem, VPN, or LAN bridge.

The relay can still observe connection metadata such as IP addresses, timing,
record sizes, and pseudonymous routes. It can delay or drop traffic. A
compromised unlocked controller can use its current grants until you revoke
it. Fabric Link reduces the reachable surface; it does not make compromised
endpoints safe.

## Before you start

You need:

1. Fabric on each machine you want to control.
2. The Fabric Link native core on every host or Desktop/Terminal controller.
3. One HTTPS relay origin with WebSocket support.
4. The Fabric iOS app or Fabric Desktop if you want a graphical controller.

Signed Fabric Desktop releases bundle the matching native core and verify it
during first-launch installation. In a source checkout, build and install it
once:

```bash
fabric link core install --from-source
fabric link core status
```

If you downloaded a `fabric_link_core-*.whl` release asset, use the SHA-256
from that same release's `release-manifest.json`:

```bash
fabric link core install \
  --wheel /path/to/fabric_link_core-0.21.0-py3-none-PLATFORM.whl \
  --sha256 THE_64_CHARACTER_RELEASE_MANIFEST_DIGEST
```

Fabric rejects a wheel for another Fabric version or platform, a symlink, a
world-writable file, a digest mismatch, or a core with the wrong protocol or
ciphersuite.

## Set up a relay

You can use a Fabric-operated relay when one is configured for your release,
or run the reference relay on a small internet-reachable host. The relay does
not need the native core or any machine/controller secret.

Run it as an unprivileged service account and bind it to loopback:

```bash
fabric link relay serve \
  --origin https://link.example.com \
  --database /srv/fabric-link/relay.sqlite3 \
  --bind 127.0.0.1 \
  --port 8787
```

Terminate TLS in a reverse proxy. For example, a dedicated Caddy origin needs
only:

```caddyfile
link.example.com {
    reverse_proxy 127.0.0.1:8787
}
```

Keep the relay database on private persistent storage and supervise the relay
process with your normal user-level service manager. Do not expose port 8787,
run the relay as root, reuse the origin for untrusted web content, or terminate
TLS on the Fabric machine you are controlling. Controllers pin the HTTPS
origin from the pairing link; production origins require valid public TLS.

Loopback HTTP is accepted only for local development and tests.

## Configure a machine

On the machine you want to control:

```bash
fabric link setup --relay https://link.example.com
fabric link status
```

`setup` creates a device-local Ed25519 machine identity and random relay route,
then stores behavioral settings in `config.yaml`. It creates no account and
opens no listener.

### Pair an iPhone

Keep this command open:

```bash
fabric link pair mobile
```

Then, on iPhone:

1. Open **Settings → Fabric Link**.
2. Tap **Scan Fabric Link code**. You can paste the link instead.
3. Wait for the six-character authentication string.
4. Compare it with the string printed on the machine.
5. Type `yes` on the machine only when both values match.

The QR/link contains a short-lived enrollment secret, so treat it like a
temporary credential. Do not send it through chat or save screenshots.

### Pair Fabric Desktop

On the machine:

```bash
fabric link pair desktop
```

In Fabric Desktop:

1. Open **Settings → Fabric Link**.
2. Paste the one-time v3 pairing link.
3. Choose the name shown on the machine and select **Start secure pairing**.
4. Compare the short authentication string on both screens.
5. Approve with `yes` on the machine.
6. Select **I compared it** in Desktop and wait for the encrypted response.

Desktop can be your only controller; an iPhone is not required. A signed
Desktop install includes the managed Fabric CLI, so it can also be the target
machine: initialize and pair its local backend with the commands above, then
use `/remote` in a Desktop chat or install the always-available service.

### Pair another Terminal

Run `fabric link pair desktop` on the target machine, copy its pairing URL,
and run this on the controller machine:

```bash
fabric link controller pair 'PASTE_THE_PAIRING_URL' \
  --name 'Travel laptop' \
  --platform cli
```

Compare and approve on the target. Then inspect the controller-side machine
ID:

```bash
fabric link controller list
```

## Use exact-session Remote Control

In the Terminal, TUI, or Desktop conversation you want to share, enter:

```text
/remote
```

The response names the exact session ID and confirms whether the encrypted
Link broker is active. On iPhone, open **Settings → Fabric Link**, choose the
machine, then **Open exact live session**. In Desktop, open
**Settings → Fabric Link**, choose **Live sessions**, and attach.

Use these in the owning conversation:

```text
/remote status
/remote off
```

Only sessions explicitly published with `/remote` appear in controller
pickers. Multiple viewers can observe one publication. Inputs are
deduplicated, attributed to the paired controller, and serialized so they
cannot create two concurrent user turns.

## Dispatch Work

Dispatch requires the `dispatch` grant. From iPhone, choose a paired machine
and tap **Dispatch new Work**. From Desktop, choose **Dispatch** beside the
machine. The job keeps running on the host after the controller closes.

From a Terminal controller:

```bash
fabric link dispatch CONTROLLER_ID \
  'Run the release checks and summarize failures' \
  --title 'Release checks'
```

The returned JSON is the durable job receipt. Dispatch does not require a
published `/remote` session.

## Make a machine always available

For Dispatch when no Desktop or terminal conversation is open, install the
unprivileged current-user host:

```bash
fabric link service install --workspace /absolute/path/to/default/workspace
fabric link service status
```

Fabric installs a LaunchAgent on macOS, a systemd user unit on Linux, or a
Task Scheduler entry on Windows. The service opens only the outbound relay
connection and runs with your user permissions.

Useful lifecycle commands:

```bash
fabric link service start
fabric link service stop
fabric link service restart
fabric link service uninstall
```

When an interactive `/remote` publication starts, it temporarily takes the
single broker ownership lease. A running Fabric-managed service is stopped,
the foreground process serves the exact live session, and the service is
resumed when the last publication ends. This prevents two processes from
mutating the same MLS state.

Always-available mode supports new Dispatch work. It cannot keep a closed
terminal's exact in-memory conversation alive.

## Grants, revocation, and recovery

List controller IDs and fingerprints on a host:

```bash
fabric link devices
```

Replace a controller's grants:

```bash
fabric link grant DEVICE_ID --preset observe
fabric link grant DEVICE_ID --preset dispatch
fabric link grant DEVICE_ID --preset standard
fabric link grant DEVICE_ID --grants observe,chat,dispatch --approve
```

The presets never add approval authority implicitly. `--approve` permits that
controller to answer Fabric approval/clarification requests and should be
granted sparingly.

Revoke a lost or untrusted controller from the machine first:

```bash
fabric link revoke DEVICE_ID
```

Local denial is immediate. If the relay is offline, Fabric reports pending
MLS/relay cleanup and retries later. After revocation, use **Forget** on the
controller to remove its protected local state.

If all controllers are lost, local access to each machine is the recovery
path. There is no cloud-support, email, Google, or GitHub reset. To destroy the
host identity completely:

```bash
fabric link service uninstall
fabric link status
fabric link reset --confirm MACHINE_FINGERPRINT
```

Reset preserves controller profiles that this computer uses to control other
machines. It removes only this computer's host authority and disables Link.

## iOS behavior

The controller's MLS state and crash-safe encrypted outbox are stored in the
iOS Keychain with user-presence and ThisDeviceOnly protection. One successful
authentication is reused while a live controller flow remains in the
foreground; all cached authorization contexts are invalidated when the app
backgrounds.

Without APNs, Fabric does not promise immediate background wake. Pairing,
starting a request, and following an exact live session require the app in the
foreground. Once the host accepts a durable Dispatch job, that host-side job
continues independently.

## Dashboard and Web

The local Dashboard can publish its embedded TUI conversation with `/remote`.
Run host-management commands such as `fabric link setup`, `pair`, `grant`, and
`revoke` from a terminal on that machine. An ordinary Dashboard login, gateway
token, Google account, or GitHub account never grants Link authority.

A browser must become an explicitly paired controller and protect its own MLS
state before it can control another machine. The native Desktop/iOS paths do
not fall back to Dashboard authentication, and exposing `/api/ws` through a
generic tunnel is not a substitute for Link.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `native core is not installed` | Run `fabric link core status`, then install the matching release wheel or build from source |
| `relay_not_configured` | Run `fabric link setup --relay https://…` |
| Pairing expires | Generate a fresh QR; links are intentionally short-lived |
| Authentication strings differ | Deny pairing immediately and create a fresh code |
| No live sessions on controller | Enter `/remote` in the exact owning conversation |
| Dispatch unavailable | Check the controller has `dispatch` and the host/service is online |
| `broker_already_running` | Stop the other foreground host or inspect `fabric link service status` |
| Revocation says cleanup pending | Local access is already denied; bring the relay online so cleanup can finish |

For machine-readable diagnostics:

```bash
fabric link status --json
fabric link devices --json
fabric link service status --json
fabric link core status --json
```
