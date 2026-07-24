# Fabric Social Media Assistant — Product Specification

**Status:** Build-ready product and engineering specification
**Version:** 0.1
**Date:** 2026-07-23
**Maturity at approval:** Planned; Phase 0 and 1 are the proposed first build
**Primary platform:** Existing Fabric Mobile (native iOS, native Android, and mobile web fallback) backed by `fabric serve`
**Design partner:** Anonymized B2B company LinkedIn growth operation

> This specification is intentionally precise about uncertainty. A social system that cannot verify a post or fetch analytics must say so plainly; it must never turn missing data into a reassuring dashboard.

---

## 1. Executive summary

Fabric Social is a persistent, mobile-first operating workspace for a GTM team running a company social-growth program. It combines goal setting, content operations, research, agent roles, manual publishing handoff, metric capture, attribution, and executive reporting on top of Fabric’s existing gateway-owned session and Work architecture.

The first target workflow is a company LinkedIn page. It is designed for an anonymized B2B company’s stated goal: work toward 10,000 followers, increase quality-adjusted interaction/reach, and improve top-of-funnel demand. The product is intentionally channel-extensible, but it must not pretend that all platform data or publishing APIs are available.

### Current implementation baseline

Fabric `main` already includes **Social Studio** across desktop, web, iOS, and Android. It shares a LinkedIn post-prompt builder and `linkedin-post` artifact parser through `apps/shared/src/social.ts`, then exposes Compose/Library flows that draft a post in chat and let the user copy post-ready output. It is a text-first compose-and-artifact product, not yet a durable social-growth ledger.

This specification evolves that shipped foundation. It must preserve the Compose/Library artifact contract and use it as the initial source for versioned content items; it must not create a second, incompatible social composer or local content store.

### Product promise

> From a phone, know what social action matters today, why it matters, what needs a human decision, what actually went live, and whether the evidence says it is working.

### Product outcome

A GTM lead can operate a daily social experiment with a small team or an agent ensemble without losing:

- content provenance;
- channel/account boundaries;
- explicit human approval;
- manual-publish proof;
- metric provenance and completeness;
- report accuracy; or
- links between social activity and business outcomes.

---

## 2. Product principles

### 2.1 Server-authoritative truth

The gateway owns Social state. iOS, Android, mobile web, desktop, CLI, agent tools, scheduled reports, and exports read/write the same product records through capability-gated gateway APIs. No client keeps a shadow truth that can later be mistaken for a published post or verified analytic.

### 2.2 Evidence before performance claims

**No fake data or analytics:** every metric carries source, observation time, capture time, coverage status, and confidence. Unknown (`null`) is not zero. An unpublished draft cannot contribute to performance totals. A user-entered value is not presented as API-verified data.

### 2.3 Human control over public actions

The first product release has no write/publish/comment API to a social network. Agents can research, draft, format, prepare assets, classify evidence, and recommend actions. Only a human posts externally. Approval is a review state, not an external side effect.

### 2.4 Mobile is for decisions, not a compressed spreadsheet

The default Social tab answers, in order:

1. What needs my attention today?
2. What changed since yesterday / last week?
3. What is the next highest-value action?
4. What evidence is missing?
5. What should we expect if the plan is executed?

Detailed ledgers, raw evidence, full analytics, and CSV exports remain one tap away without cluttering the primary view.

### 2.5 Separate lanes, coordinated strategy

Company pages, founder profiles, employee advocacy, paid distribution, competitor observation, and customer proof are separate entities. Cross-lane reports may compare them, but never silently combine them.

### 2.6 Fail closed on capability, integrity, and provenance

Like existing Fabric mobile contracts:

- a missing or contradictory `social_growth` capability disables only the persistent Social Growth workspace with an honest unsupported state; the existing Social Studio Compose/Library flow remains available through supported session methods;
- malformed Social data is rejected rather than partially projected;
- stale connection generations cannot publish older snapshots;
- unknown future state enums remain visible only where safe and non-actionable; and
- side-effecting mutations use optimistic versions and idempotency keys.

---

## 3. Goals, non-goals, and success metrics

### 3.1 Product goals

1. Give a GTM owner one daily operating surface for company social growth.
2. Improve content consistency without lowering brand quality or human oversight.
3. Make publication, measurement, and attribution status explicit.
4. Produce decision-ready SOD/EOD/weekly reports on mobile.
5. Make agent work inspectable, source-backed, attributable to a content item, and reversible before external publication.
6. Establish a reusable Social workspace that can support LinkedIn first and other channels later.

### 3.2 Non-goals for the first release

- Autonomous posting, commenting, messaging, liking, following, or connection requests.
- Circumventing LinkedIn API eligibility, rate limits, permissions, or terms.
- Claiming that a LinkedIn preview determines “Show more” behavior or algorithmic distribution.
- Treating a copied draft, selected asset, or external calendar entry as a verified published post.
- A generic social-listening firehose, sentiment model, or all-channel ad manager.
- Replacing CRM, web analytics, DAM, or a social-platform native analytics product.
- Computing a causal pipeline claim without source attribution and an agreed definition.

### 3.3 Business outcomes configured by the workspace owner

A workspace can define targets such as:

| Outcome layer | Illustrative outcome | Required configuration |
| --- | --- | --- |
| Audience | Reach 10,000 LinkedIn page followers by a date | baseline followers, target, due date |
| Attention | Increase qualified interactions and impressions | baseline period, exact metric(s), comparison window |
| Demand | Increase LinkedIn-sourced qualified inbounds | CRM/analytics definition and source attribution policy |
| Execution | Publish consistently without sacrificing quality | cadence, owner, approval SLA, proof requirements |

The app does not display a numeric forecast until the prerequisites for that forecast exist. In setup mode it may display the required daily/weekly follower path as an **assumption-based pace**, clearly labeled—not a prediction.

### 3.4 Product success metrics

| Metric | Target for a pilot workspace | Definition |
| --- | --- | --- |
| Publication evidence coverage | ≥90% | live posts with an exact post URL or captured platform evidence |
| 24h metric coverage | ≥80% | expected published-post snapshots with captured or explicitly unavailable metrics |
| Data-health honesty | 100% | unknown/partial/stale states visible; no implicit zeros |
| Daily review duration | <5 minutes | operator can read Today and decide next action |
| Human control | 100% | public post actions are manually completed and recorded by a human |
| Decision traceability | ≥1 weekly decision | report links a recommendation to evidence, sample, and action |

---

## 4. Personas and jobs to be done

### 4.1 GTM owner / executive operator

**Example:** a GTM owner leading Example Company’s company-page growth.

**Jobs**

- Set a realistic social-growth target and see pace versus actual.
- Decide today’s action without hunting across chat, drafts, LinkedIn, and screenshots.
- Approve company content that supports the real GTM strategy.
- Understand whether creative effort is earning better outcomes.
- Read concise SOD/EOD/weekly briefs on a phone.

**Success:** can answer “what happened, why, what is next, and how sure are we?” in a few minutes.

### 4.2 Content operator

**Jobs**

- Turn a strategy brief into an authentic, non-repetitive company post.
- Ensure product/founder/company voice boundaries are honored.
- Copy a LinkedIn-ready version, post it manually, and record the URL.
- Capture performance evidence at the correct checkpoints.

**Success:** creates higher-quality, more consistent content without losing a chain of evidence.

### 4.3 Analyst / growth operator

**Jobs**

- Maintain metric definitions and data quality.
- Compare formats, topics, timing, and effort without over-claiming causality.
- Export raw rows and explain a forecast’s assumptions.

**Success:** reports are auditable and decisions are based on comparable cohorts.

### 4.4 Agent ensemble

**Jobs**

- Research competitors and audience context.
- Produce options within a defined brand voice.
- Identify factual claims requiring sources or approval.
- Reconcile data, highlight gaps, and prepare a decision-ready report.

**Success:** assists without inventing access, facts, metrics, or publishing outcomes.

---

## 5. Core operating model

### 5.1 Hierarchy

```text
Workspace (e.g., Example Company GTM)
  ├── Brand (Example Company)
  │   ├── Channel account (LinkedIn Company Page)
  │   ├── Channel account (Founder profile — separate lane, optional)
  │   ├── Growth objective(s)
  │   ├── Campaign / experiment(s)
  │   │   └── Content item(s)
  │   │       ├── draft versions / assets
  │   │       ├── approvals / human decisions
  │   │       ├── publication evidence
  │   │       ├── metric snapshots
  │   │       └── agent work / source evidence
  │   ├── Competitor / inspiration watchlist
  │   └── Reports and exports
  └── Audit ledger
```

### 5.2 Content lifecycle

The client must display these exact states and no shortcut may bypass them.

| State | Meaning | May count as live? | Required transition evidence |
| --- | --- | ---: | --- |
| `idea` | A hypothesis or content seed | No | author / source note |
| `researching` | Agent/human research is underway | No | task/reference |
| `draft_ready` | A draft is ready for internal review | No | versioned draft |
| `review_requested` | A named reviewer has been asked | No | request record |
| `changes_requested` | Review rejected or requested changes | No | reason |
| `approved_manual_publish` | Human has approved the exact version for manual posting | No | reviewer, version, timestamp |
| `posted_unverified` | Human says it was posted; no reliable post proof captured yet | No | manual attestation, optional external timestamp |
| `publication_verified` | Exact post URL or accepted platform evidence confirms the live post | Yes | URL/evidence + verification actor |
| `metrics_partial` | Live post has some, but not all expected measurement windows/fields | Yes | metric snapshot(s) and missingness state |
| `measured` | Required checkpoint coverage is complete or explicitly unavailable | Yes | metric checkpoint reconciliation |
| `archived` | Closed/superseded historical item | Historical only | archive reason |

Additional terminal state: `cancelled` for an item intentionally not shipped.

**Hard rule:** `approved_manual_publish` does not transition to `publication_verified` automatically. `posted_unverified` exists specifically to prevent an approval from being reported as a live post.

### 5.3 Publication evidence model

A verified publication needs one or more `PublicationEvidence` records:

```text
PublicationEvidence
  evidence_id
  content_id
  kind: post_url | platform_screenshot | platform_export | api_record
  source_uri?                 # canonical post URL when available
  artifact_id?                # protected Fabric artifact reference
  captured_at
  observed_published_at?
  submitted_by                # user / agent label; agent cannot assert manual posting without user input
  verification_state: pending | accepted | rejected
  verified_by?
  verified_at?
  notes?
```

- A pasted URL becomes `pending` until it passes basic validation and the user confirms it is the intended post.
- A screenshot/import can corroborate publication if it visibly identifies the post. OCR extraction is never silently authoritative; a human must confirm extracted fields.
- The UI must state whether publication time is platform-observed, user-entered, or unknown.

### 5.4 Metric snapshot model

```text
MetricSnapshot
  snapshot_id
  account_id
  content_id?                 # null for page/account-level metrics
  observed_at                 # when platform says the metric applies
  captured_at                 # when Fabric received it
  window: baseline | 1h | 24h | 72h | 7d | 28d | custom
  source: manual | csv_import | screenshot_confirmed | api_verified | web_analytics | crm
  confidence: entered | extracted_confirmed | verified | unavailable
  coverage: complete | partial | unavailable | stale
  values:
    followers_total?
    followers_net_new?
    impressions?
    reach?
    reactions?
    comments?
    reposts?
    saves?
    shares?
    clicks?
    profile_views?
    website_sessions?
    inbound_leads?
    qualified_inbounds?
    meetings?
    pipeline_value?
  source_reference?           # artifact or report origin
  notes?
```

All metric values are nullable. The distinction is mandatory:

| UI state | Meaning |
| --- | --- |
| `0` | Source explicitly reported zero |
| `—` / Not captured | No value has been observed |
| Partial | Some requested fields/window data are known |
| Unavailable | The integration/source cannot provide the field |
| Stale | Last capture is outside the workspace’s freshness threshold |
| Verified | Confirmed from an approved platform/API source |

### 5.5 Forecast model

A `Forecast` is a versioned scenario, not a claim of future truth.

```text
Forecast
  forecast_id
  objective_id
  created_at
  method: setup_pace | rolling_trend | scenario
  data_window_start?
  data_window_end?
  assumptions[]
  baseline_coverage
  sample_size
  low_estimate?
  expected_estimate?
  high_estimate?
  confidence: insufficient | directional | moderate
  explanation
```

Rules:

- `setup_pace` can appear after baseline, target, and target date are known.
- `rolling_trend` requires at least 7 days of comparable data and reports the window.
- Content-level performance forecasts require a minimum cohort configured by the workspace owner; until then, recommendations say “hypothesis” rather than “expected reach.”
- A 7–15% daily improvement is never a default forecast. It can be recorded as an experiment target only with baseline, metric definition, window, and sufficient sample.

---

## 6. Mobile information architecture and UX

### 6.1 Navigation

Promote the existing Social Studio Compose/Library surface into one canonical **Social** destination; do not leave two competing social entry points. The target connected mobile shell is:

```text
Home | Social | Sessions | Settings
```

- **Home:** remains Fabric-wide and can show a compact Social attention card when enabled.
- **Social:** the dedicated social-growth workspace, retaining Social Studio’s Compose and Library as draft/artifact entry points.
- **Sessions:** existing conversation/session browser.
- **Settings:** gateway, privacy, Social permissions/integrations, and notification schedules.

Android receives the equivalent Compose navigation destination. Mobile web receives the same hierarchy after the native contract/UI is defined.

### 6.2 Social tab: Today

The default Social screen is intentionally short and ranked.

1. **Workspace header** — selected brand/channel, data-health badge, “last synced/captured” time.
2. **Today’s decision** — one primary action, e.g. “Review Example Company’s exception-handling post before 11:30” or “Capture 24h metrics for the Jul 23 post.”
3. **Attention queue** — approvals, missing proof, overdue metric windows, stalled agent work.
4. **Growth pulse** — follower total/net new, impressions, quality engagement, inbounds; each shows current value, comparator, source quality, and coverage.
5. **Next seven days** — content cadence, experiment labels, owner, and human publish windows.
6. **Latest brief** — SOD/EOD/weekly report preview with export/download action.

The page must never render a zero-filled “success” card while the true state is unavailable.

### 6.3 Core screens

| Screen | Primary user action | Required states |
| --- | --- | --- |
| Setup wizard | define workspace, channel, goals, baseline, cadence, evidence policy | empty, saved draft, validation error, incomplete forecast |
| Today | choose next action | current, partial data, stale, offline/read-only, unsupported |
| Content queue | filter by lifecycle and owner | empty, loading, draft, needs-review, approved, live/measurement |
| Content detail | review exact post version and provenance | version diff, assets, sources, approval, publication evidence, metric checkpoints |
| Draft composer | give agent a brief or revise a draft | working, waiting for clarification, source warning, approval request |
| Post preview | inspect LinkedIn-oriented formatting | text-only/mobile preview, “approximate presentation” label, asset accessibility alt text |
| Manual publish handoff | copy post, open destination, record exact URL | approved, copied, URL pending, URL verified, verification failed |
| Metric capture | enter/import/confirm analytics | manual, screenshot extraction review, CSV mapping, unavailable, validation error |
| Report | read SOD/EOD/weekly executive brief | current, partial, stale, insufficient data, export created |
| Experiment detail | see hypothesis/comparison/results | planned, active, inconclusive, completed |
| Settings | manage data source, schedules, retention | unconnected, manual, authorized read-only, consent revoked |

### 6.4 Mobile content preview behavior

The preview helps the operator inspect hierarchy, line breaks, asset crop, CTA, alt text, and the approximate early-text cut. It must contain the following persistent disclosure:

> LinkedIn presentation and “Show more” behavior are platform-controlled. This preview is an editing aid, not a distribution prediction.

### 6.5 Accessibility requirements

- All status badges include spoken labels: e.g., “Publication unverified,” not color alone.
- Metric source/coverage appears in VoiceOver/TalkBack labels.
- Large type converts dense scorecards to vertical cards; never clip values or label a missing value as zero.
- Timestamp formats include local timezone and are not color-only.
- Tap targets: at least 44 pt iOS / 48 dp Android.
- CSV import mapping and approval choices are keyboard and screen-reader operable.

---

## 7. Agent ensemble

The ensemble is a set of named, constrained roles orchestrated by one **Social Growth Lead**. It is not a collection of agents that independently create public work.

| Role | Inputs | Allowed outputs | Must not do |
| --- | --- | --- | --- |
| Social Growth Lead | objective, scorecard, prior experiments, capacity | daily plan, prioritization, report, forecast assumptions | publish, invent performance data |
| Market/Competitor Scout | approved watchlist, public sources, saved evidence | concise observation brief with URLs and dates | claim private competitor metrics or copy protected content |
| Audience & ICP Researcher | ICP, customer evidence, current market context | pain points, language patterns, objections, source-backed claims | fabricate customer quotes |
| Brand/Voice Guardian | positioning, voice profile, previous approved posts | tone check, repetition/similarity warning, claim risks | overwrite an approved human voice silently |
| Content Strategist | campaign, proof pillar, research | 2–3 distinct angles and content brief | generate multiple near-duplicate rewrites when a pillar was rejected |
| Copy Editor | chosen angle, formatting constraints | post-ready copy, CTA, comments/reply suggestions | claim a platform algorithm outcome |
| Visual Direction Agent | approved asset library/design system | visual brief, alt text, asset checklist | fake product UI or imply a visual is proof when it is concept art |
| Measurement Steward | snapshots, source evidence, CRM/UTM policy | data-quality checks, metric reconciliation, CSV mapping | convert unknown data to zero or verified data |
| Report Analyst | verified ledger, completed activities, forecast inputs | mobile executive report, learning, next action | attribute inbound/pipeline without recorded source evidence |

### 7.1 Ensemble orchestration

For a proposed post:

1. Social Growth Lead selects objective and asks for needed research.
2. Scout/Researcher gather source-backed context.
3. Content Strategist offers materially distinct angles.
4. Voice Guardian checks for repetition and brand/claim issues.
5. Copy Editor produces the final candidate only after angle selection.
6. Visual Direction provides a brief only if a visual adds proof or comprehension.
7. Human reviewer approves a specific content version.
8. Human publishes manually and attaches evidence.
9. Measurement Steward prompts/validates 1h/24h/7d metrics.
10. Report Analyst summarizes outcome and confidence.

All role outputs are attached to the content item/job with source links, timestamps, and the model/agent session reference. The operator can inspect or discard them.

---

## 8. Reporting and data exports

### 8.1 SOD brief

The start-of-day report contains:

- growth pulse since prior day and rolling 7/28-day context;
- data-health warnings;
- open approvals / missing evidence;
- scheduled or recommended actions;
- today’s primary experiment hypothesis;
- expected result as a labeled scenario; and
- a concise ask if the agent requires human context.

### 8.2 EOD brief

The end-of-day report contains:

- actions completed and their verified status;
- posts live today vs approved/draft/unverified;
- metric changes with source/coverage;
- reactions, comments, reposts, saves, clicks, reach/impressions, followers, and inbound outcomes where available;
- deviations from forecast and explanation;
- data gaps; and
- the next-day plan.

### 8.3 Weekly review

The weekly report compares cohorts by explicit dimensions: channel lane, format, proof pillar, topic, publish window, effort band, and distribution. It must show sample size and avoid ranking two observations as a statistically meaningful “winner.”

### 8.4 Export requirements

Every workspace can generate a CSV artifact with machine-readable, normalized rows. At minimum export these files/relations:

```text
content_items.csv
metric_snapshots.csv
publication_evidence.csv
daily_scorecard.csv
experiments.csv
reports.csv
```

Required `daily_scorecard.csv` columns:

```text
workspace_id,brand_id,account_id,date_local,timezone,
followers_total,followers_net_new,impressions,reach,reactions,comments,
reposts,saves,shares,clicks,profile_views,website_sessions,inbound_leads,
qualified_inbounds,meetings,pipeline_value,
metric_coverage,source_confidence,posts_verified_live,posts_unverified,
posts_approved_manual_publish,posts_draft,primary_action,report_id
```

All absent numeric values export as empty cells, not `0`. An accompanying `README` in the artifact explains each field and source semantics.

---

## 9. Gateway contract and data architecture

### 9.1 Feature negotiation

Add one optional gateway feature key:

```text
social_growth
```

It is true only when all required methods are advertised. Add the key and method subset to the canonical gateway feature registry in `apps/mobile/contracts/gateway-feature-registry-v1.json`, then mirror through `apps/shared`, Swift, Kotlin, and mobile web capability parsers.

Required initial methods:

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

A client surfaces Social only when the verified negotiated contract advertises `social_growth` and this exact method subset. It must not probe individual methods or infer support from an error.

### 9.2 Server storage and ownership

- Store Social state in a profile-private gateway data store (proposed `social_growth.db` alongside profile-private durable state), never in the mobile client.
- Scope every record by gateway identity, Fabric profile, workspace, and brand/account authorization.
- External attachments use protected Fabric artifact references; mobile caches only bounded display metadata and clears on disconnect/profile switch.
- Social data needs a migration/version story, backup/export path, retention setting, and audit record for mutations.
- OAuth/API tokens, if introduced later, are encrypted server-side and separable from ordinary Social records. They never appear in prompt text, client logs, exports, screenshots, or chat history.

### 9.3 Versioned mutation rules

Every mutating Social method receives:

```text
expected_version: integer >= 1    # required for existing entity mutations
idempotency_key: UUID/string      # required for all external-facing mutations
```

Every receipt returns the entity after-state plus:

```text
mutation_id
replayed
version
```

On network ambiguity, the client displays **Outcome unknown — refresh to reconcile**. It does not resend a different mutation, infer success, or mutate a local row permanently.

### 9.4 Example RPC shapes

```text
social.content.transition {
  content_id,
  expected_version,
  to_state: "review_requested" | "changes_requested" | "approved_manual_publish" |
            "posted_unverified" | "publication_verified" | "metrics_partial" |
            "measured" | "archived" | "cancelled",
  reason?,
  idempotency_key
}
→ { content: ContentItem, mutation_id, replayed }

social.publication.record {
  content_id,
  expected_version,
  attested_published_at?,
  post_url?,
  note?,
  idempotency_key
}
→ { content: ContentItem(state:"posted_unverified"), evidence, mutation_id, replayed }

social.metric.record {
  account_id,
  content_id?,
  window,
  observed_at,
  source: "manual",
  values: { impressions?, reactions?, comments?, reposts?, saves?, clicks?, followers_total? },
  note?,
  idempotency_key
}
→ { snapshot: MetricSnapshot, mutation_id, replayed }
```

The server validates state transitions. For example, `publication_verified` is invalid without accepted publication evidence, and `measured` is invalid until required window reconciliation exists.

### 9.5 Events

Social emits authoritative gateway events after committed mutations:

```text
social.workspace.changed
social.content.changed
social.metric.changed
social.report.ready
social.attention.changed
social.audit.appended
```

Events contain bounded, redacted summary data. A client resyncs list/detail data when it detects a cursor/version gap; it never treats a pushed event as a complete record if the contract says otherwise.

### 9.6 Shared contract artifacts

Create canonical fixtures under `apps/mobile/contracts/fabric-social-v1/` for:

- valid bootstrap/list/detail records;
- all known content states and allowed transitions;
- unknown additive enum values;
- malformed entity payloads;
- missing metrics versus explicit zero;
- partial/unavailable/stale snapshots;
- publication URL and screenshot evidence states;
- mutation receipts, replayed receipts, stale expected versions, and outcome-unknown paths;
- export manifest and report summary.

TypeScript is the reference parser; Swift and Kotlin must validate against the same fixture corpus.

---

## 10. Integrations and permissions

### 10.1 Manual capture is a first-class integration mode

Initial account modes:

| Mode | What it allows | First-release status |
| --- | --- | --- |
| `manual_capture` | paste post URL, manually enter metrics, import screenshot/CSV | Required |
| `read_only_authorized` | future approved platform data read | Planned |
| `revoked` | retains history, blocks new sync | Required behavior |
| `unavailable` | connector/API not supported for account | Required honest state |

A manual workflow is not a degraded product. It is the default proof path until a connector is explicitly enabled and verified.

### 10.2 LinkedIn connector policy

- Do not begin implementation by assuming an API endpoint, page-admin scope, or analytics field is available.
- Validate the current official developer product, organization/page permissions, rate limits, and terms before adding a connector.
- Use a dedicated connector abstraction with declared capabilities (e.g., `read_page_analytics`, `read_post_analytics`), not a Boolean `linkedin_connected`.
- Default to read-only. Publishing is out of scope for the Social first release and requires a separate product/safety review even if API access later permits it.
- Every fetched snapshot stores exact source/capture metadata and field availability.

### 10.3 Attribution

The first release supports UTM template generation and manual CRM/analytics import. A downstream result is only labeled “LinkedIn-sourced” when it satisfies the workspace-defined attribution rule. The UI should distinguish:

- platform engagement;
- website session tagged with a social UTM;
- lead form/source entry;
- qualified inbound;
- meeting; and
- pipeline/revenue.

---

## 11. Notifications and schedules

Social may use Fabric’s existing scheduling/notification framework only after a workspace owner explicitly chooses a schedule and delivery destination.

Recommended configurable notifications:

- SOD brief at local business start;
- a publish-window reminder for an approved post;
- 1h / 24h / 72h / 7d metric-capture reminders after verified publication;
- EOD brief;
- weekly retrospective.

Push copy is redacted: e.g., “Example Company Social: 24h metrics are due for one post.” It deep-links to the exact in-app item and never includes raw platform credentials, post content that is embargoed, or one-tap external publishing.

No schedule is silently created in setup.

---

## 12. Delivery plan

### Phase 0 — Contracts and Social ledger

**Build:** shared social types/parsers/fixtures, feature gate, gateway service/store, permissions, audit ledger, basic workspace/objective/content/evidence/metric/report APIs.

**Do not build yet:** LinkedIn OAuth, native full dashboard, external publishing.

**Exit:** contract tests prove correct state transitions, unknown/null/zero semantics, stale-version handling, idempotent receipts, and capability fail-closed behavior.

### Phase 1 — Social Mobile vertical

**Build:** Social tab on iOS/Android, mobile-web proof surface, workspace setup, Today, content queue/detail, draft review, manual publication record, evidence attach/confirm, metric capture, data-health card, SOD/EOD report and CSV export handoff.

**Exit:** an anonymized company can run one company-page content item end-to-end from setup through verified URL and a partial 24-hour measurement state without an external API.

### Phase 2 — Agent ensemble and report jobs

**Build:** role templates, content/research/report job creation, source attachments, review/clarify loop, effort metadata, approved skill orchestration, report artifacts.

**Exit:** an agent-generated daily brief cites evidence, respects company/founder lane separation, and clearly labels unavailable data.

### Phase 3 — Approved read-only connectors

**Build:** connector capability model, system-browser OAuth where approved, server-side encrypted token store, read-only sync, data reconciliation, consent/revoke, connector diagnostics.

**Exit:** one supported account can pull approved analytics and show both connected and unavailable states correctly.

### Phase 4 — Experiment intelligence

**Build:** cohort comparisons, effort bands, timing/format/topic experiments, forecast scenarios, UTM/CRM adapters, mobile weekly review.

**Exit:** recommendations cite the exact cohort, data window, source coverage, and confidence.

---

## 13. Quality, security, and release criteria

Every build slice must meet the existing Fabric Mobile production invariants plus:

### Data integrity

- A draft never contributes to reach, interactions, or live-post counts.
- `posted_unverified` never counts as a verified live post.
- Metric `null`, explicit `0`, `partial`, `unavailable`, and `stale` render and export differently.
- All transitions validate server-side and return the expected entity/version receipt.
- An agent cannot create a false publication verification from its own output.
- A content report identifies source coverage for every total.

### Safety and privacy

- No social-network token is retained in mobile storage, transcripts, logs, or screenshots.
- Connector consent is explicit, viewable, and revocable in Settings/Trust Center.
- Attachment evidence respects gateway artifact access controls and does not become publicly accessible by default.
- Reports redact secrets and sensitive customer information by policy.
- External actions remain manual in the first release.

### UX and accessibility

- Screens cover loading, empty, offline/read-only, capability unsupported, partial-data, stale-data, validation error, outcome-unknown, and permission-revoked states.
- Light/dark screenshots, small device, AX XXXL, and screen-reader checks are captured for every new native screen.
- Metric provenance is visible without needing to open a detail screen.

### Verification

- Shared TypeScript contract tests pass.
- iOS Swift and Android Kotlin parsers pass the same Social fixtures.
- iOS local simulator + unsigned release build and Android test/build checks pass per the current mobile release contract.
- Mobile web type/test/build checks pass.
- A physical-device smoke test executes: setup → content approval → manual URL capture → metric import → report/export.
- Exported CSV is parsed in a test and preserves empty values for unavailable metrics.

---

## 14. Decisions to make with the design partner

Before building Phase 1, confirm:

1. the design partner’s current company-page follower baseline and target date.
2. Which exact metrics constitute the “200% interaction/reach” goal.
3. Which metrics should be required at each checkpoint (1h/24h/7d).
4. Company, founder, and employee account lanes and content-approval owners.
5. ICP, offer/CTA, attribution rule, CRM owner, and UTM convention.
6. Whether reports are delivered to the GTM owner only or a team channel as well.
7. Timezone, SOD/EOD schedules, weekly review time, and acceptable notification volume.
8. Evidence-retention policy for screenshots, assets, and customer-referenced material.
9. Authorized competitor/inspiration watchlist and ethical research boundaries.
10. Whether/when an official LinkedIn read-only connector can be evaluated.

Until these are set, the app should guide configuration and label forecasts/attribution as incomplete rather than pretending the strategy is fully specified.
