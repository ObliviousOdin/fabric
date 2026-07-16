---
title: Documentation System
description: How Fabric keeps code-owned reference data and human-authored guidance synchronized.
---

Fabric's documentation has two complementary layers:

- **Generated reference** is derived deterministically from code-owned registries and
  committed manifests.
- **Narrative guidance** explains behavior, workflows, constraints, and migration
  advice. Humans still own the judgment and examples in these pages.

This is intentionally a build-time system. It does not add model tools, change the
agent prompt, call an LLM, or run in a Fabric conversation, so it has no effect on
model latency or prompt-cache performance.

## Canonical sources

| Public contract | Canonical repository source | Generated output |
| --- | --- | --- |
| Top-level CLI commands | Static argparse registrations and `fabric_cli/main.py::_BUILTIN_SUBCOMMANDS` | Runtime surface catalog |
| Slash commands | `fabric_cli/commands.py::COMMAND_REGISTRY` | Runtime surface catalog |
| Product surfaces and providers | `scripts/build_capability_evidence.py` and its static authorities | Runtime surface catalog |
| Messaging platforms | `gateway/config.py::Platform` and platform manifests | Runtime surface catalog |
| Toolsets | `toolsets.py::TOOLSETS` | Runtime surface catalog |
| Dashboard routes | `web/src/app/routes.tsx::APP_ROUTES` | Runtime surface catalog |
| Dashboard extensions | `plugins/**/dashboard/manifest.json` | Runtime surface catalog |
| Skills catalog | First-party `SKILL.md` files | Skills Hub JSON and generated skill pages |
| Automation blueprints | `metadata.fabric.blueprint` in first-party skills | Blueprint catalog JSON |

The generated [Runtime Surface Catalog](../reference/runtime-surfaces) is also
published as machine-readable
[`runtime-surfaces.json`](https://obliviousodin.github.io/fabric/api/runtime-surfaces.json).
It represents what the repository ships, not what a particular user's profile has
installed, configured, enabled, or activated.

## Contributor workflow

After changing a canonical registry or manifest, regenerate the committed catalog:

```bash
python scripts/docs_sync.py generate
python website/scripts/generate-skill-docs.py
```

Before opening a pull request, run the same deterministic gates as CI:

```bash
python scripts/docs_sync.py check
python website/scripts/generate-skill-docs.py --check
python scripts/docs_sync.py audit
python -m unittest tests.scripts.test_docs_sync
npm run --prefix website build
```

`npm run --prefix website build` invokes the generator during prebuild when a
supported Python 3.11–3.13 interpreter is available, so a configured local docs
build sees current registry data. The prebuild log names any generator it must
skip. CI always provides supported Python and runs `check` first, before prebuild
can refresh anything, which catches a contributor who forgot to commit generated
changes.

The skill-doc generator also detects pages whose source `SKILL.md` was removed.
Generation deletes only pages carrying its generated marker and refuses to delete a
hand-authored file inside the generated tree.

## Narrative documentation impact

Generated tables answer “what is declared now,” but they cannot explain why a
behavior changed or how users should adapt. `docs/documentation-contracts.json`
maps high-signal code paths to the narrative pages that own those contracts.

On pull requests, the impact check compares the base and head commits. If mapped
code changes and none of its narrative pages change, CI fails with the relevant
contract ID and documentation paths.

For a non-behavioral refactor, use a scoped declaration in the pull request body:

```text
Docs-impact: none [command-registry] — Refactored parsing only; command names, arguments, and dispatch behavior are unchanged.
```

Use one declaration per affected contract (or list multiple IDs in the brackets).
The reason must be specific; template placeholders and bare “N/A” declarations do
not bypass the check. This gives maintainers an auditable alternative to empty
documentation churn.

## Legacy identity audit

The source audit extracts every `FABRIC_*` and `HERMES_*` token from authored
Markdown/MDX and requires an exact backing occurrence in non-document repository
source. This distinguishes live compatibility identifiers from stale examples.

Rare wildcard families can be recorded in the explicit exemption ledger in
`docs/documentation-contracts.json`; each exemption requires a concrete reason.
Do not use the ledger to preserve a removed command or variable.

First-party skills must author UI metadata under `metadata.fabric`. The runtime may
continue reading `metadata.hermes` from user and third-party skills for backward
compatibility, but the repository audit rejects that legacy namespace in shipped
`SKILL.md` frontmatter.

## Extending the system

When adding a new code-owned public catalog:

1. Keep its canonical data in the runtime registry or manifest that already owns
   the behavior.
2. Extend `scripts/docs_sync.py` with static parsing. Do not import providers,
   plugins, tools, or user configuration.
3. Add the generated facts to `website/static/api/runtime-surfaces.json` and, when
   useful to readers, the generated reference page.
4. Add a focused test and a documentation-impact contract for the narrative owner.
5. Regenerate and commit the artifacts.

Generated reference reduces copying; it does not replace product documentation.
Behavior changes still need an authored explanation, migration note, and examples
where users would otherwise be surprised.
