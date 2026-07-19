# Fabric Achievement Journey V2

## Objective

Turn the private Achievements plugin into Fabric's interactive capability
curriculum: guide users to their next useful outcome, recognize durable
mastery, and make the breadth of Fabric discoverable without rewarding spend,
spam, idling, or unsafe behavior.

The primary product metric is the percentage of new users who complete
successful outcomes in at least three capability families during their first
seven active days. Raw hours, messages, API calls, tool calls, tokens, and cost
are private reflection metrics only.

## Product decisions

- Tracking is default-on, profile-local, inspectable, exportable, disableable,
  and deletable.
- No event or progress data leaves the device automatically.
- The next quest is the primary product; badges preserve evidence of mastery.
- Rank requires both XP and capability breadth, so repetition cannot substitute
  for learning Fabric.
- Existing V1 milestones remain visible in a Legacy collection and keep their
  earned timestamps.
- The leaderboard is secondary. Verified local progress and self-reported
  friendly cards never share the same ranking.

## What already exists

- `plugins/achievements/` provides a profile-scoped dashboard API, immutable
  unlock ledger, static 54-milestone catalog, manual share cards, and local
  leaderboard.
- `fabric_state.py` stores session timestamps, sources, models, billing
  providers, parent sessions, and aggregate counters.
- Message rows store structured timestamps and tool names, but the V1 plugin
  intentionally does not read the message table.
- `fabric_cli.plugins` already emits observer hooks for API calls, tool calls,
  turn/session lifecycle, subagents, approvals, and Kanban work.
- `web/DESIGN.md` defines Woven Operations: objective-first hierarchy, ledger
  sections, functional thread motifs, neutral surfaces, restrained purple, and
  explicit live states.
- Dashboard plugins receive authenticated `SDK.fetchJSON`, host navigation,
  semantic primitives, icons, and profile query scoping.

## Product model

### Levels

| Level | Gate |
| --- | --- |
| Explorer | 0–249 XP; complete one meaningful Fabric outcome to begin advancing |
| Operator | 250 XP, three achievements across two families, and the starter journey |
| Builder | 750 XP, seven achievements across four families |
| Orchestrator | 1,750 XP, twelve achievements across six families, and one multi-step quest |
| Weaver | 3,000 XP, seventeen achievements across seven families, successful parallel agents, and reliable automation or parallel sessions |
| Patternmaker | 4,500 XP, twenty-three achievements across eight families, plus successful skill authoring or an explicitly verified contribution |

XP has no fixed global denominator. Adding future quests never lowers a user's
existing completion percentage.

### Capability paths

1. Conversation — chat, resume, and cross-surface continuity.
2. Agent crew — delegation, successful parallel batches, and orchestration.
3. Deep work — bounded active intervals and meaningful completed outcomes.
4. Model lab — successful use of providers including OpenAI/ChatGPT and xAI/Grok.
5. Create — images, voice, design, and content workflows.
6. Computer use — browser and CUA workflows.
7. Automate — successful scheduled and durable recurring work.
8. Skills — use, breadth, authoring, and successful reuse.
9. Contributor — reusable improvements and explicitly verified contributions.
10. Anywhere — useful work across Fabric surfaces and profiles.

### Starter journey

The first-run journey is always available and contains three outcome steps:

1. Complete a real chat turn.
2. Let Fabric complete one tool call successfully.
3. Delegate one bounded task and receive a successful result.

Before the first action, the page names the three starter steps without showing
zero-valued score or catalog counters. After progress begins, it reports the
current step in plain language, such as `Step 2 of 3`. The primary action opens
Chat with a concrete prompt prefilled but not submitted. A separate copy action
is available when prompt prefill is unavailable.

### Quest types

- Starter quests teach the activation path.
- Daily Sparks recommend one small unfamiliar or unfinished capability.
- Weekly Expeditions require three meaningful outcomes across at least two
  capability families.
- Path quests teach one capability from first success through repeated mastery.
- Prestige achievements recognize rare accomplishments but award little or no
  repeatable XP.
- Legacy milestones preserve V1 history without influencing recommendations.

Daily Sparks are deterministic and persisted until completed, expired, or
rerolled. They take 5–15 minutes, offer one free reroll per local day, prefer
the nearest unfinished achievement and the chosen outcome path, avoid a family
used repeatedly, and never select credential entry, external publishing,
dangerous actions, paid/high-compute work, or hidden prestige quests. A Daily
Spark awards 10 Momentum at most once per day.

Weekly Expeditions unlock after three permanent achievements. Each is a
30–90-minute chain crossing at least two families, offers one free reroll, and
awards 60 Momentum once per local week. Missing one causes no XP, rank, or
streak loss. Momentum resets every 28 days and unlocks cosmetic checkpoints at
100, 250, and 400; it never affects permanent rank.

### Economy safeguards

- Only successful observed outcomes earn normal XP.
- Permanent mastery XP is awarded once per achievement. Repeatable outcomes
  earn a separate, capped Momentum score and never advance rank directly.
- Daily repeatable outcomes count at most once per capability family; weekly
  missions must cross at least two families.
- One observed event may satisfy multiple achievement predicates, but each
  immutable achievement unlock grants its XP only once. Events never carry XP.
- Rank gates require breadth and multi-step completion in addition to XP.
- Failures, interrupted work, retries, setup without successful use, raw token
  or API volume, dangerous-command approvals, and idle wall time earn no XP.
- A 20-agent run qualifies only when at least 80% of children finish
  successfully inside one objective. It is a hidden prestige achievement, not
  a farming path.
- A five-hour Long Haul requires a five-hour elapsed span, 300 engaged minutes
  after interval union, no idle gap over ten minutes, at least twenty meaningful
  events, and a completed output. It is hidden and prestige-only.
- Momentum is weekly and recoverable. Missing a day never destroys accumulated
  progress.

The reward model intentionally treats points and leaderboards as feedback, not
the product's main motivation. Controlled research found that these mechanics
can increase output quantity without increasing intrinsic motivation; newer
work likewise emphasizes whether rewards feel competence-supporting rather than
controlling. That is why Fabric defaults to personal mastery, meaningful
outcomes, choice of path, and loss-free Momentum, with competition kept in a
separate view ([Mekler et al.](https://research.aalto.fi/en/publications/towards-understanding-the-effects-of-individual-gamification-elem/),
[CHI 2026 reward interpretation study](https://doi.org/10.1145/3772318.3791046)).

### Launch catalog contract

V2 IDs never collide with V1 IDs. Catalog entries reference a small closed set
of Python evidence predicates; do not introduce a generic JSON rule language.
An event may unlock several distinct achievements, but XP is derived only from
unique immutable unlock rows. `historical` and `self_attested` evidence can be
displayed but does not grant rank XP or verified leaderboard score.

| ID | XP | Launch evidence |
| --- | ---: | --- |
| `conversation.first_thread` | 50 | One completed foreground turn |
| `conversation.keep_thread` | 100 | Three completed turns in one session |
| `conversation.everywhere` | 175 | Completed turns on two surfaces |
| `models.chatgpt_online` | 75 | Successful OpenAI/ChatGPT provider response |
| `models.grok_online` | 75 | Successful xAI/Grok provider response |
| `models.two_minds` | 125 | Both provider families used successfully |
| `skills.skill_spark` | 75 | One successfully used skill |
| `skills.capability_garden` | 175 | Five distinct successfully used skills |
| `skills.skillsmith` | 250 | Create or patch a skill, then use it successfully |
| `memory.remember_recall` | 150 | Store memory, then recall it in a later turn |
| `research.scout` | 75 | Successful web search in a completed turn |
| `research.brief` | 150 | Search plus two extracts and a completed saved artifact |
| `creative.image_maker` | 75 | One successful image generation |
| `creative.art_director` | 150 | Three successful image outcomes across two local days |
| `browser.navigator` | 100 | Navigation plus two successful browser actions in one turn |
| `cua.hands_on` | 125 | Three successful computer-use actions in one turn |
| `browser.web_operator` | 225 | Five browser/CUA workflows across three sessions |
| `voice.voice_on` | 75 | Successful transcription or TTS followed by a completed turn |
| `voice.full_duplex` | 200 | Successful transcription and TTS in one completed turn |
| `automation.clock_set` | 125 | Create an enabled schedule and complete its first successful run |
| `automation.reliable_loop` | 250 | Seven consecutive scheduled successes across seven days |
| `automation.quiet_machinery` | 400 | Thirty successes across fourteen days with ≥90% recent reliability |
| `agents.first_delegate` | 100 | One child completes with non-empty output |
| `agents.parallel_crew` | 200 | Three children, peak concurrency ≥3, ≥80% successful, parent complete |
| `agents.orchestra` | 350 | Eight children, peak concurrency ≥3, ≥80% successful, parent complete |
| `agents.swarm_commander` | 500 | Twenty children under the same success/concurrency contract; hidden |
| `sessions.parallel_pilot` | 250 | Two foreground sessions overlap for ten active minutes and both complete |
| `focus.focus_block` | 75 | Thirty meaningful active minutes plus a completed outcome |
| `focus.deep_work` | 175 | 120 meaningful active minutes plus a completed outcome |
| `focus.long_haul` | 400 | Five-hour/300-minute/twenty-event contract; hidden |
| `contribution.verified_builder` | 175 | A reusable skill improvement is used successfully in a later session |
| `content.linkedin_launch` | 0 | Explicit self-attestation after the guided draft/publish flow |
| `contribution.fabric_contributor` | 0 | Visible preview pending explicit opt-in upstream verification |
| `contribution.patternmaker` | 0 | Visible preview pending repeated explicit upstream verification |

The first 31 rows provide more than 4,500 attainable verified XP across at
least eight families, so Patternmaker never depends on LinkedIn or GitHub
claims. Unsupported preview quests remain visible in Paths, never appear in
Today, and never block lower ranks.

## Measurement architecture

```text
safe edge emitters ─> plugin hooks ─> closed projection ─> bounded queue
                                                           │
                                                           v
existing session aggregates ─┐                     profile-local SQLite
skill usage sidecar ─────────┼─> evidence facts ─> Journey evaluator ─> V2 unlocks
observed event ledger ───────┘                              │
                                                           ├─> Journey API
frozen V1 ledger/catalog ───────────────────────────────────┘   + Legacy UI
```

### Engineering boundary

- Freeze `catalog.py`, the V1 reconciliation behavior in `engine.py`, the V1
  JSON ledger, V1 card IDs, and share-card schema. V2 is additive and never
  rewrites V1 state during bootstrap.
- Add a closed V2 catalog/evaluator and one profile-local SQLite store for
  activity events, immutable V2 unlocks, challenge assignments, Momentum
  awards, and control metadata.
- `GET /summary`, `POST /refresh`, and existing share/import/delete endpoints
  remain V1-compatible. The new UI consumes `GET /journey` and additive Journey
  mutation/data-control routes.
- The general plugin system gains only `default_enabled: bool`. It is honored
  exclusively for a repository-bundled manifest; explicit disable wins, and a
  user/project/entry-point plugin can never self-authorize.
- A generic `capability_event` observer hook is added with concrete first-party
  emitters for successful skill use/authoring, memory store/recall, cron
  creation/run completion, and transcription. This is not a model tool and
  carries only closed action/status fields plus IDs that the recorder HMACs.
- Existing `post_tool_call` covers search, image generation, TTS, browser, and
  computer-use outcomes without reading arguments or results. Existing turn,
  API, and subagent hooks cover chat, provider use, active work, delegation,
  and concurrency.
- Dashboard CTAs use the existing Chat `fresh` + `draft` contract or existing
  product routes. No Chat code, prompt, tool schema, or system prompt changes.

### Historical backfill

Backfill is read-only and labeled `historical`:

- Session-table aggregates provide sessions, active days, surfaces, providers,
  models, delegated children, and coarse automation history.
- Skill `.usage.json` contributes only aggregate use/view/patch counters and
  hashed skill identities.
- V2 does not query the `messages` table. The frozen V1 ledger already preserves
  existing credit; avoiding ambiguous message/tool inference materially reduces
  privacy and double-counting risk.
- SQL must never select or deserialize content, reasoning, tool arguments or
  results, titles, paths, URLs, identities, token totals, or cost.
- Historical aggregates show `Previously seen` progress but cannot satisfy
  success-only XP, rank, duration, concurrency, or verified leaderboard gates.
- Backfill version and source are recorded so compaction or repeated refreshes
  cannot double count.

### Runtime event ledger

Use profile-local SQLite at `achievements-v2/events.db`. Writers use WAL,
`busy_timeout`, short transactions, and `INSERT OR IGNORE` idempotency.

Allowed event fields form a closed schema:

| Field | Contract |
| --- | --- |
| `event_id` | HMAC-derived idempotency key |
| `schema_version` | Positive supported integer |
| `event_type` | Closed enum |
| `occurred_at` | UTC epoch seconds |
| `duration_ms` | Non-negative bounded integer or null |
| `session_ref` | Profile-local HMAC reference or null |
| `turn_ref` | Profile-local HMAC reference or null |
| `subject_ref` | Profile-local HMAC reference or null |
| `capability` | Closed capability enum |
| `outcome` | `success`, `failed`, `interrupted`, or `historical` |
| `surface` | Closed Fabric surface enum or `unknown` |
| `provider` | Closed normalized provider enum or `unknown` |
| `count` | Positive bounded integer, normally 1 |
| `source` | `observed_hook`, `historical_inferred`, or `self_attested` |

There is no free-form attributes column.

Forbidden inputs are ignored before event construction: prompts, responses,
tool arguments/results, commands, goals, summaries, error text, URLs, paths,
filenames, generated content, post text, user/chat/account IDs, raw session or
tool IDs, secrets, tokens, cost, and base URLs.

Raw observed events are retained for 90 days. Before pruning, lifetime-safe
counts are folded into daily rollups by date, event type, capability, outcome,
surface, and provider. Earned unlock records remain immutable. Export exposes
only the same safe fields. Event deletion can preserve V2 unlocks; an explicit
Journey reset clears V2 progress, preserves V1 Legacy/friendly cards, and sets
a history floor so paused or deleted activity is not re-imported.

### Runtime sources

- `pre_llm_call` + per-turn `on_session_end`: completed foreground work and
  active intervals.
- `post_api_request`: successful provider use.
- `post_tool_call`: successful or failed closed tool capability, ignoring args
  and result payloads.
- `subagent_start` + `subagent_stop`: concurrency, duration, and completion.
- Kanban completion hooks: durable work outcomes.
- `capability_event`: successful skill, memory, transcription, and authoritative
  cron lifecycle outcomes without importing the achievements plugin from edge
  modules.

The achievements plugin gains a bundled-only default-enabled manifest. The
general plugin loader may honor a manifest default only for repository-bundled
standalone plugins; user/project/entry-point plugins remain opt-in. Explicit
disable always wins. `fabric plugins list` and the dashboard plugin roster must
report this effective state accurately.

Hook callbacks never write SQLite directly. Each process owns one lazy bounded
queue and a writer-thread-owned connection; inserts are batched, idempotent,
short, and fail open. Queue overflow is counted and exposed locally. SQLite WAL
is preferred for same-machine multi-process readers/writers; if the filesystem
cannot enable WAL, the store falls back to rollback journaling with the same
bounded busy retries rather than breaking Fabric.

### Active time

- Foreground intervals span `pre_llm_call` to per-turn `on_session_end`.
- Subagent and cron intervals represent background/autonomous work.
- Tool and API durations are nested evidence and are not summed separately.
- Compute interval unions, split at local-day boundaries for display, and cap
  foreground idle gaps at ten minutes. Cap meaningful active time at twelve
  hours per local day and discard sleep/clock discontinuities.
- Parallel-session quests require overlap between distinct session references;
  repeated events in one session do not qualify.

## Dashboard information architecture

```text
Achievements
├─ Today (default)
│  ├─ level + progress to next level
│  ├─ one primary next quest
│  ├─ up to two optional quests
│  ├─ weekly momentum
│  └─ recent wins
├─ Paths
│  ├─ selected path thread
│  └─ next, completed, and locked-by-prerequisite steps
├─ Collection
│  ├─ earned achievements
│  ├─ a small Up next section
│  └─ Legacy milestones
└─ Leaderboard
   ├─ personal bests
   ├─ local profiles
   ├─ optional verified team board (future)
   └─ separate Friendly board for imported self-reported cards
```

Canonical route:

```text
/workspace/achievements
  ?view=today|paths|collection|leaderboard
  &path=<path_id>
  &status=earned|active|legacy
  &board=you|profiles|friendly
  &focus=<quest_id>
```

Missing or invalid `view` resolves to `today`. View changes push browser
history; filters replace history. Existing `tab=achievements` migrates to
`view=collection`, and `tab=leaderboard` migrates to `view=leaderboard`. The
shell and plugin together must expose exactly one page landmark and one `h1`.
Today is the default view; the leaderboard defaults to personal comparison.

The shell owns the page `<main>`, visible `Achievements` `<h1>`, and scrolling
container for `layout: page`. The plugin renders a normal section root: no
nested landmark, duplicate heading, fixed viewport height, or nested page
scroll. This corrects the current plugin structure.

### Journey API projection

Keep V1 routes unchanged and add a bounded projection rather than exposing the
event schema directly:

```text
GET    /api/plugins/achievements/journey
POST   /api/plugins/achievements/journey/refresh
PATCH  /api/plugins/achievements/settings
POST   /api/plugins/achievements/quests/{quest_id}/snooze
POST   /api/plugins/achievements/quests/{quest_id}/attest
POST   /api/plugins/achievements/challenges/{daily|weekly}/reroll
GET    /api/plugins/achievements/activity/export
DELETE /api/plugins/achievements/activity
```

Launch deliberately consolidates activity inspection into the bounded export
instead of adding a second raw-event browsing API. This keeps the plugin
surface smaller and prevents an unbounded dashboard query path.

`GET /journey` returns `onboarding`, `mastery`, `today`, `paths`, `collection`,
`tracking`, and `newly_earned`. Every quest includes bounded title/copy,
confidence, exact progress text, estimate, readiness, and a closed action:
`chat` with a catalog-owned draft, `route` with an existing Fabric path, or
`none` with a concrete explanation. Frontend code never reconstructs evidence
or capability semantics.

Chat actions navigate to
`/workspace/chat?fresh=<unique-id>&draft=<encoded-prompt>`. Chat already removes
and sanitizes `draft`, places it in the composer, and never submits it. A CTA
never grants progress; only later authoritative evidence does.

### First-run hierarchy

1. Shell-owned page heading `Achievements`.
2. “Learn Fabric by doing” and one-sentence outcome explanation.
3. Compact outcome choice: Finish work faster, Build with agents, Create
   content, or Automate recurring work.
4. The three-step starter quest and one primary `Start in Chat` action.
5. Three recommended paths.
6. Compact “How progress is tracked” disclosure.

Do not show a completion ring, total score, `0 of N`, locked achievement wall,
empty leaderboard prompt, or large privacy banner before the starter action.

### Returning hierarchy

1. Current level, XP to next rank, and capability breadth.
2. One `Continue` quest with time estimate, progress, and action.
3. Weekly expedition and momentum.
4. Recent wins.
5. Paths and collection summaries.

The Today view contains one visually dominant Continue quest, at most two
optional quests, one weekly mission, compact momentum, at most three recent
wins, and at most two active paths. It explains the recommendation in one
sentence and allows a seven-day snooze. Unsupported or unconfigured
capabilities never appear in Today.

### Interaction states

| Surface | Loading | Empty/first run | Error/degraded | Success | Partial |
| --- | --- | --- | --- | --- | --- |
| Journey summary | Stable skeleton preserving hierarchy | Starter quest, never zero cards | Explain local source failure; retry | Level and next gate | Show available sources and confidence labels |
| Today quests | Quest-shaped skeleton | Outcome selector + starter | Keep last known quests; refresh | Primary + optional quests | Unsupported quests hidden with reason in Paths |
| Paths | Path-thread skeleton | All paths at first step | Per-path retry | Progress and next prerequisite | Historical credit labeled |
| Collection | Compact row skeleton | Warm “first win appears here” | Preserve earned ledger if event DB fails | Earned history | Legacy separated |
| Tracking controls | Disabled controls while loading | Default-on explanation | No destructive action on uncertainty | Confirm preference/export/delete | Event and historical sources reported separately |
| Leaderboard | Row skeleton | Personal records first | Local board remains if imports fail | Separate verified/friendly sections | Skipped profiles reported |

### Celebration

- A normal unlock is a non-blocking polite live-region notice with title, XP,
  capability learned, and one next-step action.
- Completing a path uses a full-width woven-thread treatment inside the page,
  never a blocking modal.
- Motion uses opacity/transform only and is disabled under reduced motion.
- Celebration effects can be disabled independently of tracking.

## User journey storyboard

| Step | User does | Intended feeling | Product support |
| --- | --- | --- | --- |
| 1 | Opens Achievements at zero | Curious, not judged | Outcome choice and one useful quest above the fold |
| 2 | Starts in Chat | Confident | Concrete prompt and visible 0-of-3 chain |
| 3 | Completes first tool outcome | Surprised by capability | Quiet unlock and explanation of what was learned |
| 4 | Delegates a task | Powerful | Progress advances to completed starter journey |
| 5 | Returns next day | Oriented | One personalized next quest, not a catalog reset |
| 6 | Explores Paths | Ambitious | Prerequisites and mastery depth are explicit |
| 7 | Shares progress | Proud and in control | Readable local share card; no automatic upload |

Five-second experience: one clear next action. Five-minute experience: a real
Fabric outcome. Long-term experience: a credible private record of capability
breadth and mastery.

## Design-system alignment

- Reuse semantic plugin primitives, Fabric icons, system typography, native
  focus treatment, and host tokens.
- Use one active purple thread for the current quest/path; keep at least 90% of
  the surface neutral.
- Use ledger sections and ruled quest rows, not equal-weight card grids.
- Cards represent actual quest/path objects only.
- Keep the woven canvas for first-run and path-completion moments, not dense
  catalog reading.
- All copy is concrete and sentence case. Replace poetic labels that hide the
  capability being learned.

## Responsive and accessibility contract

- The plugin route renders one page landmark and one page-level heading.
- On mobile, the primary quest and CTA appear before privacy and statistics.
- Level progress is a compact horizontal summary; zero metrics never stack into
  the first viewport.
- Paths become an ordered outline with the active step expanded.
- Leaderboard rows become vertical records on narrow screens rather than a wide
  horizontal table.
- Every target is at least 44 by 44 CSS pixels.
- Status always has icon/shape, label, and optional color.
- Tab and path navigation support arrow, Home, End, Enter, and Space where
  appropriate; focus remains visible.
- Unlocks use `aria-live=polite`; decorative motion is hidden from assistive
  technology.
- Progress exposes exact text such as “2 of 3 successful agent runs.”
- Activity feedback uses the user's local calendar, while stored timestamps
  remain UTC.
- Metadata text remains at least 12px and meets contrast requirements at 200%
  zoom in both Fabric themes.

## Tracking controls

`How progress is tracked` opens a focused disclosure containing:

- Tracking status and profile name.
- Exact allowed event fields and forbidden content categories.
- Counts by source: observed, historical, and self-verified.
- `Export activity metadata` action.
- `Pause tracking` / `Resume tracking` action.
- `Delete activity metadata` destructive action with explicit confirmation.
- A note that pausing does not delete earned achievements and that deletion does
  not remove immutable unlock history unless a separate future reset is added.

Behavioral preferences are profile-scoped keys in `config.yaml`, never `.env`:
tracking defaults on for this bundled plugin, active-time tracking can be
disabled independently, and celebration mode is `standard`, `quiet`, or `off`.
Pausing prevents new events and evaluation, preserves earned progress, and does
not backfill the paused interval later.

## Migration

1. Preserve the V1 unlock JSONL and imported cards unchanged.
2. Create V2 settings and event stores lazily under the selected profile.
3. Run versioned historical backfill idempotently.
4. Map existing earned milestones into the Legacy collection.
5. Do not convert inferred historical attempts into observed success.
6. Share-card readers accept V1; V2 cards add level, breadth, and source labels
   under a new schema version with strict bounds.

## Testing contract

- Seed every rich hook payload field with sentinel secrets; assert none reach
  SQLite, logs, exports, summaries, or errors.
- Assert V2 historical queries never touch the `messages` table and select only
  the approved session columns; keep the source database byte-identical.
- Reject unknown event fields/enums, negative or unbounded values, and raw IDs.
- Test idempotent duplicate delivery and concurrent multi-process writers.
- Verify 20 overlapping children yields concurrency 20 while serial children
  yield 1.
- Verify interval union, nested subagents, midnight splits, idle gaps, and clock
  anomalies.
- Test provider fallback and mid-session provider changes.
- Test success/failure distinctions for tools, images, browser/CUA, voice, and
  automation.
- Test default-on, pause, export, delete, and profile isolation.
- Test backfill does not double count after compaction or repeated refresh.
- Test V1 unlock/import preservation and V1/V2 share-card compatibility.
- Assert system-prompt bytes and model tool schemas are unchanged.
- Assert hook/storage failures never break user work.
- Cover all dashboard loading, first-run, error, success, and partial states;
  keyboard navigation; reduced motion; mobile layouts; and theme contrast.

### Code-path and user-flow coverage

```text
CODE PATH COVERAGE
==================
[+] generic plugin loading
    ├─ bundled default enabled / explicit disabled / user override ignored
    ├─ effective status in CLI + dashboard roster
    └─ registration is import-safe and performs no I/O

[+] edge capability signals
    ├─ skill use + authoring
    ├─ memory store + recall
    ├─ cron create + successful/failed scheduled run
    └─ transcription success/failure

[+] observer and local store
    ├─ rich hook payload -> closed projection -> no forbidden data
    ├─ disabled/malformed config -> no collection
    ├─ bounded queue -> batch writer -> idempotent insert/reduction
    ├─ duplicate and out-of-order start/stop
    ├─ concurrent processes / SQLITE_BUSY / non-WAL fallback
    ├─ crash-stale starts -> interrupted without invented duration
    ├─ 90-day reduction + purge + checkpoint
    └─ delete generation rejects pre-delete queued events

[+] Journey evaluator
    ├─ evidence confidence and per-turn/capability deduplication
    ├─ starter steps may arrive out of order
    ├─ one-time XP + breadth/rank gates
    ├─ active-time union / midnight / overlap / clock anomaly
    ├─ agent peak concurrency + 80% success + parent completion
    ├─ deterministic Daily baseline/reroll and Weekly two-family chain
    ├─ Momentum idempotency and 28-day reset
    └─ V1 ledger bytes, timestamps, unknown IDs, cards, and imports preserved

[+] Journey API
    ├─ bounded projection and profile isolation
    ├─ strict settings with unrelated config preserved
    ├─ sanitized inspect/export and both deletion scopes
    ├─ Friendly cards separated from verified local profiles
    └─ partial legacy/event-store failures remain recoverable

USER FLOW COVERAGE
==================
[→E2E] Fresh profile -> Today -> safe Chat draft -> observed turn -> first win
[→E2E] Tool success -> starter progress; failed tool earns nothing
[→E2E] Three concurrent children -> Parallel Crew; serial children do not
[→E2E] Pause -> work -> resume -> paused interval is never backfilled
[→E2E] Reset V2 progress -> Legacy remains -> stale queued event is rejected
[→E2E] Route history, old tab migration, Back, deep-linked path/filter/board
[→E2E] Keyboard-only tabs/paths/settings/delete and grouped live announcement
[→E2E] Mobile first-run/returning/leaderboard with no horizontal or nested scroll
```

Every branch above requires a behavior test. Pure projection, evaluator, store,
and routing helpers use unit tests; hook-to-store-to-API and deletion races use
integration tests; browser-visible route/history, accessibility, and responsive
flows use dashboard component/browser tests. No LLM eval is required because
the change does not modify prompts, system instructions, or model tool schemas.

### Production failure modes

| Path | Failure | Handling and required proof |
| --- | --- | --- |
| Plugin loading | A user plugin sets `default_enabled` or shadows the bundled key | Source trust check ignores it; loader and CLI-status regression tests |
| Registration | Import starts a thread/creates files and slows every command | Register callbacks only; no-I/O import test |
| Settings | Malformed Boolean accidentally enables collection | Fail closed for tracking; API exposes `settings_invalid`; unit test |
| Projection | Sentinel prompt/result/path leaks through a hook | Construct events only from selected scalars; raw SQLite/WAL/export/log scan |
| Queue | Burst exceeds capacity | Drop rather than block user work; persist a local dropped counter and warning |
| SQLite | Writer is busy or WAL unsupported | Bounded retries, rollback-journal fallback, fail open; concurrency tests |
| Lifecycle | Crash leaves a turn/agent `started` | Reconcile after 24 hours as interrupted with no invented duration |
| Idempotency | A replayed hook double-awards XP | Stable keyed IDs + insert/reduce once + immutable unique unlock; replay tests |
| Retention | Purge loses evidence before folding it | Seal rollup in the same transaction before delete; boundary tests |
| Reset | Old queued events repopulate deleted progress | Increment generation; reject stale-generation writes; race test |
| Backfill | Refresh imports activity performed while paused | Persist history floor and cutoff; pause/resume integration test |
| Active time | Sleep, clock jump, or one long wait becomes five hours | Ten-minute gaps, clock checks, interval union, and twenty-event Long Haul gate |
| Agents | Twenty spawned failures earn prestige | Unique completed children, ≥80% success, peak ≥3, parent completion |
| Leaderboard | Self-reported card outranks verified local work | Separate response collections and visible labels; API/UI tests |
| UI | Slow section request clears usable state | Preserve last good section, show inline warning/retry; component test |
| CTA | Clicking a quest awards progress or auto-submits content | Navigation only; existing draft-prefill contract; browser test |
| Legacy | V2 bootstrap rewrites/mangles old achievements | Byte-stability and unknown-ID fallback tests |

No failure above may be silent while also lacking error handling and a test.

### Implementation ownership

- Generic host surface: `fabric_cli/plugins.py`, `fabric_cli/plugins_cmd.py`,
  `fabric_cli/config.py`, and their focused tests.
- Privacy/event foundation: achievements `plugin.yaml`, `__init__.py`, and new
  event projection, observer, and SQLite-store modules plus edge emitters.
- Product model/API: new Journey catalog/evidence/engine modules and additive
  `dashboard/plugin_api.py` routes. V1 catalog/store/share cards stay frozen.
- Dashboard: achievements `dist/index.js`, `dist/style.css`, manifest/README,
  static contracts, and a raw-IIFE React integration test under `web/src/plugins`.
- Inline ASCII comments belong at the queue-to-writer lifecycle, active-time
  interval reducer, and Daily/Weekly assignment state machine.

## Rollout

1. Land the event/store/privacy foundation and migration tests.
2. Land quest evaluation, rank gates, daily/weekly selection, and API shapes.
3. Replace the dashboard with Today, Paths, Collection, and Leaderboard.
4. Run backend, web, docs, identity, privacy, browser, responsive, keyboard,
   screen-reader, and reduced-motion QA.
5. Ship the complete starter journey with the initial path catalog. Do not ship
   the recorder without the user-facing inspect/pause/export/delete controls.

## NOT in scope

- Automatic uploads, remote analytics, or a global leaderboard.
- Functional rewards, paid advantages, or model/tool access gated by XP.
- Reading prompts, replies, tool arguments/results, URLs, paths, generated
  content, post text, identities, cost, or token totals.
- Parsing terminal commands to infer contributions or social publishing.
- Automatic LinkedIn posting or a new social connector.
- Claiming an upstream Fabric PR is merged without explicit opt-in verification.
- A shared team service; the API and event schema may support it later, but V2
  remains local.
- Rebuilding Chat or adding a second composer to the dashboard.

## Decisions log

| Date | Decision | Rationale |
| --- | --- | --- |
| 2026-07-19 | Build Fabric Journey rather than expand the metric catalog | Guided next actions increase capability discovery; raw counters do not |
| 2026-07-19 | Default-on local-only event ledger | Precise success measurement without outbound telemetry or content capture |
| 2026-07-19 | Hybrid historical backfill plus observed future events | Existing users retain credit while future quests gain reliable semantics |
| 2026-07-19 | Personal mastery before competition | Prevents spend, time, and agent-count incentives from dominating learning |

## RSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
| --- | --- | --- | ---: | --- | --- |
| CEO Review | `/plan-ceo-review` | Scope and strategy | 0 | — | Product north star was resolved by the brainstorming pass |
| Codex Review | `/codex review` | Independent second opinion | 0 | — | Parallel specialist reviews covered instrumentation, economy, UX, and architecture |
| Eng Review | `/plan-eng-review` | Architecture and tests (required) | 1 | CLEAR | 24 issues resolved in-plan; 0 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 1 | CLEAR | Score 3/10 → 10/10; 20 decisions |

**UNRESOLVED:** 0

**VERDICT:** ENG + DESIGN CLEARED — ready to implement. Run `design-review`
after implementation for visual QA.
