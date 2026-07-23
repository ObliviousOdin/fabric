# Authoring profiles

Authored source lives in `source/metadata.json` and
`source/personas/<category>.json`. Generated distributions are disposable.
Root `LICENSE`, `RIGHTS.md`, and `THIRD_PARTY_NOTICES.md` are also copied into
every generated distribution; keep upstream notices intact when adapting
collection tooling.

## Persona contract

Each persona object must use the strict schema enforced by
`tools/build_collection.py`:

- Identity: `slug`, `name`, `category`, `inspiration`, `role`, `scope`,
  `description`, `core_identity`
- Behavioral lists: `voice`, `worldview`, `operating_method`, `strengths`,
  `blind_spots`
- Interaction: `user_relationship`, `under_pressure`, `disagreement_style`,
  `humor`, `greeting_style`
- Fit and limits: `task_affinities`, `behavioral_rules`, `design_anchors`,
  `failure_mode_guards`, `avoid`

The builder rejects missing fields, unknown fields, duplicate items, invalid
slugs, thin lists, unknown categories, duplicate slugs across files, reused
routing descriptions, and duplicated operating methods. The quality floors are
five task affinities, four voice traits, four worldview principles, five
operating steps, four strengths, three blind spots, six behavioral rules, five
design anchors, four failure-mode guards, and four avoidances. Routing
descriptions and core identities must each be at least 80 characters.

`description` is the one- or two-sentence routing description that the manager
sets with `fabric profile describe` after a fresh install. It is deliberately
not emitted as `profile.yaml`: current Fabric updates copy every unprotected
top-level distribution entry, so shipping that file would overwrite a user's
later description edits.

## Writing standard

A useful profile must change working behavior, not merely vocabulary.

- State what evidence it seeks first.
- Give it a repeatable operating method.
- Explain how it behaves under pressure and disagreement.
- Give it genuine blind spots, followed by compensations that protect the
  user from those blind spots.
- Name tasks where its asymmetry helps.
- Keep fictional flavor optional and sparse.
- Preserve factual standards, tool discipline, user agency, and Fabric's
  normal completion contract.

For a fan profile, use only original behavioral prose. Do not include dialogue,
catchphrases, scene recreations, plot summaries, issue or episode text, logos,
art, actor descriptions, costume details, or signature visual trade dress.

Security-oriented and red-team profiles require especially explicit limits:
authorized user-controlled targets only; no credential theft, persistence,
evasion, destructive exploitation, exfiltration, or attacks on third parties.

## Rebuild

```bash
python3 tools/build_collection.py
python3 tools/validate_collection.py
python3 tools/build_collection.py --check
```

`--check` builds in memory/a temporary tree and fails when committed generated
outputs differ. It must not rewrite the working tree.

## Versioning

The top-level metadata version becomes each generated distribution's version.
Bump it when the generated identity, config, or skin contract changes in a way
installers should see. Do not write a test that merely freezes the current
version or number of profiles; tests should validate relationships and
behavioral invariants.

## Review checklist

- The profile is behaviorally distinct from its siblings.
- All wording is original.
- The description is useful for task routing.
- The profile selects no provider or model.
- No credential, session, memory, log, state, or personal data is present.
- No symlink or binary asset is present.
- User authority and real-world permission boundaries are explicit.
- A new session is required after install or identity-changing update.
- Build, validation, tests, and isolated CLI E2E pass.
