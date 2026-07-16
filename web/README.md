# Fabric — Web UI

The browser experience for Fabric's local-first runtime. It coordinates a
business-facing **Workspace** and a technical **Admin** console while keeping
the real `fabric --tui` process as the browser Chat transcript and composer.

The current product includes the responsive shell, canonical Workspace/Admin
routes, live Home projections, Design, persistent three-panel Chat, management
pages, and dashboard plugin routes. The bundled Work plugin replaces the
`/workspace/work` placeholder with the persistent task board and contributes
live task context to Chat. Surfaces without a runtime contract (including the
typed Memory ledger, durable approvals, and unified activity) remain explicit
unavailable states; the UI must not simulate them.

## Stack

- **Vite** + **React 19** + **TypeScript**
- **Tailwind CSS v4** with custom dark theme
- **shadcn/ui**-style components (hand-rolled, no CLI dependency)

## Development

```bash
# Start the backend API server and built SPA host
cd ../
python -m fabric_cli.main dashboard --no-open

# In another terminal, start the Vite dev server (with HMR + API proxy)
cd web/
npm install
npm run dev
```

Open the **Vite URL** printed in the terminal (usually `http://localhost:5173`). That is the live-reload UI.

`fabric dashboard` on port 9119 serves the **built** bundle from
`fabric_cli/web_dist/`, not the Vite dev server. Changes in `web/src/` will not
appear there until you run `npm run build` and restart the dashboard (or run
the dashboard backend alongside Vite as above).

The Vite dev server proxies `/api` requests to `http://127.0.0.1:9119` (the FastAPI backend).

## Build

```bash
npm run build
```

This outputs to `../fabric_cli/web_dist/`, which the FastAPI server serves as a static SPA. The built assets are included in the Python package via `pyproject.toml` package-data.

## Structure

```
src/
├── app/
│   └── routes.tsx   # Canonical lazy Workspace/Admin route and alias catalog
├── components/
│   ├── chat/        # Three-panel presentation around the persistent TUI
│   ├── experience/  # Shared screen-state components
│   ├── sidebar/     # Responsive Workspace/Admin navigation shell
│   └── ui/          # Fabric-owned reusable UI wrappers
├── contexts/        # Profile, page-header, and system-action state
├── lib/
│   ├── api.ts       # API client — typed fetch wrappers for all backend endpoints
│   ├── chat-draft.ts # Safe draft handoff to the embedded PTY-backed TUI
│   └── utils.ts     # cn() helper for Tailwind class merging
├── pages/
│   ├── WorkspaceHomePage.tsx        # Live operational projections
│   ├── DesignPage.tsx                # Structured brief and system-preset workspace
│   ├── ChatPage.tsx                 # Persistent PTY/xterm host
│   ├── WorkspacePlaceholderPage.tsx # Honest unavailable-runtime states
│   └── *Page.tsx                    # Reused Workspace/Admin capabilities
├── plugins/          # Generic route, slot, and extension contracts
├── themes/           # Generated canonical pair + optional presets
├── App.tsx           # Shell composition and persistent Chat lifecycle
├── main.tsx         # React entry point
└── index.css        # Tailwind imports and theme variables
```

## Route contract

`src/app/routes.tsx` is the source of truth for route identity, lazy component
loading, navigation order, Workspace/Admin ownership, and legacy aliases. Do
not add a parallel path/title/nav table elsewhere.

Chat is a persistent route. Its PTY, WebSocket, and xterm instance must stay
mounted while users navigate. React may provide conversations, agent status,
context, evidence, memory, and artifact rails around it, but must not implement
a second transcript or composer.

Machine profiles remain independent configuration/memory islands. Never label
a profile as a tenant, team workspace, site, user, or role. Navigation
visibility is presentational until matching server-side capability guards
exist.

## Design system

Read [DESIGN.md](./DESIGN.md) and the generated foundation in
[`apps/design-system`](../apps/design-system/README.md) before adding or editing
the web UI. The Fabric-owned contract supersedes inherited dashboard visual
conventions.

The short version:

- Generated Fabric Light/Dark are the canonical theme pair, built from neutral
  woven surfaces and `#4628CC` as the single brand/action accent. Expressive
  themes remain optional presets; old teal/blue identities migrate to the
  canonical pair.
- Product language uses sentence case and the theme's system-humanist sans.
  Monospace is only for technical values such as IDs, branches, paths, and logs.
- Body copy is at least 14px and interactive targets are at least 44×44px.
- Consume semantic text, surface, border, interaction, and status tokens. Do
  not stack opacity on readable text or hardcode status colors.
- Prefer flat tonal surfaces, hairline separation, progressive disclosure, and
  one primary action. Avoid glow, decorative grain, and uppercase tracking as
  hierarchy devices.
- Raw `@nous-research/ui` controls are transitional implementation details.
  New Fabric surfaces should use Fabric-owned wrappers and plugin SDK seams.
