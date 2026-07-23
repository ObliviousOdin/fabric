# Fabric Profile Market

Fabric Profile Market is a standalone collection of 64 installable behavioral
profiles arranged across ten shelves. It is built on Fabric's native profile
distribution format: every persona installs as an isolated Fabric profile with
its own `SOUL.md`, provider-neutral config, terminal skin, and complete local
rights/license/third-party notices so the profile directory remains
redistributable.

This collection does not add a model tool, patch Fabric's agent loop, or swap a
persona inside an existing conversation. Install or update a profile, then
start a new session so the identity becomes part of that session's stable
prompt prefix.

The structure is inspired by
[`teknium1/hermes-star-trek-profiles`](https://github.com/teknium1/hermes-star-trek-profiles),
adapted for Fabric's current CLI and profile-distribution contract.

## Shelves

| Category | Profiles | Kind | What it emphasizes |
|---|---:|---|---|
| `dc-universe` | 8 | Unofficial fan profiles | Investigation, principled leadership, diplomacy, systems thinking |
| `marvel-universe` | 8 | Unofficial fan profiles | Prototyping, team alignment, strategy, scenario planning |
| `mythic-council` | 6 | Public-domain inspiration | Strategy, craft, communication, fairness, long projects |
| `round-table` | 6 | Public-domain inspiration | Facilitation, forecasting, diplomacy, execution, red teaming |
| `baker-street-bureau` | 6 | Public-domain inspiration | Observation, hypotheses, chronology, evidence, argument |
| `gothic-cabinet` | 6 | Public-domain inspiration | Responsible innovation, coercion detection, conflicts, incident response |
| `galactic-expedition` | 6 | Original | Mission leadership, science, engineering, care, security, diplomacy |
| `arcane-academy` | 6 | Original | Architecture, debugging, research, safeguards, experimentation, delegation |
| `neon-circuit` | 6 | Original | Authorized defensive security, integrations, source intelligence, privacy |
| `creator-studio` | 6 | Original | Creative direction, story, production, continuity, audience research |

The DC and Marvel shelves are unofficial fan-made behavioral adaptations.
They contain original prose and no logos, comic art, film stills, actor
likenesses, costume art, scripts, copied dialogue, catchphrases, audio, or
video. Read [RIGHTS.md](RIGHTS.md) before redistributing those shelves.

## Browse

```bash
python3 manage.py list
python3 manage.py list --category dc-universe
python3 manage.py search investigation
python3 manage.py show batman
```

`catalog.json`, `ROSTER.md`, and everything under `profiles/` are generated.
The canonical authored data lives under `source/`.

## Install

Keep this checkout at a stable path. Fabric currently records the absolute
local distribution path for updates.

```bash
# One profile
python3 manage.py install batman --alias

# Several profiles
python3 manage.py install batman oracle mister-terrific --alias

# A complete shelf
python3 manage.py install --category creator-studio --alias

# Everything
python3 manage.py install --all --alias
```

The manager delegates each install to Fabric's native command:

```bash
fabric profile install ./profiles/<slug> --name <slug> -y
```

It does not write directly into `FABRIC_HOME`. The optional `--alias` flag asks
Fabric to create the normal shell wrapper for each profile.

Start a profile with either form:

```bash
batman chat
fabric -p batman chat
```

Fresh Fabric profiles are isolated and do not inherit the default profile's
model or credentials. Configure each newly installed profile before its first
chat (the alias form works too):

```bash
fabric -p batman setup
# or: batman setup
```

All distributions leave `model` empty and ship no credentials. Provider
selection, authentication, sessions, memories, and user data remain
profile-local and under your control.

## Update

Review and update this checkout through git first, then apply the selected
profile payloads:

```bash
git pull --ff-only
python3 manage.py update batman oracle
python3 manage.py update --category creator-studio
python3 manage.py update --all
```

Fabric preserves profile memories, sessions, credentials, and local
`config.yaml` changes during a normal update. Pass `--force-config` only when
you intentionally want to replace the entire local `config.yaml` with this
pack's empty model plus skin selection. That removes local model/provider
choices from the file and may require running profile setup again.

Do not move or delete the checkout after installation: current Fabric releases
record its absolute path as the update source. Reinstall with `--force` from a
new stable location if the checkout has moved. The manager refuses to update a
same-named profile recorded from any other path. Review the target before a
forced reinstall: `install --force` replaces that profile's `SOUL.md`,
`config.yaml`, and skins. Memories, sessions, credentials, and its routing
description remain, but local model/provider config is lost.

## Optional management skill

The collection includes a zero-tool skill at `skills/profile-market/SKILL.md`.
It teaches a Fabric agent how to browse this checkout and invoke the same
manager commands. It does not inject a new tool or silently install profiles.

For local development, copy it into the default profile's skill directory (or
run the equivalent copy inside a named profile's own Fabric home):

```bash
cp -R skills/profile-market ~/.fabric/skills/profile-market
```

After publishing this collection as its own repository, it can be installed
through Fabric's GitHub skill source instead.

## Build and verify

```bash
python3 tools/build_collection.py
python3 tools/build_collection.py --check
python3 tools/validate_collection.py
pytest -q tests
python3 tools/e2e_collection.py --fabric-bin fabric
```

The end-to-end check uses a temporary `FABRIC_HOME`, installs every generated
distribution through the real Fabric CLI, and verifies that an update replaces
distribution-owned identity files while preserving local config and memory.

## Design principles

1. **Behavior over cosplay.** A profile changes how Fabric frames and solves
   work; it does not turn every reply into lore or roleplay.
2. **Useful asymmetry.** Profiles tackling the same task should emphasize
   different evidence, tradeoffs, and collaboration styles.
3. **User authority remains real.** Fictional status, intelligence, magic, or
   power never grants credentials, access, or command over the user.
4. **Provider neutral.** No profile chooses a model, ships credentials, or
   assumes a paid service.
5. **Original expression only.** No copied dialogue, scripts, artwork, music,
   or franchise assets.
6. **Safe limits survive the theme.** Blind spots add texture but never excuse
   deception, recklessness, coercion, unauthorized access, or false expertise.
7. **Generated means generated.** Edit source data and rebuild; never hand-edit
   `profiles/`, `catalog.json`, or `ROSTER.md`.

## Repository layout

```text
profile-market/
├── source/
│   ├── metadata.json
│   └── personas/*.json
├── profiles/                 # generated native distributions
├── skills/profile-market/    # optional management skill
├── catalog.json              # generated machine-readable catalog
├── ROSTER.md                 # generated human-readable catalog
├── manage.py
└── tools/
    ├── build_collection.py
    ├── validate_collection.py
    └── e2e_collection.py
```

See [AUTHORING.md](AUTHORING.md) to add or revise profiles,
[SECURITY.md](SECURITY.md) for the trust model, and [NOTICE.md](NOTICE.md) for
attribution. Upstream code notices are preserved in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
