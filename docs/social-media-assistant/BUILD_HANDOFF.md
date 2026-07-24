# Build Handoff — Fabric Social Media Assistant

Copy the following prompt into the implementation session that will build the product. It is intentionally constrained to Fabric’s existing mobile/gateway architecture and requires real verification rather than a mock dashboard.

---

## Implementation prompt

You are the principal product engineer for Fabric. Build the first production-grade vertical slice of **Fabric Social Media Assistant** according to:

- `docs/social-media-assistant/README.md`
- `docs/social-media-assistant/PRODUCT_SPEC.md`
- `docs/social-media-assistant/MOBILE_USER_GUIDE.md`
- `apps/mobile/README.md`
- `apps/mobile/PRODUCTION.md`
- `apps/mobile/ARCHITECTURE.md`
- `apps/mobile/UPGRADE_PLAN.md`
- `apps/mobile/JOURNEYS.md`
- the nearest `AGENTS.md` instructions in the repository.

### Product context

This is not a generic social dashboard. It comes from an anonymized B2B GTM workflow: a company wants to grow its LinkedIn page toward 10,000 followers and stronger qualified interaction/inbound demand. The workflow includes research, content strategy, agent-assisted drafting, human review, manual LinkedIn publishing, exact post URL capture, analytics capture, and mobile executive reporting.

The principal failure to prevent is **false certainty**: a draft being reported as live, an approved post being counted as published, missing analytics becoming zeros, or a forecast becoming a promise. The product must make the state/evidence chain clear.

### Current codebase baseline — extend, do not duplicate

Fabric `main` already ships **Social Studio** across desktop, web, iOS, and Android. `apps/shared/src/social.ts` defines the shared LinkedIn prompt builder and `linkedin-post` artifact parser. Existing Compose/Library surfaces use that contract to start an agent chat, discover post-ready artifacts from transcripts, and copy the final caption.

Treat Social Studio as the starting point for this build: preserve its Compose/Library behavior and use its artifact/session output as the initial source for a versioned content item. Do not create a second incompatible composer, another artifact format, or a client-local social ledger.

### Your mission

Implement **Phase 0 and Phase 1 only** unless a later dependency is genuinely required:

1. a server-authoritative Social workspace/data contract;
2. a capability-gated Social Growth workspace on iOS and Android, with mobile-web proof parity, while the existing Social Studio Compose/Library flow remains available on gateways that lack the new backend;
3. a manual LinkedIn operating loop from content draft to verified publication evidence to partially captured metrics and an exportable report.

Do **not** build a LinkedIn OAuth connector, automated posting, automated commenting, or a pretend live-analytics experience in this slice.

---

## Non-negotiable product constraints

1. **No public external action is automatic.** Agents may draft and recommend. A user must manually publish. `approved_manual_publish` is internal approval only.
2. **No fake data.** Unknown metric values remain `null`; explicit `0` is distinct. Display and export `partial`, `unavailable`, and `stale` honestly.
3. **No inferred publication.** Copying, approving, selecting an asset, or scheduling outside Fabric cannot mark a post live. `publication_verified` requires accepted evidence.
4. **No new local source of truth.** Gateway/profile-owned data is authoritative. Native/mobile-web clients are consumers of a common capability-negotiated contract.
5. **No secrets in client state or prompts.** Do not add social tokens to keychain storage, logs, mobile caches, fixtures, screenshots, or chat transcripts. There is no OAuth connector in this phase.
6. **No unsupported capability fallback.** Add one optional feature key and gate the new Growth UI and action handlers exactly as current Fabric Mobile does. Do not hide or regress the existing Social Studio Compose/Library flow when `social_growth` is unavailable.
7. **No simulated UI.** Fixtures are allowed in test/debug builds only. The release client must surface unavailable/unsupported states rather than fake records.
8. **No blind retries of mutations.** Use `expected_version` and `idempotency_key`; unknown outcomes require refresh/reconciliation.
9. **No scope creep into a separate app.** Extend existing Fabric Mobile navigation and gateway architecture.

---

## Required scope

### A. Contract and gateway service

Create the `social_growth` optional feature family.

1. Add the feature/method subset to `apps/mobile/contracts/gateway-feature-registry-v1.json`.
2. Extend the canonical capability parser in `apps/shared` and mirror gates in Swift and Kotlin.
3. A `social_growth` feature is valid only when the required Social methods are advertised. An omitted feature is unavailable; a feature/method contradiction invalidates the capability contract.
4. Implement a profile-private, gateway-owned Social service/store. Follow the repository’s established service/data patterns; do not allow a client to write database state directly.
5. Scope data by Fabric profile and workspace. Re-check authorization at the service boundary.
6. Add a server audit record for every state-changing Social operation.

Initial RPC methods:

```text
social.workspace.list
social.workspace.get
social.workspace.create
social.workspace.update
social.objective.create
social.objective.update
social.today.get
social.content.list
social.content.get
social.content.create
social.content.update
social.content.transition
social.content.approve
social.publication.record
social.publication.verify
social.metric.list
social.metric.record
social.metric.import
social.report.create
social.report.get
social.report.export
social.evidence.list
social.evidence.attach
social.audit.list
```

If an initial method is not needed by the narrow vertical, do not falsely advertise it. Either finish the feature’s complete subset as specified, or deliberately make a smaller `social_growth_v1` method subset and update the specification/fixture registry consistently before coding. Do not ship a contradictory manifest.

### B. Domain model

Implement strongly typed, versioned records matching `PRODUCT_SPEC.md`:

- Workspace, Brand, ChannelAccount, Objective
- ContentItem and versioned draft/content assets
- PublicationEvidence
- MetricSnapshot
- Forecast scenario
- Daily/weekly Report summary
- Social Audit event

Use these content states exactly:

```text
idea
researching
draft_ready
review_requested
changes_requested
approved_manual_publish
posted_unverified
publication_verified
metrics_partial
measured
archived
cancelled
```

Server-side transition validation is required. Test both valid and invalid paths.

### C. Shared contract fixtures and parsers

Create a new fixture corpus, proposed path:

```text
apps/mobile/contracts/fabric-social-v1/
```

Include valid records, malformed records, unknown future enums, lifecycle transitions, stale version receipts, idempotent replay receipts, missing vs zero metrics, partial/unavailable/stale metrics, report/export summaries, and invalid publication verification attempts.

- TypeScript is the reference parser/reducer.
- Swift and Kotlin consume the canonical fixture bytes and test semantic parity.
- Unknown additive states may be visible in a diagnostics/history surface but are never actionable.
- Parsers must cap/validate strings, IDs, timestamps, arrays, and payload size to prevent arbitrary JSON reaching UI state.

### D. Gateway API mutation discipline

Every existing-object mutation must send `expected_version`; every mutation must send an `idempotency_key`; every receipt must return `mutation_id`, `replayed`, updated entity/version.

On a timeout/closed connection/ambiguous error:

- do not create a new mutation;
- retain the original in-flight identity only long enough for an explicit reconciliation path;
- render “Outcome unknown — refresh to reconcile”; and
- clear only after the authoritative after-state shows the operation was resolved.

### E. iOS Social tab

Promote the existing `SocialStudioView` Compose/Library flow to the canonical **Social** destination, then extend `ConnectedAppTab` in `apps/mobile/ios/Fabric/App/FabricMobileApp.swift` if that is the selected navigation implementation. Do not create a second social composer or break Home, Sessions, Settings, the existing post artifact parser, or copy-caption flow.

Implement native SwiftUI screens:

1. **Growth workspace unavailable** — when the negotiated capability is absent/invalid, show a clear explanation without a fake dashboard while retaining the existing Social Studio Compose/Library flow.
2. **Workspace setup** — create workspace, brand, manual LinkedIn company channel, objective baseline/target/date, cadence, timezone, and metric-checkpoint choices.
3. **Today** — primary action, attention queue, data-health badge, growth pulse with provenance, next-seven-day plan, report preview.
4. **Content queue** — lifecycle-aware list with state, owner, publication proof status, metric checkpoint status.
5. **Content detail** — draft/version, source/asset/evidence list, approval, manual publish handoff, publication record/verify, metrics list, audit history.
6. **Manual publish handoff** — copy approved text, show explicit “Post manually on LinkedIn” instruction, capture exact URL, and place item in `posted_unverified` until evidence acceptance.
7. **Metric capture** — manual value entry with nullable fields and source labels. Screenshot/CSV attachment UI may be implemented only if it uses the existing gated files/artifact path truthfully; otherwise leave it as an honest planned/unsupported affordance rather than a fabricated importer.
8. **Reports** — SOD/EOD summary rendered natively; CSV export appears as a real fetched/delivered artifact only when the artifact capability path is actually implemented.

Use `@Observable` models, connection-generation guards, and typed `GatewayAPI` wrappers. Clear Social projections on disconnect/profile switch. Keep sensitive payloads out of list state.

### F. Android and mobile-web parity

Implement the same capability gate and the narrow product flow in:

- `apps/mobile/android` via Jetpack Compose and typed Kotlin contract models;
- `apps/mobile-web` as the PWA/browser proof surface using the shared TypeScript contract.

Presentation may be platform-native, but state machine, labels, source semantics, and action boundaries must be the same.

### G. Agent ensemble hooks (minimal only)

Do not build a generic autonomous multi-agent platform. Add the product seams needed for a Social content item to link a Fabric session/job as its source work:

- content item references an originating session/job ID;
- agent output can be attached as a bounded research or draft artifact;
- human review remains an explicit `approve` transition;
- reports include completed agent work and distinguish it from external publication/metrics.

The role catalog can initially be configuration/seed data. The actual product must not claim a role ran unless a linked Fabric session/job/evidence record exists.

---

## UX and writing requirements

- Use operator language: “Needs proof,” “24h metrics due,” “Posted — not yet verified,” “Data incomplete.”
- Avoid inflated marketing language (“AI growth engine,” “guaranteed reach,” “auto-optimized”).
- A LinkedIn post preview says it is approximate and cannot guarantee “Show more” or algorithm performance.
- Company/founder/employee lanes are visibly distinct.
- Source/provenance is visible in a metric card, not buried in a debug panel.
- The first page answers: what changed, what needs a decision, what to do next, and what is unknown.

---

## Required test and verification plan

### Contract/service

- Valid/invalid capability feature subset tests.
- Social parser fixture tests in TypeScript, Swift, Kotlin.
- Service state-transition tests for every lifecycle edge.
- Optimistic-version conflict and idempotency replay tests.
- Profile/workspace authorization tests.
- Missing vs zero vs partial/unavailable/stale metric tests.
- Report aggregation tests proving drafts/unverified posts do not inflate live counts.
- CSV export parse test proving unavailable numerics are empty cells, not zero.

### Clients

For iOS, Android, and mobile web capture/verify:

- capability unavailable;
- empty workspace;
- setup validation error;
- loading;
- current Today view;
- offline/read-only snapshot;
- partial/stale/unavailable data;
- review approval;
- manually posted but unverified;
- verified publication;
- outcome-unknown mutation and reconciliation;
- AX XXXL / font scaling and VoiceOver/TalkBack semantics;
- light and dark mode.

### Build checks

Follow the repository’s existing mobile release contract. At minimum run the smallest focused test suites while iterating, then:

- shared TypeScript typecheck/test;
- mobile-web test/typecheck/build;
- iOS XcodeGen regeneration check, simulator tests, unsigned Release build, metadata/privacy audit;
- Android unit tests and debug/release build on a valid Android SDK/JDK host;
- physical device smoke pass on a supported iPhone and Android device.

Never state a client path is shipped if only fixtures or a simulator passed. Record exactly what was tested.

---

## Delivery sequence

Work in small vertical PR-sized loops. Do not create a giant cross-platform unreviewable change.

1. **Loop 0:** social feature registry + shared types/fixture corpus + parser tests; no live feature advertisement.
2. **Loop 1:** server Social service/store + state transitions + audit + gateway methods; advertise feature only when the full planned method subset and contract are verified.
3. **Loop 2:** mobile-web proof flow for setup/content/manual publication/metric entry/report and contract integration.
4. **Loop 3:** iOS Social tab + capability gate + full state matrix.
5. **Loop 4:** Android Social tab + parity tests.
6. **Loop 5:** real artifact/evidence attachment/export path only after verifying existing artifact/files capability support end-to-end.
7. **Loop 6:** agent-session/content linkage and report job integration.

Each loop must leave `main` shippable. Do not flip future Fabric Mobile features (Durable Work, push, artifact fetch) solely to make Social appear complete; use existing verified seams or explicitly represent the dependency as unavailable.

---

## Completion definition for this handoff

The build is complete only when a real user can:

1. create an anonymized company Social workspace on their Fabric gateway;
2. set a LinkedIn company-page objective with baseline, target, and date;
3. create/review/approve a company post without it being mistaken for published;
4. manually publish it outside Fabric, paste the exact URL, and obtain verified publication state;
5. record a 24-hour partial metric snapshot where blank is visibly different from zero;
6. read an EOD report that correctly distinguishes verified live content, unverified content, drafts, and unknown analytics;
7. export a parseable CSV artifact with correct null semantics; and
8. complete the flow on at least one native mobile client backed by real gateway state—not debug fixtures or local fake data.

Report back with changed files, contract/version decisions, tests executed and their exact results, screenshots/artifacts, known gaps, and any decision that needs product-owner input.
