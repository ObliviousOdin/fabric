---
name: rstack
description: "Build and ship frontend projects with the Rstack toolchain — Rspack bundling, Rsbuild app builds, Rslib libraries, Rspress docs sites, Rsdoctor build analysis, and Rstest testing — including migrations from webpack and Vite. Use when a project uses or should adopt Rspack/Rsbuild or the user mentions Rstack."
version: 1.0.0
author: Fabric
license: MIT
platforms: [linux, macos, windows]
metadata:
  fabric:
    tags: [rstack, rspack, rsbuild, rslib, rspress, rsdoctor]
    related_skills: [webapp-development, website-building]
---

# Rstack Toolchain

Use this skill when the build toolchain itself is the work: a project already uses Rspack or Rsbuild, the user names any Rstack tool, a webpack build is too slow and a migration is on the table, or a new app/library/docs site should start on the Rstack stack. It covers tool selection, scaffolding, configuration, webpack and Vite migrations, and build performance debugging.

Do NOT use this for general product work where the bundler is incidental — load `webapp-development` with skill_view for building app features, or `website-building` with skill_view for marketing and content sites where any static pipeline would do. Do not retrofit Rspack into frameworks that own their build layer (Next.js, SvelteKit, Astro, Remix): work inside the framework's toolchain instead. If the user only wants faster CI and the bundler is not the bottleneck, profile first — this skill's Rsdoctor section can prove or disprove that.

## The toolchain at a glance

All six tools share one Rust core and one team. The `rstackjs` GitHub org (github.com/rstackjs) is the umbrella home; each tool's docs live on its own `.rs` domain.

| Tool | What it is | Reach for it when | Docs |
|---|---|---|---|
| Rspack | webpack-API-compatible bundler in Rust | Existing webpack config to keep, Module Federation, low-level control | rspack.rs |
| Rsbuild | Batteries-included app build tool on Rspack | New apps, or replacing webpack/Vite/CRA without hand-writing bundler config | rsbuild.rs |
| Rslib | Library bundler built on Rsbuild | npm packages: ESM/CJS output, type declarations, component libraries | rslib.rs |
| Rspress | Static site generator built on Rsbuild | Documentation sites, MDX content, product docs with search | rspress.rs |
| Rsdoctor | Build analyzer and profiler | Slow builds, mystery bundle bloat, loader/plugin time attribution | rsdoctor.rs |
| Rstest | Testing framework on the same pipeline | Unit/component tests that should share the project's build config | rstest.rs |

Rule of thumb: prefer Rsbuild over raw Rspack unless the project needs webpack-config-level control. Rsbuild wraps Rspack with sensible defaults, a plugin system, and built-in Rsdoctor support, so most projects never touch a raw `rspack.config` at all. The ecosystem also grows sideways (a linter and other tools have appeared) — check the `rstackjs` GitHub org (github.com/rstackjs, or the `rstackjs/awesome-rstack` list) for the current roster before assuming this table is complete.

## Workflow

1. **Verify current state of the ecosystem.** These tools ship fast and commands evolve. Before running anything, `web_extract` the relevant quick-start page (e.g. `https://rsbuild.rs/guide/start/quick-start`) or search for it, and confirm: the scaffolding command, the required Node.js floor (the Rsbuild v2 line requires a recent Node 20/22; older majors differ), and whether a new major changed config shape. Never scaffold from memory alone.
2. **Route the job.** Use the table above. Composite jobs compose: a component library often wants Rslib for the package, Rspress for its docs, and Rstest for its tests — the scaffolders can wire these together.
3. **Inspect the project.** `read_file` on `package.json`, existing `webpack.config.*`, `vite.config.*`, or `rsbuild.config.*`. Note the package manager (lockfile), framework, TypeScript usage, CSS approach, and any Module Federation or monorepo structure. This decides greenfield-scaffold vs. in-place migration.
4. **Scaffold or integrate.** Greenfield: run the create command (next section). Existing project: add the core package as a devDependency and write a minimal config, or follow the migration path below.
5. **Configure minimally.** Start from defaults; add plugins only for what the project actually uses (framework plugin, Sass, SVGR, etc.). Every config line you add is a line to maintain — Rsbuild's defaults already handle TS, JSX, CSS, assets, and env injection.
6. **Prove it works.** Run the dev server and confirm HMR on a real edit; run the production build and confirm output lands in `dist/`. For migrations, compare the artifact list and page behavior against the old build before deleting anything.
7. **Profile if slow or bloated.** Enable Rsdoctor, rebuild, and read the report before guessing at fixes (see the tuning section).
8. **Deliver.** Report exact config paths, the commands to run dev/build/test, and — for migrations — the parity report from the template below.

## Scaffolding and install commands

Confirmed against official docs as of mid-2026 — re-verify per step 1, since the `create-*` prompts (templates, optional tools) change often:

- New app: `npm create rsbuild@latest` (pnpm/bun/yarn `create` variants work too; the prompt offers React, Vue, Svelte, Solid, Preact, Lit, and vanilla templates plus optional tooling)
- New library: `npm create rslib@latest` (can co-scaffold Rspress docs, a testing setup, and lint/format tooling)
- New docs site: `npm create rspress@latest`
- Add to an existing app: `npm add @rsbuild/core -D`, then create `rsbuild.config.ts`
- Testing: `npm add @rstest/core -D`, set `"test": "rstest"` in package.json scripts; supports Node and browser-mode runs
- Build analysis: `npm add @rsdoctor/rspack-plugin -D` in the Rsbuild project too, then run the build with `RSDOCTOR=true` — Rsbuild auto-registers the installed plugin; for raw Rspack or webpack, install the same plugin (or the webpack-plugin variant) and register it manually in the config, guarded so normal builds stay fast
- Raw bundler project: `npm create rspack@latest` — only when Rsbuild is genuinely too high-level

## Rslib and Rspress specifics

Libraries are not small apps; docs sites are not small libraries. Set expectations per tool:

**Rslib** builds packages for other people's bundlers, so the defaults differ from app builds:

- Emit both ESM and CJS unless the user explicitly targets ESM-only; configure the `lib` array with one entry per format.
- Generate type declarations (`dts: true`) for any TypeScript package — a library without types is a support burden.
- Keep dependencies external by default (Rslib externalizes `dependencies` and `peerDependencies`); bundling them in causes duplicate-React-style breakage downstream.
- Verify the published surface, not just the build: check `package.json` `exports` map against the actual `dist/` files, then dry-run with `npm pack` and inspect the tarball contents.
- For component libraries, "bundleless" per-file output preserves tree-shaking for consumers; check current Rslib docs for the option name before configuring it.

**Rspress** is content-first:

- Content is MDX under a docs directory; navigation and sidebar come from config plus frontmatter, and full-text search is built in.
- Prefer the default theme with targeted overrides over a custom theme; a docs site that needs heavy custom UI is usually an app wearing a docs costume — reconsider the routing table.
- `rspress build` emits fully static output, deployable to any static host; verify with `rspress preview` before handing off.

## Migrating from webpack

Rspack tracks the webpack v5 API surface, so most webpack 5 projects migrate mechanically. Do it in-place and incrementally:

1. Branch first. Keep the webpack build runnable until parity is proven.
2. Swap packages: remove `webpack`, `webpack-cli`, `webpack-dev-server`; add `@rspack/core` and `@rspack/cli`. Point npm scripts at `rspack build` / `rspack serve` (or `rspack dev`, per current CLI docs).
3. Reuse the config: `rspack.config.js` accepts webpack-v5-shaped config. Rename or copy the file and fix what errors.
4. Replace slow or incompatible pieces using this table:

| webpack piece | Rspack replacement | Why |
|---|---|---|
| babel-loader | `builtin:swc-loader` | Built-in Rust SWC transform; largest single speed win |
| file-loader / url-loader / raw-loader | Asset modules (`type: 'asset/resource'` etc.) | webpack 5 already deprecated these |
| mini-css-extract-plugin | `rspack.CssExtractRspackPlugin` | Native, faster |
| copy-webpack-plugin | `rspack.CopyRspackPlugin` | Native, faster |
| terser-webpack-plugin | Built-in SWC minimizer (default in production) | Delete the plugin entirely |
| html-webpack-plugin | Works as-is; `rspack.HtmlRspackPlugin` is the native option | Compat layer covers common options |
| fork-ts-checker-webpack-plugin | Keep it, or run `tsc --noEmit` as a separate script | SWC transpiles without type-checking |

5. Loader/plugin parity caveats, stated honestly: most published loaders work unchanged. Plugins are compatible when they stick to documented webpack hooks; plugins that poke undocumented compiler internals can fail. Check `rspack.rs/guide/compatibility/plugin` for the maintained compatibility list before promising a clean migration. Babel-only transforms (rare macros, custom plugins) have no SWC equivalent — keep `babel-loader` for just those files rather than blocking the migration.
6. Verify parity: dev server + HMR, production build, bundle contents diff (`ls -R dist` old vs. new), and a manual smoke of the built app. Only then remove webpack dependencies.

A CRA, Vue CLI, or Vite project migrating to **Rsbuild** (rather than raw Rspack) is usually less work, not more — Rsbuild's docs ship dedicated migration guides per source tool; follow the current one rather than improvising.

Deliverable — fill this in and include it in your handoff for any migration:

```markdown
# Build migration report: {project}

**From:** webpack {x} / Vite {x} | **To:** {Rspack or Rsbuild} {version}
**Config:** `{path/to/rsbuild.config.ts}` | **Node floor:** {version}

## Parity checklist
- [ ] Dev server starts; HMR verified on a real edit
- [ ] Production build succeeds; artifact list compared with old build
- [ ] All entry points / pages smoke-tested from `dist/`
- [ ] Env vars and public assets resolve as before
- [ ] Source maps usable in devtools

## Replacements made
| Old | New | Notes |
|---|---|---|
| ... | ... | ... |

## Kept for compatibility (revisit later)
- {loader or plugin} — {reason}

## Measurements
Cold prod build: {old}s -> {new}s | Dev boot: {old}s -> {new}s

## Open risks
- ...
```

## Rspack vs. Vite, honestly

Do not oversell. Vite is excellent and switching a healthy Vite project rarely pays. The real differences:

- **Dev/prod parity.** Rspack bundles the same way in dev and prod. Vite historically used an unbundled ESM dev server with a separate production bundler, so prod-only bugs could hide — though Vite's newer Rust bundler work narrows this gap. Verify the current Vite architecture before repeating this claim.
- **webpack ecosystem.** Rspack runs most webpack loaders/plugins; Vite runs none of them. A project locked to webpack-only tooling (Module Federation especially) has a clear Rspack path and no clean Vite path.
- **Very large apps.** A bundled dev server avoids the request waterfall of thousands of unbundled modules; Rspack's lazy compilation keeps boot fast anyway. On small apps both feel instant and the choice is taste.
- **Plugin culture.** Vite's plugin ecosystem is broader for bleeding-edge frameworks; Rsbuild's is smaller but first-party plugins cover the common ground.

Recommend migration to Rstack when: webpack-locked and slow, Module Federation is required, or a monorepo wants one config system for apps (Rsbuild), libs (Rslib), and docs (Rspress). Recommend staying put when the current tool is fast and nobody is fighting it.

## Performance tuning with Rsdoctor

1. Enable it: with Rsbuild, `RSDOCTOR=true npm run build` (plugin installed per the scaffolding section); with raw Rspack/webpack, register `RsdoctorRspackPlugin` guarded by the same env var. Never leave it on unconditionally — it adds measurable build time.
2. Read the report in this order: loader time attribution (which loader, which files), plugin hook durations, module graph for duplicate packages, bundle size treemap.
3. Apply the usual wins, largest first: replace JS-based transforms with builtin SWC; dedupe multi-version dependencies (lockfile resolutions); split oversized vendors with `splitChunks`; lazy-load heavy routes; check that the minifier and CSS extraction are the native implementations, not JS holdovers.
4. Re-measure after each change with the same command. Report before/after numbers, never adjectives.

## Common failure modes

- **Scaffolding from stale memory.** The `create-*` prompts, template names, and even CLI subcommands change between minors. Symptoms: "unknown option" errors, missing templates. Fix: step 1 — read the current quick-start first, every time.
- **Node too old.** New Rsbuild/Rspack majors raise the Node floor and fail with confusing syntax or ESM errors. Check `node --version` against the docs before debugging anything else.
- **Porting the whole webpack config verbatim.** Half of a mature webpack config exists to work around webpack's speed; Rspack makes it dead weight. Port entries, outputs, aliases, and genuinely custom loaders — let defaults handle the rest.
- **Keeping babel-loader everywhere.** Leaves the biggest performance win on the table. Scope Babel to the few files that need a Babel-only transform; SWC handles the rest.
- **Assuming every webpack plugin works.** The compatibility layer is broad, not total. Test the exact plugin list against the compatibility docs; have a fallback for anything that touches compiler internals.
- **Declaring victory on a green build.** A build that completes is not a build that works. Serve `dist/` and click through the app; diff the artifact list against the old build.
- **Confusing the tools.** Rspress is not for app shells; Rslib is not for apps; raw Rspack config in a project that only needed Rsbuild doubles maintenance for nothing. Route with the table, once, at the start.
- **Rsdoctor left enabled in CI.** It is a profiler, not a monitor. Gate it behind an env var and turn it on only when investigating.

## Keep current

This ecosystem moves faster than most: majors land, defaults change, and new tools join the family. At the start of any Rstack task, spend two minutes on the relevant tool's changelog or blog (each docs domain has one) with `web_extract` or `web_search`. When project docs and this skill disagree with the official docs, the official docs win — and note the discrepancy in your handoff so the next session starts smarter.
