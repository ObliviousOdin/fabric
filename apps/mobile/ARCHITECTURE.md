# Fabric Mobile capability architecture (post-v1 upgrade)

> **Scope note.** This document is the engineering architecture for the
> post-v1 mobile capability program — the work that turns Fabric Mobile from a
> remote text client into a bidirectional **node** the agent can reach through.
> It builds on the first-release contract in [`PRODUCTION.md`](PRODUCTION.md)
> and the fail-closed wire contract in [`README.md`](README.md); it does not
> replace them. The loop-driven delivery order lives in
> [`UPGRADE_PLAN.md`](UPGRADE_PLAN.md); the journey-by-journey gap map lives in
> [`JOURNEYS.md`](JOURNEYS.md).
>
> Everything here obeys the four standing invariants: **fail-closed capability
> gating**, **no simulated surfaces**, **least-privilege / secure credentials**,
> and the **release-contract gates**. A design that cannot satisfy all four is
> not ready to build.

## The one spine (why seven epics are one system)

A naïve reading of the 14 user journeys produces seven independent server
programs: progressive permissions, device enrollment, `node.invoke`, a Trust
Center, push, offline durability, and phone audio. They are not independent.
They are one substrate seen from seven surfaces, and building them separately
would fork the single fail-closed capability check into seven divergent code
paths and ship contradictory contracts (three different "audit ledgers", two
different "consent engines", three different "scope" definitions).

The correct decomposition is a single spine:

```
                    ┌──────────────────────────────────────────────┐
                    │  0. Capability-manifest governance            │
                    │     gateway.capabilities grows by ONE rule    │
                    │     (feature flag ⇔ required-method subset)   │
                    └───────────────────────┬──────────────────────┘
                                            │ every family below is one feature
              ┌─────────────────────────────┼─────────────────────────────┐
              ▼                              ▼                             ▼
   ┌────────────────────┐        ┌────────────────────────┐    ┌────────────────────┐
   │ 1. Node identity   │        │ 3. ConsentGrantLedger  │    │ 6. Push / attention │
   │    & enrollment    │──node_id▶│  one consent + grant  │    │    backbone (APNs) │
   │  enroll→pending→   │        │  + server-authoritative│    │  register/redact/  │
   │  active→revoke     │        │  audit, per-gateway     │    │  wake/deep-link    │
   └─────────┬──────────┘        └───────────┬────────────┘    └─────────┬──────────┘
             │                               │ grants + audit            │ wakes
             ▼                               ▼                           ▼
   ┌────────────────────┐        ┌────────────────────────┐    ┌────────────────────┐
   │ 4. node.invoke     │◀───────│ 5. Trust Center surface │    │ background node/    │
   │  bidirectional      │ gates  │  posture + grants +    │    │ approval delivery  │
   │  transport          │ audit  │  nodes + audit         │    │                    │
   │  (camera, location…)│        └────────────────────────┘    └────────────────────┘
   └────────────────────┘
```

Read the spine as one sentence: **a phone enrolls as a scoped node (1),
everything the agent asks that node to do passes through one consent + grant +
audit subsystem (3), `node.invoke` is the transport that carries those requests
(4), the Trust Center is that subsystem made visible and revocable (5), and
push is how the node answers when the app is asleep (6) — all advertised
through one manifest rule (0).** The rest of this document specifies each stage
so that any one of them can be built as a self-contained loop without
re-deriving the others.

Three cross-cutting design conflicts are resolved up front, once, here:

- **One audit stream, server-authoritative.** The phone is never the sole
  record of what left it. The client keeps a corroborating in-memory view fed
  by `trust.audit.*`; the gateway owns the truth.
- **One consent/grant engine.** The "progressive-consent broker" and the
  "`node.invoke` consent engine" are the same component. "Scoped temporary
  grants" is its persistence/review layer, not a third engine.
- **One scope taxonomy, nested.** Pairing-time coarse scope (`full` / `limited`)
  bounds per-capability just-in-time scope, and Trust Center revoke operates on
  both.

---

## 0. Capability-manifest governance (the master dependency)

Every server-backed feature below is advertised the same way the shipped
contract already advertises `durable_work`: an **additive-optional feature
flag** whose boolean **must equal** whether its required method set is a subset
of the advertised `methods[]`. The parser
(`GatewayCapabilitiesParser.parse`) already enforces this for the baseline
feature map (`gatewayFeatureMethods`) and for the optional `durable_work` key
(`GatewayCapabilityNegotiation.supportsDurableWork`). New families extend that
map; they do not invent a new gating mechanism.

The governance rules a new family must follow:

1. **One feature key, one method set.** Add `feature ⇔ requiredMethods` to the
   client's map and to the gateway manifest. The client exposes a
   `supports<Family>` computed property on `GatewayCapabilityNegotiation`
   modeled exactly on `supportsDurableWork` (`verified && features[key] == true
   && requiredMethods.isSubset(of: methods)`).
2. **Additive-optional parsing.** An omitted key means *unavailable* (`false`),
   never legacy. A present key that contradicts its methods invalidates the
   *entire* contract (`.invalid`), because a lying manifest is a bug, not a
   partial capability.
3. **Version discipline.** New *methods* are additive and need no version bump.
   A change to an **execution invariant** (`location`, `tool_execution`,
   `survives_client_disconnect`, `survives_gateway_restart`,
   `requires_gateway_host_online`) or to the meaning of an existing method bumps
   `contract.version` and, if it breaks old clients, `min_compatible` — which
   the client already turns into an honest "update Fabric Mobile" state.
4. **No per-method probing, ever.** Capability is read from the manifest, not
   discovered by calling a method and catching an error (except the one
   sanctioned `-32601 ⇒ legacy` bootstrap that predates negotiation).

All timestamps in these contracts (`at`, `granted_at`, `expires_at`, …) are
**Unix epoch milliseconds**, matching the shipped `fabric-work-v1` corpus. The
canonical machine-readable registry lives at
`apps/mobile/contracts/gateway-feature-registry-v1.json`; every platform
asserts parity with it (see `contracts/README.md`).

The registry this program adds (see the appendix for the full table):

| Feature key | Direction | Required methods (subset check) |
| --- | --- | --- |
| `device_node` | phone ⇄ gateway | `node.enroll` |
| `node_invoke` | gateway → phone | `node.announce`, `node.result`, `node.reject` |
| `trust_center` | phone → gateway | `trust.audit.list`, `grant.list`, `grant.create`, `grant.revoke` |
| `scoped_grants` | phone → gateway | (flag only; extends `approval.respond` params) |
| `push` | phone → gateway | `push.register_device`, `push.deregister_device` |
| `connected_nodes` | phone → gateway | `node.list`, `node.revoke` |
| `session_admin` | phone → gateway | `session.rename`, `session.archive` |
| `artifact_fetch` | gateway → phone | `artifact.list`, `artifact.fetch` |
| `workspace_read` | gateway → phone | `fs.list`, `fs.read` |
| `phone_audio` | phone ⇄ gateway | (transport contract — see §8) |

Two feature keys already exist in the client map but have **no UI consumer
yet** — treat them as pre-wired gates, not new work: `files`
(`image.attach_bytes`, `pdf.attach`, `file.attach` — *outbound* attach from the
phone) and `live_view` (`visual.status`, `visual.frame`). `code_session_baseline`
(`session.branch`, `session.undo`, `projects.discover_repos`), `delegation`,
`handoff`, and `automation` (`cron.manage`) are likewise gated but not surfaced.

---

## 1. Node identity & enrollment lifecycle (one lifecycle, not three)

Journey 3's "Full or Limited access → generate code → approve on Gateway", the
`device_node` enrollment stub, and the Trust Center's "connected nodes" review
are **one lifecycle**: `enroll → pending-approval → active → revoke`. Today the
pairing-v2 `enrollment` handle is recognized and deliberately fails closed as
`.unsupportedEnrollment` (`AppModel.receivePairingURL`,
`PairingFlowModel`) — the seam exists; this fills it.

**Wire contract (server work).**

```
POST /api/pair/enroll
  { enrollment: <handle>,                     # single-use, consumed server-side
    device: { name, platform: "ios",
              public_key_b64 },                # P-256 SPKI, from Secure Enclave
    scope: "full" | "limited" }
  → { enrollment_id, state: "pending", poll_after_ms }
  # or, for a hosted/OAuth gateway:
  → { enrollment_id, state: "pending", authorize_url }

GET /api/pair/status?enrollment_id=<id>
  → { state: "pending" | "approved" | "denied" | "expired",
      granted_scope?: "full" | "limited",
      ws_credential?: { mode: "token" | "ticket", value?, ticket? } }
```

On `approved+local`, the device signs a server nonce (returned in the enroll
body) with its P-256 key to bind the WebSocket credential to the key. After the
socket opens, `gateway.capabilities` additionally echoes `granted_scope` and, for
a `limited` credential, the reduced method set — so scope enforcement rides the
existing fail-closed negotiation rather than a parallel check.

**Client modules.**

- `Core/Node/DeviceIdentityKey.swift` — P-256 key generated in and never leaving
  the Secure Enclave/Keychain (`kSecAttrTokenID`); signs the enrollment nonce.
- `Core/Node/DeviceNodeIdentity.swift` — per-gateway `node_id` stored as
  **non-secret** metadata in `GatewayStore` (keyed per server, like the existing
  per-server token slots).
- `Core/PairingEnrollmentSession.swift` — an `actor` driving
  `enroll() → poll() → cancel()` with an `EnrollmentState` enum.
- `Features/Connect/DeviceEnrollmentView.swift` — the pending/approved/denied/
  expired UI that replaces the `.unsupportedEnrollment` dead end in
  `AddGatewayView.handleScan` / `AppModel.receivePairingURL`.
- `Core/BrowserAuthSession.swift` — `ASWebAuthenticationSession` wrapper for the
  `authorize_url` (hosted/OAuth) branch. This same wrapper closes the separate
  OAuth-provider sign-in gap.

**Fail-closed rules.** A `404`/`501`/malformed enroll response keeps the exact
current `.unsupportedEnrollment` message — never a silent downgrade to a
token/password path. The handle never enters observable state or logs (reuse the
`withUnsafeToken` redaction from `PairingTokenAcceptance`). The private key never
leaves the enclave. `expired`/`denied`/poll-timeout are terminal — never retried
through another pairing path. Only `approved` with a valid `ws_credential`
persists a `SavedGateway`.

---

## 2. The ConsentGrantLedger subsystem (one consent + grant + audit)

This is the pivotal shared module. It brokers just-in-time scoped grants,
persists standing grants per gateway, records every invocation, and feeds the
Trust Center. Every capability the agent invokes on the phone goes through it.

**Scope taxonomy (nested, single source).**

```
pairing-time scope:   full | limited                # bounds everything below
per-capability grant: once | scoped(ttl) | session | always
                      └ ttl ≤ 900 s for JIT sensor grants; in-memory only
```

A `limited` node can never be asked for a capability outside its pairing scope,
regardless of a per-capability grant. Trust Center revoke operates on both
layers.

**Grant model (server-authoritative, client-corroborated).**

```
grant.list  {} → { grants: [ Grant ] }
Grant = { grant_id, capability, scope, version≥1, session_id?, node_id?,
          granted_at, expires_at?|null, last_used_at?|null, use_count,
          source: "mobile"|"desktop"|"cli", revocable: bool }

grant.create { capability, scope, ttl_seconds?(req iff scoped),
               session_id?, node_id?, idempotency_key }
             → { grant_id, scope, expires_at?|null, granted_at,
                 mutation_id, replayed }

grant.revoke { grant_id, expected_version≥1, idempotency_key }
             → { grant_id, revoked, revoked_at, grant_version(> expected),
                 mutation_id, replayed }
```

Standing grants (`scoped`/`session`/`always`) are **server-owned** — the
gateway prunes expired grants; the client only re-queries. `expires_at` is
display-only and never trusted for enforcement. Revoke uses `expected_version`
optimistic concurrency and an `idempotency_key` (reuse the existing
mutation-id/idempotency regex and the receipt-echo discipline from durable
Work's `job.cancel` / `attention.respond`). A grant with `revocable: false`
renders disabled with a reason.

**Just-in-time grants** are extended from the existing `approval.respond`
rather than a new call, so the same "first answer wins across surfaces"
guarantee holds:

```
approval.respond { session_id, request_id,
                   choice: "once"|"session"|"always"|"scoped"|"deny",
                   ttl_seconds?(req iff scoped, 60..86400) }
                 → <existing receipt> + { grant_id?, expires_at?|null }
```

Today `ChatViewModel.respondToApproval(allow:)` hardcodes `choice: "once"|"deny"`.
The scope menu (`scoped`/`session`/`always`) appears **only** when the additive
`scoped_grants` feature flag is advertised; absent the flag, the phone keeps its
current once/deny behavior rather than sending an unsupported choice.

**Audit stream (resolves the "three ledgers" conflict).**

```
trust.audit.list { limit:1..200, after?, since?, kinds?[] }
  → { cursor, entries: [ AuditEntry ], next_before? }
AuditEntry = { entry_id(monotonic), at, actor:"agent"|"user"|"system",
               kind:"capability_invocation"|"approval"|"grant_change"
                    |"node_change"|"auth",
               method, session_id?, session_title?, node_id?, grant_id?,
               decision?:"allowed"|"denied"|"auto",
               summary(server-redacted ≤512), redacted:true }
event: { type: "trust.audit.appended", payload: { entry_id } }
```

**Client modules.**

- `Core/Consent/ConsentGrantLedger.swift` — `@Observable @MainActor`, the single
  broker. Owns the in-memory grant cache, subscribes to `trust.audit.appended`
  and `trust.grants.changed`, and enforces strictly-increasing `entry_id` (like
  durable Work's event replay). **Per-gateway keyed** even though one socket is
  live at a time, so switching servers never shows another gateway's grants.
  `clear()` is called from `AppModel.disconnect`.
- `Core/TrustCenterContract.swift` — strict parsers (`.verified`/`.incompatible`/
  `.invalid`) mirroring `FabricWorkParser`, plus `TrustGrant`, `TrustAuditEntry`,
  and typed errors.
- `GatewayAPI` additions — `listAudit`, `listGrants`, `createGrant`,
  `revokeGrant`, each behind a `requireTrustCenter` gate, each validating the
  echoed receipt.

**Fail-closed rules.** Add `trustCenterGatewayMethods = { trust.audit.list,
grant.list, grant.create, grant.revoke }` and a `supportsTrustCenter` computed
property modeled on `supportsDurableWork`. The ledger is **never** populated from
any legacy fallback; a malformed page is an honest `.invalid` error state, never
simulated entries. Everything is in memory, connection-scoped, cleared on
disconnect/server-switch.

---

## 3. `node.invoke` — the bidirectional node transport (peak differentiator)

`node.invoke` is what makes the phone the agent's eyes, ears, and location
sensor. It is the single most differentiating surface and the highest residual
security risk, so it is built as a deliberately narrow vertical first (one
capability: `camera.capture`) over the ConsentGrantLedger, then generalized.

**Feature advertisement** is additive-optional (parsed like `durable_work`):
`features.node_invoke` must equal `nodeInvokeGatewayMethods.isSubset(of: methods)`
where `nodeInvokeGatewayMethods = { node.announce, node.result, node.reject }`.
**Individual device capabilities are not gateway methods** — they are advertised
in the `node.announce` *result* and re-verified per invocation, so a partially
implemented capability can never look available.

**Wire contract (server work).**

```
# client → server
node.announce { node_id(uuid, regenerated per connect), platform:"ios",
                app_version, capabilities:[{name, version}] }
             → { accepted:[string](⊆ announced), node_token, routable:[string] }

node.result  { invocation_id, node_token, capability,
               grant_scope:"once"|"grant", captured_at,
               data:{ mime, bytes_b64?, json?, width?, height?,
                      redactions:[{kind, region?:[x,y,w,h]}] } }
             → { invocation_id, accepted:true }          # echo enforced

node.reject  { invocation_id, node_token,
               reason:"denied"|"unsupported"|"foreground_required"
                     |"grant_expired"|"permission_denied"|"capture_failed"
                     |"expired", detail? }
             → { invocation_id, accepted:true }

# server → client (event frames)
node.invoke  { invocation_id, session_id, capability, reason, params, expires_at }
node.cancel  { invocation_id, reason }
```

**The provider seam (resolves the testability-vs-no-simulated-surfaces tension).**
Each capability is a `NodeCaptureProvider`:

```swift
protocol NodeCaptureProvider {
    var capability: String { get }
    func announceEligible() -> Bool                 // Info.plist key present,
                                                    // framework linked, OS not denied
    func capture(_ params: NodeInvocationParams) async throws -> NodeCapturedData
}
```

A test-only fake conforms to the protocol for contract/screenshot fixtures and
is **compiled out of release builds** (behind a `DEBUG`/test-only target
membership), so CI exercises the path deterministically while production can
never ship a fake surface.

**Client modules** live under `Core/NodeInvoke/`:
`NodeInvokeContract.swift` (strict parser), `NodeInvokeCoordinator.swift`
(`@Observable @MainActor`, owns the invocation queue, `node_token`, foreground
flag; installed on `phase == .connected` when `node.announce` is supported; torn
down on disconnect/background), `Providers/CameraCaptureProvider.swift`,
`NodeImageRedactor.swift` (Vision face/text blur), and
`Features/Node/NodeConsentSheet.swift` (per-invocation consent driven by the
ConsentGrantLedger). `ChatViewModel.handle()` gets a no-op branch so `node.*`
events are not misrouted into the transcript.

**Fail-closed rules (all six mandatory).**

1. `node.announce` is called only on a verified `node_invoke` contract; a
   timeout/closed/malformed/incompatible negotiation never announces.
2. The phone announces a capability **only if** its provider's
   `announceEligible()` is true — never advertise what the build cannot do.
3. Every inbound `node.invoke` is **re-gated at execution**: capability in the
   last accepted announce set, `node_token` matches the current connection,
   `scenePhase == .active` (else `node.reject foreground_required`), `expires_at`
   in the future (else `reject expired`).
4. Grants are in-memory, ≤ 900 s, capped invocation budget, cleared on
   reconnect/background/session-switch/disconnect — identical lifecycle to
   `AppModel.capabilityNegotiation`.
5. A stale `NodeConsentSheet` whose invocation expired or whose socket generation
   changed cannot dispatch `node.result` (guard on `connectionGeneration` +
   `node_token`, mirroring the generation guard in `RemoteControlSheets`).
6. `node.result`/`node.reject` enforce the echoed `invocation_id` receipt or
   throw.

**First vertical — `camera.capture`** (the "Take a photo for me" magic moment):
`params { facing:"rear"|"front", max_edge(512..4096, default 2048), allow_redaction }`,
result `image/jpeg` with detected `redactions`. Capture is **always
user-confirmed** — a grant skips the allow prompt but never the shutter tap. A
denied OS camera permission yields `node.reject permission_denied`, never a
placeholder image. Redaction failure with `allow_redaction=true` fails closed to
`capture_failed` rather than sending an unredacted frame. Later providers
(`photo.pick` via PHPicker, `location.oneshot`, `screen.snapshot`,
`canvas.render`, `health.summary`, `contacts.read`, `calendar.read`) are the
same shape with per-capability scoping.

---

## 4. Trust Center surface

The Trust Center is the ConsentGrantLedger made visible and revocable — the
product's biggest trust driver. It composes:

- **Posture (client-only):** auth mode, 2FA state (`on`/`off`/`unknown` — never
  falsely "protected"), transport security (strictly from an `https`/`wss`
  scheme), the execution contract, and the advertised capability summary. It
  must state plainly that **a gateway credential is root-equivalent for that
  machine even when everything is green** — no false reassurance.
- **Grants (server):** `grant.list` with one-tap `grant.revoke`.
- **Connected nodes (server):** `node.list` / `node.revoke` over the enrollment
  lifecycle.
- **Audit (server):** the `trust.audit.*` stream with a "revoke all / kill
  switch".

`Features/Trust/TrustCenterView.swift` + `TrustCenterModel.swift` +
`Core/TrustPosture.swift`. Each dynamic section independently checks its
capability and renders an honest unsupported state instead of an empty-looking
success. The whole surface is connection-scoped and torn down on disconnect. It
lives inside the Settings shell (see `UPGRADE_PLAN.md`, Loop 2).

---

## 5. Push / attention backbone

One APNs lifecycle serves notifications consent, out-of-app approval delivery,
and background `node.invoke` wake.

```
push.register_device   { apns_token(hex), platform:"ios", bundle_id,
                         app_version, node_id? }
                       → { registration_id, expires_at }
push.deregister_device { registration_id } → { revoked:true }
```

Alerts are delivered out-of-band via APNs with **server-redacted** copy — per
`PRODUCTION.md`, lock-screen notifications and Live Activities carry minimal
redacted hints that deep-link to the exact in-app interaction, never raw
approval commands and never a one-tap high-risk apply. A **silent** push wakes a
backgrounded app (`BGTask` + a foreground-return handshake) so a `node.invoke`
or approval that arrives while suspended can be answered — which is why §3's
background story hard-depends on this backbone.

Registration is connection-scoped: the token is (re)sent per verified `push`
contract and deregistered on disconnect/capability loss; the APNs token is not a
persisted grant. If the OS denies notification authorization, no registration
call is made and no "notification sent" state is ever simulated.

**One deep-link router.** `PairingURI` is generalized into a single URL/route
resolver that all of pairing, push deep-links, approval-cross-surface links, and
the share-extension app-group handoff go through.

---

## 6. Offline & durability contract

`PRODUCTION.md` explicitly rules out **blind offline prompt queues or automatic
retries of side-effecting RPCs**. The offline design honors that by being
presentation-plus-idempotent, never blind replay:

- **`Core/TranscriptCache.swift`** — last-known transcript, file-protected
  (`NSFileProtectionComplete`), bounded (~256 KB or last N messages per session,
  LRU). **Presentation-only:** while showing it, `sessionReady` is false, so
  composer/approvals/steer stay disabled; on resume it is atomically replaced by
  authoritative history (never merged, so stale rows cannot resurrect).
  `sudo`/`secret` prompts are never cached as answerable.
- **`Core/OutboundMessageQueue.swift`** — bounded (max 50/session, 48 h TTL,
  FIFO eviction), persisted, **only definitely-unsent** messages enqueued
  (reuse `ChatViewModel.mayNeedDurableBackgroundRetry` /
  `WorkInboxModel.isDefinitelyUnsent`). Flush on reconnect via the **gated**
  `prompt.submit`; if the reconnected gateway lost that capability, items are
  held or expired, never sent through another path. Steer notes are never queued
  (valid only mid-turn). Per-scope: a gateway/profile switch does not cross-flush.

The safe path for a *side-effecting* offline action (a queued approval, a
capture to deliver, a revoke to apply) is the durable Work idempotency contract —
a stable mutation key with at-most-once server semantics — not a blind retry.
Until Durable Work is truthfully advertised (see below), those actions surface as
"will be sent when reconnected" and are never silently retried.

---

## 7. Shared clients & standing constraints

These are not features; they are components every feature above consumes, plus
constraints every new surface must satisfy. Owning them centrally is what keeps
the program from fragmenting.

| Shared component | Consumers | Contract |
| --- | --- | --- |
| **Gated blob transfer + Quick Look** | inbound artifacts, share-extension staging, workspace `fs.read` | one fetch path with size/TTL limits and file protection. Note: the `files` feature (`image.attach_bytes`/`pdf.attach`/`file.attach`) is *outbound* attach and already gated; *inbound* artifact fetch (`artifact.list`/`artifact.fetch`) and `fs.*` are new server work. |
| **One `AVAudioSession` owner** | Listen/TTS, Talk Mode capture/return | a single routing/interruption manager; two owners fight over the route. On-device speech is the fail-closed fallback; a gateway audio path is gated. |
| **Typed-error taxonomy** | every new family | extend the `-32601 ⇒ unsupported` and `5040 ⇒ can't-capture` precedent into `unsupported` / `denied` / `transient` / `needs-reauth` so fail-closed UI separates "gateway can't" from "was denied" from "try again". |

Standing constraints (apply to *every* new surface, enforced at the release
gate, not retrofitted):

- **Privacy-manifest matrix, one owner.** Each provider that touches a sensor
  needs a matched `Info.plist` `NS*UsageDescription` **and** a
  `PrivacyInfo.xcprivacy` entry, added via `project.yml` `info.properties` and
  regenerated — never hand-edited. Apple review rejects inconsistency, so the
  matrix (below) is versioned with the providers, and the `mobile.yml` PrivacyInfo
  audit block is updated in the same slice. See the appendix.
- **Localization.** All new copy is heavy and user-facing (consent priming, Trust
  Center, approval context, route diagnosis, denial recovery). Author against a
  String Catalog from the first slice; retrofitting a dozen surfaces later is far
  costlier.
- **Accessibility as a design input.** Streamed reasoning/tool text must be
  announced without VoiceOver spam; `canvas.render` output needs an explicit
  semantic description; the QR reticle/torch and live camera need labeled
  controls; diff/table/math rendering must reflow at AX XXXL. These are designed
  in, because release gate 4 is non-negotiable.
- **On-device-only telemetry.** The activation funnel and the invocation ledger
  stay local and redacted; no analytics egress without its own consent gate.

---

## Durable Work stays dark (a release invariant on this branch)

None of the above flips FMB-002 Durable Work on. `supportsDurableWork` returns
true only on a `.verified` contract with `features.durable_work == true` **and**
all nine `job.*`/`attention.*` methods advertised; absence is deliberately
`false`, not legacy. Released behavior keeps `prompt.background` authoritative,
and a timeout/typed failure from a durable mutation is never retried through
`prompt.background`. Do not add `job.*`/`attention.*` to any capability fixture
used as a live manifest, and do not let a partial server upgrade produce a second
work surface. Durable Work is advertised only when the full client/server
contract is verified end-to-end (ROADMAP FMB-P3).

---

## Appendix A — capability manifest table

| Feature | Client gate (`GatewayCapabilityNegotiation`) | Required methods | Notes |
| --- | --- | --- | --- |
| `baseline_chat` | `allowsBaselineSessionCalls` | `session.create/list/resume`, `prompt.submit` | shipped |
| `background_work` | `supportsGatewayMethod` | `session.active_list`, `prompt.background`, `session.steer` | shipped |
| `files` (outbound) | `supportsGatewayMethod` | `image.attach_bytes`, `pdf.attach`, `file.attach` | gated, no UI yet |
| `live_view` | `supportsGatewayMethod` | `visual.status`, `visual.frame` | gated, no UI yet |
| `durable_work` | `supportsDurableWork` | 9× `job.*`/`attention.*` | **kept dark** |
| `device_node` | `supportsDeviceNode` (new) | `node.enroll` | §1 |
| `node_invoke` | `supportsNodeInvoke` (new) | `node.announce/result/reject` | §3 |
| `scoped_grants` | flag only | — (extends `approval.respond`) | §2 |
| `trust_center` | `supportsTrustCenter` (new) | `trust.audit.list`, `grant.list/create/revoke` | §2, §4 |
| `connected_nodes` | `supportsConnectedNodes` (new) | `node.list`, `node.revoke` | §4 |
| `push` | `supportsPush` (new) | `push.register_device`, `push.deregister_device` | §5 |
| `session_admin` | `supportsSessionAdmin` (new) | `session.rename`, `session.archive` | Journey 4 |
| `artifact_fetch` | `supportsArtifactFetch` (new) | `artifact.list`, `artifact.fetch` | §7 |
| `workspace_read` | `supportsWorkspaceRead` (new) | `fs.list`, `fs.read` | Journey 12 |

## Appendix B — privacy-manifest matrix

Every provider ships its `Info.plist` key and `PrivacyInfo.xcprivacy` entry in
the same slice; the `mobile.yml` PrivacyInfo audit is extended to match.

| Provider | `Info.plist` key | PrivacyInfo entry |
| --- | --- | --- |
| QR pairing (shipped) | `NSCameraUsageDescription` | — (camera not a Required-Reason API) |
| `camera.capture` | `NSCameraUsageDescription` (reused) | — |
| `photo.pick` | none (PHPicker needs no library permission) | — |
| `location.oneshot` | `NSLocationWhenInUseUsageDescription` | — |
| Talk Mode / mic | `NSMicrophoneUsageDescription` | — |
| `health.summary` | `NSHealthShareUsageDescription` | HealthKit data type declaration |
| `contacts.read` | `NSContactsUsageDescription` | — |
| `calendar.read` | `NSCalendarsUsageDescription` (or full-access variant) | — |
| existing UserDefaults | — | `NSPrivacyAccessedAPICategoryUserDefaults` / `CA92.1` (shipped) |
