---
sidebar_position: 3
title: "Low-Memory Devices (Raspberry Pi)"
description: "Run a lean Fabric profile on a Raspberry Pi or other 1 GB single-board computer, with memory options that avoid a local embedding stack"
---

# Fabric on Low-Memory Devices (Raspberry Pi)

:::warning Tier 2 platform
Raspberry Pi and other arm64 single-board computers fall under the **Linux
arm64** row of the [platform-support matrix](./platform-support.md#tier-2):
a headless and package compatibility target, not a release-blocking Tier 1
platform. The lean profile described here is maintained on a best-effort
basis.
:::

Yes — Fabric runs on a 1 GB device. The core agent is a Python process that
talks to a model over the network; it is not the model itself. A base install
measures roughly **70 MiB peak RSS** at runtime import (measured on Linux,
Python 3.13, Fabric 0.21.0 — expect around 100–200 MB for a live session once
conversation state and tool subprocesses are included) and about **104 MB of
disk** for the virtual environment. What does *not* fit in 1 GB is local model
inference and the heavier optional surfaces, so a low-memory deployment is
about choosing a lean profile, not porting Fabric.

## What fits where

| Device class | Verdict |
| --- | --- |
| 512 MB (Pi Zero 2 W) | Not recommended. Installs and upgrades alone can exhaust memory. |
| 1 GB (Pi 3, early Pi 4) | Works headless: CLI sessions and one messaging gateway, cloud or remote inference, file-based or SQLite memory. |
| 2–4 GB (Pi 4/5) | Comfortable: add the TUI, dashboard, and more gateway channels. Local LLM inference is still impractical. |
| 8 GB (Pi 5) | Small quantized local models via Ollama become *possible*, but slow; remote inference remains the better experience. |

Use a **64-bit OS** (Raspberry Pi OS 64-bit, Ubuntu Server arm64). 32-bit
armv7 userlands are not supported: Rust-backed dependencies such as
`pydantic-core` and `cryptography` do not publish armv7 wheels, and Fabric
requires Python 3.11–3.13.

## The lean ("lite") install profile

Skip the `.[all]` extra. Install the base package plus only the extras you
will actually use — the same philosophy as the tested
[Termux profile](./termux.md), which targets similarly constrained phones:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv ripgrep
git clone https://github.com/ObliviousOdin/fabric.git
cd fabric
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -e '.[cli]'          # base + interactive CLI menus
# add extras individually as needed, e.g.:
# pip install -e '.[cli,mcp]'                # + MCP support
# pip install -e '.[cli,mcp,messaging]'      # + Telegram/Discord/Slack gateway
fabric setup
```

Notes for a 1 GB device:

- **Add swap or zram before installing.** Dependency resolution and any
  wheel-less source build can spike past the install-time baseline. 1 GB of
  zram (or a swapfile on non-SD storage) makes installs reliable; steady-state
  operation rarely touches it.
- **Prefer the plain CLI over the TUI.** `fabric --tui` launches a Node ≥ 20
  subprocess for the Ink terminal UI; plain `fabric` keeps everything in one
  Python process.
- **Run the gateway headless.** `fabric gateway start` under systemd is the
  natural deployment for a Pi. Skip `fabric dashboard` when memory is tight —
  it is another long-running process.
- Many optional backends (Telegram, Slack, Honcho, and others) lazy-install on
  first use, so an extra you never touch costs nothing.

## What to leave out at 1 GB

| Surface | Why |
| --- | --- |
| Local LLM inference (on-device Ollama) | Even small quantized 1–3 B models want 2 GB+ and Pi-class CPUs make them painfully slow. Use a cloud provider, or run Ollama on another machine (see below). |
| Desktop app | Electron. Build and runtime footprints are desktop-class by design. |
| Browser tools | The browser stack drives a Chromium instance (local CDP browser or the auto-spawned Chromium sidecar for cloud providers) — hundreds of MB on its own. |
| `voice` extra | `faster-whisper` pulls `ctranslate2` and `onnxruntime`: large native libraries with patchy ARM wheel coverage. |
| `matrix` extra | Builds `python-olm` from source and adds an encryption stack. |
| Docker-based terminal isolation | Running a container engine next to the agent defeats the memory budget. |

## Models: keep inference off the device

The agent core is transport, not inference. Two patterns work well:

1. **Cloud providers** — any provider configured through `fabric model`
   (OpenAI, Anthropic, OpenRouter, subscription/OAuth providers). On-device
   cost is just the HTTPS client.
2. **Remote Ollama on your LAN** — run Ollama on a desktop or homelab box and
   point the Pi at it. Select Ollama in `fabric model` and set the server URL
   (`model.base_url`) to the remote host instead of `http://localhost:11434`.
   The Pi stays under load-free; the LAN box does the inference. See
   [Local Ollama Setup](/guides/local-ollama-setup).

## Memory without a local embedding stack

"Semantic memory" usually implies an embedding model plus a vector database —
exactly the two components a 1 GB device cannot spare. Fabric's memory system
is layered so you can get persistent memory without either:

### Tier 1 (recommended default): built-in file memory

`MEMORY.md` and `USER.md` are plain Markdown files injected into context.
No embedding model, no vector store, effectively zero RAM overhead. This is
the default and needs no configuration. For most single-user Pi deployments
this is all you need.

### Tier 2: `holographic` — local search without an embedding model

If you want searchable, structured long-term memory on-device, select the
`holographic` provider:

```bash
fabric memory setup    # choose "holographic"
```

It is a local SQLite fact store using FTS5 full-text search, trust scoring,
and HRR-based compositional retrieval — **no embedding model and no vector
database required** (NumPy is optional, for the HRR algebra). SQLite ships
with Python, so there is nothing heavy to install. If you enable the HRR
features and want to shrink the per-fact vector footprint further, lower
`hrr_dim` (default 1024, e.g. 512) in the provider config. See
[Memory Providers](/user-guide/features/memory-providers).

### Tier 3: semantic/vector memory with off-device embeddings

If you genuinely need vector-embedding recall, keep the embedding computation
off the device:

- **Hosted providers** (Honcho, hosted Mem0, Supermemory, RetainDB, and other
  cloud adapters): embeddings are computed and stored service-side; the Pi
  only makes API calls. Note that recall sends the query to the provider —
  this is not a local-only mode.
- **Mem0 OSS with a remote embedder**: point the embedder at the OpenAI API
  (`text-embedding-3-small`, 1536 dimensions) or at your LAN Ollama host
  running `nomic-embed-text` (768 dimensions — half the per-memory vector
  footprint of the 1536-dimension models, a meaningful saving on both storage
  and query RAM). The embedded Qdrant store in local *path* mode runs
  in-process and is fine for small collections; do **not** run a separate
  Qdrant server, Postgres/pgvector, or an on-device Ollama embedder next to
  the agent on a 1 GB board.

What to avoid entirely at 1 GB: any provider mode that loads a local
embedding model into the agent's process or requires a database server on the
same host.

## Verifying the deployment

```bash
fabric doctor      # environment and dependency checks
fabric status      # active configuration
free -m            # confirm headroom; expect the agent well under 200 MB
```

If installs fail with out-of-memory kills (`pip` or a compiler being killed),
add swap/zram and retry; if a dependency tries to compile from source on
armv7, you are on a 32-bit OS — reinstall with a 64-bit image.

## See also

- [Platform Support](./platform-support.md) — support tiers for Linux arm64
- [Android / Termux](./termux.md) — the same lean-profile approach on phones
- [Memory Providers](/user-guide/features/memory-providers) — full provider matrix and consent model
- [Local Ollama Setup](/guides/local-ollama-setup) — including remote-host configuration
