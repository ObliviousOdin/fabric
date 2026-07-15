# Fabric design foundation

This directory is the dependency-free source of truth for Fabric's visual
foundation. It deliberately contains no React components and performs no
runtime color calculation. Applications can consume the generated CSS,
tree-shakeable JavaScript constants, terminal palette, or individual brand
assets without pulling another framework into their bundle.

It intentionally has no `package.json` in Phase 1. Consumers use the committed
generated files directly, keeping the foundation independent from application
frameworks and package-manager resolution. It can become a named workspace
package later when multiple external consumers need a versioned boundary.

The canonical brand primary is #4628CC. Product status colors remain semantic
and must not be recolored to match the brand.

## Font policy

Phase 1 retains the native system sans stack for speed and platform fidelity.
The supplied design archive includes Inter binaries but no accompanying font
license, so those files are intentionally not copied into this repository.
Inter can be added later after its provenance and license are committed with
the font files. Monospace remains reserved for terminal and technical values.

## Generated files

Run `node apps/design-system/scripts/generate-tokens.mjs` from the repo root to
regenerate token outputs. Run
`.venv/bin/python scripts/build_brand_assets.py` to regenerate the isolated
SVG/PNG/ICO/ICNS brand bundle. Both generators have a `--check` mode for CI and
do not write into product integration paths.

`dist/tokens.js` exports the foundation and semantic token maps plus
`resolvedSemanticThemes`, which provides complete light and dark semantic roles
with every palette reference resolved to a CSS-ready value. Product surfaces
should consume those resolved roles instead of duplicating palette values.

The full wordmark keeps the supplied bracket underline. Compact icons use the
simplified lowercase f only; the bracket is intentionally omitted below
wordmark scale.

## Supplied logo reference

`src/brand/fabric/reference-wordmark.png` preserves the supplied raster for
audit and visual comparison only. It is 1792 by 1008 pixels with SHA-256
ed6ce701ca2ce7ceb88c70f1a2c41ce91b5783e57a0b0a017048beead1d8e7ac.
The raster is not copied into dist and is never used to generate icons; all
runtime assets derive from the manually reconstructed SVG geometry.
