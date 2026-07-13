# CONNECT + SYSTEM Sections Revamp — Implementation Spec ("Agentic Look")

Scope: the four pages in the **Connect** nav group — Channels, Webhooks, Pairing,
Files — and the four in the **System** bottom cluster — Profiles, Config, Keys (Env),
System — per the design direction in `docs/design/dashboard-revamp-research.md`
("terminal-grade minimalism", single accent, value-density metric) and the shared
vocabulary shipped by `docs/design/work-section-spec.md` (G1–G13),
`docs/design/observe-section-spec.md` (O1–O7), and
`docs/design/capabilities-section-spec.md` (CAP1–CAP10, `CapabilityRow`,
`capability-state.ts`).

Framing: **Connect is the agent's senses; System is the operator's console.**
Channels are the platforms the agent listens on, Webhooks are the HTTP events it can
receive, Pairing is who is allowed to talk to it, Files is what it can reach on disk.
Profiles are the agent's identities, Config is its standing orders, Keys are its
credentials, System is the health and lifecycle of the machine it runs on. Connect
surfaces render in the CapabilityRow five-zone grammar wherever items are equipment;
runtime link state (a channel actually being connected) renders in the G1
agent-status vocabulary — the two axes are never merged (CN1).

Status: implementation-ready. Requirements are numbered `CN` (shared), `H` (Channels),
`W` (Webhooks), `D` (Pairing), `F` (Files), `PR` (Profiles), `CF` (Config), `E` (Env/
Keys), `Y` (System). Non-goals and risks continue the Work/Observe/Capabilities
numbering (`N21+`, `R22+`); Appendix A continues at `A-4`, Appendix B at `B24`.
`G*`/`O*`/`CAP*` references are the prior shared rules, reused as-is.

Source-of-truth files audited (2026-07-13):

- Frontend: `web/src/pages/{ChannelsPage,WebhooksPage,PairingPage,FilesPage,
  ProfilesPage,ConfigPage,EnvPage,SystemPage}.tsx`, `web/src/pages/SystemPage.test.tsx`,
  `web/src/components/{EgressStatusCard,OAuthProvidersCard,FabricConsoleModal,
  AutoField}.tsx`, `web/src/components/sessions/GatewayStrip.tsx`,
  `web/src/components/{SidebarStatusStrip.tsx,sidebar/GatewayDot.tsx,
  sidebar/SidebarSystemActions.tsx}`, `web/src/hooks/useSidebarStatus.ts`,
  `web/src/components/ui/` (full barrel incl. `CapabilityRow`, `capability-state.ts`,
  `RunRow`, `agent-status.ts`, `source-icons.ts`), `web/src/lib/api.ts`,
  `web/src/contexts/{ProfileProvider.tsx,useProfileScope.ts}`, `web/src/i18n/types.ts`
- Backend: `fabric_cli/web_server.py` — status (~L2566), messaging platforms
  (~L7093–8400), Telegram/WhatsApp onboarding (~L7791–8309), gateway lifecycle
  (~L3427, ~L12951), webhooks (~L12794–12938), pairing (~L12719–12768), managed
  files (~L1352–2138), profiles (~L14131–14700), config (~L5355, ~L6292, ~L15508),
  env (~L6442–6718, `_channel_managed_env_keys` ~L7134), provider OAuth (~L8854),
  system stats/update/ops (~L2846, ~L3510–3689, ~L13177–13569), action status
  (~L3932); `gateway/platforms/base.py` (~L3075 platform state writes),
  `gateway/pairing.py` (PairingStore)

---

## 0. Data audit — what the backend actually serves TODAY

Everything in the main spec is buildable against these endpoints as they exist now.
Anything requiring server work is in Appendix B only.

### 0.1 Channels + gateway/platform status

**There is no `/api/channels*` route.** The Channels page is served by
`/api/messaging/*`; the sidebar strip and SessionsPage `GatewayStrip` read
`/api/status`. **Both draw platform runtime state from the same source** — the
gateway writes `gateway_state.json` (`write_runtime_status`), the web server reads
it back (`read_runtime_status()`), so the two endpoints agree by construction.

| Endpoint | Shape (verified) |
|---|---|
| `GET /api/status` (~L2566, profile-scoped, public liveness probe) | `{version, release_date, config_version, latest_config_version, can_update_hermes, gateway_running, gateway_state (starting\|running\|draining\|degraded\|startup_failed\|stopped\|null), gateway_platforms: {id → {state, error_code, error_message, updated_at}}, gateway_exit_reason, gateway_updated_at, active_sessions, active_agents, gateway_busy, gateway_drainable, restart_drain_timeout, auth_required, auth_providers[], nous_session_valid, egress {mode, status, available, scope, reason, allowed_private_cidr_count}, profiles[], gateway_mode}` + (loopback only) `hermes_home, config_path, env_path, gateway_pid, gateway_health_url, gateways[]`. `gateway_platforms` is **filtered to configured platforms and blanked when the gateway is down**. |
| `GET /api/messaging/platforms` (~L8310, profile-scoped) | `{env_path, gateway_start_command, platforms: [{id, name, description, docs_url, enabled, configured, gateway_running, state, error_code, error_message, updated_at, home_channel {platform, chat_id, name, thread_id?}\|null, env_vars: [{key, required, is_set, redacted_value, description, prompt, help, url, is_password, advanced}], whatsapp_setup? {mode, allowed_users_set, home_channel_set}}]}` |
| `PUT /api/messaging/platforms/{id}` (~L8331) | body `{env?, clear_env?, enabled?}`; validates keys against the platform's `env_vars` (400 otherwise); writes profile `.env` values + `platforms.{id}.enabled` config. **Does not restart the gateway.** |
| `POST /api/messaging/platforms/{id}/test` (~L8374) | `{ok, state, message}` — pure diagnostic, no side effects |
| WhatsApp onboarding `POST …/whatsapp/onboarding/start`, `GET …/{pairing_id}`, `POST …/{pairing_id}/apply`, `DELETE …/{pairing_id}` (~L7791–7936) | payload `{pairing_id, status (starting\|installing\|waiting…\|connected\|error\|expired\|cancelled), qr_payload, expires_at (TTL 600 s), mode, allowed_users, account_id/name/phone, error}`; apply persists creds **and restarts the gateway** |
| Telegram onboarding `POST …/telegram/onboarding/start` etc. (~L8091–8309) | proxied to an external pairing service; `{pairing_id, suggested_username, deep_link, qr_payload, expires_at}`; status `waiting\|ready (+bot_username, owner_user_id)`; apply → `{ok, needs_restart, restart_started?, restart_action?, restart_error?}` |
| `POST /api/gateway/restart` / `start` / `stop` (~L3427, ~L12951) | spawn `fabric gateway <verb>` → `{ok, pid, name: "gateway-restart"\|"gateway-start"\|"gateway-stop"}`; progress via `GET /api/actions/{name}/status` |

**Platform `state` semantics (the load-bearing finding):** the gateway itself only
ever persists `connected | disconnected | fatal` (`gateway/platforms/base.py`
~L3075). Everything else the dashboard shows — `disabled`, `not_configured`,
`pending_restart`, `startup_failed`, `gateway_stopped` — is a **web-server-derived
overlay** computed per request (~L7361–7379). So the state field mixes two axes:
configuration (disabled/not_configured/pending_restart) and runtime
(connected/disconnected/fatal, plus the gateway-level gateway_stopped/
startup_failed). CN1/CN2 formalize that split; the frontend must never re-derive
the overlay itself (R23).

**No per-channel usage telemetry exists** on the messaging endpoints. But
`GET /api/sessions/stats` already serves `by_source` counts (Observe §0.2) — a
truthful, zero-backend "N sessions" evidence segment per platform (H6).

### 0.2 Webhooks

| Endpoint | Shape |
|---|---|
| `GET /api/webhooks` (~L12813) | `{enabled, base_url, subscriptions: [{name, description, events[], deliver (default "log"), deliver_only, prompt, script, skills[], created_at (ISO), url, secret_set, enabled}]}` — secret always masked |
| `POST /api/webhooks/enable` (~L12829) | sets `platforms.webhook.enabled=true` **and restarts the gateway**; `{ok, enabled: true, needs_restart, restart_started?, restart_error?, …}` |
| `POST /api/webhooks` (~L12850) | create; guards: receiver must be enabled (400), name `^[a-z0-9][a-z0-9_-]*$` (400), `deliver_only` with `deliver=="log"` rejected (400); secret auto-generated (`token_urlsafe(32)`) when omitted; returns route summary **+ plaintext `secret` exactly once** |
| `DELETE /api/webhooks/{name}` (~L12904) | `{ok}` / 404 |
| `PUT /api/webhooks/{name}/enabled` (~L12921) | `{ok, name, enabled}` — hot-reloads in the running receiver |

**No test-fire endpoint, and no last-delivery data of any kind** — only
`created_at`. Delivery evidence is Appendix B24 (decision in §3.1). The create
endpoint accepts `skills[]`, `script`, `deliver_chat_id` that the current form never
sends (Appendix A-5).

### 0.3 Pairing

| Endpoint | Shape |
|---|---|
| `GET /api/pairing` (~L12719) | `{pending: [{platform, code (first 8 hex of the code **hash**, or "legacy"), user_id, user_name, age_minutes}], approved: [{platform, user_id, …persisted info incl. user_name}]}` |
| `POST /api/pairing/approve` (~L12728) | `{platform, code}` → `{ok, user}`; 400/404, **429 after MAX_FAILED_ATTEMPTS lockout** |
| `POST /api/pairing/revoke` (~L12750) | `{platform, user_id}` → `{ok}` / 404 |
| `POST /api/pairing/clear-pending` (~L12764) | `{ok, cleared}` |

No raw request timestamps (only `age_minutes`), no QR here (channel QR onboarding
lives on Channels, §0.1), no push channel — the list is fetch-on-demand.

### 0.4 Files (managed files)

| Endpoint | Shape |
|---|---|
| `GET /api/files?path=` (~L1893) | `{path, parent, entries: [{name, path, is_directory, size (null for dirs), mtime (epoch s float), mime_type}], root, locked_root, can_change_path}` — dirs first; **sensitive entries filtered server-side** |
| `GET /api/files/read` (~L1925) | `{name, path, size, mime_type, data_url}`; 413 over 100 MiB, 403 for sensitive paths |
| `POST /api/files/upload-stream` (~L2031) | multipart `file/path/overwrite`; chunked, atomic rename, 413 mid-stream |
| `POST /api/files/mkdir` (~L2095), `DELETE /api/files` (~L2116) | `{ok, entry/path, …meta}`; cannot delete locked root |

Guards: `_resolve_managed_path` rejects `..` (400) and escapes of `locked_root`
(403). `_is_sensitive_path` hides credential files (`auth.json`, `.env*`,
`config.yaml`, token stores…) and whole trees (`mcp-tokens`, `pairing`, `backups`,
`state-snapshots`) **on the read side only** — write endpoints deliberately skip
the guard (documented backend design decision; see R31). The separate `/api/fs/*`
family (editor/picker filesystem) is not this page and stays out of scope.

### 0.5 Profiles

| Endpoint | Shape |
|---|---|
| `GET /api/profiles` (~L14336) | `{profiles: [{name, path, is_default, model, provider, has_env, skill_count, gateway_running, description, description_auto, distribution_name/version/source, has_alias}]}` |
| `POST /api/profiles` (~L14348) | create/clone: `{name, clone_from?, clone_all, no_skills, description?, provider?, model?, …}` → `{ok, name, path, model_set, mcp_written, skills_disabled, hub_installs[]}` |
| `GET/POST /api/profiles/active` (~L14461/14482) | `{active, current}` — **`active` = sticky default** (what new CLI/gateway runs use); **`current` = the profile this dashboard process is scoped to**. POST sets the sticky default only; it never retargets the running process. |
| `PATCH /api/profiles/{name}` (rename), `DELETE` (~L14561/14576) | `{ok, …}` |
| `GET/PUT /api/profiles/{name}/soul` (~L14594) | `{content, exists}` / `{ok}` |
| `PUT …/description`, `POST …/describe-auto` (~L14616/14659) | `{ok, description, description_auto}`; auto-describe uses an aux LLM, sets `description_auto: true` |
| `PUT …/model` (~L14639) | `{ok, provider, model}` |
| `GET …/setup-command` (~L14502) | `{command}` (`"fabric setup"` / `"{name} setup"`) |
| `POST …/open-terminal` (~L14507) | spawns an OS terminal **on the server host**; exists, unbound in `api.ts` (rejected for this pass — §6.1) |

The dashboard "management profile" is a frontend concept: `ProfileProvider` mirrors
the selected profile into `api.ts` (`setManagementProfile`), and `fetchJSON` appends
`?profile=` to every `PROFILE_SCOPED_PREFIXES` URL. All eight pages in this spec
inherit that scoping transparently (N29).

### 0.6 Config

| Endpoint | Shape |
|---|---|
| `GET /api/config` (~L5355) | **parsed dict** (underscore-prefixed keys stripped) — not YAML |
| `GET /api/config/defaults` (~L5363) | `DEFAULT_CONFIG` dict |
| `GET /api/config/schema` (~L5368) | `{fields: CONFIG_SCHEMA, category_order}` — drives the whole form UI |
| `PUT /api/config` (~L6292) | **deep-merges** the payload over on-disk config so schema-absent keys survive; server-side `memory.provider` readiness gating; `{ok}` |
| `GET /api/config/raw` (~L15508) | `{yaml, path}` (profile-scoped path) |
| `PUT /api/config/raw` (~L15524) | parses YAML (400 if not a mapping) then **full-replace** `save_config` |

No config-save backup, no restart-required metadata per field (Appendix B30).

### 0.7 Env keys + OAuth

**`GET /api/env`** (~L6442) → `Record<key, {is_set, redacted_value, description,
url, category (provider|tool|messaging|setting|custom), is_password, tools[],
advanced, channel_managed, provider, provider_label, custom}>`. Values are always
masked; plaintext only via **`POST /api/env/reveal`** (~L6688) — token-required,
**rate-limited (5 per 30 s → 429)**, audit-logged. `PUT /api/env` (denylists
`LD_PRELOAD`/`PATH`/`PYTHONPATH`…), `DELETE /api/env`.

**The channel-managed exclusion (canonical, verified ~L7134):**
`_channel_managed_env_keys()` = the union of `env_vars` across **every** messaging
platform catalog entry; rows for those keys carry `channel_managed: true` and the
backend comment states the rule: *"The Channels page is the canonical surface for
configuring messaging platform credentials … the Keys/Env page consults this set to
hide those vars so the same fields aren't duplicated."* Custom-key synthesis also
skips channel keys. A deliberate carve-out `_MESSAGING_KEYS_PAGE_KEYS`
(~L7156) = `{GATEWAY_ALLOW_ALL_USERS, GATEWAY_PROXY_KEY, GATEWAY_PROXY_URL}` keeps
the three cross-cutting gateway knobs on the Keys page. Decision E1: stays exactly
as-is.

**`POST /api/providers/validate`** (~L6583) — token-gated live credential probe
(`{ok, reachable, message, models?}`) for `OPENROUTER_API_KEY`, `OPENAI_API_KEY`,
`XAI_API_KEY`, `GEMINI_API_KEY` (+ an `OPENAI_BASE_URL` compatibility branch).
**Exists server-side, entirely unused by the frontend** — the E7 unlock.

**`GET /api/providers/oauth`** (~L8854) + start/submit/poll/disconnect flows —
consumed by `OAuthProvidersCard` on this page; N30 freezes them.

### 0.8 System

| Endpoint | Shape |
|---|---|
| `GET /api/system/stats` (~L2846) | `{os, os_release, os_version, platform, arch, hostname, python_version, python_impl, hermes_version, cpu_count, psutil}` + psutil-gated `{memory{}, disk{}, cpu_percent, load_avg[], uptime_seconds, process{}}` |
| `GET /api/hermes/update/check?force=` (~L3602) | `{install_method, current_version, behind (n ≥ 1 \| 0 up-to-date \| -1 behind-unknown \| null check-failed), update_available, can_apply (git/pip only), update_command, message, commits?}` |
| `POST /api/hermes/update` (~L3510) | spawns `fabric update` → `{ok, pid, name}`; refuses when updates are managed externally / docker (`{ok: false, error, update_command}`) |
| `POST /api/ops/doctor` (~L13177), `security-audit`, `prompt-size`, `dump`, `config-migrate` | spawn CLI → `{ok, pid, name}`; **results are text log lines only**, polled via `GET /api/actions/{name}/status` (~L3932) → `{name, running, exit_code, pid, lines[]}`. **No structured check list exists** (decision §9.1, Appendix B25). |
| `POST /api/ops/backup` (~L13211) / `GET …/backup/download` / `POST …/import` / `…/import-upload` | backup zip (+`archive` path), path-guarded download, force-restore |
| `POST /api/ops/debug-share` (~L3142) | `{urls {label → url}, redacted, auto_delete_seconds, failures[]}` |
| `GET/POST/DELETE /api/ops/hooks` (~L13379–13500) | `{hooks: [{event, matcher, command, timeout, allowed, approved_at, executable}], valid_events[]}`; create body `{event, command, matcher?, timeout?, approve?}` |
| `GET /api/ops/checkpoints`, `POST …/prune` (~L13537/13569) | `{sessions[], total_bytes}` / spawn action |
| memory/credential-pool/curator/portal (`/api/memory`, `/api/credential-pool`, `/api/curator`, `/api/portal`) | as consumed by SystemPage today (selection states, pool entries `{label, token_preview, auth_type, last_status}`, curator `{enabled, paused, interval_hours, last_run_at}`, portal `{logged_in, provider, features[], subscription_url}`) |

There is no `/api/system/restart` — gateway lifecycle is §0.1's endpoints. `egress`
on `/api/status` feeds `EgressStatusCard`, the one component under test
(`SystemPage.test.tsx`).

---

## 1. Shared Connect/System rules (CN-requirements)

**CN1. Two-axis state discipline.** Connect/System items carry up to two state
indicators, never merged into one badge:

- **Configuration axis** — enabled/disabled/needs-setup: the CAP2
  capability-state vocabulary (`capability-state.ts` tones), rendered as the row's
  Switch plus at most one CAP2-toned Badge. Applies to channel enablement, webhook
  subscriptions, shell hooks, env keys, curator enablement.
- **Runtime axis** — a link or process that is actually up: the G1 agent-status
  vocabulary via `AgentStatusBadge` (`connected` channel → `live`, gateway process
  running → `live`, profile gateway running → `live`). Only used where the backend
  reports real runtime state (§0.1's persisted `connected|disconnected|fatal`,
  `gateway_running` flags) — never inferred.

This is the CAP2/O2 rule extended: a channel that is *enabled* but the gateway is
down shows an enabled Switch + a muted runtime note, not a green badge.

**CN2. New pure module `web/src/components/ui/channel-state.ts`** — the single
mapping for the §0.1 platform-state overlay, consumed by BOTH ChannelsPage and
SessionsPage's `GatewayStrip` (today each has its own inline table — the "one
shared source" decision, ACCEPTED at the mapping layer):

```ts
/** Runtime-axis states (persisted by the gateway, plus gateway-level web overlays). */
export function channelRuntimeStatus(state: string): DerivedAgentStatus | null;
// connected → {status:"live"} · disconnected → {status:"failed", label:"disconnected"}
// fatal → {status:"failed", label:"error"} · startup_failed → {status:"failed", label:"start failed"}
// gateway_stopped → {status:"idle", label:"gateway stopped"} · anything else → null

/** Config-axis states (web-server overlay; §0.1). */
export function channelConfigState(state: string): DerivedCapabilityState | null;
// disabled → {state:"disabled", label:"disabled"}
// not_configured → {state:"needs-setup", label:"not configured"}
// pending_restart → {state:"needs-setup", label:"restart to apply"}
// anything else → null
```

Component-free, unit-tested (same pattern as `agent-status.ts`). Unknown states
render raw-labelled on the idle/outline tone, never crash (R18). Exactly one of the
two mappers returns non-null for every known state — assert that in the unit tests.
`GatewayStrip` keeps its alert semantics (fatal/disconnected → destructive alert
box) and swaps its healthy-chip mapping onto `channelRuntimeStatus`; its
`state === "disabled"` branch is kept as a fallback but is unreachable from
`/api/status` (which only relays persisted runtime states — R24 documents why).
The sidebar's `gatewayLine()` (gateway *process*, not platforms) is App-shell
chrome and out of this spec's scope — no change.

**CN3. One gateway-restart lifecycle, not four.** `watchRestartOutcome` is
currently copy-pasted in WebhooksPage, ChannelsPage, TelegramOnboardingPanel and
WhatsAppOnboardingPanel. Extract:

- `web/src/hooks/useGatewayRestart.ts` — owns `{restartNeeded, restarting,
  restartMessage, restartError}`, `restart()` (calls `api.restartGateway`, 4 s
  delayed reload callback), and `watchOutcome()` — the exact shipped algorithm:
  poll `getActionStatus("gateway-restart", 5)` up to 20×1.5 s; `exit_code !== 0 &&
  !== null` → failure toast + `restartNeeded`; **`null` after the window counts as
  success** (no-service installs keep the child in the foreground — the existing
  comment moves into the hook verbatim); transient fetch errors keep polling.
- `RestartBanner` (page-local pattern, shared component in `components/`):
  warning-tinted 1px box + message + "Restart now" button — replaces the three
  hand-rolled banner Cards on Webhooks and the one on Channels.

Consumers: Channels (top banner + both onboarding panels), Webhooks (all three
banner states). Behavior bit-for-bit (R25 is the regression watch).

**CN4. G-rules apply wholesale.** G9 type assignment (mono for env keys, webhook
URLs/secrets, paths, pids, cron-ish schedules, pairing ids/codes, profile paths,
hook commands, version strings); G10 (1px borders, tokens only); G11 (single
accent; the pages are already largely compliant — `text-primary` link affordances
are interactive and stay); G12 (`tabular-nums` for counts/sizes); G13
(PageToolbar/EmptyState/Skeleton on every page — today Webhooks, Pairing, Config,
Env, System and Profiles all block on full-page Spinners; every one becomes
layout-shaped Skeletons with `aria-busy`, background refreshes never skeleton).

**CN5. Timestamps.** `RelativeTime` for webhook `created_at`, curator
`last_run_at`, platform `updated_at` (title = absolute). Pairing serves only
`age_minutes` — render `{n}m ago` mono as today; do not fabricate a timestamp
(raw timestamps are B27). Files keeps its absolute `Modified` column
(file-manager convention; a directory listing is a record, not a feed).

**CN6. i18n.** `t.channels`, `t.profiles`, `t.config`, `t.env` groups exist;
**`t.webhooks`, `t.pairing`, `t.files`, `t.system` do not** — add them as optional
groups with English fallbacks (O5 pattern). No restructuring of existing keys.

**CN7. Source glyph continuity.** Channel platforms and pairing rows reuse
`sourceIcon()` from `ui/source-icons.ts` (telegram/discord/slack/whatsapp glyphs)
so a channel wears the same monochrome glyph as its sessions in the Work/Observe
ledgers (G11 — glyph carries identity, never color).

**CN8. Restart truthfulness (R16 continuation).** Every state that means "saved
but not live" says so: channel toggles keep the optimistic
`pending_restart`/`disabled` flip + global restart banner; the webhook receiver
enable keeps its auto-restart flow; webhook *subscription* toggles keep the
hot-reload copy ("Subscription changes hot-reload once the receiver is running") —
that asymmetry is real and load-bearing. Badge `title`s carry the applicable
"takes effect…" copy.

**CN9. Secrets discipline.** No new surface renders a secret. Frozen as-is: env
reveal (token + rate limit + audit log, §0.7), the webhook secret-shown-once
panel, channel env placeholders (`redacted_value` / "set — leave blank to keep"),
credential-pool `token_preview`, OAuth `token_preview`. All secret-ish strings
render `font-mono-ui` and are never written to URL/localStorage.

**CN10. Action logs.** `ActionLogViewer` (SystemPage) is this section's
implementation of the CAP10 spawn→poll→mono-tail idiom and is reused for every
spawned op (doctor, audit, backup, import, update, gateway verbs). It stays
page-local this pass; unifying it with the skills-hub log card into a shared
`ui/ActionLog` is Appendix A-4.

**CN11. Polling discipline (O7).** No new polling loops. The section's existing
polls stay exactly as shipped: onboarding status polls (1.5–2 s, bounded by the
600 s pairing TTL), `ActionLogViewer` 1.2 s while running, the CN3 restart watch
(≤30 s), SessionsPage/App-shell status polls (5 s/10 s, other pages' concern).
Channels/Pairing/Webhooks remain fetch-on-action + explicit refresh.

**CN12. Zero-backend type/binding unlocks** (verified served, `api.ts` only):
- ChannelsPage: render `home_channel` (served, typed, currently unrendered — H6).
- EnvPage: bind `POST /api/providers/validate` → `api.validateProviderKey(key)`
  (E7).
- No other new bindings. `POST /api/profiles/{name}/open-terminal` and
  `POST /api/gateway/drain` exist but are **rejected** for this pass (§6.1, §9.1).

---

## 2. CHANNELS page — "what the agent listens on" (H-requirements)

### 2.1 Decisions on the table

- **Platform cards on `CapabilityRow` — ACCEPT (consumer #6).** The five-zone
  grammar maps exactly: identity = platform name + glyph; state = enable Switch +
  CN2 config badge; provenance = docs link; usage evidence = sessions-by-source
  count (H6); actions = Test/Configure. The QR onboarding panels ride in the
  `detail` zone unchanged. This replaces the bespoke Card grid.
- **Gateway-status integration / one shared source — ACCEPT at the mapper layer,
  REJECT at the fetch layer.** §0.1 verified both endpoints read the same
  `gateway_state.json`, so a shared *vocabulary* (`channel-state.ts`, CN2) makes
  ChannelsPage, GatewayStrip and the badge tones agree for free. Merging the
  *fetches* (making ChannelsPage read `/api/status`, or the strip read
  `/api/messaging/platforms`) is rejected: the payloads serve different questions
  (`/api/status` blanks platforms when the gateway is down and filters to
  configured; the messaging payload carries env metadata the strip must never
  fetch), and no new polling is allowed on ChannelsPage (CN11).
- **Per-channel usage evidence — ACCEPT via `GET /api/sessions/stats`.** One cheap
  already-bound fetch; `by_source[platform]` renders as `N sessions` in the meta
  zone. Honest (exact local fact, all-time), zero backend. Message-level telemetry
  is B26.
- **Live per-channel health polling — REJECT.** State refreshes on load, after
  saves, and 4 s after restart (shipped behavior). A standing poll duplicates the
  sidebar/Sessions polls for marginal value (CN11).

### 2.2 Information architecture

**H1.** Top-to-bottom: (1) `RestartBanner` (CN3, conditional), (2) gateway-not-
running notice (kept: WifiOff + `gateway_start_command` in mono `code`, hidden
while restart banner shows), (3) summary line (kept: `N of M channels configured` +
env-path mono — copy verbatim, it documents the write target), (4) **platform
roster** — 1-col `CapabilityRow` list, (5) config modal unchanged. Header `end`:
Restart gateway button (kept).

**H2.** Platform row (`CapabilityRow` consumer #6):
- `switch`: `enabled` toggle — optimistic update preserved verbatim (`enabled →
  state:"pending_restart"`, `disabled → state:"disabled"`, sets global
  `restartNeeded`); `busy` = `togglingId` (replaces the Spinner-in-place-of-Switch
  swap with the Switch's own busy pulse).
- `icon`: `sourceIcon(platform.id)` (CN7); `mono={false}` — platform display names
  are human labels; `title` = `platform.id`.
- `badges`: exactly one axis badge per CN2 — runtime states render
  `AgentStatusBadge` (`connected` → live, `disconnected`/`fatal`/`startup_failed`
  → failed with label, `gateway_stopped` → idle label); config states render a
  CAP2-toned Badge (`not configured`, `restart to apply`, `disabled`). This
  preserves every label of today's 8-state `STATE_BADGE` table with shared tones;
  unknown states → outline raw label (R18/R23).
- `description`: kept.
- `meta` (mono): `N sessions` from `stats.by_source[id]` when > 0 (R4) ·
  `home: {home_channel.name ?? chat_id}` when set (CN12 unlock; `title` = full
  platform/chat/thread) · `RelativeTime(updated_at)` when a runtime state exists.
- `detail`: `error_message` destructive line (kept) · Telegram/WhatsApp onboarding
  panels (H4) rendered exactly where they render today.
- `actions`: `Test` (kept: `testMessagingPlatform` → toast `ok ? success : error`,
  per-row busy) · `Configure` (kept: opens the env modal).

**H3.** Config modal frozen in behavior (N23-adjacent): per-field prompt/help/
description, password inputs, `is_set` placeholder ("set — leave blank to keep"),
**only-filled-fields sent**, required-and-unset check, the Slack validation
mirrors (`SLACK_TOKEN_PREFIXES`, `SLACK_MEMBER_ID_RE` incl. `*` wildcard and
empty-part tolerance — the gateway-parse-mirror comment stays), field-error
clearing on edit, "Save & enable" (`{env, enabled: true}`), sets `restartNeeded`,
docs-url "Setup guide" link. Container polish only.

**H4.** Onboarding panels frozen (N23): Telegram — start (`bot_name: "Fabric
Agent"`), QR via `qrcode` (width 224/margin 1), 2 s status poll, terminal-410 +
expiry detection, `ready` → bot username + detected-owner chip + numeric-only
allowed-ID chips (add/remove, ≥1 required), apply → `restart_started` /
legacy `needs_restart` fallback (explicit `restartGateway`) / failure → banner;
expiry countdown 1 s tick; deep-link button; cancel best-effort. WhatsApp — mode
bot/self-chat, allowed-numbers input, `installing/starting/waiting` copy states,
QR refresh on payload change (width 240/margin 3), 1.5–2 s poll, expiry/410 reset,
linked-account panel (`+phone` / name / id, `wa.me` link, 3-step instructions,
saved-allowlist copy branches), apply → restart + `watchRestartOutcome` (now the
CN3 hook), cancel. The only change inside the panels: their hand-rolled restart
watching moves to `useGatewayRestart` (CN3) and their inline error boxes adopt the
shared destructive-tinted 1px idiom (already close).

**H5.** States: loading Skeleton layout kept (`h-4 w-80` line + 3 × `h-28`
blocks, `aria-busy`); empty `EmptyState icon={Radio}` kept (title/description/
Refresh action, i18n fallbacks kept). Errors: `load()` failure currently only
toasts over a blank page — add the destructive 1px banner + Retry; the
sessions-stats fetch (H6 evidence) degrades silently to no meta segment
(supplementary data must never break the roster — the Observe A11 rule).

**H6.** Usage evidence fetch: one `api.getSessionStats()` on mount (management
profile, like every other call); join client-side on `platform.id ===
by_source` key. Label `title`: "sessions started from this channel (all time)".

### 2.3 Data mapping

| Surface | Source | Field | Display |
|---|---|---|---|
| Roster rows | `GET /api/messaging/platforms` | platform payload | CapabilityRow per H2 |
| State badge | same | `state` | CN2 mappers → AgentStatusBadge / CAP2 Badge |
| Toggle | `PUT /api/messaging/platforms/{id}` | `enabled` | Switch + optimistic overlay |
| Test | `POST …/{id}/test` | `ok, message` | toast (kept) |
| Env modal | `PUT …/{id}` | `env{}` | H3 flow |
| Sessions evidence | `GET /api/sessions/stats` | `by_source` | `N sessions` meta (H6) |
| Home channel | messaging payload | `home_channel` | meta segment (CN12) |
| Restart | `POST /api/gateway/restart` + action status | — | CN3 hook + banner |
| QR flows | onboarding endpoints (§0.1) | — | H4 panels, frozen |

---

## 3. WEBHOOKS page — "HTTP events in" (W-requirements)

### 3.1 Decisions on the table

- **Rows with last-delivery evidence — REJECT.** Verified: nothing is persisted or
  served beyond `created_at` (§0.2) — no last-fired timestamp, no delivery count,
  no outcome. Rendering any "last delivered" claim would be invented state. The
  usage-evidence zone stays honestly empty; `RelativeTime(created_at)` is the only
  temporal fact shown. Delivery telemetry is **B24**.
- **Subscription rows on `CapabilityRow` — ACCEPT (consumer #7).** Webhook names
  are server-validated slugs (mono identity); enable/disable is the primary
  action (Switch); deliver/deliver-only are provenance badges.
- **Test-fire button — REJECT.** No endpoint exists (§0.2); a fake "test" that
  POSTs to the public URL from the browser would bypass signature semantics and
  likely CORS. B24 covers the real version.
- **Receiver enable + restart flows — keep, consolidated onto CN3.** The three
  banner variants (restarting message, restart-needed + error, enable-failed)
  become `RestartBanner` states; logic unchanged.

### 3.2 Information architecture

**W1.** Top-to-bottom: (1) **receiver gate card** when `!enabled` (kept verbatim:
warning-tinted, the "webhooks are their own gateway platform" explainer copy,
Enable button → `enableWebhooks` → auto-restart outcome handling), (2)
`RestartBanner` states (CN3), (3) **subscriptions roster**: section heading with
count + the hot-reload note (kept, CN8), CapabilityRow list, (4) create modal.
Header `end`: "New subscription" (kept, disabled until receiver enabled).

**W2.** Subscription row (`CapabilityRow` consumer #7):
- `switch`: `enabled` → `setWebhookEnabled` (replaces the ghost Enable/Disable
  text button; same per-name busy + toasts). The current warning-toned `disabled`
  Badge is dropped — the Switch is the state zone (CAP1.2, no double indicator);
  `dimmed` when disabled (kept).
- name: `sub.name` mono (server slug grammar, §0.2).
- `badges`: `deliver` outline (kept) · `deliver only` secondary (kept).
- `description`: kept.
- `detail`: events chip row (kept: `(all)` secondary when empty, else one
  secondary Badge per event).
- `meta` (mono): endpoint `url` truncated + `CopyButton` (kept) ·
  `RelativeTime(created_at)` (new, served) · `N skills` when `skills.length > 0`
  (served, currently unrendered; `title` lists them).
- `actions`: Delete (confirm dialog kept).

**W3.** Create flow frozen: name required client-side, events CSV → list, deliver
select (`log/telegram/discord/slack/email/github_comment`), deliver-only checkbox,
prompt textarea, server 400s surfaced via toast (incl. the deliver_only+log
rejection), then the **secret-once panel**: URL row + warning-tinted secret row +
copy buttons + "only shown once" copy — pixel-polish only, never redesign the
consent moment (CN9). Reset-on-create kept.

**W4.** States: loading full-page Spinner → Skeleton (`block h-24` gate slot +
`row-list rows={4}`, `aria-busy`); empty subscriptions → `EmptyState
icon={Webhook}`, title "No webhook subscriptions yet", description pointing at
"New subscription", action = open the create modal (disabled state mirrors the
header button); `getWebhooks` failure currently toasts over a blank page — add
destructive banner + Retry.

### 3.3 Data mapping

| Surface | Source | Field | Display |
|---|---|---|---|
| Gate card | `GET /api/webhooks` | `enabled` | W1 hero card |
| Enable | `POST /api/webhooks/enable` | `restart_started, restart_error` | CN3 outcomes |
| Rows | `GET /api/webhooks` | route summary | CapabilityRow per W2 |
| Toggle | `PUT /api/webhooks/{name}/enabled` | — | Switch, hot-reload copy |
| Create | `POST /api/webhooks` | `…route + secret` | modal + secret-once panel |
| Delete | `DELETE /api/webhooks/{name}` | — | confirm (kept) |

---

## 4. PAIRING page — "who may talk to the agent" (D-requirements)

### 4.1 Decisions on the table

- **Rows on `CapabilityRow` — ACCEPT (consumer #8).** Paired people/devices are
  access grants — equipment in the CAP sense. Pending requests and approved users
  share one row grammar; no Switch (approval is a one-way action, not a toggle).
- **Auto-refresh polling — REJECT (CN11).** The list stays fetch-on-mount +
  after mutations; add an explicit header Refresh button (today there is no way
  to re-check for new requests without a full page reload — a real gap, fixed
  with a button, not a poll).
- **`window.confirm` for clear-pending → DS `ConfirmDialog` — ACCEPT.** Same
  consent, consistent chrome; copy and cleared-count toast unchanged.

**D1.** IA: (1) **pending requests** section (count in heading, kept), (2)
**approved users** section (count, kept). Header `end`: Clear pending (kept) +
new Refresh ghost button.

**D2.** Pending row (`CapabilityRow`): icon `sourceIcon(platform)` (CN7) —
replaces the platform Badge as the identity glyph, platform name stays as an
outline Badge; name = `user_name || user_id` (`mono` when it's the raw id);
`meta` (mono): `user_id` (when a user_name exists) · `code` (kept mono; `title`
notes it is a code *reference* — the backend serves the first 8 hex of the code
hash, §0.3) · `{age_minutes}m ago` (CN5). `actions`: Approve (kept: disabled
while in-flight or when `!code` — legacy rows without codes stay un-approvable
from the UI, R27); approve errors surface the server detail (the 429 lockout
message included) via toast (kept).

**D3.** Approved row: same grammar; name = `user_id` mono; `user_name` as
description line; `actions`: Revoke (destructive, `useConfirmDelete` +
`DeleteConfirmDialog`, copy kept: "will lose access. This cannot be undone.").

**D4.** States: Spinner → `Skeleton row-list rows={3}` per section; empties
become compact `EmptyState`s — pending: icon `Users`, description "Pairing codes
appear here when an unapproved user messages the agent on a connected channel"
(the real mechanism, ties Connect together); approved: icon `ShieldCheck`,
"No approved users yet". Load failure keeps the toast and adds banner + Retry.

**D5.** Data mapping: `GET /api/pairing` → rows per D2/D3; `POST …/approve`
`{platform, code}`; `POST …/revoke` `{platform, user_id}`;
`POST …/clear-pending` → cleared-count toast. Key = `platform:user_id` (kept).

---

## 5. FILES page — "what the agent can reach" (F-requirements)

### 5.1 Decisions on the table

- **File rows on `CapabilityRow` or `DataTable` — REJECT both.** Files are not
  capabilities, and `DataTable`'s client-side sorting fights the server's
  dirs-first ordering, the `..` parent-navigation row, and name-click navigation.
  The existing fixed-grid table is the right shape; it adopts the shared visual
  rules only.
- **Scope — keep `/api/files` (managed root) only.** The `/api/fs/*` family is an
  editor/picker API, not this page (§0.4).
- **Sensitive-path honesty.** The server silently filters credential files and
  trees from listings (§0.4). Page copy must not claim completeness; the empty
  state says "No files here" (not "this directory is empty of everything").

**F1.** IA kept: path bar (input + Go when `can_change_path`, read-only mono line
otherwise) · Upload/Create buttons · drag-drop dropzone · listing table. Header:
path Badge (`locked_root ?? path`, truncated, `title` full) + Refresh (kept).

**F2.** Table restyle only: header row keeps the chrome idiom; name cells mono
(kept) with the dir/file glyph — **the `text-warning` folder icon becomes
`text-muted-foreground`** (G11: color is not decoration; warning means warning);
size `tabular-nums` (kept); Modified stays absolute (CN5). Row hover/border
treatment moves to the shared `border-border` tint idiom (already close).

**F3.** Preserved behaviors: path Go (trim + required toast), `..` parent row,
open-directory on name/dir click, download via `readFile().data_url` (server 413
at 100 MiB surfaces as the failed-toast, kept), multi-file upload with
`overwrite=true`, drag-enter/leave depth tracking + `canUpload` gating +
copy-effect, create-folder dialog (`joinPath` separator heuristic, Enter-to-
submit, busy lock), delete confirm (directory copy: "removes the folder and
everything inside it"), file-input reset after upload, `locked_root` escape →
server 403 surfaces in the error banner.

**F4.** States: first-load inline spinner → `Skeleton row-list rows={8}` inside
the card (`aria-busy`); "No files" → `EmptyState icon={FolderOpen}` with
description "Drop files here or upload to make them available to the agent" and
an Upload action (wires the same input); error banner kept, gains a Retry button
(`load()`). Background reloads (post-mutation) never skeleton.

**F5.** Data mapping: `GET /api/files?path=` → table + path state;
`POST /api/files/upload-stream` (multipart) per file; `POST /api/files/mkdir`;
`DELETE /api/files` `{path, recursive: is_directory}`; `GET /api/files/read` →
data-url download. `can_change_path`/`locked_root` gate the path UI exactly as
today.

---

## 6. PROFILES page — "agent identities" (PR-requirements)

### 6.1 Decisions on the table

- **"Agent identities" framing — ACCEPT.** A profile is a complete agent identity:
  its own model, SOUL, skills, env, and (per-profile) gateway. The page reads as
  an identity roster, and the vocabulary follows: the per-profile
  `gateway_running` flag is real runtime state → `AgentStatusBadge` (CN1), the
  description is "what this agent is good at" (the kanban-routing placeholder copy
  already says so — kept).
- **Cards stay page-local cards — REJECT CapabilityRow.** The 3-col identity grid
  with an actions menu is a different density class than a capability list-row
  (the CAP3/R21 lesson: don't force the shared row where it costs signal). Cards
  adopt the zone *order* and shared badges/vocabulary instead.
- **`open-terminal` endpoint binding — REJECT.** It spawns a terminal on the
  *server host* (§0.5) — correct only for the local-desktop case and surprising
  everywhere else. The shipped copy-the-setup-command flow already covers the
  intent. Not even Appendix material until there's a local-only capability signal.
- **Active-vs-current legibility — ACCEPT (copy only).** `active` (sticky default
  for new runs) vs `current` (this dashboard's scope) is verified backend
  semantics (§0.5); the banner keeps showing both and gains `title` copy spelling
  out the distinction. No behavior change.

### 6.2 Information architecture

**PR1.** Top-to-bottom: (1) **active-identity banner** (kept: check glyph +
active name + `(current)` mono when they differ; add the PR-decision `title`
copy), (2) **identity roster** — heading with count, `sm:grid-cols-2
xl:grid-cols-3` grid (kept), (3) create modal + editor dialog (unchanged
internals). Header `end`: Build (→ `/profiles/new`) + Create (kept).

**PR2.** Identity card zones (page-local, restyled):
1. Identity: name (sans, truncate) + badges — `active` (success, kept) ·
   `default` (secondary) · `alias` (outline) · `env` (outline) · distribution
   `name@version` (outline + Package glyph) — all kept.
2. Runtime: the gateway dot+label line becomes `AgentStatusBadge` —
   `gateway_running` → `live` label "gateway running" (pulse), else `idle` label
   "gateway stopped". Same fact, shared vocabulary.
3. Description: kept (line-clamp-2, italic "No description" fallback, warning
   `review` badge when `description_auto` — auto-generated text needs human eyes;
   kept).
4. Evidence (mono, muted): `model (provider)` (kept) · `skills: N` (kept) ·
   `path` mono truncated (kept, `title` full).
5. Actions: the `⋯` menu, frozen — set active (hidden when active) / change
   model / edit description / edit SOUL / manage skills (→
   `/skills?profile=`) / copy terminal command / rename + delete (both hidden
   for default). Outside-click close scoped to the owning menu (comment kept).

**PR3.** Create modal frozen: `PROFILE_NAME_RE` mirror (comment referencing
`fabric_cli/profiles.py::_PROFILE_ID_RE` stays — R28), clone-from select
(default preselected, "none" branch), clone-all only when cloning, no-skills only
when not cloning, optional description + lazy-loaded model picker
(`getModelOptions` flattened, `\u0000` composite keys, "no authenticated
providers" empty copy), `model_set === false` follow-up warning toast, field
reset on success.

**PR4.** Set-active frozen: trust the canonical `active` returned by the server,
`setProfile(active)` scope switch, the "{name} — dashboard switched…" hint toast,
per-profile in-flight state.

**PR5.** Editor dialog frozen: exactly-one-open derivation (model/desc/SOUL),
re-select-collapses affordance, SOUL lazy fetch with stale-request ref guard,
description save/auto-generate with per-request refs + concurrent in-flight
counters (the saving indicator only clears when the last request settles),
auto-describe failure reasons surfaced, model save via `setProfileModel` +
local list patch.

**PR6.** Rename/delete frozen: inline rename editor (Enter/Escape, same-name
no-op, validation line), delete confirm with the gateway-running warning appended
when `gateway_running` (kept), default profile protected (menu hides both).

**PR7.** States: the braille `ProfilesLoadingSpinner` is replaced by `Skeleton`
card blocks (grid of 6 × `block h-40`, `aria-busy`) per G13 — the bespoke spinner
does not survive the shared-primitives rule; empty roster → `EmptyState
icon={Users}` + Create action (replaces the bare Card text); load failure keeps
the toast and gains banner + Retry.

### 6.3 Data mapping

| Surface | Source | Field | Display |
|---|---|---|---|
| Roster | `GET /api/profiles` | `ProfileInfo` | PR2 cards |
| Banner | `GET /api/profiles/active` | `active, current` | PR1 |
| Runtime badge | `ProfileInfo.gateway_running` | — | AgentStatusBadge (PR2.2) |
| Create/clone | `POST /api/profiles` | `model_set, …` | PR3 modal |
| Set active | `POST /api/profiles/active` | `active` | PR4 |
| SOUL / description / model | profile sub-endpoints (§0.5) | — | PR5 editors |
| Rename / delete | `PATCH`/`DELETE /api/profiles/{name}` | — | PR6 |
| Setup command | `GET …/setup-command` | `command` | clipboard flow (kept) |

---

## 7. CONFIG page — "standing orders" (CF-requirements)

### 7.1 Decisions on the table

- **Raw YAML editing stays untouched — ACCEPT (the "probably yes" is a yes).**
  `PUT /api/config/raw` is a **full-replace** write (§0.6) — the highest-blast-
  radius surface in the dashboard. High risk, low reward: no redesign, no
  editor upgrade, no schema hints; container polish only. The form mode is the
  safe path (deep-merge PUT) and gets the attention.
- **Form internals (`AutoField`, nested get/set) — out of scope.** This spec
  touches page chrome and states only; field-widget redesign is its own project.

**CF1.** IA kept: path line + toolbar (export / import / scoped reset / YAML
toggle / Save) · category rail (icons, counts, ordered by `category_order` +
alphabetical extras) · active-category or search-results card. The toolbar row
adopts `PageToolbar` (G13) with filters = nothing (search lives in the header
`end` slot, kept) and actions = the existing button cluster.

**CF2.** Preserved behaviors: header search (key/label/category/description
match, clear button, rail deselect while searching), category switch clears
search, config-path preference order (`getConfigRaw().path` first because it is
profile-scoped; `/api/status.config_path` fallback only — the comment explaining
why stays verbatim), **scoped reset** (search-matches or active category only,
ConfirmDialog with field count; the `@ykmfb001` footgun comment history stays —
it is the documented reason the button is scoped), export JSON blob, import JSON
(parse-failure toast), save (`saveConfig` → deep-merge, §0.6), YAML mode lazy
`getConfigRaw` on toggle + `saveConfigRaw` + parsed-config reload after save,
`PluginSlot config:top/bottom`.

**CF3.** Vocabulary: category chrome labels + section dividers keep the
uppercase-tracked idiom (already G9-compliant); field keys render mono wherever
shown raw; counts `tabular-nums`.

**CF4.** States: full-page Spinner → Skeleton (rail `block h-64` + content
`block h-96`, `aria-busy`); the three silent `catch(() => {})` loads get one
shared destructive banner + Retry when config *and* schema both failed (partial
failures degrade as today); YAML-load failure keeps its toast; no-match search
keeps its inline message (add "Clear search" action button).

**CF5.** Truthfulness note rendered once (muted line under the path): "Most
changes apply to new sessions or after a gateway restart." — today the page
implies immediacy nowhere and confirms it nowhere; one honest sentence, no
per-field claims (per-field effect metadata is B30).

---

## 8. ENV / KEYS page — "the agent's credentials" (E-requirements)

### 8.1 Decisions on the table

- **Channel-managed key exclusions stay canonical — ACCEPT, verbatim.** The
  backend is explicit (§0.7): Channels owns platform credentials;
  `channel_managed` rows are hidden here; the `_MESSAGING_KEYS_PAGE_KEYS` trio
  (proxy/relay/allowlist) stays on this page under the Gateway section with the
  existing hint copy ("Messaging platforms, the API server and webhooks are
  configured on the Channels page…"). No re-plumbing; the hint copy is the
  cross-page contract and must survive any restyle.
- **`EnvVarRow` on `CapabilityRow` — REJECT.** The row has three densities
  (compact unset, boxed unset, full set/editing) with an *inline* editor — a
  different interaction class than the capability grammar (R21: compose, don't
  force). It adopts shared tokens/badges only.
- **Key validation probe — ACCEPT (E7, zero-backend).** `POST
  /api/providers/validate` exists unused (§0.7). Bind it and render a `Test`
  action **only** on the four probe-supported keys (+`OPENAI_BASE_URL` branch),
  with the result as a last-outcome chip (`reachable` success / destructive
  message) — the MCP `/test` precedent (CAP2 outcome-chip row), session-local.
- **OAuth stays here — reaffirm N15/N30.** `OAuthProvidersCard` remains the
  section lead; its popup-blocker pre-open gesture, PKCE/device-code flows and
  disconnect confirm are frozen.

**E1.** IA kept: description + advanced toggle row · OAuth card · LLM providers
card (grouped) · Tools / Gateway / Settings category cards · Custom keys card ·
jump-to-section subnav in the header (kept, chrome-styled buttons).

**E2.** Provider groups kept: `PROVIDER_GROUPS` prefix table (frontend-owned;
drift noted in R28), expand/collapse ListItem header, `N set` success badge,
representative "Get key" link, API-keys → base-URLs → other ordering, compact
rows inside groups.

**E3.** Row behaviors frozen: Set/Replace opens inline editor (empty draft —
never pre-fills a secret), Save disabled on empty, local `redacted_value` update
after save (`slice(0,4)…slice(-4)` — cosmetic divergence from the server's
`redact_key`, noted, kept), Reveal toggle (`revealEnvVar`; add one specific 429
message: "Reveal rate-limited — try again in a moment", CN9/§0.7), Clear →
confirm dialog with key + description, cancel edit, tools chips, "Get key"
external links, `is_password` handling.

**E4.** Custom keys frozen: `ENV_VAR_NAME_RE` mirror (comment referencing
`fabric_cli/config.py` stays), uppercase normalization, invalid-name inline
error, add → local unset row + open editor → normal save path persists (the
comment explaining durability stays), alphabetical sort.

**E5.** Category cards frozen: set-entries always visible, unset behind
Show more/less (auto-open when none configured), configured-count line,
`showAdvanced` default **true** kept (the "Show all providers by default"
comment stays).

**E6.** Vocabulary: key names `font-mono-ui` (already), `set`/`not set` badges →
CAP2 tones (`enabled`-success / outline — same as today), counts `tabular-nums`.

**E7.** Key probe (decision above): `api.validateProviderKey(key)` binding; per-
key busy state; outcome chip renders in the row's expanded area; never auto-runs
(explicit action only — the N14 discipline); absent for every key without a
server-side probe (no fake coverage).

**E8.** States: full-page Spinner → Skeleton (`block h-40` OAuth + `row-list
rows={6}` providers, `aria-busy`); the silent `getEnvVars` catch becomes banner +
Retry; per-mutation toasts kept.

---

## 9. SYSTEM page — "the operator's console" (Y-requirements)

### 9.1 Decisions on the table

- **Health/doctor surfaces adopting the status vocabulary — ACCEPT for real
  states, REJECT for a structured health board.** Verified (§0.8): doctor and
  security-audit are spawned CLI processes whose only output is a text log tail —
  there is **no structured check data** to render as status rows. They stay
  `ActionLogViewer` runs (CN10). What *does* adopt the shared vocabulary is every
  surface with real state: the gateway process (Y2), the curator (Y3), profile
  gateways (PR2), channels (H2). A structured `fabric doctor --json` health board
  is **B25**.
- **Section order — ACCEPT one move: Gateway up to slot 2.** The operator's
  first two questions are "what host is this" and "is my agent process up";
  today Gateway sits below Portal and Curator. New order: Host → Gateway →
  Network & AI egress → Portal → Curator → Memory → Credential pool → Operations
  → Checkpoints → Shell hooks. Everything else keeps its relative order.
- **`SystemPage.test.tsx` must keep passing — it tests `EgressStatusCard`.**
  Inventory (Y12): the component (import path `@/components/EgressStatusCard`,
  prop `egress: StatusResponse["egress"]`) must keep rendering: the "Network &
  AI egress" heading; the mode string verbatim (`local_ai`); the scope with
  underscores → spaces (`ai inference routes`); `"{n} explicitly approved"`
  **only** when `mode === "local_ai"`; the `status` string in the enforcement
  badge (`unavailable`); the reason with underscores → spaces. The card is
  frozen this pass — no restyle that touches text content.
- **Gateway drain endpoint — REJECT.** `POST /api/gateway/drain` exists (§0.1)
  but drain/degraded lifecycle UX (busy counts, drain timers) is its own design;
  a bare button would be a footgun. Appendix A-6.
- **Shell hooks on `CapabilityRow` — ACCEPT (consumer #9).** A hook is exactly a
  capability: identity (command), state (allowed/not approved), provenance
  (event), actions (remove).

### 9.2 Requirements

**Y1.** IA per the order decision; `ActionLogViewer` stays pinned above all
sections while an action runs (kept); `FabricConsoleModal` reachable from
Operations (kept, untouched — N22).

**Y2.** Gateway card: status renders as `AgentStatusBadge` via a new mapper in
`agent-status.ts`:

```ts
export function gatewayAgentStatus(state: string | null, running: boolean): DerivedAgentStatus;
// running (or state==="running") → live · starting → {idle, "starting…"}
// startup_failed → {failed, "start failed"} · stopped/null → {idle, "stopped"}
// draining → {paused, "draining"} · degraded → {paused, "degraded"}
// unknown → {idle, raw state}   (raw label, never crash — R18)
```

`draining`/`degraded` ride the warning-toned `paused` status with truthful labels
(they are real states served today, §0.1, currently rendered as raw text only).
Meta line stays mono: raw `gateway_state` · `pid {n}`. Start/Restart/Stop buttons
frozen (disabled gating on `gateway_running`, action names `gateway-*`, 3 s
`loadAll` follow-up, toasts).

**Y3.** Curator card: badge mapping follows the cron precedent exactly
(a curator *is* a scheduled agent): `paused → paused`, `enabled → scheduled`
(label "active"), `disabled → paused` label "disabled" — via `cronJobAgentStatus`
-style logic (reuse it: `cronJobAgentStatus({enabled: curator.enabled &&
!curator.paused ? … })` is contorted; add a two-line page-local mapping instead,
tones from `AGENT_STATUS_TONES`). Meta: `every {interval_hours}h` ·
`RelativeTime(last_run_at)` / "never run". Pause/Resume + Run now frozen.

**Y4.** Memory card frozen in behavior: read-only provider display + "Change in
Plugins →" links (the Plugins page is canonical, CAP-spec P3 — the comment
explaining the dropped dropdown stays), `MEMORY_SELECTION_LABEL/TONE` maps kept
(they already agree with CAP2 tones; add the "must match backend enum" drift
comment, R18-style), missing/tiers-disabled/eligible notices verbatim (the
"static prerequisites passed… live initialization not checked" honesty copy is
load-bearing), external-capture policy line verbatim, built-in file sizes,
Reset MEMORY.md / USER.md / all confirms (copy kept: "…does not erase copies
held by an external memory provider").

**Y5.** Credential pool frozen: add form (provider/key/label, required check),
per-provider groups, entry rows (label · mono `token_preview` · `auth_type`
outline · `last_status` secondary chip when present) restyled to the 1px row
idiom, remove confirm (`provider|index` key). No reveal exists for pooled keys —
none is added (CN9).

**Y6.** Operations frozen: Open console / Run doctor / Security audit / Update
skills / Prompt size / Support dump / Migrate config — all `runOp` spawn → the
shared action log (CN10).

**Y7.** Backup/restore frozen: create backup (pending archive → downloadable
only on `exit_code === 0` via `onComplete`, kept), download (blob flow, kept),
restore-from-upload and restore-from-path both behind the destructive
ConfirmDialog whose copy owns the consent (the `force=true` / "CLI prompt would
auto-abort" comment stays verbatim — it documents why the dashboard confirms),
file-input reset.

**Y8.** Debug share frozen: redact default **true**, uploading state, result
block (uploaded/redacted/not-redacted badges, auto-delete hours, per-link copy +
copy-all, failures line). Mono URLs.

**Y9.** Update flow frozen: cached check inside `loadAll` (non-forced, the
comment stays), forced re-check button + its toast matrix (`behind > 0` /
`behind === 0` / `message`), version badge in Host (`N behind` warning /
`latest` success), `can_apply` gating (git/pip) vs `update_command` hint,
`can_update_hermes === false` → managed-externally message and no update UI,
confirm dialog copy incl. `publicCliCommand` rewrite and the prompt-cache
sentence, apply → action log (`hermes-update`).

**Y10.** Shell hooks (`CapabilityRow` consumer #9): name = `command` mono
(truncate, `title` full); badges = `event` outline · `not executable`
destructive (kept) · consent state — `allowed` → CAP2 success "allowed",
`!allowed` → warning "not approved" (kept tones); meta = `matcher: {m}` ·
`timeout {n}s` when set; actions = Remove (confirm copy kept: "…revoke its
consent? It stops firing on the next restart."). Create modal frozen: event
select from `valid_events` (fallback list kept), absolute-path command, matcher,
timeout, **approve-now consent checkbox + the arbitrary-commands warning copy
verbatim** (this is a consent surface, CN9-class).

**Y11.** Host card: grid kept; values `tabular-nums` mono where numeric; version
row + update badge (Y9); psutil hint kept; uptime via existing `formatDuration`.

**Y12.** Egress card: frozen (decision above — the test inventory is the
contract).

**Y13.** Portal card kept as-is (logged-in badge, provider line, features list,
subscription link, `fabric portal` hint).

**Y14.** States: the single full-page Spinner → per-section Skeletons
(`aria-busy`), sections resolving independently exactly as `Promise.allSettled`
already allows — a failed portal fetch must skeleton→hide only the Portal card,
never the page. Empty hooks EmptyState (icon `Terminal`, action "New hook");
empty pool keeps its inline hint line.

---

## 10. Non-goals and risks (continuing prior numbering)

**N21.** No backend changes of any kind in the main spec — every requirement is
frontend-only against verified existing endpoints (Appendix B holds the rest).

**N22.** `FabricConsoleModal` internals untouched (terminal-adjacent, N1-class).

**N23.** Onboarding flows frozen end-to-end: Telegram external-service proxying,
WhatsApp bridge lifecycle, poll cadences, 410/expiry handling, QR generation
parameters, TTL semantics, cancel best-effort. Any diff to their request
payloads or fetch triggers is a review flag.

**N24.** Secrets handling frozen (CN9): reveal endpoint semantics untouched, no
secret prefetch, no secret persistence, the webhook secret-once contract, empty
edit drafts.

**N25.** Config write semantics frozen: form save stays the deep-merge `PUT
/api/config`; YAML save stays the full-replace `PUT /api/config/raw`; the
server-side memory-provider gating is relied upon, never reimplemented
client-side.

**N26.** `EgressStatusCard` is under test (`SystemPage.test.tsx`): export path,
prop shape, and every rendered string in the Y12 inventory are frozen.

**N27.** No new polling loops (CN11). Pairing/Channels/Webhooks liveness stays
manual; the sidebar (10 s) and Sessions (5 s) status polls are other pages'
surfaces and are not consolidated in this pass.

**N28.** Destructive flows bit-for-bit: webhook/profile/hook/credential/file
deletes, memory resets, checkpoint prune, backup restore (force-confirm),
pairing revoke, clear-pending. All keep `DeleteConfirmDialog`/`ConfirmDialog`.

**N29.** Profile scoping untouched: `ProfileProvider` → `setManagementProfile` →
`PROFILE_SCOPED_PREFIXES` query-param plumbing; every page keeps inheriting it
transparently; no per-page profile pickers are added.

**N30.** OAuth flows untouched: `OAuthProvidersCard`, popup pre-open gesture,
PKCE/device-code paths, disconnect confirm; provider OAuth stays on Env/Keys
(N15 reaffirmed).

**R22.** Concurrent-edit hazard: another process is editing this repo. Highest-
risk merge zones: ChannelsPage onboarding panels (recently reworked), SystemPage
(63 KB monolith), `api.ts`. Rebase at build time; the CN3 extraction must diff
against the then-current four copies.

**R23.** The platform-state overlay is server-computed per request (§0.1). The
frontend maps it (CN2) but never re-derives it from `enabled`/`configured` —
if the mappers receive an unknown state, render it raw on a neutral tone.

**R24.** `/api/status` and `/api/messaging/platforms` read the same file but
filter differently (status blanks platforms when the gateway is down; messaging
shows `gateway_stopped`). Do not "reconcile" them client-side; each surface
trusts its own endpoint. GatewayStrip's `disabled` branch is kept as dead-code
insurance, not removed.

**R25.** The restart watcher's exit-code semantics are subtle (`null` after the
window = success in no-service installs). CN3 centralizes four copies into one —
the highest-regression-risk refactor in this spec; port the comment and add a
unit test on the outcome classification.

**R26.** ChannelsPage's optimistic toggle writes `pending_restart`/`disabled`
locally; the server may disagree on the next load (e.g. env got cleared
elsewhere). The optimistic value must never be written anywhere but component
state, and every reload takes server truth wholesale.

**R27.** Pairing `code` is a hash-prefix reference, not the user's code (§0.3);
legacy rows serve `"legacy"` and cannot be approved from the UI (Approve stays
disabled — do not "fix" by sending the string). Copy must call it a code
reference, not the code.

**R28.** Frontend mirrors that can drift: `PROFILE_NAME_RE` ↔
`_PROFILE_ID_RE`, `ENV_VAR_NAME_RE` ↔ `_ENV_VAR_NAME_RE`, Slack validation ↔
`gateway/platforms/slack.py`, `PROVIDER_GROUPS` prefixes ↔ provider catalog,
`MEMORY_SELECTION_*` ↔ backend enum, `HOOK_EVENTS_FALLBACK` ↔ hook registry.
Keep the "must match" comments adjacent; unknown enum values render raw (R18).

**R29.** SystemPage's `loadAll` fans out 9 fetches incl. a network-bound update
check; Y14's per-section skeletons must key off each fetch settling, not the
batch — otherwise the slowest endpoint (update check) blanks the whole console.

**R30.** EnvPage's post-save local redaction (`slice(0,4)+"…"+slice(-4)`)
diverges from the server's `redact_key` format until the next full load —
cosmetic, kept, but do not propagate the local format anywhere else.

**R31.** The files sensitive-path guard is read-side only (server design, §0.4):
listings hide credential files but writes to those paths are not blocked. The UI
must not present the managed root as a security boundary (no "safe sandbox"
copy), and F4's empty-state copy stays neutral ("No files here").

---

## Appendix A — Out-of-scope frontend enablers (continuing prior numbering)

**A-4. Shared `ui/ActionLog`.** Unify SystemPage's `ActionLogViewer` and the
skills-hub action-log card (CAP10) into one shared component consumed by System,
Skills hub, and MCP catalog installs (X8). Pure consolidation; needs prop design
for the hub's header variant.

**A-5. Webhook create: expose served fields.** `POST /api/webhooks` accepts
`skills[]`, `script`, `deliver_chat_id` today (§0.2); the form never sends them.
A fuller create form wants the Cron page's delivery-target picker — its own
small design.

**A-6. Gateway drain UX.** `POST /api/gateway/drain` + `gateway_busy`/
`gateway_drainable`/`restart_drain_timeout` are served and unused (§0.1). A
graceful-restart flow ("drain, then restart when idle") belongs with a proper
lifecycle design, not a bare button.

## Appendix B — "Needs backend" (explicitly NOT in the main spec)

**B24. Webhook delivery telemetry.** Persist and serve `last_delivered_at`,
`delivery_count`, `last_status` (+ optionally a bounded recent-deliveries list)
per subscription — unlocks the W usage-evidence zone and a real test-fire
endpoint. Rejected client-side substitutes in §3.1.

**B25. Structured doctor output.** `fabric doctor --json` (or a
`GET /api/ops/doctor/report`) returning `[{check, status: ok|warn|fail,
detail}]` — unlocks a health board rendered in CAP2 tones on SystemPage instead
of a text tail (§9.1 decision).

**B26. Per-channel activity telemetry.** Messages handled / last-activity
timestamp per platform on the messaging payload — upgrades H6's sessions-count
evidence to true channel throughput.

**B27. Pairing timestamps.** Serve `requested_at`/`approved_at` ISO timestamps
(the store knows them; only `age_minutes` is exposed) → `RelativeTime`
everywhere instead of the D2 minutes string, plus approved-since evidence.

**B28. Server-computed pending-restart.** A `pending_restart: true` per platform
/ a global `config_dirty` flag computed against the running gateway's snapshot —
replaces the client-side `restartNeeded` heuristic (CN8) with per-item truth
(same want as B22).

**B29. Managed-files write guard parity.** Apply `_is_sensitive_path` to
upload/mkdir/delete (today read-side only, §0.4) — closes the asymmetry R31
warns about; frontend needs no change when it lands.

**B30. Config field effect metadata.** Per-field `takes_effect:
immediate|new_session|gateway_restart` in `CONFIG_SCHEMA` → honest per-field
chips on ConfigPage instead of the single CF5 sentence.
