# Desktop brand manifest

`fabric.json` is the canonical identity contract for the Fabric desktop app.
The Electron main-process bundle, renderer bundle, Electron Builder metadata,
installer names, protocol registrations, and Windows PE resources must all be
derived from this file through `../scripts/desktop-brand.mjs`.

The checked-in manifest is validated and baked into the renderer and Electron
main bundles. Asset paths remain relative to `apps/desktop`. The manifest also
preserves the legacy protocol scheme so existing installed links keep working
across an upgrade.
