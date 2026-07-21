# Fabric iOS TestFlight release log

This is the living, tester-facing change log for Fabric iOS. Each uploaded build
gets one entry tied to an exact merged commit. Planned builds stay clearly
marked as planned; they are never presented as shipped.

## Build ledger

| Version (build) | Date | Phase | Channel | Source | Result |
| --- | --- | --- | --- | --- | --- |
| `0.1.0 (1)` | 2026-07-20 | Development preview | Internal TestFlight | SHA not recorded at archive time | Uploaded and installed; connection/chat vertical slice works. |
| `0.1.x (2+)` | Planned | FMB-P0 | Internal TestFlight | `00c8c2f0` foundation; archive SHA pending | Reproducible release foundation merged; release-environment archive/upload still pending. |
| `0.2.0 (pending)` | Planned | FMB-P1 | Internal TestFlight | Validated branch; merged `main` SHA pending | Conversation-first Home candidate; local release gates pass, device/archive/upload pending. |

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

### Apple release-state audit (2026-07-20)

- App Store Connect confirms that `0.1.0 (1)` is installed by an internal
  tester and is currently waiting for beta review.
- The active Xcode Cloud `Default` workflow targets `main`, the `Fabric`
  scheme, and `apps/mobile/ios/FabricMobile.xcodeproj`.
- Its first two builds failed before custom scripts ran because the generated
  project was absent from the checkout. FMB-P0 now commits a generic,
  CI-synchronized Xcode project and Info.plist bootstrap so Xcode Cloud can
  discover the project before applying protected release overrides.
- The workflow still needs its protected release bundle environment value and
  TestFlight internal distribution enabled before the merged-SHA build runs.

### Change set

- Generate release projects without mutating tracked `project.yml`.
- Apply the protected App Store bundle identifier only to a temporary spec.
- Map Xcode Cloud's `CI_BUILD_NUMBER` (or explicit local release number) into
  `CFBundleVersion`, rejecting missing/invalid release values at the release
  gate.
- Require a clean tracked checkout and embed its exact Git commit in the
  packaged Info.plist as `FabricSourceRevision`.
- Run the same generator in GitHub CI and derive metadata assertions from the
  source manifest.

### Required evidence before upload

- Merged commit SHA: pending.
- Packaged `FabricSourceRevision` (must match merged SHA): pending.
- Required GitHub checks: pending.
- iOS unit/release build: pending on final PR SHA.
- Physical-iPhone smoke: pending.
- Archive/upload/processing: pending.
- Internal tester result: pending.

## Planned upload — FMB-P1 conversation-first home

### Change set under test

- Replace the connected stock session list with the approved conversation-first
  home: canonical Fabric identity, a large outcome composer, one solid-purple
  **Start goal** action, one prioritized live conversation, and at most two
  recent conversations.
- Start a goal by creating a normal conversation and attempting its initial
  prompt at most once. Preserve the objective until that attempt. If creation
  has an unknown outcome, return to conversations with the goal still on Home
  instead of retrying the non-idempotent create; only a known durable session
  key may offer an explicit resume retry.
  Resume live and recent conversations through their
  server-issued stable session keys; keep the complete session browser one tap
  away through **See all**.
- Preserve new-chat, switch-server, disconnect, reconnect, and pull-to-refresh
  controls without returning to a server-admin-first hierarchy.
- Add deterministic Debug fixtures for running, typed/enabled, empty, loading,
  error, and offline states in both simulator appearance modes.

This home is deliberately session-backed. The gateway does not yet advertise
the complete Durable Work contract, so the native goal portfolio is not shown
as production authority and no Job state is inferred from event hints.

### Required evidence before upload

- Marketing version: `0.2.0` confirmed in the unsigned Release package.
- Merged commit SHA, packaged `FabricSourceRevision`, and required hosted checks:
  pending until merge.
- Same-viewport source/implementation screenshot comparison: passed. See the
  iOS Home section in [`design-qa.md`](../../design-qa.md); final comparison
  SHA-256 `d6c0bcc0efd0e44c65c7bd2f516e418a77f6b4aa639ed8e57a313f4e8047ef1e`.
- Light/dark/running/typed-enabled/loading/empty/error/offline, AX XXXL, and
  small-device fixture review: passed; state-matrix SHA-256
  `22d6d01834a37cf8b2700ff4d7625af6cfe143d80b8eb373ced9eec6ec100e15`.
- Local branch gates: 12/12 project-generation tests and 80/80 native iOS tests
  passed; generator idempotence, unsigned Release build, packaged metadata,
  privacy manifest, public release audit, and final code/design reviews passed.
- Dynamic Type reflow, accessibility reading order and announcements, contrast,
  and 44-point target review: passed locally with no remaining P0-P2 findings;
  the physical VoiceOver gesture smoke remains part of the device gate.
- Physical-iPhone Start goal, progress resume, Recent, reconnect, and QR pass:
  pending.
- Archive/upload/processing/internal tester result: pending.
- Rollback: latest verified `0.1.x` build, once uploaded; until then use
  development preview `0.1.0 (1)`.

## Entry template

Copy this section for every upload:

```markdown
## `<version> (<build>)` — <phase name>

- Date:
- Merged commit SHA:
- Packaged `FabricSourceRevision`:
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
