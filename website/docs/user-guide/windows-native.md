---
title: "Windows (Native)"
description: "Run Fabric on Windows 10/11: desktop packaging status, native feature matrix, data paths, updates, and troubleshooting."
sidebar_label: "Windows (Native)"
sidebar_position: 3
---

# Windows (Native)

Fabric targets native Windows 10/11 x64 for the CLI, gateway, dashboard,
and desktop app. The package target produces a Fabric-branded NSIS installer and
MSI, but a package is not a public release until it is Authenticode-signed,
checksummed, and published under `ObliviousOdin/fabric`.

:::caution Verify Windows installers
Until a signed Windows asset appears on the
[Fabric release page](https://github.com/ObliviousOdin/fabric/releases),
use WSL2 for the source setup or build from the public checkout for development.
:::

For WSL2, follow the [WSL guide](/user-guide/windows-wsl-quickstart) together with the
[Fabric installation guide](/getting-started/installation).

## Desktop package contract {#desktop-installer-alternative}

The Windows build derives its identity from
`apps/desktop/branding/fabric.json`:

| Property             | Required value                        |
| -------------------- | ------------------------------------- |
| Product display name | Fabric                          |
| Executable           | `Fabric.exe`                          |
| Application ID       | `io.github.obliviousodin.fabric`                     |
| Primary URL scheme   | `fabric:`                             |
| NSIS artifact        | `Fabric-<version>-win-x64.exe`  |
| MSI artifact         | `Fabric-<version>-win-x64.msi`  |

Windows packaging CI rejects missing formats and drift from the manifest. CI artifacts remain unsigned developer
outputs; Windows SmartScreen warnings are expected for them and must not be
normalized into the production experience.

## Feature matrix

| Feature                             |                              Native Windows |                                                             WSL2 |
| ----------------------------------- | ------------------------------------------: | ---------------------------------------------------------------: |
| Fabric Desktop                |                            ✓ package target | Run the Windows app against a WSL/remote backend when configured |
| CLI (`fabric`)                      |                                           ✓ |                                                                ✓ |
| Interactive TUI (`fabric --tui`)    |                                           ✓ |                                                                ✓ |
| Messaging gateway                   |                                           ✓ |                                                                ✓ |
| Scheduled jobs                      |                                           ✓ |                                                                ✓ |
| Browser tools                       | ✓ with supported Chromium/Node dependencies |                                                                ✓ |
| MCP stdio and HTTP servers          |          ✓ when the server supports Windows |                                                                ✓ |
| Native Ollama                       |                                           ✓ |                          ✓ through the selected network boundary |
| Web management pages                |                                           ✓ |                                                                ✓ |
| Dashboard's embedded POSIX terminal |                     Not currently supported |                                                                ✓ |

The embedded terminal needs a POSIX PTY. This limitation does not remove the
native desktop chat surface or the rest of the web dashboard.

## Source-development setup

Native Windows development requires the public
`ObliviousOdin/fabric` checkout, Git for Windows, Node 22, and a compatible
Python/uv environment. Follow the repository's
[developer setup](/developer-guide/contributing), then:

```powershell
npm ci
npm run --prefix apps/desktop build
npm run --prefix apps/desktop test:desktop:platforms
```

Run the desktop development process from the checkout only after the engine
environment is ready. Use only download URLs published by the official repository.

## Data layout

New Fabric profiles use `%LOCALAPPDATA%\fabric` by default:

| Path                                | Contents                                                         |
| ----------------------------------- | ---------------------------------------------------------------- |
| `%LOCALAPPDATA%\fabric\config.yaml` | Default-profile settings                                         |
| `%LOCALAPPDATA%\fabric\.env`        | Mode-restricted secret file when a vault/keychain is unavailable |
| `%LOCALAPPDATA%\fabric\profiles\`   | Named profile roots                                              |
| `%LOCALAPPDATA%\fabric\sessions\`   | Default-profile sessions                                         |
| `%LOCALAPPDATA%\fabric\logs\`       | Agent, gateway, update, and desktop logs                         |
| `%LOCALAPPDATA%\fabric\fabric-agent\venv\Scripts\` | Default native CLI launchers                         |

`FABRIC_HOME` selects another data root. `FABRIC_HOME` and several
`HERMES_DESKTOP_*` variables remain internal compatibility inputs; new
instructions use Fabric names wherever a first-class Fabric name is implemented.

After installation, a new PowerShell window should resolve the Fabric launcher:

```powershell
Get-Command fabric  # defaults to %LOCALAPPDATA%\fabric\fabric-agent\venv\Scripts\fabric.exe
```

## Shell execution {#how-fabric-runs-shell-commands-on-windows}

The terminal tool uses Git Bash on native Windows. The compatibility resolver
checks the configured Git-Bash path, a managed PortableGit install, a system
Git-for-Windows install, then other supported Bash locations. Existing
installations may still configure `HERMES_GIT_BASH_PATH`; treat it as a technical
compatibility key, not product branding.

When a command has a Windows `.cmd` shim, invoke the shim resolved from `PATH`
rather than hard-coding the extensionless Node script.

## UTF-8 and editors

Fabric configures UTF-8 console I/O early so multilingual prompts, tool output,
and Rich/TUI rendering do not fail under a legacy Windows code page. Windows
Terminal is the recommended host.

Set a blocking editor for `/edit` and external-edit shortcuts:

```powershell
$env:EDITOR = "code --wait"
```

Notepad, Neovim, Helix, and Notepad++ also work when their executable is on
`PATH`. A non-blocking editor command returns before Fabric can read the edited
buffer.

## Gateway at login

Install the profile's gateway startup task without an administrator shell:

```powershell
fabric gateway install
fabric gateway status
```

The native implementation uses a per-user Scheduled Task with a Startup-folder
fallback where policy prevents task registration. Manage it through Fabric so
the task, process, profile, and log paths remain consistent:

```powershell
fabric gateway start
fabric gateway stop
fabric gateway restart
fabric gateway uninstall
```

## Updates and locked files

Before a native update, exit Fabric Desktop and stop processes using the
managed environment:

```powershell
fabric gateway stop
fabric update --check
fabric update
```

Windows cannot atomically replace a running `Fabric.exe`, console launcher,
Python interpreter, or loaded `.pyd`. A safe updater reports the owning process
and refuses to leave the environment half-updated. Do not use force options as a
routine workaround.

## Uninstall

Remove only the desktop application:

```powershell
fabric uninstall --gui
```

Remove the engine while choosing whether to retain profiles:

```powershell
fabric uninstall
```

Use `fabric uninstall --full` only after reviewing the profile-data removal and
creating any required backup.

## Troubleshooting

| Symptom                                         | Resolution                                                                                               |
| ----------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `fabric` is not found after install             | Open a new terminal and confirm the Fabric environment's Scripts/bin directory is on User `PATH`          |
| `Fabric.exe` is locked during build/update      | Exit Desktop and stop its backend/gateway before retrying                                                |
| Unicode renders as `?`                          | Use Windows Terminal and verify the UTF-8 compatibility opt-out is not set                               |
| Browser helper is not a valid Win32 application | Resolve the Windows `.cmd` shim rather than an extensionless Node script                                 |
| Native dashboard Chat terminal is unavailable   | Use `fabric --tui`, Desktop chat, or WSL2 for the POSIX terminal pane                                    |
| Ollama cannot be discovered                     | Start the Windows Ollama service, verify the native `/api/tags` route, then press **Refresh** explicitly |
| An unsigned installer triggers SmartScreen      | Do not bypass the warning for production; verify a signed Fabric release and checksum                     |

Inspect logs and environment health with:

```powershell
fabric doctor
fabric logs desktop -n 100
fabric logs errors -n 100
```
