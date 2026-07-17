# Fabric Desktop

<p align="center">
  <a href="https://github.com/ObliviousOdin/fabric/releases"><img src="https://img.shields.io/badge/Releases-macOS%20%C2%B7%20Windows%20%C2%B7%20Linux-6F4BF2?style=for-the-badge" alt="Fabric releases"></a>
  <a href="https://obliviousodin.github.io/fabric/"><img src="https://img.shields.io/badge/Docs-Fabric-6F4BF2?style=for-the-badge" alt="Fabric documentation"></a>
  <a href="https://github.com/ObliviousOdin/fabric/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-Apache--2.0-green?style=for-the-badge" alt="License: Apache-2.0"></a>
</p>

**Fabric Desktop is the native macOS, Windows, and Linux interface for
[Fabric](../../README.md).** It runs the same agent core, profiles,
provider accounts, sessions, memory, and skills as the `fabric` CLI and gateway,
with a purpose-built chat, preview, file-browser, voice, and settings experience.

| Capability        | Desktop experience                                                                      |
| ----------------- | --------------------------------------------------------------------------------------- |
| Agent chat        | Streaming responses, live tool activity, structured results, and shared session history |
| Agent Live View   | Docked Browser and Computer Use previews with action history and an always-on-top PiP    |
| Design            | Structured briefs, deliverable and fidelity choices, and reusable system presets         |
| Workspaces        | File browsing, side-by-side previews, multiple projects, and coding rails               |
| Providers         | Personal OAuth/subscriptions, API keys, native Ollama, and per-profile model selection  |
| Memory and skills | The same profile-scoped memory and Skills Hub state used by every Fabric surface        |
| Operations        | Profiles, messaging, schedules, tools, updates, diagnostics, and uninstall controls     |

## Distribution status

The source build is available from this repository. Public Fabric installers are
not considered released until the matching entry appears on the
[Fabric releases page](https://github.com/ObliviousOdin/fabric/releases)
with platform signatures, notarization where applicable, and checksums. Do not
download a similarly named Fabric/Nous installer and assume it is a Fabric build.

The checked-in packaging contract currently produces these release names:

- macOS: `Fabric-<version>-mac-arm64.dmg` and `.zip`
- Windows: `Fabric-<version>-win-x64.exe` and `.msi`
- Linux: `Fabric-<version>-linux-x64.AppImage`, `.deb`, and `.rpm`

CI packages are unsigned verification artifacts. They are not substitutes for a
signed production release.

## Run from a Fabric checkout

Install the engine first by following the
[Fabric installation guide](https://obliviousodin.github.io/fabric/getting-started/installation),
then launch the desktop app with:

```bash
fabric desktop
```

That command builds and launches the app against the active Fabric profile. The
CLI and desktop share `~/.fabric` (or `%LOCALAPPDATA%\fabric` on Windows), so
there is no second account or session store to configure.

## Development

Install workspace dependencies at the repository root, then start the renderer
and Electron main process:

```bash
npm ci
cd apps/desktop
npm run dev
```

Before changing desktop colors, typography, brand assets, overlays, or shared
controls, read the [desktop design contract](DESIGN.md) and the canonical
[Fabric design foundation](../design-system/README.md).

Use a disposable profile while changing onboarding, authentication, or update
code. Legacy `HERMES_DESKTOP_*` environment names remain readable compatibility
interfaces; use the canonical Fabric names in new development instructions.

```bash
FABRIC_HOME=/tmp/fabric-desktop-dev npm run dev
FABRIC_DESKTOP_ROOT=/path/to/fabric npm run dev
npm run dev:fake-boot
```

### Build packages

The brand manifest at [`branding/fabric.json`](branding/fabric.json) is the
single identity source for the app name, bundle ID, protocols, native icons,
installer labels, executable metadata, support links, and artifact stem.

```bash
npm run dist:mac     # DMG + zip on macOS
npm run dist:win     # NSIS + MSI on Windows
npm run dist:linux   # AppImage + deb + rpm on Linux
npm run pack         # unpacked app for the current host
```

The checked-in Fabric manifest is the only release identity. Asset paths must
remain inside `apps/desktop`, and the manifest retains the compatibility
protocol required for in-place upgrades. See
[`branding/README.md`](branding/README.md).

### Signing and notarization

Packaging and release are separate gates:

- macOS Developer ID signing uses Electron Builder's `CSC_LINK` and
  `CSC_KEY_PASSWORD` inputs. Notarization additionally requires either an
  `APPLE_NOTARY_PROFILE`, or the complete `APPLE_API_KEY`,
  `APPLE_API_KEY_ID`, and `APPLE_API_ISSUER` set.
- Windows production packages require a Fabric-controlled Authenticode signing
  identity and a post-sign verification step. An unsigned `.exe` or `.msi` is
  only a CI/developer artifact.
- Linux packages are not code-signed by Electron Builder today. A release must
  still publish checksums (and any separately approved release signature).

Never place signing credentials in a brand manifest or commit them to the
repository.

## Architecture

The package contains an Electron shell and React renderer. It launches a local
`fabric serve` backend and communicates over the shared JSON-RPC/WebSocket
client in [`apps/shared`](../shared/). It does not embed the terminal TUI or
require the web dashboard UI.

Agent Live View is supporting UI around the existing conversation, not another
chat surface. Compatible Browser sessions on a local backend pull one bounded
frame at a time over a separate authenticated visual connection, while Computer
Use reuses images already returned by its actions. Electron accepts PiP commands
only from the owning renderer/window pair. Neither visual path adds a model
tool, prompt content, context tokens, or model calls. See the [Browser](https://obliviousodin.github.io/fabric/user-guide/features/browser#desktop-live-view)
and [Computer Use](https://obliviousodin.github.io/fabric/user-guide/features/computer-use#desktop-live-view)
guides for the docked and picture-in-picture workflows.

Compatibility identifiers such as `HERMES_DESKTOP_HERMES_ROOT`, the legacy
`hermes:` URL scheme, and older managed-install markers remain readable for one
migration window. New package identity comes from the Fabric manifest:
`io.github.obliviousodin.fabric`, `fabric:`, `Fabric.app`, and `Fabric.exe`.

## Verification

Before opening a desktop PR:

```bash
npm run --prefix apps/desktop typecheck
npm run --prefix apps/desktop lint
npm run --prefix apps/desktop test:desktop:platforms
npm run --prefix apps/desktop test:ui
```

The native packaging workflow also builds packages on macOS, Windows, and Linux
and rejects artifact names that drift from the manifest.

## Troubleshooting

Desktop boot logs are written to `FABRIC_HOME/logs/desktop.log`. The legacy
`HERMES_HOME` variable is still accepted as an input, but new Fabric installs
use `FABRIC_HOME` and `~/.fabric`.

On macOS, reset a stuck microphone permission for the Fabric bundle with:

```bash
tccutil reset Microphone io.github.obliviousodin.fabric
```

For product issues, use the
[Fabric issue tracker](https://github.com/ObliviousOdin/fabric/issues).

## License and upstream attribution

Fabric is distributed under the repository's Apache License 2.0. The complete
upstream MIT notice is preserved in
[`LICENSES/MIT-hermes-agent.txt`](../../LICENSES/MIT-hermes-agent.txt), with
the required attribution summarized in [`NOTICE`](../../NOTICE).
