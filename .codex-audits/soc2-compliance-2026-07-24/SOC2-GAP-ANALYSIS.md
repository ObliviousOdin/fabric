# IRONLOOM — SOC 2 Readiness & Security Gap Analysis

**Repository:** `ObliviousOdin/fabric` (Fabric — single-tenant personal AI agent; Python + TypeScript monorepo)
**Engagement codename:** IRONLOOM
**Audit date:** 2026-07-24
**Audited revision:** `main` @ `5d5938b` (branch `claude/soc2-compliance-audit-h5oh2b`)
**Framework:** AICPA SOC 2 Trust Services Criteria (2017, rev. 2022) — Security (Common Criteria CC1–CC9), Availability, Confidentiality, Processing Integrity, Privacy
**Type:** Point-in-time readiness / gap analysis (design-of-controls). This is **not** a SOC 2 examination or attestation; it is an internal readiness assessment against the TSC.
**Method:** Read-only static review. No source files were modified. Repo scale reviewed: ~3,257 Python files, ~1,643 TS/JS files, 6,981 tracked files, across seven parallel evidence workstreams.

---

## 1. Executive summary

Fabric is an unusually **security-literate** codebase for its class. It ships a written trust model (`SECURITY.md`) that honestly names the OS as its only real boundary, a fail-closed authorization architecture across every external surface, comprehensive credential redaction, disciplined dependency pinning, and a CI change-management surface whose *own workflow files* are enforced by a tested meta-audit. **No Critical findings and no confirmed remote-exploitable defects were identified in first-party code.**

The gaps are not in the preventive controls the team has clearly invested in — they are in the **detective and governance layers** that a SOC 2 examiner weighs most heavily:

- **Automated vulnerability detection is essentially absent.** There is no SAST, no secret-scanning, no dependency-vulnerability scanning, and no automated dependency-update tooling anywhere in CI. Two documents describe a `supply-chain-audit.yml` gate that **does not exist**, and the change-classification code it would drive (`scripts/ci/classify_changes.py`) is dead — invoked by no workflow.
- **Change governance is policy-strong but evidence-weak.** Separation of duties (no self-merge, reviewer/merger roles) is documented in prose only — there is no `CODEOWNERS`, and branch protection lives in GitHub settings outside the auditable repo. The commit-identity control is genuinely strong, yet forbidden AI-attribution footers still reached mainline history through squash-merge messages.
- **Data governance for a single-tenant tool is immature.** Full conversation transcripts, user identifiers, and credentials persist in plaintext SQLite and on-disk `.env`/`auth.json` with **no retention limit, no auto-purge, no at-rest encryption, and no data-subject-deletion process**.
- **The extension supply chain is the largest technical attack surface.** The *externally-installed-skill* path is well-defended (trust tiers, TOCTOU-proof attested install, SSRF guards). But plugins load **unsigned arbitrary Python at import**, first-party skills **bypass the scanner entirely**, the **MCP-launch malware preflight is bypassable and fails open**, agent-created skills are unscanned by default, and offensive/jailbreak skills ship in the distribution.
- **One dependency anomaly warrants urgent human verification:** `lodash`/`lodash-es` are pinned via `package.json` `overrides` to **`4.18.1`**, a version at/above the last publicly-known release (4.17.21), introduced inside an unrelated compression-hotfix commit.

**Overall readiness verdict: PARTIALLY READY.** Preventive access and change controls are at or above SOC 2 expectations; monitoring (CC4/CC7), privacy (P-series), and control-documentation accuracy (CC2/CC4) require remediation before a clean Type II window.

### Severity tally

| Severity | Count |
|---|---|
| Critical | 0 |
| High | 3 |
| Medium | 21 |
| Low | 20 |
| Informational | 6 |

---

## 2. Scope, methodology & limitations

### 2.1 Workstreams (evidence dimensions)
1. Secrets & credential management (CC6.1, CC6.7, C1)
2. Skills, plugins & MCP extension surface (CC6.8, CC7.1, CC8.1)
3. Authentication, authorization & external surfaces (CC6.1–CC6.6)
4. Injection & code execution — sinks, deserialization, SSTI/XSS, SSRF, path traversal, TLS, temp files (CC6.1, CC7.1, PI1)
5. Dependency & supply-chain security (CC7.1, CC8.1, CC9.2)
6. CI/CD change management, release integrity, logging, monitoring, data handling & privacy (CC3, CC4, CC7.2–7.4, CC8.1, P-series)

### 2.2 Limitations (material to reading this report)
- **Offline environment.** `pip-audit`, `npm audit`, `uv`, `safety`, and live registry resolution could **not** be run. Dependency-vulnerability claims are reasoned from pinned versions and flagged with confidence. **No CVE identifiers were fabricated.**
- **2026 timeline.** The tree cites many `CVE-2026-*` / `GHSA-*` / `PYSEC-2026-*` identifiers beyond the reviewer's January 2026 knowledge cutoff; these were neither confirmed nor refuted.
- **GitHub server-side configuration is out of scope of the repo artifact.** Branch protection, required reviews, environment approval gates, and tag rulesets are asserted in documentation but cannot be verified from the checkout. Several findings ask that this configuration be **exported as audit evidence**.
- **The `lodash 4.18.1` finding could not be resolved against the live npm registry** and is reported as an anomaly requiring verification, not a confirmed compromise.

---

## 3. Findings register (ranked)

| ID | Sev | SOC 2 | Title | Primary evidence |
|---|---|---|---|---|
| **H-01** | High | CC7.1, CC9.2 | Anomalous `lodash`/`lodash-es` override to non-canonical `4.18.1` | `package.json:39`, `package-lock.json:13689-13700` |
| **H-02** | High | CC6.8, CC8.1 | MCP-server launch malware preflight is bypassable and fails open | `tools/osv_check.py:46-72,167`, `tools/mcp_tool.py:2028-2052` |
| **H-03** | High | CC4.1, CC7.1 | No automated security scanning; documented supply-chain gate not operating | `.github/workflows/*`, `CONTRIBUTING.md:937`, `scripts/ci/classify_changes.py` |
| **M-01** | Med | CC6.8 | Plugins load unsigned arbitrary Python at import, no integrity verification | `fabric_cli/plugins.py:1734-1853` |
| **M-02** | Med | CC6.8 | First-party (bundled + optional) skills bypass Skills Guard entirely | `tools/skills_guard.py:57-59,1321` |
| **M-03** | Med | CC6.8 | Skills Guard: medium clusters never block; scan skips many executable types | `tools/skills_guard.py:1331-1344,542-546` |
| **M-04** | Med | CC1.1, CC2.3 | Offensive/dual-use skills shipped (LLM-jailbreak, active exploitation) | `optional-skills/security/godmode/**`, `.../web-pentest/**` |
| **M-05** | Med | CC6.8, CC7.1 | Skills-index build ingests unsanitized community frontmatter (poisoning/injection) | `scripts/build_skills_index.py:495-520` |
| **M-06** | Med | CC6.1 | Dashboard/API skill-install suppresses the interactive confirm gate | `fabric_cli/web_server.py:13622-13646` |
| **M-07** | Med | CC6.1, CC6.7 | No secret-scanning gate in CI or pre-commit | `.github/workflows/*`, `.githooks/*` |
| **M-08** | Med | CC6.7 | SSRF redirect-bypass in WeCom / QQBot / Feishu media downloads | `wecom/adapter.py:1099`, `qqbot/adapter.py:1977`, `feishu/adapter.py:3463` |
| **M-09** | Med | CC7.4, C1 | External observability egress (Langfuse) lacks secret/PII scrubbing | `plugins/observability/langfuse/__init__.py:201,261` |
| **M-10** | Med | P1–P6, CC7.4 | No data retention/purge, plaintext state at rest, no data-subject process | `fabric_state.py:808-876` |
| **M-11** | Med | CC8.1, CC4.1 | Forbidden AI-attribution footers reached mainline squash history | commits `c534318` (#81), `f230d17` (#76) |
| **M-12** | Med | CC1.3, CC8.1 | Separation of duties is documentation-only; no CODEOWNERS / evidenceable protection | absent `.github/CODEOWNERS` |
| **M-13** | Med | CC6.6 | Shipped compose "whole-process" wrapper weaker than documented containment | `docker-compose.yml:35,67` |
| **M-14** | Med | CC7.1, CC8.1 | Hosted deploy pulls unpinned `:latest` image with no in-repo build/provenance | `deploy/docker-compose.hosted.yml:22,47` |
| **M-15** | Med | CC6.1, CC7.1 | Pages/skills-index workflows expose elevated `GITHUB_TOKEN` to npm build + crawler | `docs-pages.yml:32-74`, `skills-index.yml:20-58` |
| **M-16** | Med | CC8.1 | No signing/attestation for Python release artifacts; Windows-signing escapable | `release-channels.yml`, `desktop-release.yml:234-246` |
| **M-17** | Med | CC6.1, CC6.6 | API-server per-request auth fails open when key unset (mitigated by startup guard) | `gateway/platforms/api_server.py:1063-1064` |
| **M-18** | Med | CC6.3 | Single-tenant trust model: no per-user RBAC once authenticated (by design) | `plugins/kanban/dashboard/plugin_api.py:2189,2300` |
| **M-19** | Med | C1.1 | Credentials plaintext at rest, no OS keychain; `auth.json` pools provider refresh tokens | `fabric_cli/auth.py:1696-1774`, `agent/secret_sources/__init__.py:30` |
| **M-20** | Med | CC6.1 | LINE adapter binds `0.0.0.0` by default | `plugins/platforms/line/adapter.py:661` |
| **M-21** | Med | CC7.1 | No automated dependency-update / vulnerability monitoring (no Dependabot/Renovate) | absent `.github/dependabot.yml` |
| **L-01** | Low | PI1, CC6.1 | Reflected XSS in transient MCP OAuth loopback callback page | `tools/mcp_oauth.py:513-523` |
| **L-02** | Low | CC7.2, CC7.3 | Security audit trails not tamper-evident; dashboard-auth log fail-open, no rotation | `fabric_cli/dashboard_auth/audit.py:74-82` |
| **L-03** | Low | CC7.2 | Web-server error responses echo raw exception text (info disclosure) | `fabric_cli/web_server.py:12114,14366,…` |
| **L-04** | Low | CC9.2, CC7.1 | Install scripts fetch toolchain (uv/Node/Docker) with no checksum verification | `scripts/install.sh:577-909`, `install.ps1:472-929` |
| **L-05** | Low | CC8.1 | `uv sync --locked` gate is path-filtered; not on the always-on PR workflow | `public-ci.yml` vs `fabric-link.yml:58` |
| **L-06** | Low | CC8.1 | `pyproject.toml` "no ranges" claim contradicted by ranged core deps | `pyproject.toml:25,89-125` |
| **L-07** | Low | CC7.1 | Runtime base image `debian:13.4` tag-pinned, not digest-pinned | `Dockerfile:10`, `.hadolint.yaml:33-34` |
| **L-08** | Low | CC8.1 | `desktop-release.yml` interpolates unvalidated `inputs.release_tag` into `run:` | `desktop-release.yml:65,137,256` |
| **L-09** | Low | CC6.1 | Kanban `/events` WS auth helper fails open on import failure | `plugins/kanban/dashboard/plugin_api.py:87-93` |
| **L-10** | Low | CC6.3 | ACP `AUTO_APPROVE_SESSION` not path-confined | `acp_adapter/edit_approval.py:211-212` |
| **L-11** | Low | CC7.1 | CI pip installs version-pinned but not hash-pinned | `public-ci.yml:30,126` |
| **L-12** | Low | CC4.1 | Placeholder CI jobs satisfy required checks with `echo`; names imply real coverage | `release-channels.yml:315-341` |
| **L-13** | Low | CC9.2 | `photon` sidecar `postinstall` monkeypatches an installed third-party package | `plugins/platforms/photon/sidecar/package.json` |
| **L-14** | Low | CC9.2 | Pre-release, unofficial WhatsApp lib pinned (`baileys 7.0.0-rc13`) | `scripts/whatsapp-bridge/package.json` |
| **L-15** | Low | CC6.1 | `.gitignore` misses bare `.env.production` and extensionless SSH-key patterns | `.gitignore` |
| **L-16** | Low | CC7.4 | Raw API-key prefix printed to console outside the redaction path | `agent/conversation_loop.py:2840` |
| **L-17** | Low | CC6.1 | Compute-broker script ships default `VLLM_API_KEY="changeme-…"` on a `0.0.0.0` listener | `deploy/compute-broker/vast-vllm-onstart.sh:33` |
| **L-18** | Low | CC7.4 | `security.redact_secrets:false` disables all log redaction; debug dumps/transcripts unredacted | `agent/redact.py:61-97`, `tools/debug_helpers.py:60-89` |
| **L-19** | Low | CC7.1 | Optional OSINT skill disables TLS verification | `optional-skills/research/domain-intel/scripts/domain_intel.py:93-94` |
| **L-20** | Low | CC6.8 | Agent-created skills are unscanned by default (persistence vector) | `tools/skill_manager_tool.py:130-173` |
| **I-01** | Info | CC6.7 | DNS-rebinding / TOCTOU residual on URL safety checks (documented, unfixable pre-flight) | `tools/url_safety.py:15-19` |
| **I-02** | Info | CC7.4 | Redaction is explicitly a heuristic, not a boundary (honest framing) | `SECURITY.md:64-65,256-260` |
| **I-03** | Info | CC8.1 | Commit-identity audit enforces email, not canonical display name | `scripts/commit_identity_audit.py:99-120` |
| **I-04** | Info | CC8.1 | GitHub Actions `checkout` pin skew (v4.2.2 vs v6.0.2) without version comments | `public-ci.yml:23` |
| **I-05** | Info | CC6.1 | API-server CORS accepts wildcard `*` if an operator explicitly sets it | `gateway/platforms/api_server.py:974-978` |
| **I-06** | Info | CC6.8 | Regex-based skill/MCP scanners are inherently evadable (multi-line, obfuscation) | `tools/skills_guard.py:594` |

---

## 4. High-severity findings (detail)

### H-01 — Anomalous `lodash`/`lodash-es` override to non-canonical `4.18.1` (CC7.1, CC9.2)
`package.json:39` pins, via the `overrides` block the project otherwise uses for security back-ports, `"lodash": "4.18.1"` (and `lodash-es` to the same). `package-lock.json:13689-13700` resolves **both** to `4.18.1` from `registry.npmjs.org` with sha512 integrity, `lodash` marked `dev:true`; `wait-on@9.0.10`'s lock entry requires `lodash: "^4.18.1"` (`:19200`). The last publicly-known lodash 4.x release is **4.17.21** (frozen since 2021); **no `4.18.x` exists on the canonical registry** in the reviewer's knowledge. An `overrides` pin force-resolves *every* workspace consumer of `^4.17.x` (`package-lock.json:3185, 9238, 10162`) up to this version.

**Provenance (verified):** the override was introduced in commit `1e1244d` — subject `fix(compression): hot-apply compression.threshold to the live compressor (#70)` (MrGoat, 2026-07-20). A dependency override to a non-canonical version, landed inside an **unrelated compression hotfix**, is the classic shape of a change smuggled past review.

**Why it matters / failure scenario:** if a `4.18.1` artifact is resolvable on any registry the build reaches, the whole workspace — including the dev/build toolchain and any shipped bundle importing `lodash-es` — silently pulls a non-canonical "lodash," i.e. potential arbitrary code in build and runtime. If it is *not* resolvable, `npm ci` breaks reproducibly and the committed integrity hash is untrustworthy. Either outcome is a supply-chain integrity failure.

**This finding could not be resolved offline** and is reported as an anomaly for **urgent human verification**, not a confirmed compromise.
**Remediation:** verify the `4.18.1` integrity hash and artifact provenance against canonical npm; if unverifiable, revert the override to `4.17.21`, regenerate `package-lock.json`, and re-review commit `1e1244d`. Treat as potential lock-poisoning/dependency-confusion until proven legitimate.

### H-02 — MCP-server launch malware preflight is bypassable and fails open (CC6.8, CC8.1)
`SECURITY.md §4` advertises "supply-chain guards for MCP server launches." That guard is an OSV malware preflight (`tools/osv_check.py`, invoked at `tools/mcp_tool.py:2028-2052`) with three structural weaknesses:
- **Ecosystem-gated:** only `npx`/`uvx`/`pipx` commands are inspected (`_infer_ecosystem`, `osv_check.py:65-72`). A server configured as `command: node|python|bash|<abs-path-to-script>` returns ecosystem `None` → **no check runs at all**.
- **Fail-open:** any network error or timeout returns `None` = allow (`osv_check.py:46-51`; `mcp_tool.py:2042-2048`).
- **Malware-only, unpinned:** only confirmed `MAL-*` advisories are considered; ordinary CVEs are ignored (`:167-169`). No version pinning is enforced — `npx -y @scope/pkg` installs `latest` at runtime.

**Failure scenario:** an operator (or a config-writing code path) points `mcp_servers` at an unpinned or non-`npx` server; it spawns into the agent's own process tree — which holds provider credentials and `~/.fabric/.env` — with **zero automated gating**. MCP subprocess env-scrubbing (a real control, below) reduces casual exfiltration but is not containment.
**Remediation:** enforce version pinning + integrity for stdio MCP servers; extend the preflight beyond `npx`/`uvx` or refuse unpinned `latest`; make the fail-open state visible to the operator at launch.

### H-03 — No automated security scanning; documented supply-chain gate not operating (CC4.1, CC7.1)
Across all eight workflows there is **no** CodeQL, Semgrep, Bandit, Trivy, gitleaks/trufflehog, `pip-audit`, `npm audit` gate, or GitHub dependency-review. The extensive custom audits (`public-release-audit.py`, `fabric_identity_audit.py`, `fabric-brand-audit.py`, `skills-governance-audit.py`) enforce workflow-surface, identity, brand, and skill-contract governance — **none** scan for code vulnerabilities, embedded secrets, or vulnerable dependencies. Compounding this:
- `CONTRIBUTING.md:937` and `docs/design/desktop-release-pipeline.md:444` reference a **`supply-chain-audit.yml`** workflow that **does not exist**; `SECURITY.md:319-321` claims "supply-chain guards for … dependency / bundled-package changes in CI."
- The change-classification engine those guards would drive, `scripts/ci/classify_changes.py` (with `scan`/`deps`/`mcp_catalog` lanes), is **invoked by no workflow** — dead code.

**Failure scenario:** a PR introduces a hardcoded credential, an unbounded `>=X` dependency spec, a typo-squatted package, or a known-vulnerable version. The policy says reviewers plus `supply-chain-audit.yml` catch it; no automated gate runs, so detection rests entirely on manual reviewer vigilance — the exact failure mode the policy was written to prevent. For SOC 2, this is both a monitoring gap (CC4.1/CC7.1) and a **control-documentation-accuracy** failure: controls are described in policy that are not operating.
**Remediation:** either restore/publish `supply-chain-audit.yml` and wire `classify_changes.py`, or correct the docs; add CodeQL (or Semgrep), a secret scanner (gitleaks), and dependency review to the always-on `public-ci.yml`.

---

## 5. Medium-severity findings (detail)

**Extension surface (CC6.8).**
- **M-01 — Plugins load unsigned arbitrary Python at import.** `fabric_cli/plugins.py:1734-1853` `exec_module` + `register(ctx)` runs immediately for any file under `plugins/`, `~/.fabric/plugins/`, an opt-in `./.fabric/plugins/`, or a pip `fabric_agent.plugins` entry-point — no signing, checksum, or sandbox, in the agent process that holds credentials. *Mitigations:* no remote plugin install; untrusted manifests can't self-enable (`plugins.py:277-281`); tool override is opt-in. *Rec:* checksum-lock bundled plugins in CI; warn on first load of user/project/pip plugins.
- **M-02 — First-party skills bypass Skills Guard.** `skills_guard.py:57-59` maps the `builtin` tier to `(allow, allow, allow)` and `scan_skill` short-circuits for in-repo content, so all ~198 shipped `SKILL.md` (including the offensive skills in M-04) are never subjected to `THREAT_PATTERNS`; defense is human PR review only. *Rec:* run `scan_skill` over `skills/` + `optional-skills/` in CI, report-only.
- **M-03 — Skills Guard verdict collapses; scan coverage gaps.** `_determine_verdict` (`:1331-1344`) blocks only on *critical* (dangerous) or *high* (caution); a community skill whose worst content is **medium** — `subprocess.run`, `crontab` persistence, unpinned `pip install`, `chmod 777`, 2-level path traversal — scores `verdict=safe` and installs with no prompt. `_scan_content` (`:542-546`) also skips `.mjs .go .rs .ps1 .bat`, `Makefile`, `Dockerfile`, and extensionless scripts. *Rec:* escalate medium clusters (persistence + subprocess); widen scannable types.
- **M-04 — Offensive/dual-use skills shipped.** `optional-skills/security/godmode/` is a working LLM-jailbreak toolkit (input-obfuscation `parseltongue.py`, multi-model `godmode_race.py`, prompts explicitly aimed at "bypassing safety filters on Claude, GPT, Gemini, Grok"); also `security/web-pentest` (active exploitation), `unbroker`, `sherlock`, `research/osint-investigation`, `research/scrapling` (anti-bot bypass). Opt-in and approval-gated, but shipping a safety-bypass tool is an **acceptable-use / dual-use** governance concern (CC1/CC2). *Rec:* classify and document dual-use skills; gate install behind explicit acknowledgment; exclude from any managed/default distribution.
- **M-05 — Skills-index ingests unsanitized community frontmatter.** `build_skills_index.py:495-520` writes `name`/`description`/`tags` from arbitrary crawled repos into the published `skills-index.json` (refreshed 2×/day) with only `str()` coercion — no length bound, no injection scan. That text lands in users' `skills search` results and model context (prompt-injection / social-engineering-to-install vector). Code execution still requires the install-time scan, so this is integrity/injection, not direct RCE. *Rec:* scan crawled text with `threat_patterns`, cap length, drop/flag.
- **M-06 — Dashboard/API skill-install suppresses the confirm gate.** `POST /api/skills/hub/install` (`web_server.py:13622-13646`) and TUI paths pass `skip_confirm=True`; the scan still blocks dangerous/caution verdicts, but a caller with the dashboard token installs a *safe/caution*-verdict skill without the synchronous `y/N` human confirm the CLI enforces — the `SECURITY.md §3.1` "operator sees what they install" guarantee weakens off-TTY. *Rec:* require an explicit confirm/allowlist acknowledgment on the API path.
- **M-20 — LINE adapter binds `0.0.0.0` by default.** `plugins/platforms/line/adapter.py:661` defaults the webhook host to all interfaces, contrary to `SECURITY.md §2.6.5` (plugin HTTP servers default to loopback; non-loopback is a break-glass decision). *Rec:* default to loopback, require explicit opt-in for `0.0.0.0`.

**Secrets, data & privacy (CC6.7, CC7.4, Confidentiality, Privacy).**
- **M-07 — No secret-scanning gate.** No gitleaks/trufflehog/detect-secrets in CI or a `.pre-commit-config.yaml`; the git hooks enforce only commit identity. A live key pasted into a tracked source file is not blocked locally or in CI (runtime `.env` is git-ignored; source files are not scanned). *Rec:* add a secret scanner over the working tree and CI push range.
- **M-09 — Observability egress lacks scrubbing.** When enabled, the Langfuse plugin transmits full conversation content, tool-call **arguments** and **results** (including `read_file` output) to an external SaaS (`plugins/observability/langfuse/__init__.py:201`) with base64/length trimming but **no** call to `agent/redact.py`. Opt-in, but a key or PII in a tool result leaves the trust envelope unredacted. *Rec:* route observability payloads through `redact_sensitive_text` before export.
- **M-10 — No retention/purge; plaintext state; no data-subject process.** `fabric_state.py:808-876` persists full message content, reasoning, tool calls, `user_id`, `display_name`, `chat_id`, `system_prompt`, `cwd` in plaintext SQLite. Deletion is manual only; there is **no TTL/auto-purge** for conversation data, no at-rest encryption, and no documented GDPR/data-subject-deletion procedure. Storage-limitation and data-minimization (Privacy) and CC7.4 are unmet by default. *Rec:* documented retention window + automated purge + a deletion procedure.
- **M-19 — Credentials plaintext at rest.** `~/.fabric/.env` and `~/.fabric/auth.json` are plaintext (`auth.json` pools many providers' OAuth refresh tokens, concentrating risk); no OS keychain (`agent/secret_sources/__init__.py:30` notes it is "under discussion"). Well-mitigated by `0600`/`0700` atomic writes, but no encryption-at-rest. *Rec:* prioritize keychain backing or encrypt `auth.json` with a machine-bound key.

**Network & injection (CC6.7).**
- **M-08 — SSRF redirect-bypass in three messaging adapters.** WeCom (`wecom/adapter.py:1099`), QQBot (`qqbot/adapter.py:1977`), and Feishu (`feishu/adapter.py:3463`) validate only the *initial* URL, then follow redirects with no `_ssrf_redirect_guard` — so a 302 from an allowed host to `http://169.254.169.254/…` fetches cloud metadata/IAM credentials and surfaces them to the agent. Inconsistent with the correct pattern used by `gateway/platforms/base.py`, `teams`, `slack`, `matrix`, and `vision_tools`. Gateway messages are an untrusted input surface and credential exfiltration is in-scope per `SECURITY.md §3.1`. *Rec:* attach the shared `event_hooks={"response":[_ssrf_redirect_guard]}` (mechanical fix).

**Change management & CI/CD (CC8.1, CC4.1).**
- **M-11 — Forbidden AI-attribution footers in mainline history.** Squash commits `c534318` (#81) and `f230d17` (#76) contain `Claude-Session: https://claude.ai/code/session_…`, exactly what `commit_identity_audit.py:67-74` forbids. GitHub assembles squash messages from PR title/body at merge time; the PR-event audit checks the branch commits, and the push-to-`main` audit runs *after* the merge (detect, not prevent). *Rec:* gate the rendered squash message via a merge queue, or enforce PR title/body hygiene.
- **M-12 — Separation of duties is documentation-only.** No `.github/CODEOWNERS`; no self-merge / reviewer / merger roles are prose in `AGENT_GUARDRAILS.md` only; branch protection lives in GitHub settings outside the repo. The control cannot be evidenced from the checkout. *Rec:* commit CODEOWNERS for `.github/workflows/**`, `scripts/ci/**`, and core contracts; export the branch-protection ruleset as evidence.
- **M-14 — Hosted image has no in-repo provenance.** `deploy/docker-compose.hosted.yml:22,47` and `provision.sh:81` pull `ghcr.io/obliviousodin/fabric:latest` (mutable) and `caddy:2`; `Dockerfile:242` references a `docker.yml` build workflow that does not exist, and no workflow builds/pushes the image. The hosted path (incl. unattended `cloud-init.yaml`) has no digest, attestation, or SBOM. *Rec:* build the image from an audited workflow (or document the external pipeline as a subservice control), pin by digest, add provenance attestation.
- **M-15 — Over-privileged tokens on Pages/crawler jobs.** `docs-pages.yml:32-74` and `skills-index.yml:20-58` expose `pages: write` + `id-token: write` to the *build* job (npm build; community-repo crawler) rather than confining them to the deploy job. A compromised build-time dependency could mint OIDC / deploy Pages. *Rec:* move write scopes to the deploy job; drop `GITHUB_TOKEN` from the build step.
- **M-16 — Python release artifacts unsigned.** The release chain binds artifacts by SHA-256 manifest but applies no Sigstore/cosign/PEP 740/GPG signature; Windows Authenticode is escapable via the `ALLOW_UNSIGNED_WINDOWS` repo variable (`desktop-release.yml:234-246`). macOS notarization *is* enforced. *Rec:* add `attest-build-provenance` (SLSA) and/or PyPI Trusted Publishing; alarm on the Windows escape hatch.
- **M-21 — No automated dependency-update / vuln monitoring.** No Dependabot or Renovate config; exact pins are excellent for reproducibility but freeze deps until a human bumps them, so newly-disclosed CVEs are not surfaced ("pinned but stale"). *Rec:* enable Dependabot/Renovate (security updates only, respecting the pinning policy).

**Access model & container posture (CC6.1, CC6.3, CC6.6).**
- **M-13 — Compose wrapper weaker than documented containment.** `SECURITY.md §2.2` presents "Fabric's own Docker image and Compose setup" as a whole-process containment posture for ingesting untrusted content, but the shipped `docker-compose.yml:35,67` runs both services with `network_mode: host` and none of the `--cap-drop ALL` / `no-new-privileges` / `pids-limit` / `tmpfs` hardening. (That hardening *is* correctly applied to the ephemeral **terminal sandbox** — `website/docs/user-guide/security.md:366-373` — a different mechanism.) An operator following the documented posture gets full host-network exposure and default capabilities. *Rec:* add `cap_drop`, `security_opt: [no-new-privileges]`, `pids_limit`, and drop `network_mode: host` unless a listed adapter requires it; document the residual clearly.
- **M-17 — API-server per-request auth fails open when key unset.** `api_server.py:1063-1064` (`if not self._api_key: return None`) admits every request when the key is empty; the system is saved only by a *separate* startup guard that refuses to run without a strong key. Any refactor/embedding serving routes without `connect()` would expose all terminal-capable endpoints unauthenticated (RCE). *Rec:* have `_check_auth` return 401 when the key is empty so request-path authz is self-contained.
- **M-18 — No per-user RBAC once authenticated.** Dashboard/kanban/API grant every authenticated principal full dispatch/terminate/delete power (`plugin_api.py:2189,2300`). Consistent with `SECURITY.md §2.6` rule 4 ("all authorized callers equally trusted"), but a real authorization-granularity limitation for any shared/gated deployment. *Rec:* record as an accepted risk; recommend separate instances for capability separation.

---

## 6. Low & informational findings

All Low/Info items are in the register (§3) with evidence and criterion. Grouped remediation themes:

- **Info-disclosure & logging (L-02, L-03, L-16, L-18):** make audit logs tamper-evident/rotated and fail-closed; return generic client errors; keep vendor-prefix redaction forced even when `redact_secrets` is off; redact debug dumps and session transcripts.
- **Supply-chain hardening residuals (L-04, L-05, L-07, L-11, L-13, L-14, L-17):** checksum-verify toolchain downloads in installers; run `uv sync --locked` on the always-on PR workflow; digest-pin the runtime base image; hash-pin CI pip installs; review the `postinstall` monkeypatch and pre-release WhatsApp lib; refuse the placeholder vLLM key.
- **CI accuracy (L-08, L-12, I-03, I-04):** env-indirect the dispatch input; rename cost-gated placeholder jobs so required-check names don't overstate coverage; enforce canonical committer *name*; standardize the `checkout` pin.
- **Extension & app residuals (L-01, L-09, L-10, L-19, L-20):** `html.escape` the MCP OAuth callback; fail the kanban WS helper closed; path-confine ACP session auto-approve; note the TLS-disabling OSINT skill; default `guard_agent_created` on for shared deployments.
- **Hygiene (L-15):** add `.env.production` and `id_rsa*`/`id_ed25519*` to `.gitignore`.
- **Accepted residuals (I-01, I-02, I-05, I-06):** DNS-rebinding, heuristic redaction, opt-in wildcard CORS, and regex-scanner evadability are documented design limits — record as accepted risks with the compensating OS-isolation boundary.

---

## 7. Control strengths (SOC 2 credits)

A SOC 2 examiner credits operating controls. Fabric presents genuine, evidence-backed strengths:

- **CC6 — Fail-closed authorization architecture.** A single central gate (`gateway/authz_mixin.py:298-661`) defaults to deny, is enforced before dispatch on every inbound path, and explicitly closes the "no allowlist ⇒ accept everyone" trap (`:521-570`). Approval buttons re-authorize the clicker (fail-closed) on Telegram/Slack/Discord; all HTTP webhooks verify HMAC/clientState with `hmac.compare_digest`; the dashboard neuters `--insecure`, mandates auth off-loopback, and defends against DNS rebinding. Session IDs are routing handles, never authorization.
- **CC6.7 — Credential scrubbing across all four subprocess surfaces** (shell, MCP allowlist, cron, code-exec child), plus fail-closed per-profile secret isolation (`agent/secret_scope.py` raises rather than falling back to `os.environ`), and a comprehensive redaction engine wired into **every** log handler.
- **CC6.8 — Externally-installed-skill defense-in-depth:** trust tiers, quarantine, an **attested TOCTOU-proof re-scan** (`skills_hub.py:8538-8558`), non-overridable dangerous-community blocks, ZIP-bomb/SSRF pre-flight, an append-only `0600` install audit log, and a strong central SSRF module (`tools/url_safety.py`) with an always-on cloud-metadata floor.
- **CC7 / PI — Safe-by-construction parsing:** YAML uses `CSafeLoader`/`SafeLoader` and `ruamel YAML(typ="safe")` everywhere; the only `pickle.loads` is gated behind `--i-trust-this-file`; the dashboard upholds its documented "renders agent output as inert HTML" stance (React auto-escaping, DOMPurify/sanitized markdown, scheme-gated links); HTTP file servers canonicalize with `.resolve()` + containment. A defensive `plugins/security-guidance` plugin actively flags `eval`/`pickle`/`shell=True`/`verify=False`/`dangerouslySetInnerHTML` in written code.
- **CC8.1 — Change-management rigor:** all GitHub Actions pinned to full commit SHAs; least-privilege `contents: read` default tokens; no `pull_request_target`; a **tested meta-audit** that content-pins the workflows themselves and fails CI on drift; a three-layer commit-identity control (local config + committed hooks + CI) that resolves `git var` identities to defeat `--author`/`--no-verify`; an anti-artifact-poisoning release chain binding artifacts to repo + source SHA + digest, re-verified multiple times, never rebuilt across channels; macOS notarization asserted.
- **CC9.2 — Dependency pinning discipline:** `uv.lock` (1,912 sha256 entries, zero git/URL sources) via `uv sync --locked`/`--frozen`; `package-lock.json` (1,381 sha512 integrity entries) via `npm ci`; Gradle wrapper + distribution SHA-256 verified; `flake.lock` pinned; a documented pinning policy citing real 2026 supply-chain incidents; blast-radius minimization excluding quarantine-prone packages from eager install. (H-01 is the lone anomaly against this otherwise-strong backdrop.)
- **CC2 — Documentation quality:** `SECURITY.md`, `AGENT_GUARDRAILS.md`, `AGENTS.md`, and `CONTRIBUTING.md` form a coherent, honest control narrative — including candidly labeling in-process heuristics as *not* boundaries. (The gap is accuracy drift: docs reference a `supply-chain-audit.yml` that does not exist — H-03.)

---

## 8. SOC 2 Trust Services Criteria readiness matrix

| Criterion | State | Basis |
|---|---|---|
| **CC1** Control Environment | ⚠️ Partial | Strong written guardrails; but separation of duties unenforced (M-12) and dual-use acceptable-use undefined (M-04) |
| **CC2** Communication & Information | ⚠️ Partial | Excellent control narrative; documentation-accuracy drift (H-03, L-06) |
| **CC3** Risk Assessment | ⚠️ Partial | `SECURITY.md` is a real threat model; no formal periodic risk assessment / vuln-management program |
| **CC4** Monitoring | ❌ Gap | No automated scanning; a documented control is not operating (H-03); audit trails not tamper-evident (L-02); monitoring detects but does not prevent (M-11) |
| **CC5** Control Activities | ⚠️ Partial | Preventive activities strong; detective activities thin |
| **CC6** Logical & Physical Access | ✅ Strong / ⚠️ Partial | Fail-closed authz + credential scrubbing are strengths; gaps in at-rest encryption (M-19), RBAC (M-18), unsigned plugin code (M-01), container posture (M-13) |
| **CC7** System Operations | ⚠️ Partial / ❌ Gap | Strong release integrity & input validation; no vuln scanning (H-03, M-21), SSRF gaps (M-08), unredacted egress (M-09) |
| **CC8** Change Management | ✅ Strong / ⚠️ Partial | Commit identity, workflow meta-audit, pinning are strong; separation of duties (M-12), footers-in-history (M-11), unsigned artifacts (M-16) |
| **CC9** Risk Mitigation | ⚠️ Partial | Pinning discipline strong; no dependency vuln monitoring (M-21); supply-chain gate absent (H-03); anomaly (H-01) |
| **A1** Availability | ⚠️ Partial | Terminal sandbox hardened; compose network posture weak (M-13); no formal BCP/DR (single-tenant local tool) |
| **C1** Confidentiality | ⚠️ Partial | Strong redaction/scrubbing; at-rest encryption & retention gaps (M-10, M-19) |
| **PI1** Processing Integrity | ⚠️ Partial | Release & input-validation integrity strong; managed injection surface; three SSRF gaps (M-08) |
| **P1–P8** Privacy | ❌ Gap | No retention/purge, no data-subject process, unredacted observability egress (M-10, M-09) |

---

## 9. Prioritized remediation roadmap

**Immediate (0–2 weeks) — verify & stop-the-bleed**
1. **H-01** — Verify the `lodash 4.18.1` override against canonical npm; revert to `4.17.21` if unproven; re-review commit `1e1244d`.
2. **H-03** — Add a secret scanner (gitleaks) and dependency review to `public-ci.yml`; restore `supply-chain-audit.yml` **or** correct the docs and wire/remove `classify_changes.py`.
3. **M-08** — Attach the shared SSRF redirect guard to the WeCom/QQBot/Feishu adapters (mechanical).
4. **M-11 / M-12** — Add `CODEOWNERS`; gate squash-message hygiene; export branch-protection config as evidence.

**Short-term (2–8 weeks) — detective & governance controls**
5. **H-02** — Harden the MCP-launch preflight (pin/verify, extend beyond `npx`/`uvx`, surface fail-open).
6. **M-01 / M-02 / M-03 / M-05 / M-20** — Checksum bundled plugins; run Skills Guard over first-party skills in CI; escalate medium clusters + widen scan types; sanitize the crawled skills index; default listener plugins to loopback.
7. **M-07 / M-16 / M-21** — Secret-scanning pre-commit hook; SLSA provenance + PyPI Trusted Publishing; enable Dependabot/Renovate.
8. **CC4** — Add CodeQL/Semgrep SAST; centralize and integrity-protect the audit logs (L-02).

**Medium-term (2–4 months) — data governance & posture**
9. **M-10 / M-19** — Retention window + automated purge + data-subject-deletion procedure; at-rest encryption / OS keychain for credentials.
10. **M-09** — Route observability payloads through redaction before external egress.
11. **M-13 / M-14 / M-15** — Harden the compose deployment; build+attest the hosted image in-repo; scope Pages/crawler tokens to the deploy job.
12. **M-04** — Formal dual-use acceptable-use policy and gated distribution for offensive skills.

**Programmatic (ongoing)**
13. Stand up a documented vulnerability-management + periodic risk-assessment cadence (CC3/CC4); adopt the remaining Low/Info hardening (§6).

---

## 10. Appendix — extension inventory (attack-surface reference)

- **Skills:** 96 bundled (`skills/`, 30 categories) + 102 opt-in (`optional-skills/`). Highest-risk clusters: `security/*` (offensive/dual-use), `finance`+`payments`+`blockchain` (money movement, wallet keys), `mlops/*` (code exec + model/package downloads), `autonomous-ai-agents/*` (spawn other coding agents), `apple/*` (local PII via `osascript`), `computer-use` (screen/input control).
- **Plugins:** ~88 (`plugins/`, 19 categories). External surfaces: `platforms/*` (~22 messaging adapters, inbound listeners), `model-providers/*` (~32, API keys), `memory/*` (8, conversation+credential egress to SaaS), `browser/*` + `web/*` (arbitrary fetch), `dashboard_auth`/`observability`/`kanban` (HTTP surfaces/telemetry). Defensive: `security-guidance`.
- **MCP catalog:** 2 (`optional-mcps/`): `linear` (remote, native OAuth 2.1/PKCE — low risk), `unreal-engine` (local `127.0.0.1:8000`, `auth: none`, loopback-only — low risk). Both PR-curated ("presence = approval").
- **Capability packs:** 2 (`capability-packs/`): content-only skill routers — low direct risk.

---

*Prepared as an internal SOC 2 readiness assessment (codename IRONLOOM). Findings are evidence-based against the audited revision; severity reflects SOC 2 control-effectiveness, which is broader than Fabric's own vulnerability-disclosure scope (`SECURITY.md §3`). Items Fabric classifies as out-of-scope heuristics are reported here as control-effectiveness observations, not as claims of policy violation. No source files were modified during this audit.*
