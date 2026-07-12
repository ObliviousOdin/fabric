---
title: "Windows (WSL2)"
description: "Install Fabric in WSL2, share files and services safely with Windows, and connect the native desktop app."
sidebar_label: "Windows (WSL2)"
sidebar_position: 2
---

# Windows (WSL2)

WSL2 runs Fabric in a real Linux environment while Windows continues to
host native apps such as a browser, Ollama, and Fabric Desktop. Choose it
when you need POSIX paths, signals, sockets, and PTY-backed terminal behavior.

For direct Windows processes and the native package target, see
[Windows (Native)](/user-guide/windows-native).
The public source and issue tracker live at
[`ObliviousOdin/fabric`](https://github.com/ObliviousOdin/fabric).

## Install WSL2

From an administrator PowerShell/Windows Terminal:

```powershell
wsl --install
```

Reboot when prompted, create the Linux user, and confirm the distribution uses
WSL2:

```powershell
wsl --list --verbose
```

If needed:

```powershell
wsl --set-version Ubuntu 2
wsl --set-default-version 2
```

## Enable systemd

Inside Ubuntu/WSL:

```bash
sudo tee /etc/wsl.conf >/dev/null <<'EOF'
[boot]
systemd=true

[interop]
enabled=true
appendWindowsPath=true

[automount]
options = "metadata,umask=22,fmask=11"
EOF
```

Then restart WSL from PowerShell:

```powershell
wsl --shutdown
```

## Install Fabric inside WSL

Clone the official Fabric repository:

```bash
curl -fsSL https://raw.githubusercontent.com/ObliviousOdin/fabric/main/scripts/install.sh | bash
source ~/.bashrc
fabric version
```

The WSL profile root is `~/.fabric`. It is separate from a native Windows
profile under `%LOCALAPPDATA%\fabric`; do not point both runtimes at the same
live SQLite/session directory.

## Put Linux work on the Linux filesystem

Keep Linux projects, models, and virtual environments under
`/home/<user>`, not `/mnt/c`, unless a Windows program must directly consume the
files. WSL's Windows-drive bridge is slower and has different permission,
case-sensitivity, file-watcher, and locking behavior.

| Direction             | Example                                      |
| --------------------- | -------------------------------------------- |
| Windows file from WSL | `/mnt/c/Users/you/Documents/report.pdf`      |
| WSL file from Windows | `\\wsl.localhost\Ubuntu\home\you\report.pdf` |

Convert paths with `wslpath`:

```bash
wslpath -w ~/projects/example
wslpath -u 'C:\Users\you\Documents'
```

Use LF endings inside WSL:

```bash
git config --global core.autocrlf input
git config --global core.eol lf
```

## Connect to Windows Ollama

When Ollama runs on Windows and Fabric runs in WSL, loopback can refer to
different network namespaces. Determine the Windows host address visible from
WSL and verify the native Ollama route explicitly:

```bash
WINDOWS_HOST=$(ip route show default | awk '{print $3; exit}')
curl --fail --silent --show-error "http://${WINDOWS_HOST}:11434/api/tags"
```

Bind Ollama only to the interface needed for WSL and restrict the Windows
firewall rule. In Fabric, a non-loopback Ollama endpoint must be a private
literal address and must fall inside an explicitly approved `local_ai` CIDR.
Do not broadly expose port 11434 to the LAN.

See [Local Ollama](/guides/local-ollama-setup) for the Fabric-side setup.

## Use Windows Desktop with a WSL backend

Fabric Desktop normally launches its own local backend. To use WSL as the
engine host instead:

1. Start a protected backend inside WSL:

   ```bash
   fabric serve --host 0.0.0.0 --port 9119
   ```

2. Keep the bind private, enable an authentication provider, and allow the port
   only from the Windows host/VPN boundary.
3. In Desktop, open **Settings → Gateway → Remote gateway**, enter the WSL
   backend URL, sign in, and reconnect.

The desktop and WSL backend then use the WSL profile. The Windows app must not
simultaneously mutate a second copy of that profile.

## Run services with systemd

After systemd is enabled:

```bash
fabric gateway setup
fabric gateway install
fabric gateway status
```

WSL itself can stop when no Windows process is using the distribution. If the
gateway must be always-on, use a real Linux host/server rather than relying on a
desktop WSL session as an availability guarantee.

## Troubleshooting

| Symptom                                     | Resolution                                                                         |
| ------------------------------------------- | ---------------------------------------------------------------------------------- |
| `fabric` not found                          | Reload the Linux shell and add `~/.local/bin` to `PATH`                            |
| Git/file operations under `/mnt/c` are slow | Move the checkout/project under `~/`                                               |
| Script reports `^M` / bad interpreter       | Convert CRLF to LF and check Git line-ending settings                              |
| Windows cannot reach `fabric serve`         | Confirm the bind, WSL address/localhost forwarding, firewall, and auth gate        |
| WSL cannot reach Windows Ollama             | Verify the current Windows host address and Ollama bind; do not assume `127.0.0.1` |
| URLs open in the wrong environment          | Use `explorer.exe`/`wslview` deliberately rather than relying on shell defaults    |

Run:

```bash
fabric doctor
fabric status --deep
fabric logs errors -n 100
```
