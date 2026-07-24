# Fabric Social Media Assistant — Product Specification

**Status:** Build-ready MVP specification and staged product direction
**Version:** 0.2
**Date:** 2026-07-23
**First delivery surface:** Responsive authenticated Fabric dashboard plugin
**Design-partner context:** An anonymized B2B company LinkedIn-growth workflow

> A social system that cannot prove a post or obtain platform data must say so plainly. It must never turn a copied caption, a user-entered URL, or missing analytics into a reassuring “live” dashboard.

---

## 1. Executive summary

Fabric Social helps a GTM team operate a company social-growth experiment without turning Fabric into a social-network publisher. It combines evidence-backed drafting, explicit human review, manual publication handoff, user-supplied performance observations, and decision-ready reporting.

The first implementation is intentionally **mobile-first, not native-first**:

- Existing Social Studio remains the text-first drafting flow inside Fabric sessions.
- A responsive `social-gtm` dashboard plugin becomes the durable, profile-scoped operating ledger and works in a phone browser.
- Core gateway RPCs, mobile PWA navigation, native iOS/Android screens, OAuth, platform API polling, scraping, and automated publishing are not MVP scope.

### Product promise

> From a phone, know what social action needs a human decision, what source supports a draft, what was only copied versus user-reported as posted, and what data is actually available.

### User outcome

A GTM operator can run a lightweight daily social loop while preserving:

- lane and voice boundaries;
- claim and source provenance;
- exact-version human review;
- manual-only external publication;
- distinction among known, unknown, partial, stale, and user-supplied metrics; and
- an auditable decision trail.

---

## 2. Verified implementation baseline

Fabric `main` already includes Social Studio across desktop, web, iOS, and Android.

| Existing component | What it provides | MVP implication |
| --- | --- | --- |
| `apps/shared/src/social.ts` | LinkedIn prompt builder and `linkedin-post` fenced-block parser | Use it for drafting presentation only; do not treat parser IDs as durable ledger identifiers |
| Social Studio Compose | Starts a Fabric chat with a structured social prompt | This is the MVP draft-entry path |
| Social Studio Library | Reads session transcripts and offers caption copy | A library result is not a publishing record or analytics source |
| `session.transcript` | Read-only session content | Link a draft back to a session only when the reference is truthfully available |
| Dashboard plugin surface | Authenticated tabs/slots and `/api/plugins/<name>/*` routes | This is the correct first durable operating surface |
| Mobile PWA | A focused, paired chat shell | It does not host dashboard plugins; do not add a Social tab in MVP |
| Native iOS/Android | Session/chat clients with capability-gated features | Do not claim or add native Social Growth UI in MVP |
| Cron | Scheduled agent work and report delivery | Cron is non-interactive; it may never publish or call a publish-like action |

### Architecture decision

The MVP is an **edge extension**, not a new core Social subsystem. The plugin uses dashboard authentication and a plugin-owned profile-scoped ledger. Sessions remain the source of drafting conversation; they are not repurposed as a versioned publishing ledger.

The dashboard REST authentication boundary is distinct from mobile PWA pairing-token WebSocket authentication. This is why the first dashboard experience is opened in a mobile browser rather than embedded in the PWA.

---

## 3. Product principles

### 3.1 Evidence before performance claims

Every observation has a source, observation time, capture time, coverage state, and actor. Unknown (`null`) is not zero. A user-entered metric is not presented as platform-API verified.

### 3.2 Human control over all public actions

Agents and cron may research, draft, suggest, classify supplied evidence, and prepare reports. They cannot publish, schedule, comment, react, follow, invite, reshare, or send messages on a social network.

### 3.3 Exact version approval

A reviewer approves one caption hash/version for manual copy. Any changed caption invalidates that approval. Generic Fabric tool approval is not a durable business approval record.

### 3.4 One truth per domain

- Fabric session: conversation and draft provenance.
- Plugin ledger: social operating state, reviews, user-reported publication records, metric observations, and reports.
- LinkedIn: external publication and native platform data, which are outside MVP control.

### 3.5 Decision cockpit, not content factory

The default question is “what should we do today?” A valid outcome is **hold**. Drafts must begin with an approved source, real operating observation, approved proof, or explicitly labeled opinion—not an instruction to generate a month of generic posts.

### 3.6 Privacy and local-first isolation

All ledger access is scoped by the authenticated Fabric profile at the plugin service boundary. The client cannot select another profile ID. No LinkedIn credentials, cookies, passwords, API tokens, or raw sensitive prompt content are stored in the plugin ledger.

---

## 4. Goals, non-goals, and KPI policy

### 4.1 Product goals

1. Help a GTM owner choose a social action, owner, and rationale in under five minutes.
2. Improve drafting consistency without fabricating claims or flattening company/founder voices.
3. Preserve proof that an exact version was reviewed for manual copy.
4. Capture user-supplied social evidence and metrics truthfully.
5. Produce mobile-readable SOD/EOD reports and a parseable CSV ledger.
6. Establish an extensible workflow without prematurely expanding core or native clients.

### 4.2 Non-goals for MVP

- Publishing, scheduling, commenting, reacting, following, invitations, messages, browser automation, or social-network scraping.
- LinkedIn OAuth, platform API polling, credential storage, or a provider adapter.
- Native iOS/Android screens or a mobile-PWA Social tab.
- Image generation, binary media storage, screenshot OCR, file import, or raw workspace media paths.
- Replacing CRM, web analytics, DAM, or LinkedIn native analytics.
- Claiming deterministic “Show more” placement, reach, engagement, or pipeline causality.
- Treating a copied caption, calendar entry, or user-entered URL as API-verified publication.

### 4.3 Outcome configuration

A workspace may configure goals such as:

| Outcome layer | Example | Required configuration |
| --- | --- | --- |
| Audience | Reach 10,000 page followers by a date | baseline, target, due date |
| Attention | Improve qualified interactions or impressions | exact metric, baseline window, comparison window |
| Demand | Improve LinkedIn-sourced qualified inbound | source definition, CRM/analytics policy, owner |
| Execution | Publish useful evidence-backed work consistently | cadence, review SLA, manual publisher, proof requirements |

The product may calculate an assumption-based pace only after a baseline, target, and date are present. It must label it as a pace, not a prediction.

A 7–15% daily improvement target is never a default KPI. It can be recorded as a bounded experiment hypothesis with a baseline, sample, metric definition, and comparison window. Use 7-day and 28-day trend windows for decision-making.

### 4.4 Pilot success measures

| Product measure | Pilot target | Definition |
| --- | ---: | --- |
| Review traceability | 100% | Every manual-copy approval records reviewer, caption hash, version, and timestamp |
| Publication honesty | 100% | Copied, held, user-reported, and unknown states are distinct |
| Metric provenance | 100% | Every entered value has source, capture time, and coverage label |
| Daily review | <5 min | Operator can see next decision, blockers, and owner |
| Evidence coverage | Team-selected | Expected URL/metric checkpoints are captured or explicitly unavailable |
| Learning trace | ≥1/week | A report connects a decision to its evidence and uncertainty |

---

## 5. Personas and jobs to be done

### GTM owner

- Set a baseline, target, cadence, lane boundaries, and owner responsibilities.
- Decide whether the company should publish, prepare, measure, reply, or hold.
- Read an evidence-led report without treating activity as business impact.

### Content operator

- Turn an operating observation or source into a credible company or founder draft.
- Request exact-version review, copy the result manually, and preserve what changed.
- Avoid reusing a rejected proof pillar or repeating recent posts.

### Reviewer and manual publisher

- Approve or hold a precise caption version.
- Publish externally as a human.
- Attest to a URL only when they actually know it; never imply Fabric published it.

### Report owner

- Record source-labeled manual observations.
- Mark unavailable or stale data honestly.
- Export normalized rows for executive review.

### Constrained agent ensemble

| Role | Allowed output | Must not do |
| --- | --- | --- |
| Social Growth Lead | Daily recommendation, prioritization, assumption-labeled plan | Publish or invent performance |
| Research/Competitor Scout | Dated, source-backed observation brief | Claim private competitor data or copy protected work |
| Brand/Voice Guardian | Repetition, claim, and tone warnings | Silently rewrite approved human voice |
| Content Strategist | Two or three genuinely distinct angles | Generate near-duplicate volume |
| Copy Editor | Draft-ready copy and manual handoff checklist | Promise algorithmic outcomes |
| Measurement Steward | Data-quality checks and report inputs | Convert unknown into zero or verified data |
| Report Analyst | Evidence-labeled summary, learning, next action | Claim causal inbound/pipeline without agreed evidence |

No role has a social-network publishing tool.

---

## 6. MVP operating model

### 6.1 Workspace and lanes

A workspace defines a social program for one authenticated profile. Each lane keeps separate voice and accountability.

```text
Workspace
  ├── Goal and baseline
  ├── Lane: Company Page
  ├── Lane: Founder (optional, separate voice)
  ├── Drafts linked to Fabric sessions
  ├── Review decisions
  ├── User-reported publication records
  ├── User-supplied metric observations
  └── Daily/weekly reports and CSV exports
```

Company, founder, employee, paid, and competitor observations must never be silently blended.

### 6.2 Draft and review lifecycle

```text
Draft
  draft → review_requested → approved_manual_copy
                         → changes_requested → draft
                         → held | cancelled
```

- `draft`: a suggestion, not a public action.
- `review_requested`: a human decision is needed.
- `approved_manual_copy`: the exact caption hash/version is approved for copying only.
- `changes_requested`: the reviewer gave a reason; a replacement draft needs new approval.
- `held`: the deliberate decision not to publish now.
- `cancelled`: the work is closed.

A copy receipt may be recorded, but it does not advance any external publication state.

### 6.3 Publication record lifecycle

```text
none → user_reported → url_recorded
```

- `user_reported`: a person attests that they posted outside Fabric.
- `url_recorded`: a person supplied an external URL.

Neither state means API verification. A future connector would require a separate authorization/security/product RFC before it could create a different evidence state.

### 6.4 Metric observation semantics

Each manual observation stores:

```text
MetricObservation
  id
  workspace_id
  draft_id?                 # optional for page-level values
  metric_name
  numeric_value?            # nullable
  unit
  observed_at?              # platform/reporting period if known
  captured_at
  source_kind: user_entered
  coverage: complete | partial | unavailable | stale
  freshness_threshold?
  entered_by
  supersedes_id?
  notes?
```

Required display semantics:

| Display | Meaning |
| --- | --- |
| `0` | Supplied source explicitly reported zero |
| `Not captured` | No observation exists |
| `Partial` | Some fields/checkpoints are known |
| `Unavailable` | The source cannot provide this field/window |
| `Stale` | The last observation is outside the agreed freshness window |
| `User-supplied` | A human entered or attested the value; it is not API-verified |

### 6.5 Forecast semantics

A forecast is a scenario with explicit assumptions.

```text
ForecastScenario
  goal_id
  method: setup_pace | rolling_trend | manual_scenario
  data_window_start?
  data_window_end?
  baseline_coverage
  sample_size
  assumptions[]
  low_estimate?
  expected_estimate?
  high_estimate?
  confidence: insufficient | directional | moderate
  explanation
```

- `setup_pace` requires baseline, target, and due date.
- `rolling_trend` requires a configured minimum of comparable observations.
- Content-level forecasts remain “hypothesis” until a comparable cohort exists.

---

## 7. Dashboard experience

### 7.1 Access and navigation

The MVP is a responsive dashboard plugin tab. It works on desktop and a phone browser through dashboard authentication. It is not embedded in the mobile PWA or native clients.

| View | Primary question | Required states |
| --- | --- | --- |
| Today | What needs a decision now? | no records, current, partial, stale, auth failure |
| Drafts | Which exact captions need review/manual copy? | draft, review requested, approved, held, changes requested |
| Evidence | What did a human report or enter? | no evidence, user reported, URL recorded, metrics partial/unavailable |
| Reports | What changed and what should happen next? | insufficient data, current, partial, stale, export ready |

### 7.2 Today hierarchy

Above the fold, show only:

1. the next decision, including a valid **hold** recommendation;
2. review and evidence blockers;
3. one compact data-quality-aware signal; and
4. owner and due time.

Do not render a zero-filled performance card when observations are unavailable.

### 7.3 Draft interaction

1. Start or select a Social Studio session.
2. Choose a caption snapshot and link it to the session when possible.
3. Set lane, audience, evidence type, and intended outcome.
4. Request review.
5. Reviewer approves exact hash, requests changes, or holds.
6. User copies the approved caption for manual LinkedIn publishing.

If a source session is unavailable, partial, or lacks a durable message reference, show that fact. Do not fabricate a link.

### 7.4 Evidence and reporting interaction

1. A human records a user-reported URL only after manually publishing outside Fabric.
2. A report owner enters known metrics and labels unavailable values.
3. The report highlights what is user-supplied, partial, stale, or unknown.
4. CSV export produces rows with empty cells for absent numeric values, never fabricated zeros.

### 7.5 Mobile quality requirements

- narrow phone layout with one primary decision per view;
- keyboard and screen-reader operability;
- 44px-equivalent touch targets and labels not conveyed by color alone;
- explicit error states for unauthenticated, unauthorized, offline, and failed loads;
- no blind offline mutation queue or automatic retry of review, URL, or metric writes.

---

## 8. Plugin data and API architecture

### 8.1 Plugin boundary

The plugin owns a profile-scoped SQLite ledger or repository-standard equivalent. All queries and mutations derive profile scope from authenticated server context. The plugin must not let a client choose a profile identifier.

Suggested bundled structure:

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

Follow the existing plugin manifest and service patterns; this is a design shape, not a new plugin loader.

### 8.2 Minimum entities

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

Values must be bounded and validated. Audit rows record safe summaries only; do not duplicate raw sensitive prompts or credentials.

### 8.3 Authenticated plugin API

Exact routing follows the plugin framework, but MVP behavior must support routes equivalent to:

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

There is deliberately no `/publish`, `/schedule`, `/oauth`, `/provider`, or route that forwards content to a social-network host.

Every existing-record mutation uses optimistic versioning or an equivalent conflict check and idempotency key. On an ambiguous outcome, the UI shows an outcome-unknown state and requires reconciliation rather than replaying an approval or evidence write.

### 8.4 Session and artifact constraints

- The current parser’s `messageIndex:blockIndex` shape is unstable under transcript changes and must not be used as a durable public ID.
- Never scan or expose other profiles’ sessions.
- Do not interpret raw workspace paths or arbitrary URLs in a social block as access-controlled media identifiers.
- Media, screenshot upload, OCR, and CSV import are deferred until an authenticated artifact/import contract is designed and verified.

---

## 9. Agents, skills, and scheduled work

### 9.1 Skill

A `social-gtm` skill may encode lane boundaries, source requirements, anti-repetition rules, manual-publication constraints, and report format. It must state that it can never publish or claim external performance without supplied evidence.

### 9.2 Sessions

Ordinary Fabric sessions provide research and drafting. The plugin records a source-session reference and selected caption snapshot; it does not claim the session itself is a social ledger.

### 9.3 Cron

Cron is permitted only after plugin-ledger access is verified, and only for:

- a daily source-backed research/draft recommendation; and
- an executive report based on plugin ledger data.

Cron output is a recommendation/report artifact, not a platform action. It must not contain or receive a route to publish, schedule, comment, react, or use credentials.

---

## 10. Security, privacy, and degraded behavior

### Security and privacy

- Dashboard plugin routes use existing authenticated dashboard access.
- Preserve profile isolation at the server boundary.
- Do not log credentials, raw sensitive prompts, URLs with secrets, or personal data beyond a user-selected operator identity needed for an audit record.
- Never request a LinkedIn password, cookie, or token.
- Do not automatically write social claims or metrics into Fabric Memory.

### Degraded behavior

| Condition | Required behavior |
| --- | --- |
| Unauthenticated/unauthorized | Explain access failure; do not show an empty ledger |
| Offline or network error | Disable mutations or show outcome unknown; do not queue blind retries |
| Source session unavailable | Show unavailable/partial source link; allow a draft without fabricated provenance |
| No metrics | Show not captured or unavailable, never zero |
| Changed draft after approval | Require a new review decision |
| URL supplied by a human | Label user-reported; do not claim verification |

---

## 11. CSV export

The MVP exports normalized rows for direct analysis. A basic `daily_scorecard.csv` may contain:

```text
workspace_id,lane_id,date_local,timezone,
followers_total,followers_net_new,impressions,reach,reactions,comments,
reposts,saves,shares,clicks,profile_views,website_sessions,inbound_leads,
qualified_inbounds,meetings,pipeline_value,
metric_coverage,metric_source,posts_draft,posts_approved_manual_copy,
posts_user_reported,posts_url_recorded,primary_action,report_id
```

All absent numeric values export as empty cells. An accompanying definition sheet or README must identify source and coverage semantics.

---

## 12. Acceptance criteria and phased delivery

### Phase 0 — Social Studio safety

- Social drafting clearly says **Copy for manual LinkedIn publishing**.
- Transcript/library failure states are distinguishable from no drafts.
- Assistant-only extraction, malformed blocks, multiple blocks, partial scans, and unavailable session references are covered by tests.
- No action in the flow contacts a social-network host.

### Phase 1 — Dashboard plugin ledger

- Authenticated profile-scoped workspace/lane/draft/review records work end to end.
- A changed caption invalidates approval.
- Copy receipt, user-reported post record, and URL record never count as verified platform publication.
- Manual metric values preserve null/zero/coverage/source semantics.
- Dashboard works at mobile and desktop widths with accessibility labels and honest empty/error states.
- CSV export is parseable and retains empty numeric cells for absent values.

### Phase 2 — Reports and non-publishing cron

- EOD report distinguishes actions, copied work, user-reported evidence, unknowns, and manual data.
- Any cron job is demonstrably unable to publish or call external social hosts.
- Reports link recommendations to explicitly supplied evidence and assumptions.

### Future separate RFCs

Require separate product, security, legal, and technical approval for:

- attachments, screenshot parsing, or CSV import;
- native/mobile-PWA integration;
- OAuth, external APIs, scraping, or read-only platform analytics;
- any provider connector; and
- any external social-network write action.

### Verification requirements

- profile-isolation tests for every API method;
- validation/bounds tests for captions, URLs, timestamps, metric values, and CSV cells;
- lifecycle, version conflict, idempotency, timeout/reconciliation, and audit tests;
- proof that no route/dependency makes an outbound social-network request;
- responsive/dashboard auth and accessibility tests;
- real authenticated local plugin smoke test at a phone-width viewport; and
- implementation PR reports exact commands, results, screenshots, known gaps, and deferred work.

The MVP is complete only when an authenticated user can link a session-backed caption, approve its exact hash for manual copy, record user-supplied evidence and metrics, read a truthful report, and export a CSV without external publishing, credentials, fake data, or unimplemented native claims.