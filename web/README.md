# Fabric — Web UI

Browser-based dashboard for managing Fabric configuration, API keys, and monitoring active sessions.

## Stack

- **Vite** + **React 19** + **TypeScript**
- **Tailwind CSS v4** with custom dark theme
- **shadcn/ui**-style components (hand-rolled, no CLI dependency)

## Development

```bash
# Start the backend API server
cd ../
python -m fabric_cli.main web --no-open

# In another terminal, start the Vite dev server (with HMR + API proxy)
cd web/
npm install
npm run dev
```

Open the **Vite URL** printed in the terminal (usually `http://localhost:5173`). That is the live-reload UI.

`fabric dashboard` on port 9119 serves the **built** bundle from `fabric_cli/web_dist/`, not the Vite dev server — changes in `web/src/` will not appear there until you run `npm run build` and restart the dashboard (or use `web --no-open` + Vite as above).

The Vite dev server proxies `/api` requests to `http://127.0.0.1:9119` (the FastAPI backend).

## Build

```bash
npm run build
```

This outputs to `../fabric_cli/web_dist/`, which the FastAPI server serves as a static SPA. The built assets are included in the Python package via `pyproject.toml` package-data.

## Structure

```
src/
├── components/ui/   # Reusable UI primitives (Card, Badge, Button, Input, etc.)
├── lib/
│   ├── api.ts       # API client — typed fetch wrappers for all backend endpoints
│   └── utils.ts     # cn() helper for Tailwind class merging
├── pages/
│   ├── StatusPage   # Agent status, active/recent sessions
│   ├── ConfigPage   # Dynamic config editor (reads schema from backend)
│   └── EnvPage      # API key management with save/clear
├── App.tsx          # Main layout and navigation
├── main.tsx         # React entry point
└── index.css        # Tailwind imports and theme variables
```

## Design system

Read [DESIGN.md](./DESIGN.md) before adding or editing dashboard UI. Its
Fabric-owned contract supersedes the inherited upstream visual conventions.

The short version:

- Generated Fabric Light/Dark are the canonical theme pair. Historical themes
  remain optional skins.
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
