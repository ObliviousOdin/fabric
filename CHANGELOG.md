# Changelog

All notable changes to Fabric are documented in this file.

## [Unreleased]

### Added

- Added a bundled `venture-studio` skill category with 13 new skills covering the idea-to-market arc: brainstorming, build-something-people-want, product-taste, impeccable-craft, design-studio, proposal-writing, business-planning, website-building, webapp-development, rstack, ios-app-development, d2c-smart-products, and hardware-manufacturing. The default skills overview now answers venture questions — ideation, business plans, proposals, websites, web and iOS apps, D2C smart products, and manufacturing (CAD, PCB, EVT/DVT/PVT, production) — instead of only the classic tool-centric set.
- Added the Skills Ecosystem Directory: a curated, trust-tiered map of 224 external agent-skill sources (first-party vendor repos, expert packs, marketplaces, MCP registries, research references) published at `reference/skills-ecosystem-directory` with a machine-readable copy at `/api/skills-sources.json`.
- Added a `skills-index` workflow that rebuilds the unified skills index twice daily and redeploys the docs site, so the Skills Hub page and `fabric skills search` stop serving a stale catalog. The index build now also crawls 177 curated, tree-verified skill-pack taps (~2,400 skills across 113 repos) from the ecosystem directory using rate-limit-cheap tree + raw fetches.
- Added eight curated community skill packs to the default hub taps — superpowers, compound-engineering, marketing, startup-founder, product-management, taste, and impeccable packs — searchable via `fabric skills search`; installs still pass the skills guard scan and quarantine.

### Fixed

- The docs-site Skills Hub no longer falls back to a broken, near-empty legacy snapshot when the unified index is missing: the committed fallback caches were refreshed (OpenAI tap 0 → 44 skills after its `skills/.curated/` move) and the new `venture-studio` and `web-development` categories now render with proper labels and icons.

## [0.20.2] - 2026-07-15

### Added

- Media-heavy dashboard plugins can now load WebAssembly modules with the browser-correct MIME type and use the host's `Film` icon and ReactDOM helpers without bundling a second React renderer.

### Changed

- Studio and other OpenCut integrations now have a documented standalone-plugin path that preserves Fabric's narrow core and explicit plugin enablement model.

## [0.20.1] - 2026-07-15

### Fixed

- Packaged Fabric releases now include the compiled dashboard, so `fabric dashboard` from a wheel or source distribution serves the same Design workspace verified in web CI.
- Release promotion now rejects candidates that omit the dashboard index, JavaScript, or CSS instead of publishing an incomplete package.

## [0.20.0] - 2026-07-15

### Added

- Added Design workspaces to the desktop and web apps for turning product intent into structured briefs, choosing deliverables and fidelity, and applying reusable design-system presets.
- Added a bundled `/design` skill that coordinates Fabric's existing product-design specialists while keeping the core agent tool surface unchanged.

### Changed

- Design workspaces hand a reviewable prompt into each app's existing chat experience, preserving desktop session behavior and the dashboard's PTY-backed TUI boundary.
- The dashboard now exposes Design at `/workspace/design`, with `/design` retained as a compatibility route.

### Fixed

- Sanitized dashboard chat drafts before writing them to the embedded terminal, including bracketed-paste handling for multiline design briefs.

## [0.19.1] - 2026-07-15

### Added

- Desktop surfaces can now consume fully resolved light and dark Fabric theme roles without duplicating palette values.
- The desktop chat introduction now displays the official responsive Fabric wordmark, with distinct assets for light and dark appearances.

### Changed

- Fabric's default desktop theme now uses a warm neutral canvas, restrained violet actions, system typography, and a shared semantic surface hierarchy while preserving existing alternate themes.
- Desktop dialogs, onboarding, recovery, update, notification, and picker surfaces now share consistent overlay backgrounds, strokes, and shadows without changing their layout.
- The chat introduction now uses Fabric-owned brand assets instead of the inherited display-font treatment.

## [0.19.0] - 2026-07-14

### Added

- Added a canonical Fabric design-system package with semantic light/dark tokens, deterministic brand-asset generation, and product-wide logo formats for web, desktop, installer, TUI, ACP, favicon, and mobile/PWA use.
- Added the Workspace and Admin information architecture, including the operational Home screen, responsive three-panel Chat, explicit screen-state primitives, and compatibility routes for existing dashboard and plugin links.
- Added an enterprise Workspace/Admin guide, updated dashboard documentation, and refreshed product screenshots for the new navigation and core workflows.

### Changed

- Reworked the dashboard into the original Woven Operations visual language: warm neutral canvases, restrained Fabric violet, structural thread/bracket motifs, accessible system typography, and a neutral navigation rail across both experiences.
- Reframed Integrations as an operational ledger and preserved the latest Work Board controls inside Chat without remounting the persistent PTY session.
- Deferred non-English locale packs and replaced the inherited heavy badge dependency with a Fabric-owned primitive, reducing the HTML-referenced initial JavaScript payload.
- Aligned the website, desktop, installer, terminal, ACP, and public release boundaries to the same Fabric identity and Apache-2.0 product license.

### Fixed

- Fixed modal focus restoration, nested scroll locking, compact Chat sheets, responsive navigation semantics, and loading/empty/error-state behavior.
- Fixed release version synchronization so Python, ACP, desktop, npm workspace metadata, and the uv lockfile move together.
- Fixed PWA icon/manifest coverage and preserved query/hash state across canonical Work and other legacy route redirects.

### Removed

- Removed unused legacy display fonts and the inherited dashboard styling paths that made Fabric resemble the upstream Hermes interface.

[0.20.2]: https://github.com/ObliviousOdin/fabric/compare/v2026.7.15.2...HEAD
[0.20.1]: https://github.com/ObliviousOdin/fabric/compare/v2026.7.15...v2026.7.15.2
[0.20.0]: https://github.com/ObliviousOdin/fabric/compare/v2026.7.14...v2026.7.15
[0.19.1]: https://github.com/ObliviousOdin/fabric/compare/v2026.7.14...HEAD
[0.19.0]: https://github.com/ObliviousOdin/fabric/releases/tag/v2026.7.14
