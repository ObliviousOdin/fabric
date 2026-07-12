---
title: "Fabric Reference"
description: "Find exact Fabric commands, settings, model and skill catalogs, and recovery guidance."
sidebar_position: 0
---

<div className="docs-hub docs-hub--section docs-hub--reference">

<p className="docs-hub__eyebrow">Reference</p>

# Find the exact answer

<div className="docs-hub__lede">
Use these pages when you know what you need and want the precise command,
setting, schema, or capability contract. For a guided workflow, use the
task-oriented documentation instead.
</div>

<div className="docs-hub__actions">

[Follow the Quickstart](/getting-started/quickstart) [Browse the User Guide](/user-guide/)

</div>

## Look up by question

<div className="docs-hub-grid docs-hub-grid--two">

<section className="docs-hub-card">

<p className="docs-hub-card__kicker">Commands</p>

### What can I run?

- [CLI commands](/reference/cli-commands) — top-level commands, flags, and subcommands
- [Slash commands](/reference/slash-commands) — commands available inside a session
- [Profile commands](/reference/profile-commands) — create, select, inspect, and manage isolated profiles

</section>

<section className="docs-hub-card">

<p className="docs-hub-card__kicker">Configuration</p>

### Which setting controls this?

- [Environment variables](/reference/environment-variables) — credentials and runtime overrides
- [MCP configuration](/reference/mcp-config-reference) — server definitions, transports, and tool filtering
- [Model catalog](/reference/model-catalog) — supported model identifiers and route metadata

</section>

<section className="docs-hub-card">

<p className="docs-hub-card__kicker">Capabilities</p>

### What can Fabric load?

- [Tools](/reference/tools-reference) — callable capabilities and their contracts
- [Toolsets](/reference/toolsets-reference) — capability groups and activation rules
- [Bundled skills](/reference/skills-catalog) — skills included with Fabric
- [Optional skills](/reference/optional-skills-catalog) — additional installable workflows

</section>

<section className="docs-hub-card">

<p className="docs-hub-card__kicker">Recovery</p>

### Why is this not working?

- [FAQ and troubleshooting](/reference/faq) — common symptoms and next checks
- [Repair an install](/getting-started/repair) — restore a managed installation
- [Platform support](/getting-started/platform-support) — supported environments and known boundaries

</section>

</div>

## Verify before changing more

When a route or tool behaves unexpectedly, inspect the resolved profile before
adding another provider or changing unrelated settings:

```bash
fabric status --deep
fabric doctor
```

The status output is the better starting point for runtime questions; the
configuration file alone may not show defaults, profile selection, or the
effective provider route.

<div className="docs-hub__actions">

[Browse the User Guide](/user-guide/) [Open troubleshooting](/reference/faq)

</div>

</div>
