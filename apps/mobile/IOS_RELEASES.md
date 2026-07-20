# Fabric iOS TestFlight release log

This is the living, tester-facing change log for Fabric iOS. Each uploaded build
gets one entry tied to an exact merged commit. Planned builds stay clearly
marked as planned; they are never presented as shipped.

## Build ledger

| Version (build) | Date | Phase | Channel | Source | Result |
| --- | --- | --- | --- | --- | --- |
| `0.1.0 (1)` | 2026-07-20 | Development preview | Internal TestFlight | SHA not recorded at archive time | Uploaded and installed; connection/chat vertical slice works. |
| `0.1.x (2+)` | Planned | FMB-P0 | Internal TestFlight | Must be merged `main` SHA | Reproducible release foundation. |
| `0.2.x` | Planned | FMB-P1 | Internal TestFlight | Must be merged `main` SHA | Selected premium home/onboarding direction. |

## `0.1.0 (1)` — development preview

### Shipped

- Saved Fabric servers with QR or manual pairing.
- Token and password/TOTP connection paths.
- Session list, create, resume, streaming chat, steering, interruption, slash
  commands, background work, approval/question response, process control, and
  read-only computer screen view.
- Keychain-backed token storage and gateway capability negotiation.

### Verified

- The build was archived locally, uploaded successfully to App Store Connect,
  assigned to the internal beta group, installed from TestFlight, and connected
  successfully through an HTTPS tailnet endpoint.

### Known gaps

- Native screens are mostly stock SwiftUI `List` and `Form` compositions; the
  larger Woven product hierarchy and branded component layer are not present.
- The archive's exact source SHA was not recorded and release bundle/build
  values were applied in the generated local project, so this build is not a
  reproducibility baseline.
- Plain remote HTTP endpoints are rejected by App Transport Security; production
  pairing requires HTTPS.
- OAuth system-browser sign-in, push notifications, mobile attachments, voice,
  rich artifacts, and the goal/mission-control model are not shipped.

## Next upload — FMB-P0

### Change set

- Generate release projects without mutating tracked `project.yml`.
- Apply the protected App Store bundle identifier only to a temporary spec.
- Map Xcode Cloud's `CI_BUILD_NUMBER` (or explicit local release number) into
  `CFBundleVersion`, rejecting missing/invalid release values at the release
  gate.
- Run the same generator in GitHub CI and derive metadata assertions from the
  source manifest.

### Required evidence before upload

- Merged commit SHA: pending.
- Required GitHub checks: pending.
- iOS unit/release build: pending on final PR SHA.
- Physical-iPhone smoke: pending.
- Archive/upload/processing: pending.
- Internal tester result: pending.

## Entry template

Copy this section for every upload:

```markdown
## `<version> (<build>)` — <phase name>

- Date:
- Merged commit SHA:
- TestFlight channel/group:
- What changed:
- What to test:
- Automated checks:
- Physical-device checks:
- Archive/upload result:
- Tester result:
- Known gaps:
- Rollback build or commit:
```
