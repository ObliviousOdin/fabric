# Mithuru iOS visual QA

Captured from the deterministic `-fabric-ui-fixture mithuru` simulator surface on 2026-07-24.

## Evidence

- `ios-onboarding-dark.png` — iPhone 17 Pro simulator, dark appearance, normal text size.
- `ios-onboarding-ax-xxxl.png` — iPhone 17 Pro simulator, light appearance, Accessibility XXXL.

## Checks

- Language controls remain readable in light and dark appearances.
- Dark-mode option text uses the semantic `FabricTheme.text` role after the initial tinted-label contrast issue was found and repaired.
- Accessibility XXXL content remains inside a vertical scroll view; language options are reachable and the English option advances to the next one-question onboarding step in XCUITest.
- No overlap with the Dynamic Island or safe areas was observed.

## Release boundaries

These simulator captures do not replace the physical-device VoiceOver, microphone, Apple Speech, increased-contrast, and native Sinhala/Tamil review gates documented in `apps/mobile/README.md` and `apps/mobile/ios/VOICE.md`.
