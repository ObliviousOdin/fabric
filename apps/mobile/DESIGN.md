# Fabric Mobile design contract

The mobile apps follow the canonical [Woven Operations contract](../../web/DESIGN.md)
and consume the resolved semantic tokens from
[`apps/design-system`](../design-system/README.md). This file records how the
contract maps onto SwiftUI and Jetpack Compose so the two apps stay visually
one product with the desktop and dashboard.

## Token plumbing

- **iOS** — `Fabric/DesignSystem/FabricTheme.swift`: dynamic light/dark
  colors for every semantic role, radius/target constants, and the status
  mapping. Applied globally via `.tint(FabricTheme.action)`.
- **Android** — `ui/theme/FabricTheme.kt`: full Material3 `ColorScheme`
  pair mapped from the tokens, a `FabricExtras` composition-local for the
  roles Material3 lacks (status colors, thread accents), the type scale, and
  the shape scale.

Both files carry the resolved values from
`apps/design-system/src/tokens/tokens.json`. Never hand-tune a color in the
apps; change the token source and re-derive. When the design system grows a
mobile export target, these files become generated artifacts.

## Rules the screens implement

| Contract rule | Mobile application |
| --- | --- |
| Purple = action/focus/active thread, never a wash | Global tint; the user's own chat bubble is the one solid-accent surface; steering (touching the live turn) uses `threadActive`. |
| Neutral surfaces ≥ 90% | Canvas + surface ramp everywhere else; assistant bubbles on `surfaceRaised`, technical rows on `surfaceInset`. |
| Status colors semantic, ≤ 8–12% tint | Approval = amber edge marker + dot + `warning` tint panel; agent questions = `info` tint; failures = `danger` dot + copy, never a red panel. |
| Status pairs shape + label + color | Session rows show dot + literal status word (`working`/`waiting`/…); "Waiting for approval" is spelled out. |
| Monospace only for technical values | Commands, slash output, process tails, background-task results. Chat prose stays sans. |
| Sentence case, no uppercase chrome | All labels. |
| Body 14–16, metadata ≥ 12 | Type scales in both theme files. |
| ≥ 44pt/dp touch targets | Compose `IconButton` minimum (48dp) + explicit 44pt frames on iOS composer icons. |
| Radius 8 default / 12 dialogs+bubbles / 4 chips | Shape scales in both theme files. |
| One primary action per surface | Connect (Connect), approval (Allow filled, Deny quiet), prompts (Send filled). |
| Errors carry recovery copy | Connection loss and failures state what happened and what to do next. |

## Status → color mapping (both platforms)

| Runtime status | Role | Rationale |
| --- | --- | --- |
| `working` | `threadActive` | A running turn is the live thread, not a "success". |
| `waiting` | `warning` | Blocked on a person — same amber as approvals. |
| `starting` | `info` | Transitional. |
| `idle` | `textMuted` | Neutral; absence of activity is not a status color. |

## Known gaps (tracked, not accidental)

- The woven-canvas and bracket motifs are not rendered on mobile yet;
  neutral surfaces only. Add them via the design-system assets, not ad-hoc
  drawing.
- App icons are committed for both platforms, derived from the canonical
  `apps/design-system/dist/brand` assets: iOS uses the 1024px app icon in
  `Fabric/Assets.xcassets/AppIcon.appiconset`; Android uses an adaptive icon
  (maskable mark on the canonical purple) under `app/src/main/res`. Store
  listing/marketing icons are still produced separately at packaging time.
- Compose/SwiftUI screens are review-verified against this contract but have
  not been screenshot-diffed like the dashboard (`design-qa.md` pattern).
  A device pass should capture Connect/Sessions/Chat in both themes before
  any release.
