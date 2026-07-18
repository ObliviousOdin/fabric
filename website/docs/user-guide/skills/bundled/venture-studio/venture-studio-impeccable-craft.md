---
title: "Impeccable Craft"
sidebar_label: "Impeccable Craft"
description: "Polish work to an impeccable, ship-ready standard — systematic passes over UI states, microcopy, accessibility, responsiveness, performance, and error handli..."
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Impeccable Craft

Polish work to an impeccable, ship-ready standard — systematic passes over UI states, microcopy, accessibility, responsiveness, performance, and error handling with concrete checklists. Use before launches, demos, and releases, or when the user says something feels rough, unpolished, or 'not quite right'.

## Skill metadata

| | |
|---|---|
| Source | Bundled (installed by default) |
| Path | `skills/venture-studio/impeccable-craft` |
| Version | `1.0.0` |
| Author | Fabric |
| License | MIT |
| Platforms | linux, macos, windows |
| Tags | `polish`, `quality`, `craft`, `checklist`, `accessibility`, `microcopy` |
| Related skills | [`product-taste`](/user-guide/skills/bundled/venture-studio/venture-studio-product-taste), [`design`](/user-guide/skills/bundled/creative/creative-design), [`webapp-development`](/user-guide/skills/bundled/venture-studio/venture-studio-webapp-development) |

## Reference: full SKILL.md

:::info
The following is the complete skill definition that Fabric loads when this skill is triggered. This is what the agent sees as instructions when the skill is active.
:::

# Impeccable Craft

Use this skill when a product surface already works and now has to feel finished — before a launch, demo, or release, or whenever the user says something feels rough, cheap, or "not quite right" without being able to name why. Craft is not a vibe; it is six ordered audit passes over the same surface, each hunting one category of unfinishedness, each with an explicit pass/fail bar and evidence.

Do not use this to design a new surface or rework layout and hierarchy — load `design` with skill_view. Do not use it to decide what to build or whether a flow's behavior is right — load `product-taste` with skill_view. Do not use it to stand up the application itself — load `webapp-development` with skill_view. This skill assumes the thing exists and mostly works; it turns "works" into "would proudly demo it".

## Workflow

1. **Scope.** Ask the user two questions: which screens and flows are in scope, and what the bar is — a five-minute demo (polish the demo path ruthlessly, note the rest), or a real release (everything in scope must pass). List the flows back and get agreement before auditing.
2. **Stand up observation.** Run the app locally, open it in the browser tool, and confirm you can capture screenshots at three widths: 360, 768, and 1440 CSS pixels. If you cannot see the rendered product, stop and fix that first — code-only polish is guesswork.
3. **Run the six passes in order.** The order matters: state and copy problems change what the later passes look at. During each pass, log findings — do not fix inline, or you will lose audit coverage. Use one line per finding:
   `- [P3][high] Checkout > Pay button — no pressed state; double-click submits twice -> disable on click`
4. **Fix in severity order.** Batch fixes per pass, highest severity first. Prefer the smallest change that clears the bar; anything that turns into redesign gets filed as a finding for the `design` skill instead.
5. **Re-verify.** Re-run the checklist items your fixes touched, with fresh screenshots. A fix without a fresh observation is a claim, not a fix.
6. **Report.** Fill in the ship-readiness template at the end of this skill and deliver it with the evidence paths.

| Pass | Hunts for | Primary instruments |
|---|---|---|
| 1. States | Views that only survive the happy path | Fixtures, network throttling, code search |
| 2. Microcopy | Inconsistent, unhelpful, or robotic language | String extraction, corpus read-through |
| 3. Interaction | Keyboard gaps, dead feedback, double-submits | Keyboard-only walkthrough, touch emulation |
| 4. Accessibility | Contrast, semantics, screen-reader flow | axe/Lighthouse, manual DOM audit |
| 5. Performance | Layout shift, unmasked waits, jank | Cold reload, Lighthouse, slow-network profile |
| 6. Final details | Misalignment, spacing drift, punctuation | Zoomed-out screenshots, full string sweep |

## Pass 1 — States

Every data-bearing view meets reality in more shapes than the one it was built with. Find the views with code search — `search_files("fetch|useQuery|useSWR|axios", path="src/")` — then force each of six shapes per view: empty (zero items, brand-new account), loading (throttle to Slow 3G in browser devtools), error (stop the API or return 500), partial (null or missing fields in the fixture), overflow (hundreds of items), and long content (40-character unbroken words, very long names and emails). Screenshot each shape.

Pass bar:

- [ ] Empty states say what belongs here and offer the first action — never a blank region or bare "No data"
- [ ] Loading placeholders match the layout they are replaced by; no flash of empty-then-content
- [ ] Errors are visible where the user is looking, written in human language, and preserve any input already entered
- [ ] Partial data degrades field by field; the strings "undefined", "null", "NaN", and "Invalid Date" never render
- [ ] Overflow scrolls or truncates deliberately inside its container; nothing bleeds or pushes siblings around
- [ ] Long unbroken strings wrap or ellipsize; the layout survives three times the expected content length

## Pass 2 — Microcopy

Language problems are corpus problems: they are invisible screen by screen and glaring in aggregate. Extract every user-visible string — locale files if they exist, otherwise `search_files` over component text, button labels, aria-labels, toasts, and error messages — and dump them into one scratch file. Read it top to bottom in a single sitting before judging anything.

Pass bar:

- [ ] One term per concept everywhere — never "remove" on one screen and "delete" on the next
- [ ] Every error states what happened and what to do next, in the user's vocabulary; no raw codes or stack traces
- [ ] Buttons are verbs that name the outcome ("Save changes", "Send invite") — not "OK", "Submit", or "Yes"
- [ ] One case discipline per element class (sentence case or title case), held without exception
- [ ] No placeholder copy, developer jargon, or user-blaming phrasing ("you entered an invalid…") survives
- [ ] Empty, loading, and error strings sound like the product, not like the framework defaults

## Pass 3 — Interaction

Put the mouse away. Walk every in-scope flow keyboard-only, then repeat in the browser's touch-device emulation. Then get hostile: click primary actions twice fast, and drive the flow on a Slow 3G profile to see what the user sees between click and result.

Pass bar:

- [ ] Every interactive element shows a visible focus indicator, and focus order follows visual order
- [ ] Complete keyboard paths: Escape closes overlays, Enter submits, focus is trapped in modals and returned on close
- [ ] Touch targets are at least 44x44 px, and no affordance exists only on hover
- [ ] Every action slower than ~100 ms acknowledges the press immediately — pressed state, in-button spinner, or optimistic update
- [ ] Double-submit is impossible: the control disables on click or the action is idempotent
- [ ] Destructive actions confirm or offer undo; neither is silently absent

## Pass 4 — Accessibility

Run the automated layer first, then do the judgment work machines cannot. `terminal("npx @axe-core/cli http://localhost:PORT --exit")` per route, or Lighthouse's accessibility category. Then manually: check contrast of the actual rendered colors (including text over images and disabled-looking-but-enabled controls), read the heading outline, and walk the DOM in source order as a screen reader would — does the page make sense as a linear narration?

Pass bar:

- [ ] Text contrast is at least 4.5:1 (3:1 for large text), verified on rendered pixels, not design tokens
- [ ] Nothing communicates by color alone — state changes also change text, icon, or shape
- [ ] Every input has a programmatically associated label; validation errors are announced, not merely colored red
- [ ] Headings form a real outline — one h1, no skipped levels — and landmark regions are present
- [ ] Icon-only buttons have accessible names; purely decorative images carry empty alt text
- [ ] Zero automated-checker violations, or each remaining one documented with an explicit accepted reason

## Pass 5 — Performance (perceived)

Users experience sequencing, not benchmarks. Hard-reload with cache disabled and watch what paints first and what jumps. Run `terminal("npx lighthouse http://localhost:PORT --only-categories=performance --quiet")` and read CLS and LCP, then interact with the page while data is still loading — that is where jank lives.

Pass bar:

- [ ] No layout shift after first paint: images, embeds, and async regions reserve their dimensions (CLS under 0.1)
- [ ] Something meaningful renders quickly; skeletons match the final layout so their replacement is seamless
- [ ] No spinner appears for waits under ~300 ms, and no wait over ~1 s goes unmasked or unexplained
- [ ] Route transitions never flash a blank frame; the previous view holds until the next can paint
- [ ] Revisits and back-navigation feel instant — unchanged data does not visibly refetch
- [ ] Animations stick to transform and opacity and hold frame rate; nothing animates layout properties

## Pass 6 — Final details

This pass is pure eyes. Take full-page screenshots of every in-scope screen at all three widths, then view them at 50% zoom — misalignment and spacing drift pop when small. Sweep every string one final time for punctuation, and check the frame around the product, not just the product.

Pass bar:

- [ ] Edges that should align, align to the pixel; every spacing value comes from one scale, no one-off magic numbers
- [ ] One type ramp — no orphan font sizes or weights that appear exactly once
- [ ] Punctuation is deliberate: no terminal periods on labels, typographic quotes and apostrophes, real ellipses and dashes
- [ ] Icons come from one family at one stroke weight and one optical size
- [ ] The frame is finished: favicon, per-page titles, social preview metadata, and a designed 404 page
- [ ] Numbers behave: locale-aware separators, tabular figures in tables, one date and time format everywhere

## Ship-readiness report

Deliver this as the final artifact, with evidence paths that actually exist:

```markdown
# Ship-readiness report: {surface}

**Date:** {date}  **Scope:** {flows audited}  **Bar:** demo | release
**Verdict:** SHIP | SHIP WITH NOTES | NOT YET

| Pass | Result | Findings | Fixed | Open |
|---|---|---|---|---|
| States | pass/fail | n | n | n |
| Microcopy | pass/fail | n | n | n |
| Interaction | pass/fail | n | n | n |
| Accessibility | pass/fail | n | n | n |
| Performance | pass/fail | n | n | n |
| Final details | pass/fail | n | n | n |

## Open findings (blocking)
- [Pn][severity] location — problem -> proposed fix

## Accepted imperfections (non-blocking, with reasons)
- [Pn] location — imperfection — why it is acceptable for this bar

## Evidence
- Screenshots: {directory path}
- Checker output: axe violations before -> after; Lighthouse CLS/LCP before -> after
```

"SHIP WITH NOTES" means every open finding is listed and the user explicitly accepts them. Never issue a bare "SHIP" while blocking findings are open.

## Pitfalls

- **Fixing while auditing.** The moment you start editing mid-pass, coverage collapses — you polish one corner and never see the rest. Finish the pass, then fix.
- **Polishing only the demo path.** The user will click the one thing you did not check. Empty and error states on secondary screens are where "unpolished" reputations are made.
- **Auditing at one viewport.** A surface that is impeccable at 1440 px and broken at 360 px fails. All three widths, every pass that has a visual component.
- **Treating the checker score as accessibility.** Automated tools catch roughly a third of real issues. The heading outline, focus order, and linear-narration checks are manual, always.
- **Fixing strings one at a time.** Per-string edits create the very inconsistency this skill exists to remove. Fix terminology corpus-wide with a search across the codebase, then re-read the corpus.
- **Scope-creeping into redesign.** "This layout is wrong" is a real finding but not this skill's job. Log it, keep polishing, and hand it to `design` afterward.
- **Skeletons that lie.** A loading placeholder shaped differently from the final content causes the exact layout shift it was meant to prevent. Match dimensions, not just presence.
- **Claiming a pass without evidence.** Every "pass" in the report must be backed by a screenshot, a checker output, or a walkthrough you actually performed this session — not by reading the code and believing it.
- **Skipping the final re-verify.** Fixes from passes 4-6 routinely regress passes 1-3 (a relabeled button breaks a test fixture, a contrast fix changes a hover state). Re-run the touched checklist items before writing the verdict.
