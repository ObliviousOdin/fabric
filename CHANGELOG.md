# Changelog

All notable changes to Fabric are documented in this file.

## [Unreleased]

### Added

- Fabric Mobile (iOS) grew from a remote text client toward a robust native product: rich assistant-transcript rendering, a searchable pinned session library, reliable remote controls, a lifecycle-safe Live View, and streaming scroll preservation that holds position as tokens arrive.
- Loop 0 of the mobile upgrade plan landed the shared capability-manifest governance layer and cross-platform wire contracts (a TypeScript reference plus Swift and Kotlin ports) for future device-node families — device node, node invocation, trust center, connected nodes, push, and session admin — all additive-optional and gated behind the durable-Work fail-closed precedent, so nothing activates until a gateway advertises it.
- A hidden durable-Work inbox model is present but dark: it stays out of the mobile surfaces until its full gateway contract is reviewed and enabled.
- Loom, a Fabric-native deployment plane, with a Phase 0 CI cost cut that trims spend on pull requests.
- Multi-agent collaboration guardrails (`AGENT_GUARDRAILS.md`): ownership zones per surface, branch/worktree isolation, the no-self-merge merge gate, and the "green PR ≠ green `main`" cost-gate trap — plus canonical commit-identity enforcement (repository identity only, no AI-tool attribution) applied fail-closed across local git hooks and CI, bootstrapped by `scripts/setup-git-guardrails.sh`.
- Added a conversation-first iOS home based on the approved mobile direction: a canonical Fabric header, one obvious outcome composer, a solid-purple Start goal action, one prioritized live conversation, and a two-row recent briefing with working resume, see-all, new-chat, and server controls. The production surface truthfully uses the advertised session contract; the unadvertised Durable Work projection remains out of the home until its complete gateway contract is reviewed and enabled.
- Added exact iOS release provenance: release project generation now requires a clean tracked checkout, derives the Git commit itself, embeds it as `FabricSourceRevision`, and records the packaged revision beside the merged SHA in the TestFlight ledger.
- Added a fail-closed native iOS goal portfolio that projects verified durable Work Jobs and Attention into mutually exclusive needs-attention, active, outcome, and unsupported sections shared by the upcoming conversation-first, mission-control, and Dispatch surfaces; future Job kinds/statuses remain visible but non-actionable, linked open Attention is never hidden by a terminal or unsupported Job, and result/error bodies stay behind explicit detail fetches.
- Added a phased Fabric iOS parity roadmap and TestFlight build ledger, plus an immutable Xcode project-generation contract with a CI-verified generic Xcode Cloud bootstrap and project-adjacent post-clone hook that keep release bundle overrides out of tracked source, map Xcode Cloud build numbers into `CFBundleVersion`, and run the same pinned generator path in GitHub CI and Xcode Cloud.
- Rebuilt Achievements as the private, profile-local **Fabric Journey**: outcome-based onboarding, a chat/tool/delegation starter path, capability Paths, permanent mastery ranks, loss-free seasonal Momentum, daily and weekly quests, honest evidence labels, and separate You / local Profiles / self-reported Friendly leaderboards. Tracking is default-on but records only a closed content-free event vocabulary; users can pause collection, disable active-time reflection, export the metadata, or delete it without losing observed mastery. The original achievements remain available as Legacy history, and the plugin still adds no model tool or prompt content.
- Restored Skills Hub discoverability inside **Admin → Integrations** with direct Skills Hub and MCP links while preserving the consolidated sidebar hierarchy.
- Live host infrastructure monitor across surfaces. New `fabric monitor` (alias `fabric top`) renders CPU (aggregate + per-core), memory, disk, load, network throughput, and GPU/VRAM in a live terminal panel (`--once` / `--json` for snapshots). The web dashboard Host card and desktop Command Center → System panel poll the same shared `fabric_cli.system_stats` collector over `/api/system/stats`, so metrics never drift. GPU uses `pynvml` when available and falls back to `nvidia-smi`.
- New `fabric disk` command to see and reclaim Fabric's storage. `fabric disk usage` (alias `du`) breaks down how much space each store under `~/.fabric` is using — caches, sessions, memory, databases, backups, and more — largest-first, with a grand total and the free space left on the volume (`--json` for machine-readable output, `--profile NAME` to inspect another profile). `fabric disk clean` reclaims regenerable data (caches, rotated log backups, diagnostic traces, temp scratch, re-downloadable media); it is a dry-run preview by default and only deletes with `--yes`, never touching sessions, the state database, memories, credentials, config, backups, the cron control-plane, or persistent sandbox/browser/worktree state. `--only`/`--skip` choose categories.
- Added a bundled `venture-studio` skill category with 13 new skills covering the idea-to-market arc: brainstorming, build-something-people-want, product-taste, impeccable-craft, design-studio, proposal-writing, business-planning, website-building, webapp-development, rstack, ios-app-development, d2c-smart-products, and hardware-manufacturing. The default skills overview now answers venture questions — ideation, business plans, proposals, websites, web and iOS apps, D2C smart products, and manufacturing (CAD, PCB, EVT/DVT/PVT, production) — instead of only the classic tool-centric set.
- Added the Skills Ecosystem Directory: a curated, trust-tiered map of 224 external agent-skill sources (first-party vendor repos, expert packs, marketplaces, MCP registries, research references) published at `reference/skills-ecosystem-directory` with a machine-readable copy at `/api/skills-sources.json`.
- Added a `skills-index` workflow that rebuilds the unified skills index twice daily and redeploys the docs site, so the Skills Hub page and `fabric skills search` stop serving a stale catalog. The index build now also crawls 177 curated, tree-verified skill-pack taps (~2,400 skills across 113 repos) from the ecosystem directory using rate-limit-cheap tree + raw fetches.
- Added eight curated community skill packs to the default hub taps — superpowers, compound-engineering, marketing, startup-founder, product-management, taste, and impeccable packs — searchable via `fabric skills search`; installs still pass the skills guard scan and quarantine.
- Added a bundled `orchestration` skill category — six foundational multi-agent skills built on Fabric's real delegation machinery: `orchestration` (the routing front door), `ensemble` (diverse-lens subagent panels with judging), `fan-out` (parallel map-reduce batches), `pipeline` (staged fresh-context handoffs via artifact contracts), `builder-crew` (a chartered virtual product team for founders), and `adversarial-verify` (independent skeptic subagents as a quality gate). All examples use the actual `delegate_task` schema, state the real defaults, and route durable work to kanban worker lanes and multi-model ensembles to Mixture of Agents.
- Repositioned the Skills Hub for technical founders and builders: new hero copy, a builder-first category order (Venture Studio and Orchestration lead; personal/leisure categories such as Apple and Media sink to the bottom), two new orchestration stacks (Orchestrate the Work, Founder Crew), and orchestration skills in the featured picks.
- Extended the Skills Ecosystem Directory and curated taps with the agent-skills atlas research pass: 89 newly tree-verified sources (312 total in the directory) and 134 additional tap entries across 83 repos — first-party packs from AWS, .NET, Flutter, Databricks, Cypress, Flux, GitGuardian, LambdaTest, AllenAI, AntV, and LottieFiles, plus practitioner packs from Addy Osmani (also a runtime hub tap), Anton Babenko, Dean Peters, and others.
- The Skills Hub now opens on a Recommended view instead of the full grid: ten curated "works well together" stacks (Zero to One, Karpathy-Style Discipline, Design Studio, Launch a Website, Ship a SaaS, Ship an iOS App, Hardware & D2C, Win the Client, Compound Engineering, Superpowers Method) plus hand-picked featured skills including the community `karpathy-guidelines` pack. Stack chips are color-coded by source, community members not yet crawled render as install chips, expanded skill cards show "works well with" companions from skill metadata, and the curated data ships at `/api/skill-stacks.json` with build-time validation against the catalog.

### Changed

- Contributor docs de-duplicated: the skill-authoring "HARDLINE" standards are now maintained in one canonical place (`CONTRIBUTING.md`), with `AGENTS.md` linking to it instead of keeping a second copy that had already drifted. A new "Find your path" read-router in `CONTRIBUTING.md` points contributors to the sections that matter for their change rather than requiring the whole doc set end-to-end.

### Fixed

- Context compression now hot-applies `compression.threshold` to the live compressor instead of waiting for a restart, and calibrates context pressure using real provider token usage.
- Durable-Work replay receipts are now truthful, with the durable-Work contract proven by tests.
- QR pairing intake on iOS is hardened against malformed and hostile payloads.
- Patched dependency vulnerabilities across the npm and Python manifests.
- The commit-history audit ignores transient pull-request merge refs, removing false positives on merged branches.
- The public identity audit now closes every `git cat-file --batch` subprocess stream after full or early generator teardown, eliminating the repeated unclosed-file `ResourceWarning` noise from release-audit test runs.
- The docs-site Skills Hub no longer falls back to a broken, near-empty legacy snapshot when the unified index is missing: the committed fallback caches were refreshed (OpenAI tap 0 → 44 skills after its `skills/.curated/` move) and the new `venture-studio` and `web-development` categories now render with proper labels and icons.

## [0.21.0] - 2026-07-16

### Added

- Fabric Desktop now opens Browser and Computer Use activity in a docked Agent Live View beside chat, with pause, close, and a resizable always-on-top picture-in-picture window that docks back into the same session.
- Added Browser and Computer Use Live View guides with step-by-step instructions and clear performance and model-context behavior.

### Changed

- On local Desktop backends, Browser Live View now pulls one bounded active-tab frame at a time over a dedicated authenticated visual connection, starts at most two captures per second for each browser session, and never shares the chat, model-output, tool-event, or approval socket.
- Computer Use Live View reuses screenshots returned by existing actions instead of adding another screen-capture loop; neither viewer adds model tools, prompt text, context tokens, or model calls.
- Computer Use documentation now uses the current CuaDriver permission flow, `PATH`-based local-build selection, and `config.yaml` telemetry setting.
- Documentation impact contracts now map Desktop, Browser automation, and Computer Use code to their narrative guides so CI requires those docs to evolve with future behavior changes.

### Fixed

- Raised the optional MCP Python SDK floor to 1.28.1, which includes upstream fixes for cross-principal HTTP sessions, cross-session experimental task access, and WebSocket Host/Origin validation (CVE-2026-52869, CVE-2026-52870, and CVE-2026-59950).
- Finder and Dock launches now include user-local executable directories so Desktop can discover `cua-driver` consistently.
- Browser preview work now yields to agent-driven browser actions without queueing them, securely bounds visual payloads, and cleans up stale CDP supervisors, pending connections, and PiP ownership across timeout, reload, crash, minimize, and backend-switch paths.
