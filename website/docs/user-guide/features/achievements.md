---
sidebar_position: 13
sidebar_label: "Achievements"
title: "Fabric Journey and Achievements"
description: "Learn Fabric by completing useful work, with private local progress and explicit Friendly score cards."
---

# Fabric Journey and Achievements

Fabric's **Achievements** page is an interactive learning journey, not a wall of
badges. It recommends a useful next action, teaches Fabric's capabilities through
real work, and records demonstrated mastery. Open it at
`/workspace/achievements`; `/achievements` is a shorter alias. The feature is a
bundled dashboard plugin, so it adds no model tool and does not change the
agent's prompt.

## Start with an outcome

A new profile first chooses an outcome: finish work faster, build with agents,
create content, or automate recurring work. Fabric then guides the user through
three foundations:

1. complete one useful Chat turn;
2. use a tool successfully; and
3. delegate one bounded task to a subagent.

Chat actions open a fresh conversation with a reviewable draft in the composer.
Fabric never submits that draft automatically, and opening a quest never grants
progress by itself.

## Today, Paths, and Collection

The page has four URL-backed views:

- **Today** shows one primary quest, up to two optional quests, a weekly
  expedition, Momentum, recent wins, and active Paths. Daily assignments include
  one free reroll; Weekly offers one when a different capability pair exists.
- **Paths** teaches conversation, agent crews, deep work, model setup, creation,
  computer use, automation, skills, contribution, and work across surfaces.
- **Collection** keeps earned mastery, a bounded set of next achievements, and
  the original V1 milestones under **Legacy**.
- **Leaderboard** keeps your V2 mastery separate from other readable local
  profiles and from explicitly imported Friendly cards.

Mastery ranks progress from **Explorer** through **Operator**, **Builder**,
**Orchestrator**, **Weaver**, and **Patternmaker**. Higher ranks require both XP
and breadth across capability Paths, so repeating one easy action cannot create
mastery. Earned achievements are permanent. Momentum is a 28-day local-season
signal that rewards useful return visits without streak loss or punishment for
time away.

Some guided activities cannot be verified safely. For example, Fabric can help
draft and review a LinkedIn post, but an external publish is self-attested,
awards 0 rank XP, and never enters the verified local ranking.

## Private by default

Journey tracking is default-on and stays under the active profile's Fabric home.
It records only a closed capability envelope: event type, timestamp, bounded
duration and count, opaque references, capability, outcome, surface, provider,
and source. It does **not** record prompts, replies, conversation history, tool
arguments or results, errors, URLs, file paths, generated content, identities,
costs, or token counts.

Raw rows are pruned through the profile-local retention policy and compacted
into bounded aggregate evidence where safe. Earned achievements remain after
pruning. Opening or refreshing the page does not contact a leaderboard service
and does not publish telemetry.

The tracking disclosure lets you:

- pause or resume new collection (paused activity is not backfilled);
- disable meaningful active-time reflection independently;
- choose standard, quiet, or off celebrations;
- export the local metadata for inspection; and
- delete activity metadata after an inline confirmation while preserving
  observed earned achievements, settings, and Legacy milestones. Mutable
  quests, Momentum, snoozes, and self-attestations are cleared.

You can disable the bundled page and API by adding `achievements` to
`plugins.disabled` in `config.yaml` and restarting the dashboard.

## Local and Friendly leaderboards

V2 mastery uses only rank-eligible evidence observed on this device. The
Leaderboard view separates **You**, other readable **Profiles** on the device,
and **Friendly** cards imported from someone else. Friendly scores are always
labeled self-reported and never mix with verified local mastery.

To compare with someone on another machine:

1. Open **Leaderboard** and create a score card.
2. Review the complete JSON payload shown by the dashboard.
3. Copy it through a channel you choose.
4. On the other Fabric installation, review and confirm the import.

A score card contains only a schema version, stable card identifier, display
name, generation time, score, earned count, category totals, and—when selected—
up to five achievement identifiers. It contains no raw activity metrics or
session data. Imported entries are marked **self-reported**, can be replaced by
a newer card with the same identifier, and can be removed locally at any time.
Each profile can keep at most 250 Friendly cards; replacing an existing card
does not use a new slot.

This manual exchange is the complete networking model: Fabric never uploads a
card automatically or sends it on the user's behalf.

## Refresh behavior

Use **Refresh** to reconcile queued local events and show newly earned
mastery. Refreshing can add achievements, but it cannot remove earned entries.
Imported Friendly cards change only when you import a replacement or delete
them.
