# Build Handoff — Fabric Social Media Assistant MVP

Copy this prompt into the implementation session. It is intentionally constrained to Fabric’s current extension boundaries and must not claim product capabilities that are not implemented.

---

## Implementation prompt

You are implementing the first production-quality slice of **Fabric Social Media Assistant**. Read:

- `docs/social-media-assistant/README.md`
- `docs/social-media-assistant/PRODUCT_SPEC.md`
- `docs/social-media-assistant/MOBILE_USER_GUIDE.md`
- `website/docs/user-guide/features/extending-the-dashboard.md`
- `apps/shared/src/social.ts`
- the nearest `AGENTS.md` instructions.

### Mission

Deliver a **responsive, authenticated dashboard plugin** named `social-gtm` plus narrowly scoped Social Studio safety hardening.

The plugin is the first durable operating surface and must work well in a phone browser. Do not add a core gateway RPC family, a mobile-PWA tab, an iOS screen, an Android screen, or a social-network connector in this implementation.

The existing Social Studio Compose/Library flow remains the draft-entry path. Treat its `linkedin-post` fenced blocks as a rendering convention and a link back to a source session, not as a durable ledger API.

### Product goal

Enable a GTM operator to:

1. create a profile-scoped social workspace and lanes;
2. link a ledger draft to its originating Fabric session and exact caption hash;
3. review and approve that exact caption for **manual copy**;
4. copy it and publish outside Fabric;
5. record a user-supplied post URL/attestation and manually supplied metric observations; and
6. read a truthful daily report and export CSV rows.

### Absolute constraints

1. **No external publishing.** Do not create a publish endpoint, OAuth flow, browser automation, scraper, scheduler, or provider adapter. There must be no network request to LinkedIn or another social host.
2. **No cron publishing.** Cron jobs are non-interactive and can auto-approve tools. Any plugin cron job may prepare research or reports only; it must not call a publish-like operation.
3. **No fake data.** `null`, `0`, partial, stale, unavailable, and user-supplied values have distinct storage and UI semantics.
4. **No accidental proof.** A copied or approved caption is not posted. A user-entered URL remains `user_reported` unless a future approved connector independently validates it.
5. **No secrets.** Do not request, store, log, or display LinkedIn credentials, cookies, API tokens, or passwords.
6. **No local client ledger.** The server-side plugin owns the ledger, scoped to the authenticated Fabric profile. Chat history is not the source of truth for social state.
7. **No binary/media MVP.** Do not add image upload, generation, raw workspace paths, static-media storage, or screenshot parsing in this slice. A later phase may add authenticated artifact/import support.
8. **No scope expansion.** Do not change `apps/mobile-web/src/app.tsx`, native mobile navigation, the core capability registry, or unadvertised Durable Work merely to make Social appear complete.

---

## Existing architecture to respect

- `apps/shared/src/social.ts` provides the current prompt builder and loose transcript parser. Do not make its `messageIndex:blockIndex` IDs durable; transcript changes can invalidate them.
- The mobile PWA is a chat shell. It does not host dashboard plugins, and its pairing-token WebSocket authentication is separate from dashboard REST authentication.
- Dashboard plugins provide authenticated routes beneath `/api/plugins/<name>/*`, dashboard tabs/slots, SDK helpers, and an appropriate edge-extension surface.
- Use ordinary Fabric sessions for drafting and save only the originating session reference plus a bounded caption snapshot/hash in the plugin ledger.
- Existing generic `approval.request` is tool/command approval, not a durable business approval. The plugin must record its own reviewer, timestamp, caption hash, and explicit action.
- Existing Fabric usage analytics are not social-platform analytics. Never relabel them.

---

## Required plugin shape

Use the repository’s established bundled-plugin conventions. The expected layout is conceptually:

```text
plugins/social-gtm/
  dashboard/
    manifest.json
    plugin_api.py
    dist/
  social_gtm/
    ledger.py
    service.py
    reports.py
    cron_jobs.py
  skills/
    social-gtm/SKILL.md
```

Follow the actual plugin scaffolding and manifest schema in the repository rather than inventing a loader.

### Responsive dashboard UX

Build one plugin tab that works on desktop and narrow phone widths. It has four compact views:

1. **Today** — one next decision, open reviews, missing manual inputs, and clear data-quality labels.
2. **Drafts** — source session link, excerpt, hash/version, lane, reviewer, and manual-copy handoff.
3. **Evidence** — user-reported post URLs and manual metric observations with source/time/coverage labels.
4. **Reports** — SOD/EOD summary and a real CSV download when export is implemented.

Do not render a zero-filled dashboard when there are no observations. Distinguish `No records yet`, `Offline/authentication required`, `Data unavailable`, and `User-supplied data`.

### Profile-scoped ledger

Implement a plugin-owned SQLite ledger or repository-standard equivalent. Scope every query and mutation to the authenticated Fabric profile; the client must not supply an arbitrary profile identifier.

Minimum records:

```text
Workspace
  id, profile_id, name, timezone, created_at, updated_at

Lane
  id, workspace_id, name, account_type, audience, voice_boundary, owner

Draft
  id, workspace_id, lane_id, source_session_id, source_message_ref?,
  caption, caption_hash, version, state, created_at, updated_at

ReviewDecision
  id, draft_id, draft_version, caption_hash, reviewer, decision,
  reason?, created_at

PublicationRecord
  id, draft_id, state, user_reported_url?, user_reported_at?,
  attested_by?, notes?

MetricObservation
  id, workspace_id, draft_id?, metric_name, numeric_value?, unit,
  observed_at?, captured_at, source_kind, coverage, freshness,
  entered_by, supersedes_id?, notes?

AuditEvent
  id, workspace_id, actor, kind, entity_type, entity_id, created_at, payload_summary
```

All values are bounded and validated. Store only safe summary fields in audit rows; do not duplicate sensitive prompt or credential contents.

### State model

Use an explicit, small state model:

```text
Draft: draft -> review_requested -> approved_manual_copy
                               -> changes_requested -> draft
                               -> held | cancelled

PublicationRecord: none -> user_reported -> url_recorded

MetricObservation coverage: complete | partial | unavailable | stale
MetricObservation source: user_entered | csv_import_future | attachment_future
```

`approved_manual_copy`, `user_reported`, and `url_recorded` do not mean Fabric verified a live LinkedIn post. They are operational states only. Any changed caption invalidates a prior approval and requires another review decision.

### API boundary

Expose only authenticated plugin routes. Exact routing follows the plugin framework, but the API behavior must support:

```text
GET    /api/plugins/social-gtm/workspaces
POST   /api/plugins/social-gtm/workspaces
GET    /api/plugins/social-gtm/today
GET    /api/plugins/social-gtm/drafts
POST   /api/plugins/social-gtm/drafts
POST   /api/plugins/social-gtm/drafts/{id}/review
POST   /api/plugins/social-gtm/drafts/{id}/copy-receipt
POST   /api/plugins/social-gtm/drafts/{id}/publication-record
GET    /api/plugins/social-gtm/metrics
POST   /api/plugins/social-gtm/metrics
GET    /api/plugins/social-gtm/reports/eod
GET    /api/plugins/social-gtm/reports/export.csv
```

There is intentionally no `/publish`, `/schedule`, `/oauth`, `/provider`, or `POST` that forwards data to a social-network host.

Every existing-record mutation uses optimistic versioning or an equivalent conflict check and an idempotency key. On a timeout or ambiguous response, display an outcome-unknown state and require refresh/reconciliation; never blindly replay an approval, publication record, or metric mutation.

### Draft/session integration

- Start draft work through the existing Social Studio prompt/session flow.
- Allow the user to attach a manually selected caption snapshot to a plugin Draft, recording the source session ID and a durable message reference only when the current gateway exposes one truthfully.
- If the source transcript cannot be read, is partial, lacks a durable reference, or is unavailable, show that condition. Do not silently create a fake session link.
- Treat all assistant text as a suggestion until a human review decision is saved.

### Agents and cron

- Add a constrained `social-gtm` skill: source-backed drafting, lane/voice boundaries, manual-only publication, and data-provenance requirements.
- Ordinary sessions can run research and drafting.
- If cron jobs are added, use the full cron implementation rather than the restricted mobile wrapper and create only two non-publishing jobs:
  - daily research/draft recommendation;
  - daily executive report based on plugin ledger records.
- Each job must say that it cannot publish or infer platform performance. It writes a report artifact or recommendation, not a social-network action.

---

## Required tests and verification

### Plugin/service tests

- profile isolation for every list/get/mutation;
- validation and bounds for IDs, captions, URLs, timestamps, metric values, and CSV cells;
- valid/invalid draft transitions;
- prior approval invalidated by caption change;
- mutation conflict, idempotency replay, timeout/reconciliation behavior;
- copied text and review approval never count as a publication;
- URL record remains explicitly user-reported;
- `0` versus `null`, partial, stale, and unavailable metrics;
- report and CSV aggregation excludes drafts and distinguishes coverage/source;
- no plugin route or dependency performs an outbound social-network request.

### Dashboard/UI tests

- unauthenticated and unauthorized plugin-route behavior;
- empty workspace, no records, partial data, and stale data;
- phone-width layout, keyboard navigation, screen-reader labels, high contrast, and large text;
- review confirmation, changes requested, hold, manual-copy receipt, URL recording, and manual metrics;
- offline/authentication failure shown as an error state, never as an empty ledger.

### Release proof

- run the relevant plugin tests and dashboard build/tests required by the repository;
- manually exercise the responsive tab at a narrow mobile viewport and a desktop viewport;
- demonstrate a real local authenticated plugin route, not mock-only UI;
- attach exact commands and results to the implementation PR;
- state any deferred attachment/import or native-mobile dependency honestly.

---

## Delivery sequence

1. **Loop 0:** plugin scaffold, auth boundary, profile-scoped empty ledger, and responsive empty/error states.
2. **Loop 1:** workspace/lane/draft/review records, exact-caption hash, session link, and manual-copy receipt.
3. **Loop 2:** user-reported URL, manual metrics, data-health labels, EOD report, and CSV export.
4. **Loop 3:** constrained skill and optional non-publishing cron report jobs after ledger access is verified.
5. **Future separate RFC:** attachments, CSV import, native integration, OAuth, scraping, analytics APIs, or any external platform connector.

Each loop must leave `main` shippable and must not broaden core/mobile scope merely for parity.

## Completion definition

The MVP is complete only when an authenticated user can create a workspace, link a session-backed caption, approve the exact hash for manual copy, record a user-supplied URL and manual metric observation, read a truthful report, and download a parseable CSV—without an external social-network request, stored credentials, fake analytics, or a native-app claim.