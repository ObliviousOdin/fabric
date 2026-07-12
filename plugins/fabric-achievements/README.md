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
└── scan_checkpoint.json
```

`FABRIC_HOME` defaults to `~/.fabric`. The snapshot and checkpoint make warm
loads incremental; the unlock state is not overwritten by source updates.

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
```

The dashboard host applies its normal authentication policy to these routes.

## Development

Run focused checks from the repository root:

```bash
node --check plugins/fabric-achievements/dashboard/dist/index.js
python3 -m py_compile plugins/fabric-achievements/dashboard/plugin_api.py
python3 -m unittest plugins/fabric-achievements/tests/test_achievement_engine.py -v
pytest -q tests/plugins/test_achievements_plugin.py
```

## License and provenance

MIT. Preserve this directory's `LICENSE` and the upstream attribution above
when redistributing the plugin.
