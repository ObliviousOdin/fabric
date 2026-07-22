# Fabric iOS TestFlight release log

This is the living, tester-facing change log for Fabric iOS. Each uploaded build
gets one entry tied to an exact merged commit when provenance has been captured;
on-device observations without that evidence are explicitly labeled. Planned
builds stay clearly marked as planned; they are never presented as shipped.

## Build ledger

| Version (build) | Date | Phase | Channel | Source | Result |
| --- | --- | --- | --- | --- | --- |
| `0.1.0 (1)` | 2026-07-20 | Development preview | Internal TestFlight | SHA not recorded at archive time | Uploaded and installed; connection/chat vertical slice works. |
| `0.1.x (2+)` | 2026-07-20 | FMB-P0 | Internal TestFlight | `00c8c2f0`; first exercised by `0.2.0 (4)` | No standalone upload; the reproducible release foundation first shipped in build 4. |
| `0.2.0 (4)` | 2026-07-20 | FMB-P1 | Internal TestFlight | `6c9e034136afff841355d564a6e3b91152b34e6f` | Xcode Cloud archive/upload succeeded; processed to **Testing** and assigned to the internal `beta` group (2 members). Physical-device result pending. |
| `0.2.0 (5)` | 2026-07-20 | FMB-P1 repeat | Internal TestFlight | `6c9e034136afff841355d564a6e3b91152b34e6f` | Manual Xcode Cloud rebuild succeeded in 5 minutes; archive and internal-TestFlight post-action passed, build processed to **Testing**, `beta` remained assigned (2 members), and phase-one tester notes were published. Physical-device result pending. |
| `0.2.0 (6)` | 2026-07-20 | FMB-P1 pairing reliability | Internal TestFlight | `9651091ac45e34124184bdf1cf54a37e149c27e2` | Code-push Xcode Cloud build succeeded in 5 minutes; archive and internal-TestFlight post-action passed, build processed to **Testing**, `beta` was assigned (2 members), and pairing-specific tester notes were published. Physical-device result pending. |
| `0.2.0 (15)` | Observed 2026-07-21 | Installed baseline | Internal TestFlight | On-device metadata observed; `c5343180` is a history-based inference, not archive provenance | Installed on the physical iPhone with the protected release bundle identifier; source linkage and behavior smoke remain unverified. |
| `0.2.1 (pending)` | 2026-07-21 | FMB-P1 local candidate | Intended internal TestFlight | Candidate branch; merged `main` SHA pending | Robust product experience implemented locally; exact-head/device/archive/upload gates remain. |

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

## FMB-P0 release foundation — verified by `0.2.0 (4)`, `(5)`, and `(6)`

### Apple release-state verification

- On 2026-07-20, Xcode Cloud build 4 archived and uploaded `0.2.0` from merged
  commit `6c9e034136afff841355d564a6e3b91152b34e6f`. Its successful post-clone log
  records build number 4 and embeds that source revision before the signed
  archive.
- App Store Connect processed build 4 to **Testing**, validated the configured
  release bundle identifier, and assigned it to the internal `beta` group with
  2 members.
- A manual rebuild from the same immutable source produced build 5. Its archive
  and internal-TestFlight post-action both succeeded, and App Store Connect
  processed it to **Testing** for the same `beta` group. This repeat proves the
  workflow can issue a new build number without changing the source revision.
- Merging the reviewed pairing-reliability slice as
  `9651091ac45e34124184bdf1cf54a37e149c27e2` triggered build 6 from a code push
  to `main`. Its archive and internal-TestFlight post-action both succeeded,
  and App Store Connect processed the new source to **Testing** for the same
  `beta` group.
- A 2026-07-21 release audit confirms that the active Xcode Cloud `Default`
  workflow targets merged `main`, the `Fabric` scheme, and
  `apps/mobile/ios/FabricMobile.xcodeproj`; it supplies the protected release
  bundle identifier through `FABRIC_IOS_BUNDLE_ID`, and successful
  archives use the internal-TestFlight `beta` post-action.
- A 2026-07-21 local signing/profile audit associates the release bundle with
  the configured release signing team. Changing the bundle or signing team
  requires a fresh signing and workflow audit before upload.
- Independent extraction of `FabricSourceRevision` from a signed archive, plus
  the historical builds' physical-iPhone behavior checks, remains open.

### Change set

- Generate release projects without mutating tracked `project.yml`.
- Apply the protected App Store bundle identifier only to a temporary spec.
- Map Xcode Cloud's `CI_BUILD_NUMBER` (or explicit local release number) into
  `CFBundleVersion`, rejecting missing/invalid release values at the release
  gate.
- Require a clean tracked checkout, reject ordinary or ignored untracked inputs
  beneath the recursive app source root, and embed the exact Git commit in the
  packaged Info.plist as `FabricSourceRevision`.
- Run the same generator in GitHub CI and derive metadata assertions from the
  source manifest.

### Release evidence

- Merged commit SHA first exercised by the workflow:
  `6c9e034136afff841355d564a6e3b91152b34e6f`.
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
  key may offer an explicit resume retry. Resume live and recent conversations
  through their server-issued stable session keys; keep the complete session
  browser one tap away through **See all**.
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

## `0.2.0 (5)` — reproducibility repeat

Build 5 intentionally contains the same app source and behavior as build 4. It
is a release-path repeat, not a feature increment.

### Release evidence

- Date: 2026-07-20.
- Marketing version: `0.2.0`; Xcode Cloud/TestFlight build number: `5`.
- Merged commit SHA: `6c9e034136afff841355d564a6e3b91152b34e6f`.
- Start condition: manual `Default` workflow build of `main`.
- Toolchain: Xcode 26.6 (17F113) on macOS Tahoe 26.5.1 (25F80).
- Archive action: succeeded; Xcode Cloud duration 5 minutes after 9 seconds
  queued.
- TestFlight internal-testing post-action: succeeded.
- TestFlight result: processed to **Testing**, expires in 90 days, and assigned
  to the internal `beta` group (2 members).
- Phase-one What to Test notes: published.
- Physical-iPhone install and behavior result: pending.
- Rollback: `0.2.0 (4)` or development preview `0.1.0 (1)`.

## `0.2.0 (6)` — QR pairing reliability

Build 6 is the first TestFlight candidate containing the merged QR/pairing
reliability slice from PR #71. It deliberately does not contain the pending
visual onboarding redesign.

### Change set in build

- Emit pairing QR codes with a camera-scannable quiet zone.
- Route camera scans and native pairing links through the same fail-closed
  classifier.
- Keep machine-issued tokens out of observable SwiftUI state and persist them
  through the Keychain boundary.
- Reject concurrent duplicate pairing for the same normalized endpoint with
  explicit feedback, then release the permit on every success or failure path.
- Preserve a saved username during gated re-pair while clearing password and
  authenticator-code state.
- Keep a failed network handshake recoverable through **Retry connection**
  using the saved credential, without copying the token back into form state.
- Continue to reject unsupported secure enrollment without retaining or
  displaying its opaque handle.

### Release evidence

- Date: 2026-07-20.
- Marketing version: `0.2.0`; Xcode Cloud/TestFlight build number: `6`.
- Merged commit SHA: `9651091ac45e34124184bdf1cf54a37e149c27e2`.
- Start condition: code push to `main` after PR #71 squash-merged.
- Xcode Cloud build: `11fbaa93-6428-4669-915d-63344e045263`, `Default`
  workflow.
- Toolchain: Xcode 26.6 (17F113) on macOS Tahoe 26.5.1 (25F80).
- Archive action: succeeded; Xcode Cloud duration 5 minutes after 9 seconds
  queued.
- TestFlight internal-testing post-action: succeeded.
- TestFlight result: processed to **Testing**, expires in 90 days, and assigned
  to the internal `beta` group (2 members).
- Pairing-specific What to Test notes: published.
- Verification before merge: 19 Python pairing tests, 10 focused native pairing
  tests plus 4 saved-gateway boundary tests, 91/91 full native iOS tests,
  unsigned Release build, 12/12 project-generation checks, public release
  audit, and independent follow-up review with no findings.
- Hosted PR checks: all required mobile, public-repository, and release-channel
  checks passed on the reviewed head before merge.
- Independent signed-archive extraction of `FabricSourceRevision`: pending.
- Physical-iPhone QR recognition, duplicate-entry, offline retry, gated re-pair,
  rejection, and conversation regression pass: pending.
- Known gap: the selected visual onboarding flow is not included.
- Rollback: `0.2.0 (5)`.

## Current installed baseline — `0.2.0 (15)`

This row is an on-device observation, not a complete release-provenance entry.

- A 2026-07-21 physical-iPhone audit found the TestFlight-installed app with
  marketing version `0.2.0`, build `15`, and the protected release bundle
  identifier.
- Repository history has nine first-parent `main` merges after build 6's known
  source through current `origin/main` at `c5343180`. That sequence is
  consistent with build 15, but no signed-archive extraction or Xcode Cloud
  record linking build 15 to `c5343180` was captured in this audit. Treat the
  source mapping as an inference, never as provenance.
- Installation is confirmed; a current-build physical behavior smoke and
  tester result remain pending.
- For exact recorded source lineage, use `0.2.0 (6)`; for prior installed
  behavior evidence, use development preview `0.1.0 (1)`.

## Local candidate — `0.2.1` robust product experience

This is a candidate and tester-note draft, not a TestFlight release record. No
`0.2.1` archive has been uploaded, processed, installed, or verified by an
internal tester.

### Change set under test

- Add a branded scanner-led first run, a single camera rationale, denied-camera
  recovery, a reticle/torch scanner, Advanced manual setup, and actionable
  network/TLS guidance that never exposes a credential or raw transport error.
- Explain the verified connection handoff before Home: endpoint identity,
  execution location, disconnect behavior, gateway-online dependency, and
  credential-storage posture. Legacy gateways receive explicit unknown-state
  copy instead of inferred continuity claims.
- Use the approved conversation-first Home: canonical Fabric identity, a large
  outcome composer, one solid-purple **Start goal** action, one prioritized live
  conversation, and at most two recent conversations.
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
- Add first-class Home, Sessions, and Settings destinations; searchable/local
  pinned sessions; a redacted diagnostics report; explicit switch/re-pair/
  forget/reset confirmations; and a device-only cache recovery control.
- Fail closed for upgraded saved token gateways that use remote plaintext HTTP:
  keep the saved row visible for recovery, but do not load or send its token;
  require re-pairing through trusted HTTPS or strict loopback.
- Show persistent, bounded reasoning and tool activity in Chat; keep approval
  context and the gateway-advertised response choices beside the conversation;
  and render only remote controls supported by the negotiated capability set.
- Add deterministic Debug fixtures for onboarding, denied camera, verified and
  legacy connection review, running/typed/empty/loading/error/offline Home,
  Sessions, Chat activity, and Settings.

This home is deliberately session-backed. The gateway does not yet advertise
the complete Durable Work contract, so the native goal portfolio is not shown
as production authority and no Job state is inferred from event hints.

### Draft internal tester notes

- Pair from a fresh install with **Scan pairing code**; deny camera once and
  verify both Settings recovery and Advanced setup remain available.
- Connect to a current gateway and confirm the connection review accurately
  describes where tools run and what survives closing the phone app.
- Start one goal, resume the prioritized live conversation, open **See all**,
  search/pin a session, and return through the Home/Sessions tab structure.
- In Chat, expand reasoning, review completed/running tool cards, answer one
  approval or question, and confirm unsupported remote controls are absent.
- Disconnect/reconnect, inspect the recovery banner and redacted diagnostics,
  switch servers, and review (but cancel) the Forget/Reset confirmations.
- On an upgraded install with a saved remote-HTTP token gateway, confirm that
  automatic and manual reconnect both refuse transport and direct the tester to
  re-pair through trusted HTTPS or loopback without exposing the token.
- Confirm Durable Work, node/Trust Center, push, files/attachments, phone audio,
  and mission-control surfaces remain absent; they are not part of `0.2.1`.

### Required evidence before upload

- Marketing version: `0.2.1` in `project.yml`; the final exact-head unsigned
  Release package must be inspected again before archive.
- Merged commit SHA, packaged `FabricSourceRevision`, and required hosted checks:
  pending until merge.
- Same-viewport light/dark, state-matrix, AX XXXL, and small-device visual
  evidence is recorded in [`design-qa.md`](../../design-qa.md). Any final UI
  change invalidates the affected capture and requires a replacement.
- Project-generation regression suite: 15/15 passed locally, including a
  fail-closed check for untracked Swift/resources that recursive XcodeGen
  sources could otherwise archive under an unrelated Git revision.
- Checked-in deterministic UI journeys: 11/11 passed on both iPhone 17 Pro Max
  and the small iPhone 17e simulator; the opt-in journey also passed 1/1 against a
  disposable source gateway, exercising real pairing, Keychain, WebSocket,
  capabilities, connection review, and Home/Sessions/Settings wiring. This is
  simulator integration evidence, not a physical-device or TestFlight result.
- Native simulator suite, UI journeys, generator idempotence, unsigned Release
  build, packaged metadata, privacy manifest, public release audit, and final
  code/design review: required again at the exact PR head before merge. The
  post-merge `main` iOS job is required because iOS is skipped on pull requests.
- Physical-iPhone Start goal, progress resume, Recent, reconnect, and QR pass:
  pending.
- Release workflow configuration: verified on 2026-07-21. `Default` targets
  merged `main`, uses the protected release bundle identifier and configured
  release signing team, and distributes successful archives to the internal
  TestFlight `beta` group. Re-check the final merged-SHA run rather than
  assuming historical workflow success proves the new archive.
- Archive/upload/processing/internal tester result: pending.
- Rollback: the installed `0.2.0 (15)` baseline, with its source-mapping caveat
  above; use `0.2.0 (6)` when exact recorded source lineage is required.

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
