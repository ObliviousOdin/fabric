# Fabric

Fabric is a local-first AI agent runtime for terminal, desktop, web, and messaging workflows. It combines model choice, durable memory, reusable skills, scheduled work, browser and terminal tools, and multi-agent delegation behind one `fabric` command.

[Documentation](website/docs/index.mdx) · [Desktop app](apps/desktop/README.md) · [Security](SECURITY.md) · [Contributing](CONTRIBUTING.md)

## Highlights

- Run cloud providers, subscription-backed providers, or local Ollama models.
- Keep persistent memory across sessions with explicit privacy and write controls.
- Install and compose skills, with authored Compound Engineering and Product Design capability packs included for continued integration work.
- Turn product intent into structured design briefs from the desktop or dashboard, then continue through the existing agent conversation.
- Watch [Browser](website/docs/user-guide/features/browser.md#desktop-live-view) and [Computer Use](website/docs/user-guide/features/computer-use.md#desktop-live-view) activity beside Desktop chat, or pop the same live session into an always-on-top view without adding model context or calls.
- Use the same agent core from the CLI, Ink TUI, desktop app, dashboard, cron, and messaging gateways.
- Delegate work to subagents and connect terminal, browser, MCP, media, and remote execution tools.
- Store state locally by default under `~/.fabric` (`%LOCALAPPDATA%\fabric` on Windows).

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

## Common Commands

```bash
fabric                    # Start an interactive session
fabric --tui              # Start the terminal UI
fabric setup              # Configure providers and services
fabric model              # Select a model or provider
fabric tools              # Configure tools and integrations
fabric status             # Inspect the active configuration
fabric doctor             # Diagnose installation problems
fabric gateway setup      # Configure messaging channels
fabric gateway start      # Run messaging and scheduled jobs
fabric dashboard          # Open the local dashboard
```

## Local Models with Ollama

Install and start [Ollama](https://ollama.com), then:

```bash
fabric ollama pull qwen3:8b
fabric model
```

Choose Ollama from the model picker. Fabric also supports local-only egress policies for workflows that must remain on the machine.

## Provider Subscriptions

Run `fabric model` to connect supported subscription or OAuth providers, including OpenAI Codex and xAI. API-key providers and custom OpenAI-compatible endpoints are available from the same flow.

## Development

```bash
git clone https://github.com/ObliviousOdin/fabric.git
cd fabric
uv venv
uv pip install -e '.[dev,all]'
scripts/run_tests.sh
```

The Python runtime, desktop app, web dashboard, TUI, skills, plugins, and documentation live in this repository. See [AGENTS.md](AGENTS.md) for architecture and contribution guidance.

## License and Attribution

Fabric is distributed under the [Apache License 2.0](LICENSE). Upstream and third-party attribution is summarized in [NOTICE](NOTICE) and component-level license files, including the preserved MIT notice from the upstream Fabric Agent software in [LICENSES/MIT-hermes-agent.txt](LICENSES/MIT-hermes-agent.txt).
