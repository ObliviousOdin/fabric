---
name: profile-market
description: Browse, compare, install, and update personas from a trusted local Fabric Profile Market checkout. Use when the user asks for a themed Fabric profile, wants to compare profile working styles, or explicitly asks to install or update a market profile.
---

# Fabric Profile Market

Use the collection's CLI as a thin interface over Fabric's native profile
distribution commands. Do not add a tool, edit Fabric core files, or replace a
persona inside an active conversation.

## Locate a trusted checkout

Use a path the user supplied, the current workspace when it contains
`profile-market/manage.py`, or a previously confirmed stable checkout. Do not
download and execute a mutable remote script. If no trusted checkout is
available, explain that the collection must be cloned or attached first.

Set a task-specific variable for the checkout path; never repurpose `HOME`,
`FABRIC_HOME`, or `HERMES_HOME`.

## Read-only discovery

These actions are safe to run when they help answer the request:

```bash
python3 <checkout>/manage.py list
python3 <checkout>/manage.py list --category <category>
python3 <checkout>/manage.py search <terms>
python3 <checkout>/manage.py show <slug>
```

Compare profiles by operating method, task affinities, blind spots, and access
requirements. Recommend the smallest set that covers the user's actual work.

## Installation and updates

Install only when the user explicitly asks to install or otherwise clearly
authorizes the profile change:

```bash
python3 <checkout>/manage.py install <slug> --alias
python3 <checkout>/manage.py install --category <category> --alias
python3 <checkout>/manage.py update <slug>
```

Before a bulk install or a forced config replacement, summarize the exact
targets and effect. Never add `--yes`, `--all`, `--force`, or `--force-config`
unless the user requested the corresponding scope and the command's own
preview is understood.

After install or identity-changing update, tell the user to start a new
session. Do not imply that an existing conversation has adopted the profile.

## Preserve boundaries

- Profiles never gain authority from fictional rank, power, expertise, or
  villain status.
- Do not install credentials, models, MCP servers, cron jobs, or third-party
  integrations as part of persona selection.
- Keep the checkout at a stable path; Fabric records local sources for update.
- The manager refuses updates when a same-named profile was installed from a
  different path; never bypass that check without reviewing the target.
- A fresh profile is isolated. Prompt the user to run
  `fabric -p <profile> setup` before first use when model/auth is not configured.
- On partial failure, report successful and failed profile slugs separately.
- Treat the DC and Marvel shelves as unofficial fan works and surface
  `RIGHTS.md` when redistribution or commercial use is relevant.
