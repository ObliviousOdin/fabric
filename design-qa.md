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

# Design QA — Desktop Agent Live View

Date: 2026-07-16

## Comparison setup

- The approved exploratory source visuals were session-only artifacts and are
  unavailable outside that Product Design session. This record does not claim
  repo-only reproduction of the source comparison; the final implementation
  captures below are the portable release evidence.
- Final Browser docked implementation: `website/static/img/product/fabric-desktop-live-view-browser.png`
- Final Browser PiP implementation: `website/static/img/product/fabric-desktop-live-view-browser-pip.png`
- Final Computer Use docked state: `website/static/img/product/fabric-desktop-live-view-computer-use.png`
- Final Computer Use PiP state: `website/static/img/product/fabric-desktop-live-view-computer-use-pip.png`
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
