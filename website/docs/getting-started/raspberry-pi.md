---
sidebar_position: 3
title: "Install on Raspberry Pi"
description: "Step-by-step Fabric install on Raspberry Pi 3, 4, or 5 — 64-bit OS check, swap setup, full or lean install, and running the gateway as a service"
---

# Install Fabric on a Raspberry Pi

:::warning Tier 2 platform
Raspberry Pi is covered by the **Linux arm64** row of the
[platform-support matrix](./platform-support.md#tier-2) — a best-effort
compatibility target, not a release-blocking Tier 1 platform.
:::

This guide walks through a headless Fabric install on a Raspberry Pi:
CLI sessions plus a messaging gateway, with model inference on a cloud
provider or another machine on your LAN. For the reasoning behind the lean
profile (what fits in how much RAM, what to skip), see
[Low-Memory Devices](./low-memory.md).

## What you need

- **Raspberry Pi 3, 4, or 5** with a **64-bit OS** — Raspberry Pi OS (64-bit,
  Bookworm or later) or Ubuntu Server arm64. 32-bit (armv7) images are not
  supported. Pi Zero 2 W (512 MB) is not recommended.
- A few GB of free storage. The full install is Node + Python dependencies;
  the lean profile fits comfortably in well under 1 GB.
- Either an API key for a cloud model provider, or another machine on your
  network running [Ollama](https://ollama.com).

## 1. Confirm you are on a 64-bit OS

```bash
uname -m        # must print: aarch64
getconf LONG_BIT  # must print: 64
```

If you see `armv7l` or `32`, reflash with a 64-bit image before continuing —
this guide and Fabric's Linux SBC compatibility target cover arm64 only.

## 2. Add swap (1–2 GB boards)

Dependency resolution and occasional source builds can spike past what a
1–2 GB board has free. On Raspberry Pi OS, raise the default swapfile:

```bash
sudo sed -i 's/^CONF_SWAPSIZE=.*/CONF_SWAPSIZE=1024/' /etc/dphys-swapfile
sudo systemctl restart dphys-swapfile
```

On Ubuntu Server, install `zram-tools` (`sudo apt install zram-tools`) or
create a swapfile. Treat this as install-time insurance, then use `free -m`
to verify that normal operation does not continuously depend on swap. Boards
with 4 GB+ can usually skip this step.

## 3. Install system packages

```bash
sudo apt update
sudo apt install -y git curl ripgrep build-essential python3-dev python3-venv libffi-dev
```

`ffmpeg` is optional (media and TTS conversions); add it if you plan to use
those features.

## 4. Install Fabric

### Option A — full install (Pi 4/5 with 2 GB+ RAM)

The official installer works on arm64. It installs its own managed `uv`,
downloads a managed Python (so the OS Python version does not matter),
fetches an arm64 Node.js build for the TUI, and installs the full `[all]`
extras set:

```bash
curl -fsSL https://raw.githubusercontent.com/ObliviousOdin/fabric/main/scripts/install.sh | bash
```

### Option B — lean install (1 GB boards, or minimal deployments)

Install the base package plus only the extras you need:

```bash
git clone https://github.com/ObliviousOdin/fabric.git
cd fabric
python3 --version                            # must be 3.11-3.13
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -e '.[cli]'                    # base + interactive CLI
# add MCP only if you need it:
# pip install -e '.[cli,mcp]'
```

Gateway platform SDKs lazy-install when you configure that platform, so a lean
deployment does not need the broad `messaging` extra.

If your distribution's Python is outside 3.11–3.13, use the standalone
managed-`uv` [lean install from the Jetson guide](./jetson-nano.md#lean-install-all-boards)
instead. The bootstrap is generic Linux arm64 and avoids putting the full
`[all]` profile on a 1 GB board. In later login shells, return to the clone and
run `source venv/bin/activate` before using `fabric`.

See [Low-Memory Devices](./low-memory.md#the-lean-lite-install-profile) for
which extras to pick and which to avoid on small boards.

## 5. Configure

```bash
fabric setup     # provider keys, services
fabric model     # pick the model/provider
```

Two model patterns work well on a Pi:

- **Cloud provider** — configure any provider in `fabric model`; on-device
  cost is just the HTTPS client.
- **Remote Ollama on your LAN** — run Ollama on a desktop or homelab box,
  select Ollama in `fabric model`, and set the server URL (`model.base_url`)
  to that host instead of `http://localhost:11434`. Keep inference remote on
  1–4 GB boards. Small quantized models are possible but slow on an 8 GB Pi 5;
  see [Low-Memory Devices](./low-memory.md#models-keep-inference-off-the-device).

## 6. Run the gateway as a service (optional)

For an always-on messaging bot (Telegram, Discord, Slack, …), configure a
channel and install the built-in service. On Linux this manages a systemd
unit for you:

```bash
fabric gateway setup      # configure a messaging channel
fabric gateway install    # install + start the gateway service
fabric gateway status
```

If the service was installed in systemd *user* scope, enable lingering so it
survives logout and starts at boot on a headless Pi:

```bash
sudo loginctl enable-linger "$USER"
```

## 7. Verify

```bash
fabric version
fabric doctor
fabric status
free -m          # observe headroom during a representative live session
```

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `pip`/compiler killed during install | Out of memory — add swap (step 2) and retry. |
| A dependency tries to compile from source and fails | Check `uname -m` first; `armv7l` is outside the supported guide target, so reflash 64-bit before debugging the package. |
| `fabric --tui` fails to launch | The TUI needs Node ≥ 20. The Option A installer provides it; on a lean install use the plain `fabric` CLI or install Node yourself. |
| Gateway dies after SSH logout | Use `fabric gateway install` (service) rather than a foreground `fabric gateway start`, and enable lingering (step 6). |
| Everything is slow on first run | SD-card I/O. A USB 3 SSD (Pi 4/5) markedly improves install and startup times. |

## See also

- [Low-Memory Devices](./low-memory.md) — what fits in 1 GB and why
- [Install on Jetson Nano](./jetson-nano.md) — the same approach on NVIDIA Jetson boards
- [Local Ollama Setup](/guides/local-ollama-setup) — including remote-host configuration
- [Platform Support](./platform-support.md)
