# Changelog

All notable changes to Fabric are documented in this file.

## [0.19.1] - 2026-07-15

### Added

- Added fully resolved semantic light/dark theme exports so desktop surfaces can consume the canonical Fabric design-system roles without duplicating palette values.
- Added the official responsive Fabric wordmark to the desktop chat introduction, with distinct assets for light and dark appearances.

### Changed

- Refactored the default desktop theme onto Fabric's warm neutral canvas, restrained violet actions, system typography, and shared semantic surface hierarchy while preserving existing alternate themes.
- Standardized desktop dialogs, onboarding, recovery, update, notification, and picker surfaces on the shared overlay background, stroke, and shadow tokens without changing their layout.
- Removed the inherited display-font treatment from the chat introduction in favor of Fabric-owned brand assets.

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

[0.19.1]: https://github.com/ObliviousOdin/fabric/compare/v2026.7.14...HEAD
[0.19.0]: https://github.com/ObliviousOdin/fabric/releases/tag/v2026.7.14
