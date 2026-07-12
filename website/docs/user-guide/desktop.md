---
sidebar_position: 3
title: "Fabric Desktop"
description: "Use Fabric's native macOS, Windows, and Linux app for chat, providers, local models, memory, skills, projects, and operations."
---

# Fabric Desktop

Fabric Desktop is a native Electron application over the same agent core
used by the CLI, TUI, web dashboard, API, and messaging gateway. Profiles,
provider accounts, model choices, sessions, memory, skills, and approvals are
shared rather than copied into a desktop-only database.

The app targets **macOS, Windows, and Linux**. See
[Platform Support](/getting-started/platform-support) for the distinction
between a source build, an unsigned CI artifact, and a signed production release.

:::caution Distribution status
Do not infer that a signed Fabric installer exists from the presence of packaging
code. A public package is released only when it appears under
[`ObliviousOdin/fabric` releases](https://github.com/ObliviousOdin/fabric/releases)
with checksums and the required platform signature.
:::

## Install and launch

Install the engine from the public Fabric checkout as described in
[Install Fabric](/getting-started/installation), then run:

```bash
fabric desktop
```

The first source build installs workspace dependencies and downloads Electron,
so it is slower than later launches. Fabric reuses the build while its content
stamp is current.

Useful launch controls:

| Flag                 | Behavior                                                         |
| -------------------- | ---------------------------------------------------------------- |
| `--cwd PATH`         | Open chat in a specific project directory                        |
| `--source`           | Run against the development renderer instead of the packaged app |
| `--skip-build`       | Launch an existing build without rebuilding                      |
| `--force-build`      | Ignore the content stamp and rebuild                             |
| `--build-only`       | Build without launching                                          |
| `--ignore-existing`  | Ignore a legacy CLI found on `PATH` during backend resolution    |
| `--fabric-root PATH` | Compatibility flag that selects an engine source checkout        |
| `--fake-boot`        | Exercise deterministic startup states for development/QA         |

`--fabric-root` and the `HERMES_DESKTOP_*` variables are internal compatibility
interfaces. They do not control the visible product identity.

## Interfaces that share the profile

- **Desktop** — native chat, project navigation, previews, and visual settings.
- **CLI** — `fabric`, optimized for scripting and direct terminal work.
- **TUI** — `fabric --tui`, a full-screen terminal experience.
- **Web dashboard** — `fabric dashboard`, a browser management surface.
- **Gateway** — `fabric gateway`, messaging channels and long-running sessions.

All use the selected profile under `FABRIC_HOME` (normally `~/.fabric`). A named
profile stays isolated from the default profile across every surface.

## First-run onboarding

On first launch, choose one account/model route or select **Choose provider
later**. The supported ownership lanes remain distinct:

- **My account / subscription** — complete provider OAuth locally and store the
  resulting credential in the selected profile.
- **API key** — save a provider key to the selected profile's private auth
  store; never place it in project config.
- **Native Ollama** — connect to the native Ollama server root (normally
  `http://127.0.0.1:11434`), explicitly refresh installed models, choose one,
  and apply it without an API key.
- **Fabric-managed request** — records a profile-scoped access request. It does
  not make an account ready until the managed control plane reports a verified
  ready state.

Opening a provider picker is passive: it does not probe local network services
or begin OAuth. Discovery and sign-in start only after an explicit action.

## Chat and projects

The main window provides:

- streaming assistant output and live tool activity;
- approval prompts for dangerous actions;
- drag-and-drop attachments;
- a project file browser and preview rail;
- multiple concurrent conversations and profile-aware session history;
- composer history, queued-message editing, and model controls; and
- voice input/output when the platform grants microphone permission.

The composer model picker changes the active chat/device selection. Set the
profile-wide default under **Settings → Model**. Switching models in a live
conversation invalidates the provider prompt cache, so a new chat is often the
cheaper choice for a long transcript.

## Provider and local-model settings

Open **Settings → Providers**:

- **Accounts** contains subscription/OAuth routes.
- **API keys** contains key-based providers.
- **Local models** contains native local providers such as Ollama.

For Ollama, the app does not guess that a daemon is available. Enter the native
server root, choose **Refresh**, select an installed model, then **Apply**. A
loopback endpoint can automatically use `local_ai` policy. A LAN endpoint must
be a permitted private literal address and requires a narrowly approved CIDR;
public, metadata, credential-bearing, and unsafe URLs are rejected.

See [Local Ollama](/guides/local-ollama-setup) for context-window,
tool-capability, egress, and troubleshooting guidance.

## Memory and skills

Desktop consumes the same profile-local memory and skill registries as the CLI.
Use the visual pages for normal inspection and management; use these CLI checks
when diagnosing a mismatch:

```bash
fabric memory status
fabric skills list --enabled-only
fabric skills audit
```

External memory providers remain subject to consent, profile scope, egress, and
provider capability limits. Installing a skill remains a trust decision even
when it is initiated from a visual catalog.

## Updates

The in-app update action currently drives the managed source-update/rebuild path
used by `fabric update`; it is not proof of a signed binary auto-update channel.
Preview an engine update from the CLI with:

```bash
fabric update --check
```

Production desktop auto-update remains gated on signed, checksum-published
packages, downgrade rules, and rollback evidence. See
[Updating & Uninstalling](/getting-started/updating).

## Uninstall

Open **Settings → About → Danger zone**, or use the CLI:

```bash
fabric uninstall --gui   # remove only desktop build/data
fabric uninstall         # remove engine; choose whether to retain profiles
fabric uninstall --full  # remove engine and user data after confirmation
```

Removing only the GUI keeps providers, sessions, memory, skills, and the CLI.
Create a backup before a full removal.

## Connect to a remote Fabric backend

Desktop normally starts a local `fabric serve` child process. It can instead
connect to a Fabric backend on another machine under **Settings → Gateway →
Remote gateway**.

:::warning Treat the backend as privileged
The backend can read profile credentials and execute agent tools. Keep it on a
trusted VPN/private network, use TLS at the boundary, and enable a configured
authentication provider. Never expose a basic-password backend directly to the
public internet.
:::

For a trusted VPN test, put the compatibility auth variables in
`~/.fabric/.env` on the backend:

```bash
HERMES_DASHBOARD_BASIC_AUTH_USERNAME=admin
HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=choose-a-strong-password
HERMES_DASHBOARD_BASIC_AUTH_SECRET=replace-with-a-long-random-secret
```

Then start the backend on the machine's private/VPN address:

```bash
fabric serve --host 0.0.0.0 --port 9119
```

Enter `https://<private-host>:9119` (or the protected reverse-proxy URL) in the
desktop settings, sign in, and reconnect. The gateway for Telegram/Discord/etc.
is a separate process; start it independently if needed.

For an internet-reachable deployment, configure an approved self-hosted OIDC
provider and TLS reverse proxy. Fabric does not claim a public hosted desktop-auth
service in this guide.

## Troubleshooting

Start with the desktop log:

```bash
fabric logs desktop -f
```

The underlying file is normally `~/.fabric/logs/desktop.log`.

| Symptom                                       | Action                                                                                      |
| --------------------------------------------- | ------------------------------------------------------------------------------------------- |
| Startup cannot find the backend               | Run `fabric doctor`; confirm the selected profile and engine checkout exist                 |
| Local Ollama list is empty                    | Start Ollama, verify `/api/tags`, then press **Refresh** explicitly                         |
| Remote connection returns 401                 | Verify the advertised auth provider and credentials on the remote backend                   |
| App is signed out after every backend restart | Configure a stable authentication signing secret                                            |
| Linux app will not launch                     | Inspect sandbox/AppArmor errors; do not permanently disable system security as a first step |
| Windows rebuild reports a locked executable   | Exit all Fabric desktop/backend processes before replacing the package                      |

On macOS, reset only the Fabric microphone permission with:

```bash
tccutil reset Microphone io.github.obliviousodin.fabric
```

## Build and product branding development

From the repository root:

```bash
npm ci
cd apps/desktop
npm run dev
```

Native packages:

```bash
npm run dist:mac
npm run dist:win
npm run dist:linux
```

`apps/desktop/branding/fabric.json` is the canonical identity contract. The
checked-in Fabric manifest is the sole release identity. Brand assets
must be staged inside the desktop package; compatibility protocol aliases do not
change the visible Fabric identity.

Before a desktop PR:

```bash
npm run --prefix apps/desktop typecheck
npm run --prefix apps/desktop lint
npm run --prefix apps/desktop test:desktop:platforms
npm run --prefix apps/desktop test:ui
```
