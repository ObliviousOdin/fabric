# Website design review — public Docusaurus site (Loop A, cycle 1)

Date: 2026-07-24

Scope: the public site (`website/`) — marketing pages (`website/src/pages/`:
home, download, ios, skills), the docs shell and hub/landing pages, and
representative long-form doc pages. Method: a production build served
locally, full-page screenshots at 360×740 / 768×1024 / 1440×900 in light
and dark (94 captures), reviewed against `web/DESIGN.md` principles,
`website/src/css/custom.css` token ramps, and
`apps/design-system/src/tokens/tokens.json` (brand `#4628CC`).

## Executive verdict

The site's editorial system — hero eyebrow + serif display heading, offset
"woven" card shadows, dark ledger bands — is strong and consistent on the
homepage, docs landing, and reference hub, with good dark-mode parity and no
horizontal overflow at 360. The defects cluster in three places: (1) one
CSS rule that shattered the user-guide "reliable first session" steps into
unreadable word fragments at every viewport; (2) the Skills Hub page, which
diverges from the design system (external font import, hardcoded
dark-only accent colors that fail light-mode contrast, private-use-area
glyphs); and (3) the collapsed navbar search control at the 768–996px
breakpoint. Two secondary landing pages (iOS, and to a lesser degree
integrations/messaging) predate the current design system and read as an
earlier generation.

Two of three review passes completed; the long-form doc-content pass
(quickstart, installation, features-overview, architecture) did not run —
see Validation limits. This cycle fixed all three Critical/High items that
are localized and low-risk (UG1, K1, S1); the larger Skills contrast rework
(K2) and the Medium set are recorded as open for a scoped follow-up fix PR,
per the playbook's audit→fix separation.

## Walkthrough

1. **Homepage — good.** Hero, ledger band, surface list, model-route band,
   and install section are consistent across all widths with correct dark
   parity. Two issues: the section headed "three ways to work" shows only
   two product cards (H1), and at 360/768 the two product screenshots
   captured as black rectangles (H2, likely a lazy-load race — the images
   loaded at 1440).
2. **Docs landing — cleanest page in the set.** Consistent 3×2 card grid,
   correct 360 stacking, full dark parity. The primary install one-liner is
   visually truncated at `…install.sh |` with `bash` hidden behind
   horizontal scroll (DL1).
3. **User-guide hub — Critical defect (UG1).** The "A reliable first
   session" ordered list rendered as a 34px-wide column of 2–6 character
   fragments ("Run [fabric model] / and / conf / igur / e …") at every
   viewport and theme, with inline `code` stretched into full-width bars.
4. **Skills Hub — the highest-risk page.** External Google Fonts import
   (K1), light-theme contrast failures on all accent stats/pills (K2),
   private-use-area glyphs rendering as tofu boxes (K3), off-ramp accent
   color. The local 762-skill fallback data itself renders fine.
5. **iOS page — off the design system (I1).** Bare Infima defaults (bold
   sans H1, generic centered column); every sibling nav page uses the
   editorial hero pattern. Maintainer-facing copy is shown to the public
   (I2).
6. **Download page — degraded state lays out gracefully** but surfaces a raw
   `Error: HTTP 401 Failed to fetch` string (D1) and its sole CTA is ~35px
   tall, under the 44px target (D2). (Data unavailability itself is
   environmental — external fetches are blocked here.)
7. **Messaging / integrations / deploy hubs — Title-Case headings and
   mermaid diagram issues.** Diagrams render with unthemed mid-gray
   subgraphs in dark mode, are illegible at 360, and on deploy an edge label
   overprints a subgraph title (MG1–3, IN1–2, DP1).
8. **Navbar search — broken at 768–996px (S1).** The collapsed 48px circular
   search button has the "ctrl K" shortcut hint overflowing it, overprinting
   the magnifier, on every page in both themes. Correct at 360 and 1440.

## Ranked findings

Status legend: **resolved** (fixed + re-verified this cycle) · **open**
(recorded for a scoped follow-up fix PR) · **escalated** (needs a human
product/design decision).

### Critical

1. **UG1 — user-guide steps list shattered into word fragments.**
   `website/src/css/custom.css` `.docs-hub-steps li` was `display:grid;
   grid-template-columns:34px 1fr`, so every inline child of each `<li>`
   (the `<strong>`, text nodes, and `<code>`) became its own grid item and
   wrapped in a 34px track. Evidence: `01-user-guide-steps-shatter-360.png`.
   Fix: `display:block` with an absolutely-positioned `::before` counter.
   **Status: resolved** — re-verified in `02-user-guide-steps-fixed-360.png`.

2. **K1 — Skills Hub imports Google Fonts / uses off-policy typefaces.**
   `website/src/pages/skills/styles.module.css:1` did
   `@import url("https://fonts.googleapis.com/…DM Sans…JetBrains Mono…")`
   and set DM Sans as the page family — violating the system-font policy in
   `web/DESIGN.md` and adding a render-blocking external request the rest of
   the site deliberately avoids. Fix: import removed; both faces mapped to
   the site variables `--ifm-font-family-base` / `--ifm-font-family-monospace`.
   **Status: resolved** — build clean; page renders in system stacks.

### High

3. **S1 — collapsed navbar search hint overflows at 768–996px.** The
   `@easyops-cn/docusaurus-search-local` keyboard hint stayed visible while
   the input was collapsed to the 48px icon, overflowing the circle on every
   page in both themes. Evidence: `03-navbar-search-768-broken.png`. Fix:
   hide `[class*="searchHintContainer"]` unless the container is
   `:focus-within`, inside the existing `@media (max-width:996px)` block.
   **Status: resolved** — re-verified in `04-navbar-search-768-fixed.png`.

4. **K2 — Skills Hub light-theme contrast failures.**
   `website/src/pages/skills/index.tsx` hardcodes dark-theme accent colors
   (amber `#fbbf24`, green `#4ade80`, blue `#60a5fa`, violet `#a78bfa`) for
   stat numbers, member chips, source pills, and badges with no light-theme
   variant. On the light paper background these measure ~1.5–2.5:1 —
   below the 3:1 large-text floor — and several are interactive controls.
   Fix requires per-theme color pairs sourced from the token ramps across
   ~a dozen elements. Evidence: `05-skills-light-contrast.png`.
   **Status: open** — deferred to a scoped follow-up fix PR (too broad to
   land safely under this cycle's constraints; not a one-line change).

### Medium (recorded for follow-up)

- **H1** — homepage "three ways to work" heading vs two product cards
  (`website/src/components/Homepage/index.tsx`): fix copy or add the third
  card.
- **H2** — homepage product screenshots render as black voids at 360/768;
  `loading="lazy"` + a `#0b0a0f` placeholder makes any slow load a stark
  black box. Consider eager-loading the two near-top images.
- **D1** — download degraded-state notice concatenates raw error strings
  (`website/src/pages/download.tsx`, `website/scripts/latest-desktop-release.mjs`);
  render a human sentence, keep the technical detail out.
- **D2** — download degraded-state CTA is ~35px tall; add `button--lg` /
  min-height to meet the 44px target.
- **I1** — iOS page uses bare Infima instead of the site's hero pattern
  (`website/src/pages/ios.tsx`).
- **K3** — Skills Hub renders private-use-area codepoints (`\u{f179}` Apple
  FA glyph, `\u{F8FF}`) that show as tofu on non-Apple platforms
  (`website/src/pages/skills/index.tsx`); use real emoji/SVG.
- **S2** — dark-mode admonitions are unevenly themed: `.alert--info` is the
  custom violet, but tip/danger/note/warning keep stock Docusaurus
  green/red/gray. Extend the dark overrides in `custom.css`.
- **DL1** — docs-landing install one-liner truncated behind horizontal
  scroll (`website/docs/index.mdx`); wrap the command.
- **MG1 / IN1** — Title-Case headings on the messaging and integrations
  hubs vs the sentence-case standard.
- **MG2 / MG3 / DP1** — mermaid diagrams: unthemed mid-gray subgraphs in
  dark, illegible at 360 (downscaled instead of scroll), and a deploy edge
  label overprinting a subgraph title. Set mermaid `themeVariables` in
  `docusaurus.config.ts` and let `.theme-mermaid` scroll at natural size on
  small screens; restructure the two flowcharts.
- **IN2** — integrations/messaging hubs lack the docs-hub card system used
  by docs-landing/user-guide/reference; they read as an earlier design
  generation.

### Low (recorded for follow-up)

Metadata type below the 12px floor (breadcrumbs, footer, kickers); widowed
card at 768 on the user-guide "pick a surface" grid; breadcrumb reads
"Using Fabric › Using Fabric" (give the index a distinct `sidebar_label`);
emoji used as interface glyphs in tables; download "updates stay aligned"
cool-gray surface on warm paper; iOS default cyan info alert in light mode;
skills `installHint` dark overlay in light theme; Windows platform pill
lowercase/icon-less; several Title-Case headings in curated skill-stack
content; skills loading copy says "88k+ skills" while the build ships 762.

### Escalated (human decision required)

- **Uppercase tracked labels** (sidebar categories, eyebrows, breadcrumbs,
  table headers) appear throughout the editorial shell. `web/DESIGN.md`
  scopes uppercase display copy out of the *product* surfaces but is written
  for Workspace/Admin, not the marketing/docs site. If the docs shell's
  uppercase treatment is an intentional editorial choice, it should be
  recorded as an explicit exception; otherwise it is a systematic deviation.
  This is a taste-level call for a human maintainer (guardrails §8).
- **404 route** — the captured `/fabric/404` screenshots were byte-identical
  to the homepage, suggesting unknown paths may render homepage content
  rather than a dedicated 404. Needs a human to confirm intended behavior
  (Docusaurus ships a `404.html`; the SPA fallback may be serving `/`).

## Recommended fix sequence

1. **Done this cycle:** UG1 (steps grid), K1 (font import), S1 (search hint)
   — the Critical/High items that are localized and low-risk.
2. **Next fix PR (Skills Hub):** K2 contrast (per-theme token-sourced color
   pairs), K3 glyphs, and the skills-page Lows — they share one file and one
   theme-adaptation approach.
3. **Editorial/content PR:** Title-Case headings (MG1/IN1), DL1 truncation,
   H1 copy — cheap markdown/copy edits.
4. **Diagram PR:** mermaid theming + responsive scroll (MG2/MG3/DP1) via
   `docusaurus.config.ts` + two flowchart rewrites.
5. **Page-parity PR:** bring iOS (I1) and the integrations/messaging hubs
   (IN2) onto the editorial system.
6. **Escalations:** resolve the uppercase-label decision and the 404 route
   with a maintainer before acting.

## Validation and evidence limits

- Built and served the production site locally
  (`http://localhost:3000/fabric/`); reviewed 94 full-page captures across 3
  viewports × 2 themes plus mobile-nav-open and empty-search states.
- The Skills Hub and Download pages ran with offline data fallbacks
  (external fetches blocked in this environment); data unavailability was
  treated as environmental, but the *rendering* of the degraded states was
  reviewed and produced real findings (D1, D2).
- One of three planned review passes — the long-form doc-content pages
  (quickstart, installation, features-overview, developer-guide/architecture)
  — did not complete. Those pages have **not** been visually reviewed this
  cycle; a follow-up cycle should cover them.
- This was not an automated a11y audit (no axe/Lighthouse/contrast-tooling
  run); contrast figures for K2 are eyeball/sample estimates flagged for
  verification during the fix.
- Resolved items (UG1, K1, S1) were re-verified by rebuild + targeted
  re-capture; K2 and all Medium/Low items are unverified beyond the initial
  capture.

## Screenshot index

- `01-user-guide-steps-shatter-360.png` — UG1 before (Critical).
- `02-user-guide-steps-fixed-360.png` — UG1 after (resolved).
- `03-navbar-search-768-broken.png` — S1 before (High).
- `04-navbar-search-768-fixed.png` — S1 after (resolved).
- `05-skills-light-contrast.png` — K2 light-theme contrast (High, open).
- `06-skills-dark.png` — Skills Hub dark (native theme, for contrast reference).
- `07-download-degraded.png` — D1/D2 degraded-state rendering (Medium).
- `08-ios-bare-infima.png` — I1 off-design-system page (Medium).
