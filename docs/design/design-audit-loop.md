# Design Audit Loop — Public Site and Documentation

Status: active operating playbook
Last updated: 2026-07-24

## Purpose

A repeatable audit loop for the public Docusaurus site (`website/`) and its
documentation content. Each cycle produces captured evidence, a ranked
findings report, scoped fixes, and a re-verification pass. Two loops
interlock:

- **Loop A — design review**: visual and UX quality of the rendered site.
- **Loop B — content audit**: accuracy, freshness, and consistency of the
  documentation, one section batch per cycle.

Run cycles on demand or per release; a full Loop B rotation should complete
once per release cycle. Any human or agent should be able to execute a cycle
from this document alone.

## Scope

In scope:

- `website/src/pages/` (index, download, ios, skills) and
  `website/src/components/{Homepage,AutomationBlueprintsCatalog}/`;
- `website/src/css/custom.css` (site theme tokens);
- hand-authored content under `website/docs/**`.

Out of scope:

- generated doc pages (`user-guide/skills/**`, the skills/reference catalogs,
  `llms*.txt`) — audit their *generators* under `website/scripts/`, never
  hand-edit generated output;
- the `web/` dashboard — a separate ownership zone with its own contract
  (`web/DESIGN.md`). It can be audited as an optional extension cycle using
  the same procedure with that contract as the reference.

Design references to audit against:

- `apps/design-system/src/tokens/tokens.json` (canonical token source) and
  `apps/design-system/README.md`;
- `website/src/css/custom.css` Infima variable ramps;
- the applicable principles of `web/DESIGN.md`: brand `#4628CC` used
  sparingly, sentence-case headings, predominantly neutral surfaces, reduced
  motion support, and 44 px minimum touch targets.

## Severity rubric

Shared by both loops, matching the `.codex-audits/` precedent and the
`impeccable-craft` skill:

- **Critical** — broken or unusable behavior, wrong information that would
  mislead a user, a brand-identity violation, or a WCAG failure that blocks
  use.
- **High** — a significant visual defect, a stale document contradicting
  current behavior, or dark-mode/responsive breakage on a primary page.
- **Medium** — inconsistency (tokens, terminology, heading case), awkward
  layout, or a missing state.
- **Low** — polish and nice-to-haves.

Exit criterion per cycle: **zero open Critical or High findings** (each one
either resolved or explicitly escalated to a human decision).

## Loop A — design review cycle

1. **Build and serve.**

   ```bash
   npm ci --prefix website
   npm run --prefix website build
   npm run --prefix website serve   # answers at http://localhost:3000/fabric/
   ```

   The `/fabric/` base path is mandatory; the server root `/` is not the
   site. Prebuild generators run automatically and fall back to committed
   data when offline — check the prebuild log so degraded content is not
   misread as a design defect.

2. **Capture evidence** into `.codex-audits/website-design-<YYYY-MM-DD>/` as
   numbered PNGs.

   - Viewports: **360×740, 768×1024, 1440×900**, each in **light and dark**.
     The site respects `prefers-color-scheme`, so color-scheme emulation is
     sufficient — no toggle clicking required.
   - Page inventory: `/fabric/` (home), `/fabric/download`, `/fabric/ios`,
     `/fabric/skills`, `/fabric/docs` (landing),
     `/fabric/getting-started/quickstart`,
     `/fabric/getting-started/installation`, `/fabric/deploy/`,
     `/fabric/user-guide/`, `/fabric/user-guide/features/overview`,
     `/fabric/user-guide/messaging/`, `/fabric/integrations/`,
     `/fabric/developer-guide/architecture`, `/fabric/reference/` — plus
     `/fabric/404.html` (fetch directly) and search (page or navbar
     dropdown), and the mobile navigation open at 360.

3. **Review each capture** against a fixed checklist:

   - Palette fidelity: rendered colors trace to `custom.css` or
     design-system tokens; brand purple only where the contract allows;
     neutral surfaces dominate.
   - Typography: sentence-case headings, font policy respected, readable
     line lengths, no orphaned or overflowing text.
   - Layout: spacing rhythm, alignment, no horizontal scroll at 360,
     imagery neither stretched nor blurry.
   - Dark-mode parity: every capture has a dark twin with no illegible or
     inverted-contrast region.
   - Accessibility: visible focus states, contrast spot checks, alt text on
     images, logical heading order, touch-target size in the mobile nav.
   - States: hover/focus on nav and CTAs, empty search, 404, reduced-motion
     behavior.

4. **Report** to `.codex-audits/website-design-<date>/audit.md`, mirroring
   `.codex-audits/kanban-team-2026-07-13/audit.md`: executive verdict →
   walkthrough → ranked findings (each with severity, page, viewport/theme,
   evidence screenshot, expected vs. actual, suggested fix) → recommended
   fix sequence → validation and evidence limits.

5. **Fix** top-ranked findings on a scoped branch (`fix/website-design-…`),
   one task → one PR, with the docs-site pre-flight before push and a PR
   HANDOFF block per `AGENT_GUARDRAILS.md` §7.4.

6. **Re-verify**: recapture affected screens into the same audit directory
   and mark each finding `resolved`, `open`, or `escalated` in the report.
   On a clean pass, append an acceptance record to `design-qa.md` in its
   existing format (comparison setup, focused evidence, iteration history,
   interaction and accessibility verification, automated verification,
   final result).

## Loop B — content audit cycle

Rotation, one batch per cycle:

| Batch | Sections |
|---|---|
| 1 | `getting-started/` (11 pages) |
| 2 | `user-guide/` top level + `secrets/` |
| 3 | `user-guide/features/` |
| 4 | `user-guide/messaging/` |
| 5 | `developer-guide/` |
| 6 | `guides/` |
| 7 | `reference/` + `deploy/` + `integrations/` + root `index.mdx` |

1. **Automated gates first** (all pre-existing; run from the repo root):

   ```bash
   python3 scripts/docs_sync.py check
   python3 scripts/docs_sync.py audit
   python3 website/scripts/generate-skill-docs.py --check
   npm run --prefix website typecheck
   npm run --prefix website build          # broken links/anchors fail the build
   python3 scripts/fabric-brand-audit.py --mode public
   python3 scripts/fabric-brand-audit.py --mode public --build-dir website/build
   npm run --prefix website lint:diagrams  # optional; requires `pip install ascii-guard`
   ```

2. **Manual per-file checklist** for the batch:

   - Accuracy: commands, flags, and paths match current `fabric_cli`
     behavior (spot-run where cheap); code fences are runnable as written.
   - Freshness: no stale versions, dead feature references, or superseded
     workflows.
   - Terminology and brand: the product is "Fabric", the CLI is `fabric`,
     state lives in `~/.fabric`; no invented `FABRIC_*` environment tokens;
     naming that violates the brand audits fails CI.
   - Style: sentence-case headings, consistent admonition use, frontmatter
     present, correct `website/sidebars.ts` placement.
   - Structure: duplication or overlap with other pages noted; orphaned
     pages (absent from the sidebar) flagged.
   - Generated-file boundary: a defect in generated pages is filed against
     the generator script and fixed by regenerating in the same PR.

3. **Report** to `content-audit.md` in the same dated `.codex-audits/`
   directory, using the shared severity rubric, findings grouped by file.

4. **Fix** the batch on a scoped branch (`fix/docs-content-…`); regenerate
   rather than hand-edit; re-run the step-1 gates; the batch exits clean.

5. **Update the rotation table** at the bottom of this document with the
   audit date and outcome.

## Cadence, roles, and guardrails

- Triggers: per release (before `docs-pages.yml` publishes), after major
  merges that `python3 scripts/docs_sync.py impact` flags as touching mapped
  contracts, or on request.
- Audit-report PRs and fix PRs are separate tasks. Rebase on `origin/main`
  before push and merge; squash merge; no self-merge.
- Commits carry the canonical repository identity with no AI-tool footers
  or trailers (`AGENT_GUARDRAILS.md` §3.3).
- Coordinate before touching `docs/documentation-contracts.json`,
  restructuring `website/sidebars.ts`, or any `.github/workflows/**` file.
- Escalate taste-level calls ("should this page exist") to a human
  maintainer per `AGENT_GUARDRAILS.md` §8.

## Deferred tooling backlog

Not implemented; if adopted, start as a local script (Footprint Ladder rung
2) and wire into CI only with shared-surface coordination.

| Gap | Candidate | Note |
|---|---|---|
| External link checking | lychee | Docusaurus only enforces internal links |
| Spell/prose lint | cspell or Vale | none exists today |
| Automated accessibility scan | axe or pa11y on `website/build` | currently manual per `design-qa.md` |
| Visual regression | image diff over `.codex-audits/` captures | currently human-eye comparison |

## Rotation state

| Batch | Last audited | Outcome |
|---|---|---|
| 1 — `getting-started/` | — | not yet run |
| 2 — `user-guide/` + `secrets/` | — | not yet run |
| 3 — `user-guide/features/` | — | not yet run |
| 4 — `user-guide/messaging/` | — | not yet run |
| 5 — `developer-guide/` | — | not yet run |
| 6 — `guides/` | — | not yet run |
| 7 — `reference/` + `deploy/` + `integrations/` | — | not yet run |
