---
sidebar_position: 3
title: "Install on Jetson Nano"
description: "Step-by-step Fabric install on NVIDIA Jetson Nano and Orin Nano — JetPack Python caveats, managed-Python install path, and optional on-device Ollama"
---

# Install Fabric on an NVIDIA Jetson Nano

:::warning Tier 2 platform
Jetson boards run NVIDIA's JetPack (an Ubuntu-based L4T distribution) on
arm64, so they fall under the **Linux arm64** row of the
[platform-support matrix](./platform-support.md#tier-2) — a best-effort
compatibility target. The original Jetson Nano's JetPack 4.x line is EOL
upstream; treat it as experimental.
:::

The install is essentially the [Raspberry Pi flow](./raspberry-pi.md) with
one Jetson-specific wrinkle: **JetPack's system Python is too old for
Fabric** (Python 3.6 on JetPack 4, 3.8 on JetPack 5, 3.10 on JetPack 6 —
Fabric needs 3.11–3.13). Don't try to upgrade the OS Python; the official
installer sidesteps it by downloading a managed Python via `uv`.

## Which board?

| Board | RAM | JetPack / base OS | Verdict |
| --- | --- | --- | --- |
| Jetson Orin Nano / Orin NX | 4–16 GB | JetPack 5/6 (Ubuntu 20.04/22.04) | Recommended. Full install works; 8 GB+ can optionally run small local models. |
| Jetson Nano (original, 2019) | 4 GB | JetPack 4.x (Ubuntu 18.04, EOL) | Best-effort. The CLI and gateway run; keep inference off-device. |
| Jetson Nano 2 GB | 2 GB | JetPack 4.x (EOL) | Use the lean profile and add swap, as on a 1–2 GB Pi. |

All Jetson boards are aarch64, so the 64-bit check from the Pi guide always
passes. Jetson images ship with zram swap enabled by default
(`nvzramconfig`); check `free -m` — if total swap is small and you are on a
2–4 GB board, add a swapfile before installing.

## 1. Install system packages

```bash
sudo apt update
sudo apt install -y git curl ripgrep build-essential python3-dev libffi-dev
```

## 2. Install Fabric

Use the official installer. On Jetson it does the heavy lifting that the OS
cannot: installs a managed `uv`, which downloads a managed Python 3.11 for
aarch64 (independent of JetPack's system Python), fetches an arm64 Node.js
for the TUI, and installs the `[all]` extras:

```bash
curl -fsSL https://raw.githubusercontent.com/ObliviousOdin/fabric/main/scripts/install.sh | bash
```

On a 2 GB Nano — or if you want a minimal footprint on any board — use a
managed Python without first installing the full `[all]` profile. Install the
same managed `uv` binary used by Fabric's installer, then let it download
Python 3.11 and target the new environment explicitly:

```bash
FABRIC_HOME="${FABRIC_HOME:-$HOME/.fabric}"
mkdir -p "$FABRIC_HOME/bin"
uv_installer="$(mktemp)"
curl -LsSf https://astral.sh/uv/install.sh -o "$uv_installer"
UV_UNMANAGED_INSTALL="$FABRIC_HOME/bin" sh "$uv_installer"
rm -f "$uv_installer"

git clone https://github.com/ObliviousOdin/fabric.git
cd fabric
"$FABRIC_HOME/bin/uv" venv venv --python 3.11
"$FABRIC_HOME/bin/uv" pip install --python venv/bin/python -e '.[cli]'
source venv/bin/activate
```

Add only the extras you need, as described in the
[low-memory guide](./low-memory.md#the-lean-lite-install-profile). Gateway
platform SDKs lazy-install when that platform is configured.

:::note JetPack 4 (original Nano)
JetPack 4's Ubuntu 18.04 userland is old enough that best-effort is the
honest label: the managed-Python path is the one most likely to work, but
upstream tools drop old-glibc support over time. If the installer cannot
provision Python on your image, the practical fixes are a community Ubuntu
20.04 image for the original Nano or moving to an Orin-class board.
:::

## 3. Configure

```bash
fabric setup
fabric model
```

Fabric itself has no CUDA dependency — model inference is external either
way. Pick one:

- **Cloud provider** — any provider configured through `fabric model`.
- **Remote Ollama on your LAN** — select Ollama in `fabric model` and point
  the server URL (`model.base_url`) at the machine running it.
- **On-device Ollama (Orin Nano 8 GB+ only)** — Ollama ships arm64 Linux
  builds. Its Linux installer detects JetPack 5 (L4T R35) and JetPack 6
  (L4T R36) and downloads their dedicated support bundles. Stick to small
  quantized models and expect modest speeds:

  ```bash
  curl -fsSL https://ollama.com/install.sh | sh
  fabric ollama pull qwen3:4b
  fabric model   # choose Ollama
  ```

  Do not attempt on-device models on the original Nano — 4 GB shared with
  the OS is not enough, and JetPack 4's CUDA stack is too old for current
  Ollama GPU support.

## 4. Run the gateway as a service (optional)

Identical to the Pi:

```bash
fabric gateway setup
fabric gateway install
fabric gateway status
sudo loginctl enable-linger "$USER"   # user-scope service on headless boots
```

## 5. Verify

```bash
fabric version
fabric doctor
fabric status
```

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `pip install -e .` fails with syntax/version errors | You used JetPack's system Python (≤ 3.10). Use the installer's managed Python instead. |
| Installer cannot download Python/uv on JetPack 4 | Old glibc/CA store. Update `ca-certificates`; if it persists, see the JetPack 4 note above. |
| Install killed mid-way on 2–4 GB boards | Add a swapfile on top of the default zram, retry. |
| Ollama runs CPU-only on Jetson | Check `/etc/nv_tegra_release`; the current Ollama installer provides dedicated JetPack 5 (R35) and 6 (R36) bundles. Otherwise keep inference remote. |
| Board throttles under load | Check the power model (`sudo nvpmodel -q`) and use an adequate power supply. |

## See also

- [Install on Raspberry Pi](./raspberry-pi.md) — the same flow, plus swap and 64-bit checks in more detail
- [Low-Memory Devices](./low-memory.md) — lean profile and embedding-free memory options
- [Local Ollama Setup](/guides/local-ollama-setup)
- [Platform Support](./platform-support.md)
