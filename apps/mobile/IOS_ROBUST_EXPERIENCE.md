# Fabric iOS robust experience — implementation contract

This document turns the July 2026 UI roadmap and design handoff into one
reviewable iOS release slice. It does not expand the gateway protocol or make
future capability claims.

**Current state (2026-07-21):** implemented as the local `0.2.1` candidate on
this branch. It has not been merged, archived, uploaded to TestFlight, installed
by a tester, or promoted to a shipped support tier. See
[`IOS_RELEASES.md`](IOS_RELEASES.md) for the remaining exact-head gates.

## Product outcome

A person can install Fabric, pair with a gateway, understand where work runs,
start or resume a conversation, follow tool/reasoning activity, answer a
blocking request, recover from a network or sign-in failure, inspect connection
diagnostics, and safely remove local access without needing the desktop UI.

The selected onboarding direction is the **scanner-led hero**. The approved
conversation-first Home and the canonical Woven Operations tokens remain the
visual authority.

## Source hierarchy

1. Approved native Home and scanner-led onboarding visual artifacts.
2. `DESIGN.md`, `JOURNEYS.md`, `ARCHITECTURE.md`, and `SECURITY.md`.
3. `FabricTheme.swift` and the canonical design-system assets.
4. The current authenticated gateway capability contract.

When a visual artifact makes a security or capability claim that the wire
contract does not prove, the wire contract wins and the copy is corrected.

## One-PR surface contract

| Surface | Complete behavior in this release |
| --- | --- |
| First run | Real Fabric mark, QR-first connection, Advanced manual setup, camera priming and recovery |
| Pairing | Existing token/password/TOTP paths, typed network/auth failures, no credential disclosure |
| Connection review | Host/endpoint confirmation, gateway execution posture, credential-storage truth, Continue to Home |
| App shell | Home, Sessions, and Settings are first-class connected destinations |
| Home | Approved outcome composer, prioritized active conversation, bounded recent conversations, protected last snapshot |
| Sessions | Search, device-local pins, live status, resume/new/interrupt controls |
| Chat | Streamed/rich transcript, reasoning disclosure, persistent tool activity, approvals/questions, steer/interrupt |
| Remote controls | Advertised Commands, background dispatch, processes, and read-only Live View are discoverable; unsupported controls are omitted |
| Settings | Current server, execution posture, permissions, capability/version diagnostics, re-pair/switch/forget/reset, and device-only cache recovery |
| Recovery | Reconnect, expired sign-in, protected last-known Home/Chat presentation, and unknown-send outcome states without blind resend |

## Capability truth

The app renders a control only when both its UI action and RPC are supported by
the negotiated gateway contract. Legacy fallback remains limited to the
shipped legacy method set. A timeout, malformed contract, or incompatible
contract never becomes legacy.

This release intentionally does **not** expose:

- Durable Work / Work Inbox
- device enrollment, connected nodes, or Trust Center
- push notifications
- attachments, artifacts, or workspace browsing
- session rename/archive
- phone audio, Share extension, widgets, or Watch
- repo/branch/PR/CI/deploy/rollback mission-control claims

Those surfaces remain dark until their complete server family is advertised
and independently verified. No fixture or preview data is used in production.

Each saved gated gateway and normalized endpoint owns a distinct ephemeral
cookie jar; public status/provider discovery is cookie-disabled. Authentication
attempts are generation-fenced, a fresh password starts clean, and silent
reconnect copies cookies only from that same saved gateway. Forget and
disconnect invalidate only the targeted gateway, while full device reset
invalidates every gated session and clears device-local presentation data. None
of those actions claims to delete gateway-side work.

The remaining narrower gap is explicit: Chat's protected last-known transcript
is read-only presentation data—not an outbound queue or server-authoritative
offline state.

The Chat cache is fail-closed and bounded to 120 messages / 160,000 characters /
1 MiB per conversation, with global LRU pruning at 24 conversations, 8 MiB, or
14 days. Files require complete data protection, are excluded from backup, and
are discarded if corrupt, oversized, expired, or incorrectly protected.

## Local gateway expectation

The visual redesign ships inside the iOS app. Updating an installed local
Fabric CLI does not make an older TestFlight binary show the new UI. A gateway
update is needed only when a screen depends on a newer advertised RPC family;
this release is deliberately built on the existing baseline capability set.

## Release gates

- deterministic Debug fixtures for onboarding, recovery, chat activity, Home,
  Sessions, and Settings;
- XCTest coverage for reducers, bounds, redaction, cache isolation, and
  non-idempotent mutation behavior;
- XcodeGen reproducibility and clean generated project diff;
- Xcode 26.5 simulator tests and unsigned Release build;
- same-viewport light/dark visual comparison against approved sources;
- small-phone and accessibility Dynamic Type captures;
- VoiceOver labels/order and 44-point interactive targets;
- physical iPhone pairing, reconnect, chat, approval, offboarding, and
  relaunch checks;
- TestFlight archive from reviewed merged `main`, with exact source revision
  and truthful tester notes.

Because the hosted iOS job is skipped on pull requests, the exact PR head must
pass the complete local Xcode gate before merge and the post-merge `main` iOS
job must pass afterward. The protected Xcode Cloud bundle setting and internal
TestFlight distribution are configured; re-confirm that live workflow state
immediately before merge, then verify the new merged-SHA archive rather than
assuming historical workflow success applies to this candidate.

The opt-in `testDisposableGatewayPairingReachesTheRealConnectedShell` UI test
exercises the production pairing parser, Keychain, WebSocket, capability
negotiation, connection review, and Home/Sessions/Settings navigation. Give the
simulator test runner a disposable `FABRIC_TEST_GATEWAY_PAIRING_URL`, run only
that test, then unset the value immediately. The test forwards it only as the
app's Debug integration environment and never places it in arguments, assertion
messages, attachments, or logs. Never use a reusable credential.
