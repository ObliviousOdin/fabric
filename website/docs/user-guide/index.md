---
title: "Using Fabric"
description: "Choose a Fabric interface, shape a profile, and build reliable workflows on the shared agent core."
sidebar_position: 0
---

<div className="docs-hub docs-hub--section">

<p className="docs-hub__eyebrow">User guide</p>

# Choose how you work

<div className="docs-hub__lede">
Every Fabric interface uses the same profile-scoped agent core. Pick the surface
that fits today's task; model routes, memory, skills, approval policy, and
sessions stay with the profile.
</div>

<div className="docs-hub__actions">

[Open the first-run guide](/getting-started/quickstart) [Configure a model](/user-guide/configuring-models)

</div>

## Pick a surface

<div className="docs-hub-grid docs-hub-grid--three">

<section className="docs-hub-card">

<p className="docs-hub-card__kicker">Visual workspace</p>

### See the work as it happens

Use the native app for focused chat and project work, or open Fabric Workspace
and Admin for browser-based operations and runtime control.

[Use Desktop →](/user-guide/desktop) · [Understand Workspace and Admin →](/user-guide/workspace-admin) · [Run the web experience →](/user-guide/features/web-dashboard)

</section>

<section className="docs-hub-card">

<p className="docs-hub-card__kicker">Terminal</p>

### Stay close to the repository

Use the CLI for direct work and scripting, or the TUI for an interactive full-screen terminal experience.

[Use the CLI →](/user-guide/cli) · [Use the TUI →](/user-guide/tui)

</section>

<section className="docs-hub-card">

<p className="docs-hub-card__kicker">Messaging</p>

### Keep a conversation available

Connect a supported channel for long-running conversations, scheduled delivery, and remote access.

[Set up messaging →](/user-guide/messaging/)

</section>

</div>

## Understand the two web surfaces

- **Workspace** is where business users follow conversations, agents,
  automations, evidence, and outcomes.
- **Admin** is where operators configure integrations, channels, models,
  credentials, and the Fabric runtime.
- **Profiles** remain independent agent configuration and memory islands. They
  are not tenant, team workspace, site, or human-role scopes.

The shell and its first critical screens are available now. Enterprise tenancy,
server-enforced roles, and the durable Work Board, approvals, activity, and
typed Memory services are staged backend contracts. See the
[Workspace and Admin guide](/user-guide/workspace-admin) for the route map and
current delivery status.

## Shape the agent around your work

<div className="docs-hub-grid docs-hub-grid--two">

<section className="docs-hub-card">

### Remember the right context

Use profile-local memory for durable facts and project context files for instructions that belong with the work.

[Understand memory →](/user-guide/features/memory) · [Add project context →](/user-guide/features/context-files)

</section>

<section className="docs-hub-card">

### Add focused capabilities

Skills load task-specific playbooks on demand. Tools and plugins connect services without turning every workflow into core behavior.

[Work with skills →](/user-guide/features/skills) · [Configure tools →](/user-guide/features/tools) · [Extend with plugins →](/user-guide/features/plugins)

</section>

<section className="docs-hub-card">

### Automate repeatable work

Schedule jobs with cron, split larger tasks with delegation, and use checkpoints before risky changes.

[Schedule a job →](/user-guide/features/cron) · [Delegate work →](/user-guide/features/delegation) · [Use checkpoints →](/user-guide/checkpoints-and-rollback)

</section>

<section className="docs-hub-card">

### Separate and secure environments

Use profiles to isolate credentials and state, then review approval and network boundaries before remote or unattended operation.

[Manage profiles →](/user-guide/profiles) · [Review security →](/user-guide/security) · [Store secrets →](/user-guide/secrets/)

</section>

</div>

## A reliable first session

<ol className="docs-hub-steps">
  <li><strong>Select one route.</strong> Run <code>fabric model</code> and configure only the provider you intend to test.</li>
  <li><strong>Verify the profile.</strong> Run <code>fabric status --deep</code> before opening a long session.</li>
  <li><strong>Prove one task.</strong> Ask Fabric to complete a small, observable action, then add memory, skills, or another surface.</li>
</ol>

For the exact commands and verification criteria, follow the
[Quickstart](/getting-started/quickstart). For configuration keys and command
syntax, use the [Reference](/reference/).

</div>
