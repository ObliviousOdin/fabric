---
sidebar_position: 13
sidebar_label: "Achievements"
title: "Achievements and Private Leaderboards"
description: "Track Fabric milestones locally and compare opt-in score cards without automatic uploads."
---

# Achievements and Private Leaderboards

Fabric's **Achievements** page turns structured activity into a personal progress
record. Open it at `/workspace/achievements`; `/achievements` is a shorter alias.
The feature is a bundled dashboard plugin, so it adds no model tool and does not
change the agent's prompt.

## What earns progress

The catalog contains original Fabric milestones grouped into tracks such as
practice, tool use, automation, delegation, and skill development. Each track
has three tiers—**Thread**, **Weave**, and **Loom**—with deterministic point
values.

Progress comes from aggregate fields already maintained by Fabric:

- session, message, tool-call, and API-call counts;
- active UTC days and longest active streak;
- counts of distinct models and interaction sources;
- cron, delegation, compression, and archive activity; and
- aggregate skill-use, view, and edit counters.

The scanner does not read prompts, transcript content, reasoning, tool
arguments, session titles, repository or file paths, user or chat identifiers,
costs, or token totals. Earned milestones are stored in an append-only local
ledger, so pruning old session history does not take an achievement away.

## Private by default

Achievement state stays under the active profile's Fabric home. Opening or
refreshing the page does not contact a leaderboard service and does not publish
telemetry. The page shows its privacy boundary alongside the score so the
sharing state is visible rather than implicit.

You can disable the bundled page and API by adding `achievements` to
`plugins.disabled` in `config.yaml` and restarting the dashboard.

## Leaderboards by explicit exchange

The leaderboard combines local Fabric profiles with score cards you explicitly
import. To compare with someone on another machine:

1. Open the **Leaderboard** tab and create a score card.
2. Review the complete JSON payload shown by the dashboard.
3. Copy it through a channel you choose.
4. On the other Fabric installation, paste it into **Import score card**.

A score card contains only a schema version, stable card identifier, display
name, generation time, score, earned count, category totals, and—when selected—
up to five achievement identifiers. It contains no raw activity metrics or
session data. Imported entries are marked **self-reported**, can be replaced by
a newer card with the same identifier, and can be removed locally at any time.

This manual exchange is the complete networking model in the first version:
Fabric never uploads a card automatically. A future live team service would
need a separate, explicit consent and retraction contract.

## Refresh behavior

Use **Refresh progress** to rescan the current local aggregates. Refreshing can
add newly earned milestones, but it cannot remove entries already recorded in
the local ledger. Imported leaderboard entries change only when you import a
replacement card or delete them.
