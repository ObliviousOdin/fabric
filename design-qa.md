# Design QA — Live Work and Team Pages

Date: 2026-07-13

> Historical QA record for the first Work/Team delivery. The current canonical
> Workspace/Admin visual contract is [Woven Operations](web/DESIGN.md); later
> screenshots and token decisions supersede the colors and shell described here.

## Comparison setup

- Source visual truth: `/tmp/fabric-design-qa-20260713/reference.png`
- Final implementation: `/tmp/fabric-design-qa-20260713/kanban-final-desktop.png`
- Combined comparison: `/tmp/fabric-design-qa-20260713/reference-vs-implementation.png`
- Desktop viewport: 1440 × 1024
- Mobile viewport: 390 × 844
- Theme: Fabric Light
- State: populated isolated QA board, Graph selected, one review-ready plan step selected, one parallel agent run active, inspector open

The final side-by-side comparison preserves the approved composition: a dark indigo work rail, calm light canvas, graph-first hierarchy, clear Goal → Plan step → Agent run / Result relationships, live status, and a focused inspector. The implementation intentionally uses Fabric's blue primary action and flatter token system instead of the reference's orange action and warmer decorative treatment.

## Focused evidence

- Mobile review drawer: `/tmp/fabric-design-qa-20260713/kanban-final-mobile.png`
- Team workspace: `/tmp/fabric-design-qa-20260713/team-final-desktop.png`
- Empty graph state: `/tmp/fabric-design-qa-20260713/kanban-empty-desktop.png`

## Iteration history

1. Baseline audit found a flat multi-column board with weak hierarchy, undersized controls, inconsistent typography, and no visible relationship between goals, tasks, or parallel agents.
2. The first implementation added Board / Graph / Outline, deterministic lineage, live status, recent activity, a contextual inspector, complete work statuses, Fabric themes, task-oriented navigation, and Team Pages.
3. Browser QA then found duplicate host headers, horizontal graph clipping, sibling lineage emphasis, a clipped mobile inspector, missing Result rows in Outline, and non-library glyph controls. Those issues were corrected and re-captured.
4. Final review found a worker/reviewer overlap risk, hidden Graph/Outline errors, a filtered review no-op, missing keyboard focus on search, incomplete tab/node keyboard contracts, misleading tree semantics for the multi-parent graph, a duplicate main landmark, and inconsistent hidden-workspace layout. Each issue was fixed before this final result.

## Interaction and accessibility verification

- Board / Graph / Outline switcher supports click plus Arrow, Home, and End navigation with one roving tab stop.
- Graph and Outline expose labelled groups of interactive nodes—not a false hierarchical tree—and support directional navigation, Home/End, Enter/Space, and Escape.
- Review action clears conflicting local filters, selects the visible review item, and opens the action callout.
- Pause updates freezes visual refresh only and clearly changes to Resume updates.
- Search has a visible 2px focus outline.
- Mobile has no document-level horizontal overflow and every visible interactive target measures at least 44px high.
- Mobile inspector is fixed below the app bar and fills the 390px viewport width without clipping.
- Team Pages exposes one main landmark, keyboard page tabs, and safe declarative content blocks.
- No application-origin console errors were observed. One browser-extension message-channel warning was excluded as non-application noise.

## Automated verification

- Web typecheck and production build passed.
- Web tests: 264 passed.
- Kanban and Team Pages focused plugin tests: 122 passed.
- Dashboard theme/manifest tests: 17 passed.
- Public Fabric brand audit passed.
- Full repository lint still reports existing issues outside this change; the changed workbench behavior passed syntax, type, build, browser, and targeted integration checks.

final result: passed

---

# Design QA — iOS Conversation-First Home

Date: 2026-07-20

## Comparison setup

- Source visual truth: `<CODEX_GENERATED_IMAGES>/019f8090-688a-72d1-9756-cf712c83657f/exec-da678f5f-150c-43b9-8992-86050247d6bb.png`
  (`72b45e4543390307a3783bd039a2e8870a5bc5d8450beb088329fb61adf5a566`)
- Final implementation capture:
  `<TMPDIR>/fabric-home-final-running-light-stable.png`
- Normalized implementation:
  `<CODEX_VISUALIZATIONS>/2026/07/20/019f8090-688a-72d1-9756-cf712c83657f/phase1-home/conversation-home-running-normalized-final.png`
  (`b7c6831b05628ac667379b5a9ee89cada3cd6265cfc90e837d12db1a18f268ff`)
- Combined source/implementation comparison:
  `<CODEX_VISUALIZATIONS>/2026/07/20/019f8090-688a-72d1-9756-cf712c83657f/phase1-home/conversation-home-comparison-final.png`
  (`d6c0bcc0efd0e44c65c7bd2f516e418a77f6b4aa639ed8e57a313f4e8047ef1e`)
- Source viewport: 853 x 1844.
- Simulator viewport: 1206 x 2622; comparison crop 1206 x 2607,
  normalized to 853 x 1844.
- Themes: Fabric Light and Fabric Dark.
- Primary comparison state: connected, one running conversation, two recent
  conversations, empty outcome composer.

The final comparison preserves the approved conversation-first hierarchy:
canonical Fabric identity, one large outcome composer, one primary action, one
prominent live conversation, and a concise recent briefing. Intentional product
differences are a solid-purple action instead of a gradient, a neutral 3:1
composer boundary with purple reserved for focus, sentence-case status copy,
no decorative watermark or non-functional expand affordance, native SF Symbols,
and a disabled Start goal action until an objective exists.

## Focused evidence

- Header and composer comparison:
  `<CODEX_VISUALIZATIONS>/2026/07/20/019f8090-688a-72d1-9756-cf712c83657f/phase1-home/conversation-home-focus-header-composer-final.png`
  (`e5166584e0d04a3f5291ff1ec2469897c9cf448b692bbb92c9874369106b34ce`)
- Live and recent briefing comparison:
  `<CODEX_VISUALIZATIONS>/2026/07/20/019f8090-688a-72d1-9756-cf712c83657f/phase1-home/conversation-home-focus-work-briefing-final.png`
  (`ae0434b62619519f77e44162fe03712732dc441caf69ceb40269389de2c43ef3`)
- Final state matrix:
  `<CODEX_VISUALIZATIONS>/2026/07/20/019f8090-688a-72d1-9756-cf712c83657f/phase1-home/conversation-home-state-matrix-final.png`
  (`22d6d01834a37cf8b2700ff4d7625af6cfe143d80b8eb373ced9eec6ec100e15`)

## Iteration history

1. The baseline implementation still presented a stock session list and a
   stale private-label identity. The first comparison also found that a Home
   objective could be lost across launch failure, offline copy did not match
   the real connection state, the composer boundary lacked sufficient neutral
   contrast, the enabled action state had no proof capture, Dynamic Type could
   truncate important titles, and chevron/action icon details diverged from the
   selected direction.
2. The first native Home iteration restored the canonical mark and
   conversation-first hierarchy, preserved the objective through unknown
   create outcomes, added truthful offline/live-status copy, raised the neutral
   control contrast, added a typed-enabled fixture, removed title truncation at
   accessibility sizes, and aligned the visible disclosure/action language.
   The expanded matrix then exposed a P1 overlap between the offline recovery
   banner and Home, plus P2 gaps in dark-mark treatment, status priority, and a
   transiently dimmed comparison capture.
3. The final iteration moved recovery chrome into normal layout flow, made the
   banner adapt vertically at accessibility sizes, prioritized offline truth
   over optional live-status copy, added VoiceOver state-change announcements,
   kept accessibility-size titles unbounded and scrollable, used the canonical
   on-dark mark geometry/gradient, and recaptured the stable post-animation
   running state. The full and focused source/implementation comparisons were
   regenerated and inspected together after those fixes.

## State, interaction, and accessibility verification

- The matrix passes running light, running dark, typed/enabled, loading, empty,
  error, offline, AX XXXL running, AX XXXL offline, and small-device states.
- AX content reflows without clipping and remains vertically scrollable.
- Offline recovery stays above Home in normal layout flow and does not overlap
  the header, composer, or recent briefing.
- All visible controls meet the 44-point minimum target contract.
- Start goal is disabled for an empty objective and enabled for a typed one.
- The neutral composer boundary exceeds 3:1 against its surface in both themes;
  the stronger purple boundary appears only on focus.
- Headers and conversation titles retain their reading order and do not use
  artificial line limits at accessibility sizes.
- VoiceOver receives explicit announcements for offline, load-error, and
  optional-live-status-unavailable transitions.
- No decorative placeholder, fake asset, or non-functional control was added.

## Final review

The final independent design review reported no remaining P0, P1, or P2
findings.

final result: passed

---

# Design QA — Desktop Agent Live View

Date: 2026-07-16

## Comparison setup

- The approved exploratory source visuals and final comparison captures were
  session-only review artifacts; they are intentionally not distributed in the
  repository. This record documents the completed interaction and visual checks
  without depending on retired screenshot binaries.
- Theme: Fabric Light
- State: real Browser frame from Example Domain plus a real Computer Use capture of Calculator

The source and implementation were placed in the same combined comparison images and inspected together. The implementation preserves the approved docked-right-rail and compact always-on-top PiP hierarchy while using Fabric's existing titlebar controls, flatter surfaces, spacing, and color tokens. No clipping, control overlap, broken radius, or horizontal overflow was observed.

## Interaction verification

- Browser and Computer Use both open in the docked Live View without creating a second chat surface.
- One Pop out button moves the same session into a resizable always-on-top PiP; Dock returns it without restarting the work or losing the action history.
- Pause and Resume update both the docked view and PiP state.
- Browser requests one bounded viewport frame through the existing CDP supervisor and otherwise retains the latest visual-tool frame.
- Computer Use truthfully displays the latest desktop screenshot returned by an action rather than implying a continuous stream.
- Failed Computer Use actions remain visible without presenting an old image as a new successful capture.
- Hidden, minimized, paused, and closed views stop requesting or forwarding Browser frames.
- PiP load failure, renderer failure, readiness timeout, owner reload, and owner crash all return or close the view safely.
- No application-origin console errors were observed during live Electron QA.

## Performance contract

- Live View does not add model tools, prompt text, context tokens, or extra model calls.
- Browser preview frames live in an isolated atom, so the desktop route and transcript do not rerender for each capture.
- Browser capture is visible-only, pause-aware, server-gated to at most two starts per second for each browser session, sequential, and size-limited; frame requests never hold the model-action lock during CDP I/O or share the chat/model event socket.
- While visible and unpaused, Computer Use reuses at most one accepted, bounded screenshot from an action result, so it does not add a second capture loop.
- The desktop retains at most 24 session views and four PiP windows; image and IPC payloads are bounded and sanitized.

## Automated verification

- Desktop production build and TypeScript checks passed.
- Focused Desktop Live View renderer tests: 53 passed.
- Desktop platform/Electron tests: 340 passed, 1 skipped.
- Browser and gateway lifecycle/status/cleanup tests: 56 passed.
- Changed Python files passed Ruff; changed Live View TypeScript files passed Prettier and ESLint with no errors.
- Documentation generation, audit, impact-contract checks, and 13 documentation-sync tests passed.
- Website documentation production build passed.

final result: passed
