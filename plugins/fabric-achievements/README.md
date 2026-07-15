# Fabric Achievements

Fabric Achievements adds collectible, tiered badges to the Fabric Dashboard.
It derives progress from local Fabric session history and does not send that
history to an external service.

This bundled adaptation was originally authored by
[@PCinkusz](https://github.com/PCinkusz) in
[PCinkusz/hermes-achievements](https://github.com/PCinkusz/hermes-achievements).
The upstream project and this adapted copy are MIT licensed; the original
component license is preserved in [LICENSE](LICENSE).

The plugin ships in `plugins/fabric-achievements/` and auto-registers when
`fabric dashboard` starts. No separate installation step is required. See
[Built-in Plugins → fabric-achievements](../../website/docs/user-guide/features/built-in-plugins.md)
for the user guide.

## What it does

Fabric Achievements scans local Fabric sessions and unlocks badges for:

- autonomous tool chains
- debugging and recovery patterns
- file-editing and vibe-coding workflows
- Fabric skills, memory, cron, and plugin usage
- web research and browser automation
- model/provider workflows, including local models
- weekend, night, and other usage patterns

Achievements have three visible states:

- **Unlocked** — at least one tier has been earned
- **Discovered** — the achievement and progress are visible but incomplete
- **Secret** — hidden until Fabric detects the first related signal

Tiered achievements progress through:

```text
Copper → Silver → Gold → Diamond → Olympian
```

Each card includes a **What counts** section with the tracked metric or
requirement. Achievement IDs remain stable because they are used as unlock
state keys.

## Local state

State stays beneath the configured Fabric home directory:

```text
$FABRIC_HOME/plugins/fabric-achievements/
├── state.json
├── scan_snapshot.json
├── scan_checkpoint.json
└── team.json          # team leaderboard membership (only if you join a team)
```

`FABRIC_HOME` defaults to `~/.fabric`. The snapshot and checkpoint make warm
loads incremental; the unlock state is not overwritten by source updates.

## Team leaderboard (opt-in)

The **Team Leaderboard** tab lets several Fabric users compare achievements.
It preserves the local-first privacy promise: the achievement engine still
never sends your session history anywhere. When you *opt in* to a team, the
only thing that leaves your machine is an **aggregate profile** — a score,
unlock/tier counts, per-category tallies, up to five unlocked-badge names from
the static catalogue, and a display name you choose. Session titles,
transcripts, file paths, and raw metrics are never sent (enforced by
`build_leaderboard_profile` and re-checked by the relay's `sanitize_profile`,
and pinned by `tests/plugins/test_leaderboard_privacy.py`).

How it connects: one person runs a small **relay** (see
[`relay/README.md`](relay/README.md) — a stdlib-only, self-hostable service,
`python -m relay`). Creating a team returns a shareable **invite code**
(`fbl1_…`); others paste it and choose **Join and share my score**. The button
is the explicit opt-in, so a display name and separate consent checkbox are not
required; the member can choose a name or join without sharing from the
secondary options. Relay hosting and team creation stay under **Advanced**.
Once joined, sharing is a one-click status control and opting out actively
retracts the member's published row. Each member's dashboard talks to the relay
server-to-server through these backend routes — the browser never contacts the
relay directly. Publishing is aggregate-only, the team owner can reset the
invite or remove members, and scores are self-reported (this is a friendly
board, not an adversarial ranking).

## Dashboard API

Routes are mounted under:

```text
/api/plugins/fabric-achievements/
```

Endpoints:

```text
GET  /achievements
GET  /scan-status
GET  /recent-unlocks
GET  /sessions/{session_id}/badges
POST /rescan
POST /reset-state

# Team leaderboard (opt-in). These carry the aggregate profile / team secrets
# and write local state, so they stay behind the dashboard auth gate — they are
# NOT added to the public-paths allowlist.
GET  /team
GET  /team/leaderboard
POST /team/create
POST /team/join
POST /team/leave
POST /team/settings
POST /team/publish
POST /team/rotate     # owner only
POST /team/kick       # owner only
```

The dashboard host applies its normal authentication policy to these routes.

## Development

Run focused checks from the repository root:

```bash
node --check plugins/fabric-achievements/dashboard/dist/index.js
python3 -m py_compile plugins/fabric-achievements/dashboard/plugin_api.py
python3 -m unittest plugins/fabric-achievements/tests/test_achievement_engine.py -v
python3 -m unittest plugins/fabric-achievements/tests/test_leaderboard_store.py -v
pytest -q tests/plugins/test_achievements_plugin.py tests/plugins/test_leaderboard.py tests/plugins/test_leaderboard_privacy.py
```

Run the relay locally while iterating on the leaderboard UI:

```bash
cd plugins/fabric-achievements && python -m relay --host 127.0.0.1 --port 9137
```

## License and provenance

MIT. Preserve this directory's `LICENSE` and the upstream attribution above
when redistributing the plugin.
