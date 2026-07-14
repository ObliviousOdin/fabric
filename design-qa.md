# Design QA — Live Work and Team Pages

Date: 2026-07-13

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
