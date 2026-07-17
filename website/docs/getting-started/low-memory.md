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

Fabric can run on a 1 GB device in a carefully constrained, headless profile.
The core agent is a Python process that talks to a model over the network; it
is not the model itself. In one import-only Linux benchmark (Python 3.13,
Fabric 0.21.0), the base environment used about **104 MB of disk** and peaked
at roughly **70 MiB RSS**. Those figures are orientation, not an arm64 capacity
guarantee: live usage varies with conversation history, providers, and tool
subprocesses. What does *not* fit in 1 GB is local model inference and the
heavier optional surfaces, so a low-memory deployment is about choosing a
lean profile and measuring it on your board.

## What fits where

| Device class | Verdict |
| --- | --- |
| 512 MB (Pi Zero 2 W) | Not recommended. Installs and upgrades alone can exhaust memory. |
| 1 GB (Pi 3, early Pi 4) | Best-effort only: headless CLI sessions and one messaging gateway, cloud or remote inference, file-based or SQLite memory. Measure your real workload. |
| 2–4 GB (Pi 4/5) | More headroom for the TUI or dashboard and additional gateway channels. Local LLM inference is still impractical. |
| 8 GB (Pi 5) | Small quantized local models via Ollama become *possible*, but slow; remote inference remains the better experience. |

Use a **64-bit OS** (Raspberry Pi OS 64-bit, Ubuntu Server arm64). These guides
and Fabric's Linux SBC compatibility target cover arm64 only; 32-bit armv7 is
untested and unsupported. Fabric also requires Python 3.11–3.13.

## The lean ("lite") install profile

For full step-by-step walkthroughs, see
[Install on Raspberry Pi](./raspberry-pi.md) and
[Install on Jetson Nano](./jetson-nano.md); this section explains the profile
itself.

Skip the `.[all]` extra. Install the base package plus only the extras you
will actually use — the same philosophy as the tested
[Termux profile](./termux.md), which targets similarly constrained phones:

```bash
sudo apt update
sudo apt install -y git curl python3 python3-venv ripgrep build-essential python3-dev libffi-dev
git clone https://github.com/ObliviousOdin/fabric.git
cd fabric
python3 --version                    # must be 3.11-3.13
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -e '.[cli]'          # base + interactive CLI
# add extras individually as needed, e.g.:
# pip install -e '.[cli,mcp]'    # + MCP support
fabric setup
```

If `python3` is outside 3.11–3.13, use the standalone managed-`uv` bootstrap
in the [Jetson guide](./jetson-nano.md#lean-install-all-boards) instead. Those
commands work on Linux arm64 generally and avoid installing the full `[all]`
profile merely to obtain Python. In a later login shell, return to the clone
and run `source venv/bin/activate` before using `fabric`.

Notes for a 1 GB device:

- **Add swap or zram before installing.** Dependency resolution and any
  wheel-less source build can spike past the install-time baseline. 1 GB of
  zram (or a swapfile on non-SD storage) makes installs more reliable. Light
  headless operation should not depend on swap continuously; verify with
  `free -m` during a representative session.
- **Prefer the plain CLI over the TUI.** `fabric --tui` launches a Node ≥ 20
  subprocess for the Ink terminal UI; plain `fabric` keeps everything in one
  Python process.
- **Run the gateway headless.** `fabric gateway install` installs and starts a
  systemd service (normally in user scope). Skip `fabric dashboard` when memory
  is tight — it is another long-running process.
- Many optional backends (Telegram, Slack, Honcho, and others) lazy-install
  their own dependencies on first use. Configure only the gateway platform you
  need instead of eagerly installing the broad `messaging` extra.

## What to leave out at 1 GB

| Surface | Why |
| --- | --- |
| Local LLM inference (on-device Ollama) | Even small quantized 1–3 B models want 2 GB+ and Pi-class CPUs make them painfully slow. Use a cloud provider, or run Ollama on another machine (see below). |
| Desktop app | Electron. Build and runtime footprints are desktop-class by design. |
| Local browser tools | A local CDP browser or Chromium sidecar can consume hundreds of MB. Cloud browser providers remain viable for public URLs; if no local sidecar is acceptable, set `browser.auto_local_for_private_urls: false` and do not expect browser access to LAN/private URLs. |
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
   The Pi stays lightly loaded; the LAN box does the inference. See
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
free -m            # observe headroom during a representative live session
```

If installs fail with out-of-memory kills (`pip` or a compiler being killed),
add swap/zram and retry. If `uname -m` reports `armv7l`, reinstall with a
64-bit image before troubleshooting individual dependencies.

## See also

- [Install on Raspberry Pi](./raspberry-pi.md) — step-by-step Pi walkthrough
- [Install on Jetson Nano](./jetson-nano.md) — step-by-step Jetson walkthrough
- [Platform Support](./platform-support.md) — support tiers for Linux arm64
- [Android / Termux](./termux.md) — the same lean-profile approach on phones
- [Memory Providers](/user-guide/features/memory-providers) — full provider matrix and consent model
- [Local Ollama Setup](/guides/local-ollama-setup) — including remote-host configuration
