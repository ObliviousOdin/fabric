---
sidebar_position: 2
title: "Install Fabric"
description: "Install Fabric from the Fabric repository and launch the native desktop app on macOS, Windows, or Linux."
---

# Install Fabric

Fabric currently has a verified source-install path. Signed public desktop
packages are a separate release gate.

:::caution Check the release before downloading
Only treat a desktop package as a public Fabric release when it appears under
[`ObliviousOdin/fabric` releases](https://github.com/ObliviousOdin/fabric/releases)
with checksums and the expected platform signature.
:::

See [Platform Support](/getting-started/platform-support) for the release-blocking operating
systems and the difference between source, CI, and signed production packages.
Installing on a single-board computer? See the step-by-step
[Raspberry Pi](/getting-started/raspberry-pi) and
[Jetson Nano](/getting-started/jetson-nano) guides, and the
[Low-Memory Devices](/getting-started/low-memory) profile for 1 GB boards.

## macOS, Linux, or WSL2

Run the official installer from `ObliviousOdin/fabric`:

```bash
curl -fsSL https://raw.githubusercontent.com/ObliviousOdin/fabric/main/scripts/install.sh | bash
```

The installer creates a virtual environment, installs Python and Node
dependencies, seeds bundled skills, installs the `fabric` command under
`~/.local/bin`, and opens the setup wizard. Developers can instead clone the
repository and follow the [contributor setup](/developer-guide/contributing).

Reload your shell if necessary, then prove that the Fabric entry point and home
directory are active:

```bash
source ~/.zshrc  # use ~/.bashrc for Bash
fabric version
fabric status
```

New installs store profile data under `~/.fabric`. `FABRIC_HOME` can select a
different root. See the [environment-variable reference](/reference/environment-variables)
for migration-only compatibility inputs used by older installs.

## Native desktop app

After the engine is installed from the Fabric checkout, build and launch the
desktop app for the current host:

```bash
fabric desktop
```

This source-build command installs workspace dependencies, packages an unpacked
native app, and launches it against the same profiles used by the CLI. It is not
a signed distribution package. The first build downloads Electron and may take
several minutes.

The packaged product identity is **Fabric**:

| Platform    | App identity                                                  | Production formats   |
| ----------- | ------------------------------------------------------------- | -------------------- |
| macOS arm64 | `Fabric`, bundle `io.github.obliviousodin.fabric`, executable `Fabric` | DMG + zip            |
| Windows x64 | `Fabric`, executable `Fabric.exe`                       | NSIS `.exe` + MSI    |
| Linux x64   | `Fabric`, executable `Fabric`                           | AppImage + deb + rpm |

Native package CI verifies those formats and names. CI artifacts are unsigned
and must not be redistributed as production installers.

The manifest-derived filenames are
`Fabric-<version>-mac-arm64.{dmg,zip}`,
`Fabric-<version>-win-x64.{exe,msi}`, and
`Fabric-<version>-linux-x64.{AppImage,deb,rpm}`.

### macOS Gatekeeper

Local source builds use local/ad-hoc signing and are for development. A public
macOS package must be signed with Fabric's Developer ID, notarized by Apple, and
stapled before publication. If macOS blocks an alleged release, verify its
signature and checksum rather than disabling Gatekeeper globally.

### Windows status

The native Windows package and bootstrap paths are verified in Windows CI.
Until a signed package appears on the Fabric release page, use WSL2 for the
source install or build from the public checkout using the
[developer setup](/developer-guide/contributing).

### Linux desktop status

Linux AppImage, deb, and rpm outputs are packaging-verification targets. The
Ubuntu headless engine is Tier 1; the Linux desktop remains preview until a
clean-machine install, update, desktop integration, and uninstall run is recorded
for the release.

## Configure a model

Start with one provider route:

```bash
fabric model
```

The same provider state appears in Desktop under **Settings → Providers**. You
can use a personal subscription/OAuth account, an API key, or native local
Ollama. Follow the dedicated guides for security and ownership details:

- [ChatGPT subscription](/guides/chatgpt-codex-subscription)
- [xAI Grok OAuth](/guides/xai-grok-oauth)
- [Local Ollama](/guides/local-ollama-setup)

Then run a real readiness check instead of treating a saved credential as proof:

```bash
fabric status --deep
fabric doctor
fabric chat -q "Summarize the README in this workspace."
```

## Install without sudo

The per-user installation does not need root. Browser automation on Linux may
need system libraries that only an administrator can install. On Debian/Ubuntu,
an administrator can provision them once:

```bash
sudo npx playwright install-deps chromium
```

Then the unprivileged Fabric user can install project dependencies and the
Chromium binary in its own cache. If `fabric` is not found by a service account,
add `~/.local/bin` to that account's `PATH`; do not copy profile secrets into a
system-wide environment.

## Updates and removal

For a managed Fabric checkout:

```bash
fabric update --check
fabric update
```

The desktop app exposes the same update path under Settings. Production desktop
auto-update is not considered ready until signed release artifacts and rollback
evidence are available. See [Updating & Uninstalling](/getting-started/updating).

Remove only the desktop build or the whole engine with:

```bash
fabric uninstall --gui
fabric uninstall
```

The interactive uninstaller asks whether to retain profile data. Back up a
valuable profile before removal.

## Troubleshooting

| Symptom                               | Check                                                                                                         |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `fabric: command not found`           | Reload the shell and confirm `~/.local/bin` is on `PATH`                                                      |
| Desktop build cannot find Node/npm    | Run `fabric doctor`, then repeat from the Fabric checkout                                                      |
| Electron download fails               | Retry once on a stable connection; use only assets from the official Fabric release page                      |
| Provider saved but chat fails         | Run `fabric status --deep` and inspect the named auth, entitlement, context, or egress failure                |
| A previous Fabric install is detected | Stop its services and use the explicit Fabric home-migration flow; never merge credential directories by hand |

Use [Diagnose and Repair Fabric](/getting-started/repair) for the non-destructive
recovery ladder.

## License and attribution

Required copyright and attribution notices are preserved in the repository
[`LICENSE`](https://github.com/ObliviousOdin/fabric/blob/main/LICENSE) and
[`NOTICE`](https://github.com/ObliviousOdin/fabric/blob/main/NOTICE).
