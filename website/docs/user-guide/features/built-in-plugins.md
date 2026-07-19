---
sidebar_position: 12
sidebar_label: "Built-in Plugins"
title: "Built-in Plugins"
description: "Runtime extensions, providers, and dashboard integrations shipped with Fabric"
---

# Built-in Plugins

Fabric ships several extensions under `<repo>/plugins/`. Some register runtime
hooks or tools, some provide a selectable backend, and some only add dashboard
pages or slots. Those surfaces have different activation rules; being bundled
does not mean arbitrary lifecycle code runs automatically.

See the [Plugins](/user-guide/features/plugins) page for the general plugin system, and [Build a Fabric Plugin](/developer-guide/plugins) to write your own.

## How discovery works

The `PluginManager` scans four sources, in order:

1. **Bundled** — `<repo>/plugins/<name>/` (what this page documents)
2. **User** — `~/.fabric/plugins/<name>/`
3. **Project** — `./.fabric/plugins/<name>/` (requires `plugins.allow_project_plugins: true` in `config.yaml`)
4. **Pip entry points** — `fabric_agent.plugins`

On name collision, later sources win — a user plugin named `disk-cleanup` would replace the bundled one.

`plugins/memory/` and `plugins/context_engine/` are deliberately excluded from bundled scanning. Those directories use their own discovery paths because memory providers and context engines are single-select providers configured through `fabric memory setup` / `context.engine` in config.

Dashboard discovery separately scans `dashboard/manifest.json` beneath bundled
and user plugin directories. A dashboard manifest can provide a page, override
a built-in route, register a shell slot, or mount a plugin API without adding
anything to the model's tool schema.

## Activation depends on the surface

### Lifecycle and tool plugins are opt-in

General plugins that register hooks, slash commands, or tools do not execute
until you explicitly enable them:

```bash
fabric plugins enable disk-cleanup
```

Or via `~/.fabric/config.yaml`:

```yaml
plugins:
  enabled:
    - disk-cleanup
```

This is the same allow-list used for user-installed runtime plugins. An entry
in `plugins.disabled` always wins.

To turn a bundled plugin off again:

```bash
fabric plugins disable disk-cleanup
# or manage plugins.enabled / plugins.disabled in config.yaml
```

### Providers are selected, not multi-enabled

Memory providers, context engines, model providers, and image/video backends
use their category's selection contract. Discovery makes candidates available;
configuration such as `memory.provider`, `context.engine`, or
`image_gen.provider` chooses the active implementation.

### Dashboard integrations have an independent delivery path

Bundled dashboard manifests are trusted release assets and are available by
default unless their name is in `plugins.disabled`. User-installed dashboard
plugins must be in `plugins.enabled` before Fabric serves their JavaScript/CSS
or imports their Python API. This is intentionally separate from model-tool
activation: the bundled Work page can render without adding `kanban_*` to a
normal conversation.

Dashboard-only integrations that have no `plugin.yaml` do not appear as normal
runtime plugins in every CLI flow. Disable one directly in `config.yaml`:

```yaml
plugins:
  disabled:
    - kanban
```

Restart the dashboard after changing the list. Remove the name from
`plugins.disabled` to restore it. Do not use
`dashboard.plugins.<name>.enabled`; that is not a supported activation key.

`dashboard.hidden_plugins` controls dashboard presentation without changing
agent runtime activation. Separately, a manifest can declare `tab.hidden: true`
to provide a direct-route integration without adding primary navigation.

## Currently shipped

The repo ships these bundled extensions under `plugins/`. The **Activation**
column names the governing contract.

| Plugin | Kind | Activation | Purpose |
|---|---|---|---|
| `disk-cleanup` | hooks + slash command | `plugins.enabled` | Auto-track ephemeral files and clean them on session end |
| `security-guidance` | hooks | `plugins.enabled` | Pattern-match dangerous code on `write_file`/`patch` and append a security warning (or block) — 25 rules (Apache-2.0 fork of Anthropic's `claude-plugins-official` patterns) |
| `observability/langfuse` | hooks | `plugins.enabled` | Trace turns / LLM calls / tools to [Langfuse](https://langfuse.com) |
| `observability/nemo_relay` | hooks | `plugins.enabled` | Relay observability events (turns / LLM calls / tools) to an NVIDIA NeMo endpoint |
| `teams_pipeline` | standalone | `plugins.enabled` | Microsoft Teams meeting pipeline — Graph-backed, transcript-first meeting summaries |
| `spotify` | backend (7 tools) | `plugins.enabled` | Native Spotify playback, queue, search, playlists, albums, library |
| `google_meet` | standalone | `plugins.enabled` | Join Meet calls, live-caption transcription, optional realtime duplex audio |
| `image_gen/openai` | image backend | `image_gen.provider` | OpenAI `gpt-image-2` image generation backend (alternative to FAL) |
| `image_gen/openai-codex` | image backend | `image_gen.provider` | OpenAI image generation via Codex OAuth |
| `image_gen/xai` | image backend | `image_gen.provider` | xAI `grok-2-image` backend |
| `kanban` | dashboard integration | Bundled dashboard discovery | Persistent Work surface at `/workspace/work` with Board, Graph, and Outline views. See [Kanban Multi-Agent](./kanban.md). |
| `achievements` | dashboard integration + content-free capability hook | Bundled and default-on; explicit disable wins | Private Fabric Journey with guided capability Paths, local mastery, preserved Legacy milestones, and separately labeled self-reported Friendly cards at `/workspace/achievements`. See [Fabric Journey and Achievements](./achievements.md). |
| `team-pages` | hidden dashboard integration | Direct route only | Optional config-driven reference pages at `/admin/integrations/team-pages`; distinct from Agents and Work. |

Memory providers (`plugins/memory/*`) and context engines (`plugins/context_engine/*`) are listed separately on [Memory Providers](./memory-providers.md) — they're managed through `fabric memory` and `fabric plugins` respectively. The full per-plugin detail for the two long-running hooks-based plugins follows.

### disk-cleanup

Auto-tracks and removes ephemeral files created during sessions — test scripts, temp outputs, cron logs, stale chrome profiles — without requiring the agent to remember to call a tool.

**How it works:**

| Hook | Behaviour |
|---|---|
| `post_tool_call` | When `write_file` / `terminal` / `patch` creates a file matching `test_*`, `tmp_*`, or `*.test.*` inside `FABRIC_HOME` or `/tmp/fabric-*`, track it silently as `test` / `temp` / `cron-output`. |
| `on_session_end` | If any test files were auto-tracked during the turn, run the safe `quick` cleanup and log a one-line summary. Stays silent otherwise. |

**Deletion rules:**

| Category | Threshold | Confirmation |
|---|---|---|
| `test` | every session end | Never |
| `temp` | >7 days since tracked | Never |
| `cron-output` | >14 days since tracked | Never |
| empty dirs under FABRIC_HOME | always | Never |
| `research` | >30 days, beyond 10 newest | Always (deep only) |
| `chrome-profile` | >14 days since tracked | Always (deep only) |
| files >500 MB | never auto | Always (deep only) |

**Slash command** — `/disk-cleanup` available in both CLI and gateway sessions:

```
/disk-cleanup status                     # breakdown + top-10 largest
/disk-cleanup dry-run                    # preview without deleting
/disk-cleanup quick                      # run safe cleanup now
/disk-cleanup deep                       # quick + list items needing confirmation
/disk-cleanup track <path> <category>    # manual tracking
/disk-cleanup forget <path>              # stop tracking (does not delete)
```

**State** — everything lives at `$FABRIC_HOME/disk-cleanup/`:

| File | Contents |
|---|---|
| `tracked.json` | Tracked paths with category, size, and timestamp |
| `tracked.json.bak` | Atomic-write backup of the above |
| `cleanup.log` | Append-only audit trail of every track / skip / reject / delete |

**Safety** — cleanup only ever touches paths under `FABRIC_HOME` or `/tmp/fabric-*`. Windows mounts (`/mnt/c/...`) are rejected. Well-known top-level state dirs (`logs/`, `memories/`, `sessions/`, `cron/`, `cache/`, `skills/`, `plugins/`, `disk-cleanup/` itself) are never removed even when empty — a fresh install does not get gutted on first session end.

**Enabling:** `fabric plugins enable disk-cleanup` (or check the box in `fabric plugins`).

**Disabling again:** `fabric plugins disable disk-cleanup`.

### security-guidance

Fast pattern-matched security warnings on file writes. When the agent's `write_file` / `patch` / `skill_manage` calls carry content matching a known-dangerous code pattern — `pickle.load`, `yaml.load` without `SafeLoader`, `eval(`, `os.system`, `subprocess(...,  shell=True)`, JS `child_process.exec`, React `dangerouslySetInnerHTML`, raw `.innerHTML =` / `.outerHTML =` / `document.write`, Node `crypto.createCipher`, AES ECB mode, TLS verification disabled, XXE-prone `xml.etree` / `minidom` parsers, `<script src="//..." >` without SRI, `torch.load` without `weights_only=True`, GitHub Actions `${{ github.event.* }}` injection — the plugin appends a `⚠️ Security guidance` block to the tool's result.

The file is still written. The model reads the warning in the next turn's tool message and can either fix the code or document why the construct is safe in this context. Pattern matching has a non-trivial false-positive rate, which is why warn (not block) is the default.

**Coverage:** 25 rules total, covering unsafe deserialization, command injection, XSS sinks, crypto footguns, XXE, supply-chain (SRI), and CI/CD workflow injection. The pattern data is a verbatim Apache-2.0 fork of [Anthropic's `claude-plugins-official`](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/security-guidance/hooks) — see the plugin's `LICENSE` and `NOTICE` files for attribution.

**Modes:**

| Env var | Effect |
|---|---|
| (unset) | **warn mode** (default) — file is written, warning appended to result |
| `SECURITY_GUIDANCE_BLOCK=1` | **block mode** — write refused, warning returned as the block reason |
| `SECURITY_GUIDANCE_DISABLE=1` | kill switch — plugin loads but does nothing |

**Enabling:** `fabric plugins enable security-guidance` (or check the box in `fabric plugins`).

**Disabling again:** `fabric plugins disable security-guidance`.

**What it does not do (yet):** the upstream Anthropic plugin has two more layers — an LLM diff review on each agent turn that touched files, and an agentic commit-time review that traces data flow across files. Neither is ported. The agent can already run those reviews on demand via `delegate_task`.

### observability/langfuse

Traces Fabric turns, LLM calls, and tool invocations to [Langfuse](https://langfuse.com) — an open-source LLM observability platform. One span per turn, one generation per API call, one tool observation per tool call. Usage totals, per-type token counts, and cost estimates come out of Fabric's canonical `agent.usage_pricing` numbers, so the Langfuse dashboard sees the same breakdown (input / output / `cache_read_input_tokens` / `cache_creation_input_tokens` / `reasoning_tokens`) that appears in `fabric logs`.

The plugin is fail-open: no SDK installed, no credentials, or a transient Langfuse error — all turn into a silent no-op in the hook. The agent loop is never impacted.

**Setup (interactive — recommended):**

```bash
fabric tools          # → Langfuse Observability → Cloud or Self-Hosted
```

The wizard collects your keys, `pip install`s the `langfuse` SDK, and adds `observability/langfuse` to `plugins.enabled` for you. Restart Fabric and the next turn ships a trace.

**Setup (manual):**

```bash
pip install langfuse
fabric plugins enable observability/langfuse
```

Then put the credentials in `~/.fabric/.env`:

```bash
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
```

For a self-hosted server, set `observability.langfuse.base_url` in
`config.yaml`.

**How it works:**

| Hook | Behaviour |
|---|---|
| `pre_api_request` | Open (or reuse) a per-turn root span "Fabric turn". Start a `generation` child observation for this API call with serialized recent messages as input. |
| `post_api_request` | Close the generation, attach `usage_details`, `cost_details`, `finish_reason`, assistant output + tool calls. If no tool calls and non-empty content, close the turn. |
| `pre_tool_call` | Start a `tool` child observation with sanitized `args`. |
| `post_tool_call` | Close the tool observation with sanitized `result`. `read_file` payloads get summarized (head + tail + omitted-line count) so a huge file read stays under `observability.langfuse.max_chars`. |

Session grouping keys off the Fabric session ID (or task ID for sub-agents) via `langfuse.propagate_attributes`, so everything in a single `fabric chat` session lives under one Langfuse session.

**Verify:**

```bash
fabric plugins list                 # observability/langfuse should show "enabled"
fabric chat -q "hello"              # check the Langfuse UI for a "Fabric turn" trace
```

**Optional tuning** (in `config.yaml`):

```yaml
observability:
  langfuse:
    base_url: https://cloud.langfuse.com
    environment: production
    release: v1.0.0
    sample_rate: 0.5
    max_chars: 12000
    debug: false
```

**Performance:** the Langfuse client is cached after the first hook call. If credentials or SDK are missing, that decision is also cached — subsequent hooks fast-return without re-checking env vars or reloading config.

**Disabling:** `fabric plugins disable observability/langfuse`. The plugin module is still discovered, but no module code runs until you re-enable.

### google_meet

Lets the agent **join, transcribe, and participate in Google Meet calls** — take notes on a meeting, summarize the back-and-forth after, follow up on specific points, and (optionally) speak replies back into the call via TTS.

**What it adds:**

- A headless virtual participant that joins a Meet URL using browser automation
- Live transcription of the meeting audio via the configured STT provider
- A `meet_summarize` / `meet_speak` / `meet_followup` toolset the agent invokes to act on what it heard
- Post-meeting artifacts (transcript, speaker-attributed notes, action items) saved under `~/.fabric/cache/google_meet/<meeting_id>/`

**Setup:**

```bash
fabric plugins enable google_meet
# Prompts you to sign in via the plugin's OAuth flow on first use —
# needs a Google account with Meet access. Host approval may be required
# if the meeting enforces "only invited participants can join".
```

Usage from chat:

> "Join meet.google.com/abc-defg-hij and take notes. After the call, send me a summary with action items."

The agent kicks off the meeting join, streams the transcription back into its context as the call proceeds, and produces a structured summary when the meeting ends (or when you tell it to stop).

**When to use it:** recurring standups where you want a bot to transcribe + summarize for async attendees; deposition-style interviews where you want structured notes; any case where you'd otherwise need Fireflies / Otter / Grain. When you'd rather not have an AI listening in — don't enable it.

**Disabling:** `fabric plugins disable google_meet`. Any cached transcripts and recordings stay in `~/.fabric/cache/google_meet/` until you remove them.

### kanban (Work)

The bundled `kanban` dashboard integration overrides the reserved
`/workspace/work` route with the persistent Work experience. Board is the
operational column view, Graph shows goals/dependencies/agent runs/results, and
Outline renders the same graph as a keyboard-friendly hierarchy. `/work` and
`/kanban` are aliases.

It uses the same per-board SQLite data as `fabric kanban`, `/kanban`, and the
workflow-gated `kanban_*` tools. Loading the dashboard integration does not
enable those tools in ordinary conversations. To disable the Work frontend and
plugin API, add `kanban` to `plugins.disabled`; the CLI and core board data
remain available.

### team-pages

`team-pages` is a bundled dashboard-only integration for static internal
reference pages. Its manifest is intentionally hidden from primary navigation;
open `/admin/integrations/team-pages` directly. The built-in starter can be
replaced with `dashboard.team_pages.pages` entries in `config.yaml` using title,
text, Markdown, links, KPI, table, and status blocks.

Team Pages does not discover people, profiles, tasks, or live organization
state. `/team` is an alias for `/workspace/agents`, while persistent work lives
at `/workspace/work`. Keeping the reference integration separate prevents a
config-authored page from being mistaken for operational truth.

## Adding a bundled plugin

Bundled plugins are written exactly like any other Fabric plugin — see [Build a Fabric Plugin](/developer-guide/plugins). The only differences are:

- Directory lives at `<repo>/plugins/<name>/` instead of `~/.fabric/plugins/<name>/`
- Manifest source is reported as `bundled` in `fabric plugins list`
- User plugins with the same name override the bundled version

A plugin is a good candidate for bundling when:

- It has no optional dependencies (or they're already `pip install .[all]` deps)
- Its activation contract matches its surface: runtime hooks/tools stay
  opt-in; dashboard integrations that do not alter agent runtime may be bundled
  and opt-out
- Lifecycle logic is concrete and useful enough to justify an explicit opt-in
- It complements a core capability without expanding the model-visible tool surface

Counter-examples — things that should stay as user-installable plugins, not bundled: third-party integrations with API keys, niche workflows, large dependency trees, anything that would meaningfully change agent behaviour by default.
