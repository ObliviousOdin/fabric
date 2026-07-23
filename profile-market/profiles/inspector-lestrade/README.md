# GENERATED FILE - DO NOT EDIT. Edit source/ and rebuild.
# Inspector Lestrade

A pragmatic case-management profile for organizing evidence, coordinating specialists, and moving investigations from interesting clues to accountable decisions.

Category: **Baker Street Bureau** (`baker-street-bureau`)

## Best at

- Investigation project management
- Evidence registers
- Compliance case workflows
- Cross-team incident reviews
- Closure and escalation criteria

## Install

From the collection root:

```bash
python3 manage.py install inspector-lestrade --alias
```

Fresh profiles are isolated. Configure this profile's model and authentication,
then start a new session:

```bash
fabric -p inspector-lestrade setup
fabric -p inspector-lestrade chat
```

The distribution does not select a provider or model and ships no credentials, memories, sessions, cron jobs, MCP servers, or user state.

## Rights

Inspired only by public-domain Sherlock Holmes material and general Victorian investigative traditions. Later adaptations, likenesses, dialogue, and visual designs are excluded.

The licenses covering this collection's code and original prose do not grant rights in third-party names or fictional properties. Those remain the property of their respective rights holders. No affiliation, sponsorship, or endorsement is claimed.

The complete rights boundary, license grants, and upstream attribution travel
with this profile in `RIGHTS.md`, `LICENSE`, and `THIRD_PARTY_NOTICES.md`.
