# Achievements

Achievements is an independent, bundled first-party Fabric plugin for private,
local milestones. It is implemented for Fabric and is not a port, fork,
integration, or compatibility layer for an older or third-party achievement
system.

Open it in the dashboard at `/workspace/achievements` (or the shorter
`/achievements` alias). The plugin adds no model tool and does not change the
agent core.

## Privacy model

Achievement evaluation is device-only. Rules use structured, aggregate-only
metrics, such as counts and completion statuses, that Fabric already records
locally. The plugin does not inspect prompts, assistant replies, tool arguments
or results, conversation content, or file content.

There are no automatic uploads, analytics calls, remote leaderboards,
background outbound network requests, or WebSocket connections. Refreshing
recalculates local progress from the same structured aggregates.

Achievement state is Fabric-native. The plugin does not migrate, import, or
read state from older achievement implementations, legacy state directories,
or external achievement products.

## Milestones

The dashboard groups milestones into three tiers:

- **Thread** — early habits and first completions
- **Weave** — repeated, broader use
- **Loom** — sustained or advanced milestones

Each card shows its category, points, lock state, and the aggregate progress
toward its threshold. Category and status filters affect only the local view.
Opening the page performs an idempotent reconciliation against local structured
history. The Refresh button re-scans those same local aggregates while the page
is open.

## Manual sharing

The leaderboard is local. It contains only:

1. readable Fabric profiles on this device; and
2. share cards that the user explicitly pastes and confirms.

The active profile can export a share card. Other local profiles are shown as
read-only rows; the plugin does not modify their progress or settings. If a
local profile cannot be read safely, it is skipped and the dashboard reports
the skipped count.

Creating a share card returns its complete JSON payload in a read-only field so
the user can inspect and copy exactly what will be shared. Fabric does not send
that payload anywhere. A share card contains a stable `card_id`; importing a
newer card with the same ID updates the peer's existing row instead of creating
a duplicate.

Imported cards are self-reported, not verified by a server. Every imported row
is labeled accordingly and can be deleted locally. Import and deletion both
require an explicit user action, and import also requires confirmation.

## Dashboard API

The dashboard bundle talks only to the plugin-local API through the authenticated
dashboard SDK:

- `GET /api/plugins/achievements/summary`
- `POST /api/plugins/achievements/refresh`
- `POST /api/plugins/achievements/reset`
- `POST /api/plugins/achievements/share-card`
- `GET /api/plugins/achievements/leaderboard`
- `POST /api/plugins/achievements/leaderboard/import`
- `DELETE /api/plugins/achievements/leaderboard/{card_id}`

Share-card creation accepts `display_name` and an optional list of up to five
`achievement_ids`. Import accepts the share-card payload itself. The committed
dashboard bundle is a plain IIFE and uses `SDK.fetchJSON` for every API call;
it creates no independent React root and handles no auth token directly.

The reset contract is deliberately narrow: it accepts only
`{"scope":"imported_leaderboard","confirm":true}` and removes imported
leaderboard rows, but it never clears achievement progress. The v1 dashboard
uses per-row removal instead of presenting a bulk reset.
