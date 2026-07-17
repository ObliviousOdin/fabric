# Changelog

All notable changes to Fabric are documented in this file.

## [Unreleased]

### Added

- The Achievements **Team Leaderboard** can now host its relay from the dashboard. A **Host on this machine** button starts and supervises the relay (surviving a dashboard restart), a **Detect** button reads a running relay plus this machine's Tailscale identity to **auto-fill a shareable Relay URL**, and the panel surfaces `fabric setup tailscale` for the Tailscale QR login — no more typing a host address you have to look up. Tailscale reads and connection reuse `fabric_cli.tailscale_setup`.

## [0.21.0] - 2026-07-16

### Added

- Fabric Desktop now opens Browser and Computer Use activity in a docked Agent Live View beside chat, with pause, close, and a resizable always-on-top picture-in-picture window that docks back into the same session.
- Added Browser and Computer Use Live View guides with step-by-step product screenshots and clear performance and model-context behavior.

### Changed

- On local Desktop backends, Browser Live View now pulls one bounded active-tab frame at a time over a dedicated authenticated visual connection, starts at most two captures per second for each browser session, and never shares the chat, model-output, tool-event, or approval socket.
- Computer Use Live View reuses screenshots returned by existing actions instead of adding another screen-capture loop; neither viewer adds model tools, prompt text, context tokens, or model calls.
- Computer Use documentation now uses the current CuaDriver permission flow, `PATH`-based local-build selection, and `config.yaml` telemetry setting instead of legacy Hermes environment overrides.
- Documentation impact contracts now map Desktop, Browser automation, and Computer Use code to their narrative guides so CI requires those docs to evolve with future behavior changes.

### Fixed

- Raised the optional MCP Python SDK floor to 1.28.1, which includes upstream fixes for cross-principal HTTP sessions, cross-session experimental task access, and WebSocket Host/Origin validation (CVE-2026-52869, CVE-2026-52870, and CVE-2026-59950).
- Finder and Dock launches now include user-local executable directories so Desktop can discover `cua-driver` consistently.
- Browser preview work now yields to agent-driven browser actions without queueing them, securely bounds visual payloads, and cleans up stale CDP supervisors, pending connections, and PiP ownership across timeout, reload, crash, minimize, and backend-switch paths.

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

[0.21.0]: https://github.com/ObliviousOdin/fabric/compare/v2026.7.15.3...v2026.7.16
[0.20.2]: https://github.com/ObliviousOdin/fabric/compare/v2026.7.15.2...v2026.7.15.3
[0.20.1]: https://github.com/ObliviousOdin/fabric/compare/v2026.7.15...v2026.7.15.2
[0.20.0]: https://github.com/ObliviousOdin/fabric/compare/v2026.7.14...v2026.7.15
[0.19.1]: https://github.com/ObliviousOdin/fabric/compare/v2026.7.14...HEAD
[0.19.0]: https://github.com/ObliviousOdin/fabric/releases/tag/v2026.7.14
