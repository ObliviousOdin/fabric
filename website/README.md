# Website

This website is built using [Docusaurus](https://docusaurus.io/), a modern static website generator.

## Installation

```bash
npm ci
```

## Local Development

```bash
npm start
```

This command starts a local development server and opens up a browser window. Most changes are reflected live without having to restart the server.

## Build

```bash
npm run build
```

This command generates static content into the `build` directory and can be served using any static contents hosting service.

## Deployment

Pushes to `main` that change the documentation trigger
`.github/workflows/docs-pages.yml`. The workflow installs with the committed
npm lockfile, builds the site, audits the rendered public identity, and deploys
the result to GitHub Pages. Pull requests run the same type-check and build in
the public repository checks before merge.

## Diagram Linting

CI runs `ascii-guard` to lint docs for ASCII box diagrams. Use Mermaid (````mermaid`) or plain lists/tables instead of ASCII boxes to avoid CI failures.
