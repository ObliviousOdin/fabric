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
3. **Project** — `./.fabric/plugins/<name>/` (requires `FABRIC_ENABLE_PROJECT_PLUGINS=1`)
4. **Pip entry points** — `hermes_agent.plugins`

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
| `fabric-achievements` | dashboard integration | Bundled dashboard discovery | Steam-style collectible badges generated from your real Fabric session history, plus an opt-in team leaderboard |
| `kanban` | dashboard integration | Bundled dashboard discovery | Persistent Work surface at `/workspace/work` with Board, Graph, and Outline views. See [Kanban Multi-Agent](./kanban.md). |
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
HERMES_LANGFUSE_PUBLIC_KEY=pk-lf-...
HERMES_LANGFUSE_SECRET_KEY=sk-lf-...
HERMES_LANGFUSE_BASE_URL=https://cloud.langfuse.com   # or your self-hosted URL
```

**How it works:**

| Hook | Behaviour |
|---|---|
| `pre_api_request` / `pre_llm_call` | Open (or reuse) a per-turn root span "Fabric turn". Start a `generation` child observation for this API call with serialized recent messages as input. |
| `post_api_request` / `post_llm_call` | Close the generation, attach `usage_details`, `cost_details`, `finish_reason`, assistant output + tool calls. If no tool calls and non-empty content, close the turn. |
| `pre_tool_call` | Start a `tool` child observation with sanitized `args`. |
| `post_tool_call` | Close the tool observation with sanitized `result`. `read_file` payloads get summarized (head + tail + omitted-line count) so a huge file read stays under `HERMES_LANGFUSE_MAX_CHARS`. |

Session grouping keys off the Fabric session ID (or task ID for sub-agents) via `langfuse.propagate_attributes`, so everything in a single `fabric chat` session lives under one Langfuse session.

**Verify:**

```bash
fabric plugins list                 # observability/langfuse should show "enabled"
fabric chat -q "hello"              # check the Langfuse UI for a "Fabric turn" trace
```

**Optional tuning** (in `.env`):

| Variable | Default | Purpose |
|---|---|---|
| `HERMES_LANGFUSE_ENV` | — | Environment tag on traces (`production`, `staging`, …) |
| `HERMES_LANGFUSE_RELEASE` | — | Release/version tag |
| `HERMES_LANGFUSE_SAMPLE_RATE` | `1.0` | Sampling rate passed to the SDK (0.0–1.0) |
| `HERMES_LANGFUSE_MAX_CHARS` | `12000` | Per-field truncation for message content / tool args / tool results |
| `HERMES_LANGFUSE_DEBUG` | `false` | Verbose plugin logging to `agent.log` |

Fabric-prefixed and standard SDK env vars (`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL`) are both accepted — Fabric-prefixed wins when both are set.

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

### fabric-achievements

Adds a **Steam-style achievements tab to the dashboard** — 60+ collectible, tiered badges generated from your real Fabric session history. Tool-chain feats, debugging patterns, vibe-coding streaks, skill/memory usage, model/provider variety, lifestyle quirks (weekend and night sessions). Originally authored by [@PCinkusz](https://github.com/PCinkusz) as an external plugin; brought in-tree so it stays in lockstep with Fabric feature changes.

**How it works:**

- Scans your entire `~/.fabric/state.db` session history on the dashboard backend
- Per-session stats are cached by `(started_at, last_active)` fingerprint, so only new or changed sessions re-analyze on subsequent scans
- First-ever scan runs in a background thread — the dashboard never blocks waiting for it, even on databases with thousands of sessions
- Unlock state is persisted to `$FABRIC_HOME/plugins/fabric-achievements/state.json`

**Tier progression:** Copper → Silver → Gold → Diamond → Olympian. Each card exposes a "What counts" section listing the exact metric being tracked.

**Achievement states:**

| State | Meaning |
|---|---|
| Unlocked | At least one tier achieved |
| Discovered | Known achievement, progress visible, not yet earned |
| Secret | Hidden until Fabric detects the first related signal in your history |

**API** — routes mount under `/api/plugins/fabric-achievements/`:

| Endpoint | Purpose |
|---|---|
| `GET /achievements` | Full catalog with per-badge unlock state (returns a pending placeholder while the first cold scan is running) |
| `GET /scan-status` | State of the background scanner: `idle` / `running` / `failed`, last duration, run count |
| `GET /recent-unlocks` | Twenty most recently unlocked badges, newest first |
| `GET /sessions/{id}/badges` | Badges earned primarily in one specific session |
| `POST /rescan` | Manual synchronous rescan (blocks; use when the user clicks the rescan button) |
| `POST /reset-state` | Clear unlock history and cached snapshot |
| `GET /team`, `GET /team/leaderboard` | Team leaderboard state / ranked roster (opt-in; see below) |
| `POST /team/create`, `/team/join`, `/team/leave`, `/team/settings`, `/team/publish`, `/team/rotate`, `/team/kick` | Team lifecycle, sharing toggle, and owner controls |

**Team leaderboard (opt-in cross-user sharing):** A second **Team Leaderboard** tab lets several Fabric users compare achievements. It keeps the local-first promise — the achievement scanner still never sends session history anywhere. When you opt into a team, the *only* data that leaves your machine is an **aggregate profile**: a tier-weighted score, unlock/tier/category counts, up to five unlocked-badge names from the static catalogue, and a display name you choose. Session titles, transcripts, file paths, and raw metrics are never sent — enforced by `build_leaderboard_profile`, re-validated by the relay's `sanitize_profile`, and pinned by a golden test (`tests/plugins/test_leaderboard_privacy.py`).

Members connect through a small **relay** — a stdlib-only, self-hostable service (`python -m relay` from `plugins/fabric-achievements/`; see its [README](https://github.com/ObliviousOdin/fabric/tree/main/plugins/fabric-achievements/relay)). Creating a team returns a shareable invite code (`fbl1_…`) that others paste to join. The browser never contacts the relay directly — each dashboard proxies server-to-server through the routes above, so the loopback/OAuth auth model is untouched. Sharing is a toggle; the team owner can reset the invite (rotate) or remove members. Scores are self-reported, so it's a friendly board for teams that trust each other, not an adversarial ranking. The `/team/*` routes stay behind the dashboard auth gate (they carry secrets and write state) and are deliberately **not** in the public-paths allowlist.

**State files** — live under `$FABRIC_HOME/plugins/fabric-achievements/`:

| File | Contents |
|---|---|
| `state.json` | Unlock history: which badges you've earned and when. Stable across Fabric updates. |
| `scan_snapshot.json` | Last completed scan payload (served immediately on dashboard load) |
| `scan_checkpoint.json` | Per-session stats cache keyed by fingerprint (makes warm rescans fast) |
| `team.json` | Team leaderboard membership (relay URL, team/member ids, per-member token, sharing toggle). Only present if you join a team. |

**Performance notes:**

- Cold scan on ~8,000 sessions takes a few minutes. It runs in a background thread on first dashboard request; the UI sees a pending placeholder and polls `/scan-status`.
- **Incremental results during a cold scan** — the scanner publishes a partial snapshot every ~250 sessions so each dashboard refresh shows more badges unlocked as the scan progresses. No minute-long stare at zeros.
- Warm rescan reuses per-session stats for every session whose `started_at` + `last_active` fingerprint matches the checkpoint — completes in seconds even on large histories.
- The in-memory snapshot TTL is 120s; stale requests serve the old snapshot immediately and kick a background refresh. You never wait on a spinner just because TTL expired.

**Enabling:** Nothing to enable — `fabric-achievements` is a bundled
dashboard-only plugin (no lifecycle hooks and no model-visible tools). Its
`dashboard/manifest.json` makes the tab available when the dashboard starts,
unless the plugin is explicitly denied.

**Opting out:** Add `fabric-achievements` to `plugins.disabled` in
`config.yaml`. Its state files under
`$FABRIC_HOME/plugins/fabric-achievements/` survive, so re-enabling preserves
your unlock history. Do not edit the bundled manifest; an update would restore
the shipped file.

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
