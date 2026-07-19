# Fabric Journey (Achievements)

Achievements is Fabric's private, local learning and adoption plugin. Journey
V2 turns the page from a wall of zero-value badges into a useful next action:
choose an outcome, complete real work with Fabric, and build mastery across its
capabilities.

Open it at `/workspace/achievements` or the `/achievements` alias. The plugin
adds no model tool and does not mutate the conversation prompt or tool schema.

## Product model

The dashboard has four route-backed views:

- **Today** presents one primary quest, at most two optional quests, a weekly
  expedition, momentum, recent wins, and active paths. A new profile sees an
  outcome picker and a three-step starter journey instead of meaningless zero
  counters.
- **Paths** organizes learning into Conversation craft, Agent crew, Deep work,
  Model lab, Create, Computer use, Automate, Skills, Contributor, and Fabric
  anywhere. Each step explains its evidence, progress, reward, and next action.
- **Collection** separates earned achievements, a bounded set of useful next
  achievements, and preserved Legacy milestones.
- **Leaderboard** keeps the current profile, other locally observed profiles,
  and manually imported Friendly cards on separate boards.

The URL is the view state. Supported parameters are `view`, `path`, `status`,
`board`, and `focus`; unrelated query parameters and hashes are preserved.
Legacy `tab=achievements` and `tab=leaderboard` links migrate in place.

Quest actions can open Chat with a fresh ID and a reviewable draft. They never
submit the draft automatically. Unsupported capabilities remain visible and
explain why they cannot be observed instead of silently disappearing.

## Mastery, momentum, and time

Mastery XP represents demonstrated, rank-eligible capability use. Levels also
require breadth and starter completion, so repeating one low-value action does
not create mastery. Momentum is a short local-season signal designed to welcome
useful return visits without punishing time away.

When available, Today shows capped meaningful active time as a private
reflection. It is based on locally closed activity intervals, excludes idle
time through the engine's caps, and never awards XP or changes rank. Raw time
is not a productivity score.

## Privacy and control

Journey tracking is default-on and device-local. Fabric records a bounded
capability-event envelope such as event type, timestamp, duration, opaque
references, capability, outcome, surface, provider, count, and source. It does
not record prompts, assistant replies, conversation history, tool arguments or
results, URLs, file paths, generated content, cost, or token counts for
achievements.

The “How progress is tracked” disclosure lets the user:

- pause or resume new tracking;
- turn active-time tracking on or off;
- choose standard, quiet, or off celebrations;
- export the local activity metadata; and
- delete activity metadata after an inline confirmation.

Deleting activity preserves observed earned achievements, settings, and Legacy
milestones; it clears mutable quests, Momentum, snoozes, and self-attestations.
Paused time is not silently backfilled. There are no analytics calls,
automatic uploads, remote leaderboards, or plugin WebSocket connections.

Friendly share-card imports are profile-local and capped at 250 cards per
profile. Re-importing an existing card updates it without consuming another
slot.

## Honest guided publishing

The Create path includes a guided LinkedIn publishing quest. Fabric can help
draft and review the post in Chat, but it cannot verify an external publish.
The explicit “Mark as published” flow is therefore self-attested, awards
**0 rank XP**, and never enters Today recommendations or locally observed
profile rankings.

## Leaderboards and sharing

Journey V2 ranks only local, rank-eligible mastery records. “You” is kept apart
from “Profiles,” and imported cards are kept on “Friendly.” Friendly imports
use the existing inspectable V1 share-card format, are labeled self-reported,
and never mix with V2 mastery. Generating a card, reviewing an import, importing
it, and deleting it all require explicit actions. Fabric never sends a card on
the user's behalf.

If the Journey API is unavailable, the page falls back to the original summary
and leaderboard endpoints. Those rows are labeled **Legacy local snapshots**;
their V1 scores are not presented as V2 mastery.

## Dashboard API

The committed IIFE bundle uses only the authenticated dashboard
`SDK.fetchJSON` client:

- `GET /api/plugins/achievements/journey`
- `POST /api/plugins/achievements/journey/refresh`
- `PATCH /api/plugins/achievements/settings`
- `POST /api/plugins/achievements/quests/{id}/snooze`
- `POST /api/plugins/achievements/quests/content.linkedin_launch/attest`
- `POST /api/plugins/achievements/challenges/{daily|weekly}/reroll`
- `GET /api/plugins/achievements/activity/export`
- `DELETE /api/plugins/achievements/activity`
- `POST /api/plugins/achievements/share-card`
- `GET /api/plugins/achievements/leaderboard`
- `POST /api/plugins/achievements/leaderboard/import`
- `DELETE /api/plugins/achievements/leaderboard/{card_id}`

Settings accepts partial `tracking_enabled`, `active_time_enabled`,
`celebration_mode`, and `preferred_outcome` updates. Snoozing sends
`{"days": 7}`. Each current Daily assignment has one free local reroll;
Weekly offers one only when a genuinely different capability pair is available.
Activity deletion sends `{"confirm": true}`. The original
`GET /summary` and `POST /refresh` endpoints remain read-compatible fallbacks.

The host owns the page's sole `<main>`, page title, router, authenticated API
client, and React root. The plugin renders supporting content inside that host
surface and uses only icons exposed by the dashboard SDK.
