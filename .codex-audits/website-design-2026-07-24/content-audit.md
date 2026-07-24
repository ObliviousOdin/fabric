# Content audit — getting-started batch (Loop B, cycle 1)

Date: 2026-07-24

Scope: `website/docs/getting-started/` — 11 hand-authored pages plus
`_category_.json`, audited per `docs/design/design-audit-loop.md` (Loop B,
batch 1). Method: automated gate run, then a per-file manual review with
every load-bearing CLI command, flag, config key, path, and version claim
verified against the implementation (`fabric_cli/`, `scripts/install.sh`,
`pyproject.toml`, `nix/`, `.github/workflows/desktop-packaging.yml`).

## Executive verdict

The batch is in strong shape: across 60+ spot-checked behavioral claims in
the six core pages and the four platform guides, only two findings rise to
High — a wrong Linux desktop artifact filename pattern in `installation.md`
(it contradicts both CI and `platform-support.md`), and a container-CLI
retry behavior documented in `nix-setup.md` that does not exist in the code.
No Critical findings. The remaining findings are consistency issues
(Title Case headings on four pages, an orphaned page missing from the
sidebar) and low-severity polish. `jetson-nano.md`, `termux.md`, and
`low-memory.md` are fully accurate against the implementation.

## Automated gates

All run from the repo root on this branch; all passed.

| Gate | Result |
|---|---|
| `python3 scripts/docs_sync.py check` | pass — generated documentation current |
| `python3 scripts/docs_sync.py audit` | pass — source and skill metadata audit |
| `python3 website/scripts/generate-skill-docs.py --check` | pass — 196 skills, docs current |
| `npm run --prefix website typecheck` | pass |
| `npm run --prefix website build` | pass — broken links/anchors enforced by `onBrokenLinks/Anchors: throw` |
| `python3 scripts/fabric-brand-audit.py --mode public` | pass |
| `python3 scripts/fabric-brand-audit.py --mode public --build-dir website/build` | pass — rendered site |
| `npm run --prefix website lint:diagrams` | pass — 401 files, 0 errors (requires `pip install ascii-guard`) |

Note: the skills index used the committed local fallback during the build
(762 skills) because the deployed index is not reachable from this
environment; that is expected offline behavior, not a defect.

## Ranked findings

### High

1. **`installation.md` documents wrong Linux desktop artifact names.**
   `installation.md:79` says the manifest-derived filenames are
   `Fabric-<version>-linux-x64.{AppImage,deb,rpm}`. The packaging pipeline
   produces `linux-x86_64` for AppImage/rpm and `linux-amd64` for deb
   (`.github/workflows/desktop-packaging.yml:124-125`,
   `apps/desktop/scripts/desktop-brand.mjs:244`,
   `apps/desktop/electron/release-channel.test.ts:40`), and
   `platform-support.md:81` already documents the correct names — the two
   pages contradict each other. A user scripting a download against the
   documented names gets a 404.
   Fix: align `installation.md` with the CI-verified names.
   Status: **resolved** — corrected in this cycle.

2. **`nix-setup.md` documents container-CLI retry behavior that does not
   exist.** `nix-setup.md:151` claims the CLI "retries briefly (5s with a
   spinner for interactive use, 10s silently for scripts)" when the
   container is not running, and the troubleshooting table
   (`nix-setup.md:1015`) tells users the CLI "retries automatically".
   `_exec_in_container` (`fabric_cli/main.py:1210-1301`) performs a single
   `inspect` probe, optionally one sudo re-probe, then `os.execvp` — no
   retry loop, no spinner, no interactive/script distinction. A user
   following the troubleshooting row waits for a retry that never happens.
   Fix: describe the actual single-probe, fail-fast behavior and tell the
   user to re-run the command after the container starts.
   Status: **resolved** — corrected in this cycle.

### Medium

3. **`repair.md` is orphaned from the sidebar.** `website/sidebars.ts:10-19`
   lists every other getting-started page but omits
   `getting-started/repair`; the page is reachable only through inbound
   links (`index.mdx:101`, `reference/index.md:73`, `installation.md:174`,
   `quickstart.md:221`, `guides/local-ollama-setup.md:578`).
   Fix: add `'getting-started/repair'` after `'getting-started/updating'`.
   Status: **resolved** — added in this cycle.

4. **`repair.md` frontmatter title and H1 disagree.** Frontmatter says
   "Repair and diagnostics" (`repair.md:3`); the H1 says "Diagnose and
   Repair Fabric" (`repair.md:7`), and inbound link text uses both variants.
   Fix: use one sentence-case name for both.
   Status: **resolved** — unified as "Repair and diagnostics".

5. **`raspberry-pi.md` mislabels `fabric gateway start` as a foreground
   run.** `raspberry-pi.md:159` recommends `fabric gateway install`
   "rather than a foreground `fabric gateway start`", but `gateway start`
   starts the installed background service
   (`fabric_cli/subcommands/gateway.py:103`); the foreground command is
   `fabric gateway run` (`fabric_cli/gateway.py:655`).
   Status: **resolved** — corrected to `fabric gateway run`.

6. **`nix-setup.md` documents the wrong dev-mode bypass.**
   `nix-setup.md:152` says a source checkout can bypass container routing
   with `uv run python -m fabric_cli.main`, but the routing hook lives in
   `fabric_cli.main.main()` and fires on `$FABRIC_HOME/.container-mode`
   regardless of entrypoint; the real bypass is the `--dev` flag
   (`fabric_cli/main.py:14977`).
   Status: **resolved** — corrected to describe `--dev`.

7. **Title Case headings on four pages** (`platform-support.md`,
   `updating.md`, `learning-path.md`, `nix-setup.md`) against the
   sentence-case convention used by their peers and the design contract.
   Status: **open** — mechanical but broad (nix-setup alone has ~20
   headings, and heading changes alter anchor slugs that other pages may
   link to); deferred to a scoped follow-up fix PR per the playbook's
   one-task-one-PR rule.

8. **`nix-setup.md` SOUL.md guidance is internally contradictory.** The
   Documents section (`nix-setup.md:424`) correctly warns that a
   `documents`-installed `SOUL.md` lands in the workspace and does not
   replace the persona file, but both directory diagrams
   (`nix-setup.md:590`, `:917`) label `workspace/SOUL.md` as if that were
   intended placement, and `:615` suggests scripting installation into it.
   Status: **open** — needs an author decision on the intended example
   document name; deferred to the follow-up fix PR.

### Low

9. `:::caution` used instead of the repo-standard `:::warning`
   (`installation.md:12`, `updating.md:46`; repo-wide `:::warning` 117 vs
   `:::caution` 30). Status: open.
10. Inert `sidebar_position: 3` frontmatter duplicated across six
    getting-started pages, and `_category_.json` is vestigial — the sidebar
    is fully hand-authored (`website/sidebars.ts`), so both are dead config
    that invites fixing ordering in the wrong place. Status: open.
11. Duplicated install blocks: the curl one-liner and verification steps
    repeat across `installation.md`/`quickstart.md`, and the lean-install
    block is near-verbatim in `raspberry-pi.md:84-93` and
    `low-memory.md:52-64`. Drift risk; consider one canonical location.
    Status: open.
12. `termux.md` internal inconsistency: `nodejs-lts` at `:161` vs `nodejs`
    at `:213` and in the installer (`install.sh:834`); "Fabric now ships"
    temporal wording at `:51`; the same install command repeated five
    times. Status: open.
13. `platform-support.md`: dangling `fabric version` code block at the end
    of the page (`:103-105`) and mixed relative/absolute link styles.
    Status: open.
14. `nix-setup.md`: managed-mode signal described as "an internal process
    marker" when it is the `FABRIC_MANAGED` environment variable
    (`nix/nixosModules.nix:862`, `fabric_cli/config.py:327`); several
    lowercase "fabric" product references in prose. Status: open.
15. `learning-path.md`: the RL-training use case links only to an external
    repository plus generic pages — no Fabric-specific doc to follow.
    Status: open.
16. `quickstart.md:3,7`: "Fabric Quickstart" → "Fabric quickstart" for
    sentence case. Status: open.

### Refuted during verification

- A reported dead in-page anchor `#container-mode` in
  `nix-setup.md:1014` is **not** a defect: the heading `### Container Mode`
  at `nix-setup.md:921` generates exactly that anchor, and the build's
  `onBrokenAnchors: "throw"` gate passes.

## Pages verified clean on accuracy

`quickstart.md` (every command, flag, and config key checked),
`jetson-nano.md`, `termux.md`, `low-memory.md` — Low-severity findings only.
`repair.md` is exceptionally well aligned with the code (its log-file table
is more complete than the CLI help). No invented `FABRIC_*` environment
variables anywhere in the batch (`FABRIC_HOME` is real); terminology is
consistent (product "Fabric", binary `fabric`, state `~/.fabric`).

## Validation and evidence limits

- Accuracy verification was spot-check based: every load-bearing claim
  (commands, flags, filenames, config keys, ports, version floors) was
  checked against source; not every prose sentence was independently
  verified.
- Commands were verified by reading parsers and implementations, not by
  executing installs on the documented platforms (no Pi/Jetson/Termux/NixOS
  hardware in this environment).
- The rendered-site brand audit ran against a build whose skills index came
  from the committed local fallback.
