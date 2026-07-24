---
sidebar_position: 3
title: "Repair and diagnostics"
description: "A safe recovery ladder for Fabric: isolate customizations, inspect status and logs, then choose an explicit repair"
---

# Repair and diagnostics

Start with isolation and evidence. Move to a command that changes files only
after the diagnostics point to a specific problem.

This guide describes the commands in the current Fabric CLI. It does not
assume that every check is offline or that every warning can be repaired
automatically.

## Recovery ladder

| Stage | Command | Runs an explicit repair or migration? | Can make network requests? |
|---|---|---:|---:|
| Isolate customizations | `fabric --safe-mode` | No | Yes, when the agent uses its configured credentials to call a model or tool |
| Inspect component state | `fabric status --deep` | No repair writes | Online: yes, conditionally. `local_ai`: only the authorized Ollama readiness probe. Unavailable policy: no live probes. |
| Inspect configuration age and missing values | `fabric config check` | No | No intentional network probe |
| Run broad diagnostics | `fabric doctor` | No automatic repairs | Online: yes. `local_ai` or unavailable/malformed policy: restricted local view only. |
| Read or follow logs | `fabric logs` | No | No |
| Render a support bundle locally | `fabric debug share --local` | No current-bundle upload; may update old paste-cleanup state | Only for best-effort cleanup of expired pastes from earlier uploads |
| Migrate configuration | `fabric config migrate` | **Yes** | No intentional network probe |
| Reset corrupt provider-account metadata | `fabric auth accounts repair` | **Yes**, after confirmation | No |
| Apply available repairs | `fabric doctor --fix` | Online: **yes**. Restricted policy view: no fix is applied. | Online: yes. Restricted policy view: no live probes. |

The mutation column describes each command's explicit purpose. Ordinary CLI
startup can still create logs, and status may initialize a missing session
store while reading session counts; do not use this table as a filesystem
forensics guarantee.

Use `-p` before the command to diagnose a named profile:

```bash
fabric -p work status --deep
fabric -p work doctor
fabric -p work logs errors -n 100
```

The default profile stores its state under `~/.fabric/`. A named profile uses
`~/.fabric/profiles/<name>/`. Keep the profile explicit while troubleshooting
so that a healthy profile is not mistaken for the failing one.

## Repair the egress mode first

Each profile has one explicit application/network contract:

- `online` preserves its configured network behavior;
- `local_ai` restricts participating AI routes to canonical literal loopback
  or explicitly approved private CIDRs; and
- `air_gapped` is configured but unavailable. It blocks runtime startup because
  Fabric has not yet shipped a verified whole-process network boundary.

Inspect the policy without starting a runtime:

```bash
fabric -p work status
fabric -p work doctor
```

Status reports mode, availability, scope, a count of approved private CIDRs,
and a stable reason. It never prints the CIDR values. If the profile is
`air_gapped`, chat, gateway, TUI, dashboard, and headless server startup are
blocked before credentials, external vaults, updates, MCP, adapters, cron,
plugins, or provider work. The local `config`, `status`, `doctor`, and `version`
commands remain available for recovery; `version` stays local and does not run
its update probe in this state.

The other commands in this guide become available after the profile returns to
`online` or `local_ai`. While `air_gapped` is selected, `fabric logs` and
`fabric debug share` are intentionally blocked at the runtime gate; inspect the
profile's log files directly only if that is appropriate for your host access.

Use `fabric -p work config` or edit that profile's `config.yaml` to select a
currently available mode:

```yaml
security:
  egress_mode: local_ai  # or online
  local_ai_allowed_cidrs: []
```

Loopback requires no entry. `local_ai_allowed_cidrs` accepts only exact
RFC1918, IPv6 ULA, or CGNAT networks; other hostnames are rejected without DNS.
For a complete local-model setup, follow the
[local Ollama guide](/guides/local-ollama-setup).

## 1. Reproduce once in safe mode

```bash
fabric --safe-mode
```

Safe mode bypasses the active profile's behavioral configuration, injected
project instructions and persona, memory, preloaded skills, plugins, MCP
servers, and shell hooks for that process. It does not delete any of them.

Safe mode is an isolation tool, not an offline mode or a security sandbox.
Credentials from the profile's `.env` remain available, built-in capabilities
remain available, and a chat can still contact its model provider. If the
problem disappears in safe mode, re-enable customizations in small groups and
test again.

Safe mode is not a substitute for `local_ai`, and an `air_gapped` profile blocks
safe-mode runtime startup just like any other chat launch.

If the problem remains, continue with the read-oriented checks below.

## 2. Capture status without repairing anything

```bash
fabric status --deep
```

In `online`, the normal status report summarizes the environment, configured
model and provider, credential presence, OAuth state, tools, gateway, scheduled
jobs, and sessions. `--deep` adds these current checks:

- a bounded passive Ollama readiness inspection when the selected profile has a
  local/custom endpoint candidate; it reports protocol, selected-model, context,
  tool/vision, and optional loaded-resource evidence without sending a chat;
- an OpenRouter model-catalog request when `OPENROUTER_API_KEY` is present;
- a loopback connection check for port `18789`.

It is a general Fabric status report. It does not probe every configured model
endpoint. Its Ollama result is passive metadata and does not prove that the model
can answer a chat or complete a tool call. Verify a provider with an actual,
minimal Fabric chat after the diagnostics are clean.

In `local_ai`, status uses strict, unexpanded profile configuration and skips
remote credentials, OAuth, account, provider-catalog, external-memory, plugin,
and other live probes. `status --deep` adds only the bounded authorized Ollama
check, with proxy inheritance and redirects disabled. When the policy is
malformed or unavailable, status enters a repair-only view before credentials
or plugins load and runs no live probe.

## 3. Inspect configuration before migrating it

```bash
fabric config check
```

`config check` reports the configuration schema version, missing required and
optional environment values, and newly available configuration fields. It does
not run the migration. Use `fabric doctor` when you need broader validation of
the configuration structure and provider setup.

If the check reports an older schema, first make a private backup of the active
profile's `config.yaml` and `.env`, then run:

```bash
fabric config migrate
```

Migration is explicitly mutating. Depending on the starting version and the
files it finds, it can rewrite legacy keys, sanitize malformed `.env` entries,
update the schema version, prompt for missing credentials or skill settings,
create migration-owned directories, and disable suspicious MCP entries pending
review. It preserves current non-default settings through the repository's
versioned migration path, but it is not merely a check.

Afterward, verify the result:

```bash
fabric config check
fabric doctor
```

## 4. Run the doctor in diagnostic mode

```bash
fabric doctor
```

Without `--fix`, the doctor reports issues and suggested actions instead of
entering its automatic repair branches. It checks areas such as:

- security advisories and suspicious MCP commands;
- Python packages, configuration structure, directories, and the session store;
- command installation, external tools, skills, memory, and tool availability;
- configured provider and remote-backend connectivity.

Doctor is broader than a local file check. It can run installed utilities and
make network requests to configured providers, package registries, or remote
backends **when the profile is `online`**. Run that form from a network you
trust, and do not use it as proof that a host was tested without egress.

For `local_ai`, `air_gapped`, or an unavailable/malformed policy, Doctor instead
uses a restricted diagnostic view. It reports the egress contract, local files,
built-in memory, selected external-memory blocking, and repair guidance without
loading profile secrets or running live provider, OAuth, secret-vault, MCP,
plugin, package-audit, container, SSH, or update probes. `doctor --fix` does not
apply mutations in this restricted view.

## 5. Read the relevant logs

Start with errors, then narrow the time or component if needed:

```bash
fabric logs errors -n 100
fabric logs --level WARNING --since 1h
fabric logs gateway --since 30m
fabric logs --component tools --session <session-id>
```

Follow a live log with `-f` and stop with <kbd>Ctrl</kbd>+<kbd>C</kbd>:

```bash
fabric logs -f
```

Available named logs currently include `agent`, `errors`, `gateway`, `gui`,
`desktop`, and `mcp`; `agent` is the default. List the files present for the
active profile with:

```bash
fabric logs list
```

Logs can contain prompts, tool output, identifiers, and local paths. Inspect
them before copying any excerpt into a ticket or message.

## 6. Render a debug report locally

The current CLI requires the `share` subcommand:

```bash
fabric debug share --local
```

`fabric debug --local` is **not** a valid command.

The local form collects the same system summary and log snapshots used by the
sharing flow, applies secret redaction by default, and prints the result to the
terminal. It does not upload the current report. Redaction targets credentials;
it does not promise to remove conversation text, user identifiers, or local
filesystem paths.

If you redirect the report, protect and delete the resulting file when it is no
longer needed:

```bash
fabric debug share --local > fabric-debug.txt
```

There is one narrow network caveat: every `fabric debug` invocation performs a
best-effort sweep of expired `paste.rs` deletion records left by earlier upload
commands. If `~/.fabric/pastes/pending.json` contains an expired record, even
the local form may issue a `DELETE` request for that old paste. The current
report itself is still not uploaded. Therefore, `--local` is a no-current-upload
guarantee, not a strict no-network mode.

Running `fabric debug share` without `--local` is different: after an explicit
interactive confirmation, it uploads the report and available log snapshots to
an external paste service and prints shareable links. `--yes` skips that prompt.
Secret redaction is enabled by default, but other personal or project data can
remain, so review a local report before choosing any upload path.

## 7. Apply a targeted repair

### Reset provider-account metadata

If ChatGPT or Grok ownership/request status reports `invalid_state`, repair only
that profile's provider-account metadata:

```bash
fabric -p work auth accounts repair
```

The interactive command names the selected logical profile and asks for
confirmation without displaying its canonical filesystem path. For an unattended
local recovery, pass `--yes`:

```bash
fabric -p work auth accounts repair --yes
```

This resets every provider record in that profile's
`provider-accounts.json`, including desired ownership, managed-request history,
and OAuth lease/completion fences. It does not remove credentials from
`auth.json` or prove that a subscription is connected. When a safe state file
exists, Fabric first writes an exact owner-only backup under the profile's
`.provider-account-repair/` directory. The source is atomically claimed into that
backup before the reset is published with a native atomic no-replace move. It never
uses a hardlink or copy fallback, and it refuses to overwrite a state entry created
by another process. If publication becomes visible before an operating-system error
or interrupt, the command reports the stable non-retryable `commit_uncertain` result
instead of claiming a safe retry. The CLI result reports only whether a backup was
created; it never prints the backup path or prior bytes.

Repair refuses a newer schema, an oversized file whose schema cannot be proven,
a symlink/junction/reparse redirect, a hard link, or unsafe file/directory
permissions. It is a local operator command only: the dashboard, typed
JSON-RPC API, messaging gateway, and model tools register no dedicated reset
mutation. The TUI's generic `cli.exec` RPC also rejects this command before
loading profile secrets or starting a CLI subprocess. An authenticated,
user-entered shell such as the TUI's `!command` remains terminal-equivalent and
retains the same local-operator authority as any other shell; it is not a
separate repair API or a sandbox boundary.

### Apply Doctor's available fixes

When Doctor is in `online` mode and identifies an issue it can repair, run:

```bash
fabric doctor --fix
```

This command is mutating in the online diagnostic path. Its available repairs
depend on what it finds. They include creating missing Fabric files and
directories, running configuration migrations, removing stale settings,
repairing session-database structures with a backup, checkpointing an oversized
database WAL, and repairing a command entry link. Some findings remain manual
and will still be listed afterward. In a restricted `local_ai`, `air_gapped`,
or malformed/unavailable policy view, Doctor reports that `--fix` was not
applied.

Do not treat `--fix` as a general reset. It does not erase every customization,
and it does not guarantee that every provider, plugin, or operating-system
problem can be repaired automatically.

Finish by rerunning diagnostics without the repair flag and then testing one
plain chat:

```bash
fabric doctor
fabric config check
fabric chat
```

Only after that baseline works should you re-enable the gateway, automation,
plugins, skills, MCP servers, or other optional integrations involved in the
original failure.
