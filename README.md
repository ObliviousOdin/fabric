<p align="center">
  <img src="assets/fabric-banner.svg" alt="Fabric — the wordmark on a dark woven canvas, with a single animated thread weaving through the letters" width="760">
</p>

<p align="center">
  <a href="website/docs/index.mdx">Documentation</a> ·
  <a href="apps/desktop/README.md">Desktop app</a> ·
  <a href="SECURITY.md">Security</a> ·
  <a href="CONTRIBUTING.md">Contributing</a> ·
  <a href="LICENSING.md">Licensing</a>
</p>

# Fabric

Fabric is a continuously evolving, community-driven agent brain. It is plug
and play: connect the models you prefer, the tools you already use, and the
channels you already live in, and one local-first runtime carries your work
across all of them behind a single `fabric` command.

The brain combines model choice, durable memory, reusable skills, scheduled
work, browser and terminal tools, live host awareness, and multi-agent
delegation — and it keeps learning new skills from its community between your
sessions.

## For the operators who move the physical world

Fabric is built for the people whose work does not live in a browser tab: the
ones who run farms and fleets, workshops and warehouses, clinics, kitchens,
and construction sites. The ones who fix the pump before sunrise and file the
paperwork after dark.

Most software was made for people who sit still. Operators keep moving — so
their agent has to hold the thread for them: remember the state of the work,
watch the schedule, answer on whatever channel is in reach, and pick up
exactly where things left off. Fabric runs close to the work, on your own
hardware, with state on your own disk, on machines as small as a Raspberry
Pi — because the field, the floor, and the road rarely have a data center
nearby.

If your work moves atoms, Fabric exists so your software finally keeps up.

## Plug and play

- **Plug in a model** — cloud providers, subscription and OAuth providers, or
  local Ollama models, all from one picker. Local-only egress policies keep
  sensitive workflows on the machine.
- **Plug in skills** — install community skills and curated packs with
  `fabric skills search`; a unified index across the skills ecosystem is
  rebuilt twice a day, so the brain's capabilities grow without a release.
- **Plug in tools** — terminal, browser, computer use, MCP servers, media,
  and remote execution connect through one configuration flow.
- **Plug in channels** — the gateway runs messaging channels and scheduled
  cron jobs, so the same brain answers wherever you are.
- **Plug in surfaces** — the same agent core drives the CLI, Ink TUI, desktop
  app, web dashboard, mobile clients, and messaging gateways.

## Highlights

- Persistent memory across sessions with explicit privacy and write controls.
- Durable work: goals, plans, and agent runs live on a kanban work board with
  board, graph, timeline, and outline views of the same work model.
- Multi-agent delegation and orchestration skills — ensembles, fan-out,
  pipelines, and adversarial verification built on the real delegation
  machinery.
- Watch [Browser](website/docs/user-guide/features/browser.md#desktop-live-view)
  and [Computer Use](website/docs/user-guide/features/computer-use.md#desktop-live-view)
  activity beside Desktop chat, or pop the live session into an always-on-top
  view without adding model context or calls.
- Live host awareness: `fabric monitor` renders CPU, memory, disk, network,
  and GPU in the terminal, mirrored by the dashboard and desktop system
  panels; `fabric disk` shows and reclaims Fabric's storage safely.
- Authored Compound Engineering and Product Design capability packs, plus
  venture-studio and orchestration skill categories, ship in the box.
- Turn product intent into structured design briefs from the desktop or
  dashboard, then continue in the same agent conversation.
- State stays local by default under `~/.fabric`
  (`%LOCALAPPDATA%\fabric` on Windows).

## Install

Deploying on a single-board computer? See the step-by-step
[Raspberry Pi](website/docs/getting-started/raspberry-pi.md) and
[Jetson Nano](website/docs/getting-started/jetson-nano.md) install guides,
and the [low-memory guide](website/docs/getting-started/low-memory.md) for
the lean 1 GB profile and embedding-free memory options.

Linux, macOS, WSL, and Termux:

```bash
curl -fsSL https://raw.githubusercontent.com/ObliviousOdin/fabric/main/scripts/install.sh | bash
fabric setup
fabric
```

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/ObliviousOdin/fabric/main/scripts/install.ps1 | iex
fabric setup
fabric
```

Or install from source:

```bash
git clone https://github.com/ObliviousOdin/fabric.git
cd fabric
uv venv
uv pip install -e '.[all]'
fabric setup
fabric
```

## Common commands

```bash
fabric                    # Start an interactive session
fabric --tui              # Start the terminal UI
fabric setup              # Configure providers and services
fabric model              # Select a model or provider
fabric tools              # Configure tools and integrations
fabric skills search      # Find and install community skills
fabric kanban             # Open the durable work board
fabric monitor            # Live host infrastructure monitor
fabric disk usage         # See what Fabric's stores are using
fabric status             # Inspect the active configuration
fabric doctor             # Diagnose installation problems
fabric gateway setup      # Configure messaging channels
fabric gateway start      # Run messaging and scheduled jobs
fabric dashboard          # Open the local dashboard
```

## Local models with Ollama

Install and start [Ollama](https://ollama.com), then:

```bash
fabric ollama pull qwen3:8b
fabric model
```

Choose Ollama from the model picker. Fabric also supports local-only egress
policies for workflows that must remain on the machine.

## Provider subscriptions

Run `fabric model` to connect supported subscription or OAuth providers,
including OpenAI Codex and xAI. API-key providers and custom
OpenAI-compatible endpoints are available from the same flow.

## Continuously evolving, community driven

Fabric's brain is not frozen at release. The skills index is rebuilt twice a
day from a curated, trust-tiered ecosystem directory of external skill
sources, and installs pass a guard scan and quarantine before anything runs.
Community skill packs, capability packs, and new orchestration patterns land
continuously — update, and the brain you already configured knows more.

Contributions are welcome: start with [CONTRIBUTING.md](CONTRIBUTING.md) for
setup and project structure, and [AGENTS.md](AGENTS.md) for architecture and
the contribution rubric.

## Development

```bash
git clone https://github.com/ObliviousOdin/fabric.git
cd fabric
uv venv
uv pip install -e '.[dev,all]'
scripts/run_tests.sh
```

The Python runtime, desktop app, web dashboard, TUI, skills, plugins, and
documentation live in this repository. Licensing and attribution details live
in [LICENSING.md](LICENSING.md).
