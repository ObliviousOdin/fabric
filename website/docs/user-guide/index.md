---
title: "Using Fabric"
description: "Choose a Fabric interface, configure a profile, and understand the shared runtime behind every surface."
sidebar_position: 0
---

# Using Fabric

Fabric runs one profile-scoped agent core across desktop, terminal, web,
messaging, IDE, and API surfaces. Start with the interface that fits the work;
your model routes, memory, skills, approvals, and sessions remain attached to
the selected profile.

## Choose an interface

- [Desktop](/user-guide/desktop) for a native visual workspace.
- [CLI](/user-guide/cli) for direct terminal work and scripting.
- [TUI](/user-guide/tui) for the full-screen terminal interface.
- [Web dashboard](/user-guide/features/web-dashboard) for browser-based administration.
- [Messaging](/user-guide/messaging) for long-running channel conversations.

## Configure the profile

1. Select a model route with `fabric model`.
2. Add only the capability backends you need with `fabric tools`.
3. Verify the resolved profile with `fabric status --deep`.
4. Review [configuration](/user-guide/configuration), [profiles](/user-guide/profiles), and [security](/user-guide/security) before remote or unattended work.

## Build on the core

- [Memory](/user-guide/features/memory) carries durable context between sessions.
- [Skills](/user-guide/features/skills) load focused playbooks on demand.
- [Cron](/user-guide/features/cron) schedules repeatable work.
- [Delegation](/user-guide/features/delegation) divides larger tasks across agents.
- [Plugins](/user-guide/features/plugins) extend providers and capability surfaces without widening the core.

For a guided first run, use the [Quickstart](/getting-started/quickstart).
