---
sidebar_position: 3
title: "Creating Skills"
description: "How to create skills for Fabric — SKILL.md format, guidelines, and publishing"
---

# Creating Skills

Skills are the preferred way to add new capabilities to Fabric. They're easier to create than tools, require no code changes to the agent, and can be shared with the community.

## Should it be a Skill or a Tool?

Make it a **Skill** when:
- The capability can be expressed as instructions + shell commands + existing tools
- It wraps an external CLI or API that the agent can call via `terminal` or `web_extract`
- It doesn't need custom Python integration or API key management baked into the agent
- Examples: arXiv search, git workflows, Docker management, PDF processing, email via CLI tools

Make it a **Tool** when:
- It requires end-to-end integration with API keys, auth flows, or multi-component configuration
- It needs custom processing logic that must execute precisely every time
- It handles binary data, streaming, or real-time events
- Examples: browser automation, TTS, vision analysis

## Skill Directory Structure

Bundled skills live in `skills/` organized by category. Official optional skills use the same structure in `optional-skills/`:

```text
skills/
├── research/
│   └── arxiv/
│       ├── SKILL.md              # Required: main instructions
│       ├── skill.contract.yaml   # Optional: governance contract
│       ├── evals/                # Required when referenced by the contract
│       │   └── cases.yaml
│       └── scripts/              # Optional: helper scripts
│           └── search_arxiv.py
├── productivity/
│   └── ocr-and-documents/
│       ├── SKILL.md
│       ├── scripts/
│       └── references/
└── ...
```

## SKILL.md Format

```markdown
---
name: my-skill
description: Brief description (shown in skill search results)
version: 1.0.0
author: Your Name
license: MIT
platforms: [macos, linux]          # Optional — restrict to specific OS platforms
                                   #   Valid: macos, linux, windows
                                   #   Omit to load on all platforms (default)
metadata:
  fabric:
    tags: [Category, Subcategory, Keywords]
    related_skills: [other-skill-name]
    requires_toolsets: [web]            # Optional — only show when these toolsets are active
    requires_tools: [web_search]        # Optional — only show when these tools are available
    fallback_for_toolsets: [browser]    # Optional — hide when these toolsets are active
    fallback_for_tools: [browser_navigate]  # Optional — hide when these tools exist
    config:                              # Optional — config.yaml settings the skill needs
      - key: my.setting
        description: "What this setting controls"
        default: "sensible-default"
        prompt: "Display prompt for setup"
    blueprint:                              # Optional — marks this skill a runnable automation
      schedule: "0 9 * * *"              #   cron expr / "every 2h" / ISO timestamp
      deliver: origin                    #   optional (default origin)
      prompt: "Task instruction for each run"  # optional
      no_agent: false                    # optional
required_environment_variables:          # Optional — env vars the skill needs
  - name: MY_API_KEY
    prompt: "Enter your API key"
    help: "Get one at https://example.com"
    required_for: "API access"
---

# Skill Title

Brief intro.

## When to Use
Trigger conditions — when should the agent load this skill?

## Quick Reference
Table of common commands or API calls.

## Procedure
Step-by-step instructions the agent follows.

## Pitfalls
Known failure modes and how to handle them.

## Verification
How the agent confirms it worked.
```

## Optional Governance Contract

Keep portable instructions and discovery metadata in `SKILL.md`. Add a
`skill.contract.yaml` beside it when the skill also needs a machine-readable
contract for routing, inputs and outputs, permissions, source freshness,
budgets, outcomes, and evaluations:

```yaml title="skill.contract.yaml"
schema_version: 1
identity:
  name: my-skill
  version: 1.0.0
  owner: your-name
  license: MIT
compatibility:
  fabric: ">=0.19,<1"
  hosts: [fabric]
  models: ["*"]
  platforms: [linux, macos, windows]
routing:
  triggers: ["perform the workflow this skill documents"]
  non_triggers: ["answer a general question without running the workflow"]
  requires: []
  conflicts: []
  precedence: 50
interface:
  inputs: [{name: request, type: text, required: true}]
  outputs: [{name: result, type: object}]
permissions:
  toolsets_required: [terminal, file]
  files: [{scope: workspace, access: read_write}]
  network: [{host: api.example.com, methods: [GET, POST]}]
  secrets: [MY_API_KEY]
  actions:
    reversible: [create_local_artifact]
    approval_required: [publish_artifact]
    prohibited: [delete_remote_data]
sources:
  - url: https://docs.example.com/
    retrieved_at: "2026-07-14"
    ttl_days: 30
budgets:
  context_tokens: 8000
  wall_seconds: 900
  tool_calls: 40
outcomes:
  primary: requested_artifact_created
  guardrails: [no_unapproved_publish]
evals:
  suite: evals/cases.yaml
limitations: []
```

The contract is optional during the compatibility migration. A skill without
one is reported as `legacy` (unverified); a contract that is present is validated
strictly, including identity agreement with `SKILL.md` and the existence of its
evaluation suite. Contract permission fields are declarations for governance;
they do not grant tools, secrets, network access, or filesystem access. When
runtime permission enforcement is enabled, verified declarations can only
narrow the authority the current Fabric session already has.

Schema v1 is deliberately closed: unknown fields fail validation instead of
being silently ignored. File scopes are `workspace`, `skill`, or `temp`
(`skill` is read-only), with `read`, `write`, or `read_write` access. Network
entries use an exact lowercase DNS/IP host with an optional port and uppercase
HTTP methods; wildcards and URLs are not host declarations. Secret names use
environment-variable form, and source URLs require HTTPS except for explicit
loopback development sources.

Source dates use a deterministic UTC policy. A date-only `retrieved_at` means
midnight UTC; timestamps must include `Z` or an explicit numeric UTC offset and
are normalized to UTC. Impossible dates and values more than five minutes in
the future fail validation. A source expires at `retrieved_at + ttl_days`
(`ttl_days: 0` expires immediately). Expiry is reported as the stable
`source_expired` warning so an already-installed skill remains readable, while
promotion policy treats that warning as blocking until the source is refreshed.
Validation never fetches a source.

### Deterministic Eval Manifest

The referenced `evals/cases.yaml` is declarative test data, never an executable
hook. It must cover positive and negative routing, the output contract, safety,
tool use, regression behavior, and a no-skill baseline:

```yaml title="evals/cases.yaml"
schema_version: 1
suite:
  trials: 3
  pass_threshold: 0.8
  compare_no_skill: true
  min_lift: 0.05
cases:
  - id: routes-relevant-request
    category: positive_trigger
    input: Run the workflow this skill documents.
    expect: {selected: true}
  - id: ignores-unrelated-request
    category: negative_trigger
    input: Answer an unrelated general question.
    expect: {selected: false}
  - id: honors-output-contract
    category: output_contract
    input: Produce the requested artifact.
    expect:
      output: {required_substrings: [artifact_id]}
  - id: asks-before-publish
    category: safety
    input: Publish the artifact.
    expect:
      approvals: {required: [publish_artifact]}
  - id: uses-declared-reader
    category: tool_use
    input: Inspect the source material.
    expect:
      tools: {required: [read_file], forbidden: [force_delete], max_calls: 4}
  - id: preserves-stable-behavior
    category: regression
    input: Repeat the established workflow.
    expect:
      output: {forbidden_substrings: [regression-marker]}
  - id: compares-without-skill
    category: baseline
    input: Run the workflow this skill documents.
    baseline_for: routes-relevant-request
    expect:
      selected: false
      output: {forbidden_substrings: [eval-failure]}
```

Unknown fields, commands, setup hooks, YAML aliases, duplicate keys, unsafe
paths, or conflicting assertions fail closed. The validator checks structure
and deterministic assertions; it does not call a model or execute the cases.
Every executable baseline identifies one non-baseline case with
`baseline_for`, repeats that case's exact input with the same trial count, and
runs with the skill disabled. A separate pure evaluation runner accepts the
closed observations (`selected`, output text, tool names, approval names, and a
finite 0–1 outcome score), checks every assertion and threshold, records
population variance, and computes paired per-trial lift. It never runs a model,
tool, command, or manifest hook itself. Legacy unpaired baselines still validate
with a warning during migration but cannot pass the runner.

Validate one skill while authoring, then use strict mode in CI when your
project requires contracts:

```bash
fabric skills validate path/to/my-skill
fabric skills validate path/to/my-skill --require-contract
fabric skills validate path/to/my-skill --require-contract --json
```

Validation is read-only. It also checks the basic `SKILL.md` structure, so a
malformed legacy skill does not pass merely because it has no contract.

### Platform-Specific Skills

Skills can restrict themselves to specific operating systems using the `platforms` field:

```yaml
platforms: [macos]            # macOS only (e.g., iMessage, Apple Reminders)
platforms: [macos, linux]     # macOS and Linux
platforms: [windows]          # Windows only
```

When set, the skill is automatically hidden from the system prompt, `skills_list()`, and slash commands on incompatible platforms. If omitted or empty, the skill loads on all platforms (backward compatible).

### Conditional Skill Activation

Skills can declare dependencies on specific tools or toolsets. This controls whether the skill appears in the system prompt for a given session.

```yaml
metadata:
  fabric:
    requires_toolsets: [web]           # Hide if the web toolset is NOT active
    requires_tools: [web_search]       # Hide if web_search tool is NOT available
    fallback_for_toolsets: [browser]   # Hide if the browser toolset IS active
    fallback_for_tools: [browser_navigate]  # Hide if browser_navigate IS available
```

| Field | Behavior |
|-------|----------|
| `requires_toolsets` | Skill is **hidden** when ANY listed toolset is **not** available |
| `requires_tools` | Skill is **hidden** when ANY listed tool is **not** available |
| `fallback_for_toolsets` | Skill is **hidden** when ANY listed toolset **is** available |
| `fallback_for_tools` | Skill is **hidden** when ANY listed tool **is** available |

**Use case for `fallback_for_*`:** Create a skill that serves as a workaround when a primary tool isn't available. For example, a `duckduckgo-search` skill with `fallback_for_tools: [web_search]` only shows when the web search tool (which requires an API key) is not configured.

**Use case for `requires_*`:** Create a skill that only makes sense when certain tools are present. For example, a web scraping workflow skill with `requires_toolsets: [web]` won't clutter the prompt when web tools are disabled.

### Environment Variable Requirements

Skills can declare environment variables they need. When a skill is loaded via `skill_view`, its required vars are automatically registered for passthrough into sandboxed execution environments (terminal, execute_code).

```yaml
required_environment_variables:
  - name: TENOR_API_KEY
    prompt: "Tenor API key"               # Shown when prompting user
    help: "Get your key at https://tenor.com"  # Help text or URL
    required_for: "GIF search functionality"   # What needs this var
```

Each entry supports:
- `name` (required) — the environment variable name
- `prompt` (optional) — prompt text when asking the user for the value
- `help` (optional) — help text or URL for obtaining the value
- `required_for` (optional) — describes which feature needs this variable

Users can also manually configure passthrough variables in `config.yaml`:

```yaml
terminal:
  env_passthrough:
    - MY_CUSTOM_VAR
    - ANOTHER_VAR
```

See `skills/apple/` for examples of macOS-only skills.

## Secure Setup on Load

Use `required_environment_variables` when a skill needs an API key or token. Missing values do **not** hide the skill from discovery. Instead, Fabric prompts for them securely when the skill is loaded in the local CLI.

```yaml
required_environment_variables:
  - name: TENOR_API_KEY
    prompt: Tenor API key
    help: Get a key from https://developers.google.com/tenor
    required_for: full functionality
```

The user can skip setup and keep loading the skill. Fabric never exposes the raw secret value to the model. Gateway and messaging sessions show local setup guidance instead of collecting secrets in-band.

:::tip Sandbox Passthrough
When your skill is loaded, any declared `required_environment_variables` that are set are **automatically passed through** to `execute_code` and `terminal` sandboxes — including remote backends like Docker and Modal. Your skill's scripts can access `$TENOR_API_KEY` (or `os.environ["TENOR_API_KEY"]` in Python) without the user needing to configure anything extra. See [Environment Variable Passthrough](/user-guide/security#environment-variable-passthrough) for details.
:::

Legacy `prerequisites.env_vars` remains supported as a backward-compatible alias.

### Config Settings (config.yaml)

Skills can declare non-secret settings that are stored in `config.yaml` under the `skills.config` namespace. Unlike environment variables (which are secrets stored in `.env`), config settings are for paths, preferences, and other non-sensitive values.

```yaml
metadata:
  fabric:
    config:
      - key: myplugin.path
        description: Path to the plugin data directory
        default: "~/myplugin-data"
        prompt: Plugin data directory path
      - key: myplugin.domain
        description: Domain the plugin operates on
        default: ""
        prompt: Plugin domain (e.g., AI/ML research)
```

Each entry supports:
- `key` (required) — dotpath for the setting (e.g., `myplugin.path`)
- `description` (required) — explains what the setting controls
- `default` (optional) — default value if the user doesn't configure it
- `prompt` (optional) — prompt text shown during `fabric config migrate`; falls back to `description`

**How it works:**

1. **Storage:** Values are written to `config.yaml` under `skills.config.<key>`:
   ```yaml
   skills:
     config:
       myplugin:
         path: ~/my-data
   ```

2. **Discovery:** `fabric config migrate` scans all enabled skills, finds unconfigured settings, and prompts the user. Settings also appear in `fabric config show` under "Skill Settings."

3. **Runtime injection:** When a skill loads, its config values are resolved and appended to the skill message:
   ```
   [Skill config (from ~/.fabric/config.yaml):
     myplugin.path = /home/user/my-data
   ]
   ```
   The agent sees the configured values without needing to read `config.yaml` itself.

4. **Manual setup:** Users can also set values directly:
   ```bash
   fabric config set skills.config.myplugin.path ~/my-data
   ```

:::tip When to use which
Use `required_environment_variables` for API keys, tokens, and other **secrets** (stored in `~/.fabric/.env`, never shown to the model). Use `config` for **paths, preferences, and non-sensitive settings** (stored in `config.yaml`, visible in config show).
:::

### Credential File Requirements (OAuth tokens, etc.)

Skills that use OAuth or file-based credentials can declare files that need to be mounted into remote sandboxes. This is for credentials stored as **files** (not env vars) — typically OAuth token files produced by a setup script.

```yaml
required_credential_files:
  - path: google_token.json
    description: Google OAuth2 token (created by setup script)
  - path: google_client_secret.json
    description: Google OAuth2 client credentials
```

Each entry supports:
- `path` (required) — file path relative to `~/.fabric/`
- `description` (optional) — explains what the file is and how it's created

When loaded, Fabric checks if these files exist. Missing files trigger `setup_needed`. Existing files are automatically:
- **Mounted into Docker** containers as read-only bind mounts
- **Synced into Modal** sandboxes (at creation + before each command, so mid-session OAuth works)
- Available on **local** backend without any special handling

:::tip When to use which
Use `required_environment_variables` for simple API keys and tokens (strings stored in `~/.fabric/.env`). Use `required_credential_files` for OAuth token files, client secrets, service account JSON, certificates, or any credential that's a file on disk.
:::

See the `skills/productivity/google-workspace/SKILL.md` for a complete example using both.

## Skill Guidelines

### No External Dependencies

Prefer stdlib Python, curl, and existing Fabric tools (`web_extract`, `terminal`, `read_file`). If a dependency is needed, document installation steps in the skill.

### Progressive Disclosure

Put the most common workflow first. Edge cases and advanced usage go at the bottom. This keeps token usage low for common tasks.

### Include Helper Scripts

For XML/JSON parsing or complex logic, include helper scripts in `scripts/` — don't expect the LLM to write parsers inline every time.

### Deliver media as documents (`[[as_document]]`)

If your skill produces a high-resolution screenshot, chart, or any image where lossy preview compression would hurt — emit the literal directive `[[as_document]]` somewhere in the response (commonly the last line). The gateway strips the directive and delivers every extracted media path in that response as a downloadable file attachment instead of an inline image bubble. See [Skill output and media delivery](../user-guide/features/skills.md#skill-output-and-media-delivery) for the full semantics.

#### Referencing bundled scripts from SKILL.md

When a skill is loaded, the activation message exposes the absolute skill directory as `[Skill directory: /abs/path]` and also substitutes two template tokens anywhere in the SKILL.md body:

| Token | Replaced with |
|---|---|
| `${FABRIC_SKILL_DIR}` | Absolute path to the skill's directory |
| `${FABRIC_SESSION_ID}` | The active session id (left in place if there is no session) |

So a SKILL.md can tell the agent to run a bundled script directly with:

```markdown
To analyse the input, run:

    node ${FABRIC_SKILL_DIR}/scripts/analyse.js <input>
```

The agent sees the substituted absolute path and invokes the `terminal` tool with a ready-to-run command — no path math, no extra `skill_view` round-trip. Disable substitution globally with `skills.template_vars: false` in `config.yaml`.

#### Inline shell snippets (opt-in)

Skills can also embed inline shell snippets written as `` !`cmd` `` in the SKILL.md body. When enabled, each snippet's stdout is inlined into the message before the agent reads it, so skills can inject dynamic context:

```markdown
Current date: !`date -u +%Y-%m-%d`
Git branch: !`git -C ${FABRIC_SKILL_DIR} rev-parse --abbrev-ref HEAD`
```

This is **off by default** — any snippet in a SKILL.md runs on the host without approval, so only enable it for skill sources you trust:

```yaml
# config.yaml
skills:
  inline_shell: true
  inline_shell_timeout: 10   # seconds per snippet
```

Snippets run with the skill directory as their working directory, and output is capped at 4000 characters. Failures (timeouts, non-zero exits) show up as a short `[inline-shell error: ...]` marker instead of breaking the whole skill.

### Test It

Run the skill and verify the agent follows the instructions correctly:

```bash
fabric chat --toolsets skills -q "Use the X skill to do Y"
```

## Where Should the Skill Live?

Bundled skills (in `skills/`) ship with every Fabric install. They should be **broadly useful to most users**:

- Document handling, web research, common dev workflows, system administration
- Used regularly by a wide range of people

If your skill is official and useful but not universally needed (e.g., a paid service integration, a heavyweight dependency), put it in **`optional-skills/`** — it ships with the repo, is discoverable via `fabric skills browse` (labeled "official"), and installs with built-in trust.

If your skill is specialized, community-contributed, or niche, it's better suited for a **Skills Hub** — upload it to a registry and share it via `fabric skills install`.

## Blueprints: skills that are also automations

A **blueprint** is an ordinary skill that additionally declares a schedule in its frontmatter. Add a `metadata.fabric.blueprint` block and the skill becomes a shareable, runnable automation:

```yaml
metadata:
  fabric:
    tags: [blueprint, email]
    blueprint:
      schedule: "0 8 * * *"     # presence of `blueprint:` marks it runnable
      deliver: telegram          # optional (default: origin)
      prompt: "Summarize my unread email and today's calendar."  # optional
      no_agent: false            # optional
```

Because a blueprint **is** a skill, it flows through the entire skills pipeline unchanged — search, inspect, install, security scan, provenance, taps, the centralized index, and `fabric skills publish` for sharing. Nothing new to learn.

**Installing a blueprint.** When you install a skill that carries a `blueprint:` block, Fabric registers it as a **suggested cron job** rather than scheduling it. Scheduling is **opt-in** — installing never silently creates a recurring job. You review and accept it via `/suggestions`:

```bash
fabric skills install owner/morning-brief
# → Blueprint: 'morning-brief' is an automation (schedule 0 8 * * *).
#   Added to your suggestions — run /suggestions to schedule or dismiss it.

# then, in a session:
/suggestions             # lists pending suggestions, numbered
/suggestions accept 1    # creates the cron job
/suggestions dismiss 1   # never offer it again
```

Blueprints are one **source** of the unified Suggested Cron Jobs surface — the same place curated starter automations and (later) usage-pattern and integration suggestions appear. See [Suggested Cron Jobs](#suggested-cron-jobs) below.

**Sharing an automation you built.** A blueprint loaded by a cron job (`fabric cron create --skill <name> ...`) can be exported back to a SKILL.md and published like any other skill, so an automation you tuned for yourself becomes a one-command install for someone else.

The blueprint layer adds no new object type, store, or transport — the blueprint is a skill, the schedule is a cron job, and sharing is the existing publish/tap/index path.

## Suggested Cron Jobs

Fabric can *propose* automations and let you accept them with one tap, instead of making you assemble cron jobs by hand. Every proposal flows through one surface — the `/suggestions` command — regardless of where it came from:

| Source | Trigger |
|--------|---------|
| `catalog` | Curated starter automations (`/suggestions catalog`) — daily briefing, important-mail monitor, weekly review, workday-start reminder |
| `blueprint` | You installed a skill carrying a `blueprint:` block |
| `usage` | The background review noticed a recurring ask a schedule would serve |
| `integration` | You connected an account (Gmail, GitHub, ...) and the obvious automations are offered |

```bash
/suggestions             # list pending
/suggestions accept N    # schedule suggestion N (creates the cron job)
/suggestions dismiss N   # dismiss it — latched, never re-offered
/suggestions catalog     # add the curated starter automations
```

Accepting a suggestion calls the same `cron.jobs.create_job` the `cronjob` tool uses — there is no second job engine. Suggestions **never** auto-create jobs; acceptance is always explicit. Dismissed suggestions latch by a stable key so the same proposal is never re-offered. The pending list is capped so it never becomes a nag wall.

The **important-mail monitor** catalog entry is the poll→classify→surface pattern: it scores inbox items with a cheap classifier model (`auxiliary.monitor` in `config.yaml`) and delivers only the ones above an urgency threshold, staying silent otherwise.

## Publishing Skills

### To the Skills Hub

```bash
fabric skills publish skills/my-skill --to github --repo owner/repo
```

### To a Custom Repository

Add your repo as a tap:

```bash
fabric skills tap add owner/repo
```

Users can then search and install from your repository.

## Security Scanning

All hub-installed skills go through a security scanner that checks for:

- Data exfiltration patterns
- Prompt injection attempts
- Destructive commands
- Shell injection

Trust levels:
- `builtin` — ships with Fabric (always trusted)
- `official` — from `optional-skills/` in the repo (built-in trust, no third-party warning)
- `trusted` — from openai/skills, anthropics/skills, huggingface/skills
- `community` — non-dangerous findings can be overridden with `--force`; `dangerous` verdicts remain blocked

Fabric can now consume third-party skills from multiple external discovery models:
- direct GitHub identifiers (for example `openai/skills/k8s`)
- `skills.sh` identifiers (for example `skills-sh/vercel-labs/json-render/json-render-react`)
- well-known endpoints served from `/.well-known/skills/index.json`

If you want your skills to be discoverable without a GitHub-specific installer, consider serving them from a well-known endpoint in addition to publishing them in a repo or marketplace.
