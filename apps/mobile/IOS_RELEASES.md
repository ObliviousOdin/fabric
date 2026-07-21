# Fabric iOS TestFlight release log

This is the living, tester-facing change log for Fabric iOS. Each uploaded build
gets one entry tied to an exact merged commit. Planned builds stay clearly
marked as planned; they are never presented as shipped.

## Build ledger

| Version (build) | Date | Phase | Channel | Source | Result |
| --- | --- | --- | --- | --- | --- |
| `0.1.0 (1)` | 2026-07-20 | Development preview | Internal TestFlight | SHA not recorded at archive time | Uploaded and installed; connection/chat vertical slice works. |
| `0.1.x (2+)` | 2026-07-20 | FMB-P0 | Internal TestFlight | `00c8c2f0`; first exercised by `0.2.0 (4)` | No standalone upload; the reproducible release foundation shipped in build 4. |
| `0.2.0 (4)` | 2026-07-20 | FMB-P1 | Internal TestFlight | `6c9e034136afff841355d564a6e3b91152b34e6f` | Xcode Cloud archive/upload succeeded; processed to **Testing** and assigned to the internal `beta` group (2 members). Physical-device result pending. |

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

## FMB-P0 release foundation — verified by `0.2.0 (4)`

### Apple release-state verification (2026-07-20)

- The Xcode Cloud `Default` workflow now supplies its registered App Store
  bundle identifier through `FABRIC_IOS_BUNDLE_ID`, targets merged `main`, and
  distributes successful archives to internal TestFlight.
- Xcode Cloud build 4 archived and uploaded `0.2.0` from merged commit
  `6c9e034136afff841355d564a6e3b91152b34e6f`.
- Its successful post-clone log records build number 4 and embeds source
  revision `6c9e034136afff841355d564a6e3b91152b34e6f` before the signed archive.
- App Store Connect processed build 4 to **Testing**, validated the configured
  release bundle identifier, and assigned it to the internal `beta` group with
  2 members.
- Independent extraction of `FabricSourceRevision` from the signed archive,
  plus the physical-iPhone and internal-tester behavior checks, remains open.

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

### Release evidence

- Merged commit SHA: `6c9e034136afff841355d564a6e3b91152b34e6f`.
- Generated `FabricSourceRevision`: `6c9e034136afff841355d564a6e3b91152b34e6f`;
  independent signed-archive extraction remains pending.
- Required GitHub checks: passed on the merged SHA.
- iOS unit/release build: passed on the merged SHA.
- Physical-iPhone smoke: pending.
- Archive/upload/processing: Xcode Cloud build 4 succeeded; TestFlight status is
  **Testing**.
- Internal tester result: `beta` group assigned (2 members); install and
  behavior result pending.

## `0.2.0 (4)` — FMB-P1 conversation-first home

### Change set in build

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

### Release evidence

- Date: 2026-07-20.
- Marketing version: `0.2.0`; Xcode Cloud/TestFlight build number: `4`.
- Merged commit SHA: `6c9e034136afff841355d564a6e3b91152b34e6f`.
- Release bundle identifier: supplied through protected
  `FABRIC_IOS_BUNDLE_ID`; App Store Connect validation passed.
- Generated `FabricSourceRevision`: `6c9e034136afff841355d564a6e3b91152b34e6f`;
  independent signed-archive extraction remains pending.
- Hosted checks: Mobile clients, Public repository checks, and Fabric release
  channels passed for the merged SHA.
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
- Archive/upload result: Xcode Cloud build 4 succeeded and processed to
  **Testing**.
- TestFlight channel/group: Internal TestFlight; `beta`, 2 members. Phase-one
  What to Test notes are published.
- Tester result: pending physical installation and behavior pass.
- Rollback: development preview `0.1.0 (1)`.

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
