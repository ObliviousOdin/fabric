# Desktop release pipeline — multi-platform installers, website downloads, release-triggered automation

**Status:** Draft for engineering review
**Scope owner zone:** Release / packaging (`.github/workflows/`, `scripts/ci/`), with
coordinated work packages in the Desktop and Docs-site zones.

---

## 1. Goal

When a maintainer ships a production release (the existing dispatch + approval in
`release-channels.yml`), the pipeline must — with no additional manual steps —

1. build **complete, signed, installable desktop apps** for macOS (Apple silicon
   `.dmg`/`.zip`), Windows x64 (NSIS `.exe`, `.msi`), and Linux x64 (`.AppImage`,
   `.deb`, `.rpm`),
2. attach them, with checksums and a provenance manifest, to the **same GitHub
   Release** that already carries the Python wheel/sdist, and
3. surface them on the **website as a Downloads page** that always points at the
   latest release,

while preserving the release invariants this repo already enforces: build-once /
promote-exact-bytes, provenance manifests, SHA-pinned actions, least-privilege
`permissions:`, environment gating, and macOS/Windows cost gates.

## 2. Current state (verified against the tree)

| Surface | State today |
| --- | --- |
| `desktop-packaging.yml` | Brand contract on PRs; full mac/win/linux packaging matrix on pushes to `main` + dispatch. Builds are **explicitly unsigned** (`CSC_IDENTITY_AUTO_DISCOVERY: "false"`), artifact names are verified, per-platform `SHA256SUMS` written, artifacts uploaded as `*-unsigned` with 14-day retention. Nothing ships to users. |
| `apps/desktop` | electron-builder 26 config with signing scaffolding already present: `afterSign: scripts/notarize.mjs` (App Store Connect API key or keychain profile, graceful skip when unset), `hardenedRuntime: true`, entitlements plists, `win.signAndEditExecutable: false`, `scripts/set-exe-identity.mjs`, `scripts/notarize-artifact.mjs`. Version `0.21.0` (independent semver). Artifact name template `Fabric-${version}-${os}-${arch}.${ext}`. |
| `release-channels.yml` | Alpha (PR) → beta (push to `main`) → production (dispatch + `production` environment approval). Python wheel/sdist only. Provenance manifest binds bytes to repo/SHA/version; production **never rebuilds** — it promotes the exact beta bytes, creates an annotated CalVer tag (`vYYYY.M.D[.N]`), publishes a GitHub Release (`scripts/ci/publish_release.py`). Only the production job has `contents: write`. Workflow behavior is contract-tested (`tests/scripts/test_release_channels.py`). |
| Website | Docusaurus on GitHub Pages (`https://obliviousodin.github.io/fabric/`), deployed by `docs-pages.yml` on `main` pushes touching docs paths. `website/src/pages/ios.tsx` is an existing hand-written download page for the TestFlight app — the pattern to extend. No desktop downloads page; no release-triggered rebuild. |
| iOS / TestFlight | Distribution via Xcode Cloud (`apps/mobile/ios/ci_scripts/`); GitHub CI builds the simulator app on `main` only and enforces "committed project matches generator" drift checks. Signing lives in Xcode Cloud, not GitHub secrets. |
| Audits | Every PR runs brand/identity/public-release audits; all `*.md` are scanned (don't document invented `FABRIC_*` tokens); workflow YAML is covered by contract tests; actions are SHA-pinned everywhere; commit identity is enforced (no AI attribution). |

**Gap summary:** the repo can already *build* all three desktop platforms and can
already *release* Python artifacts with strong provenance. What's missing is the
bridge: signing/notarization in CI, attaching desktop artifacts to the production
release, a downloads page, and the release-published trigger that connects them.

## 3. Design

### 3.1 Topology — one new workflow, triggered by the release

Add **`.github/workflows/desktop-release.yml`**:

```
on:
  workflow_dispatch:
    inputs:
      release_tag:            # primary trigger; also re-run / backfill
  release:
    types: [published]        # belt-and-braces: fires for human-published releases
```

**Trigger chain (important GitHub constraint):** events caused by the default
`GITHUB_TOKEN` do not create workflow runs — and `publish_release.py` creates the
production release with `github.token`, so a `release: published` trigger alone
would **never fire** for our own releases. The documented exceptions are
`workflow_dispatch`/`repository_dispatch`. Therefore the final step of
`promote-production` (inside the audited script path, after the release is
verified live) dispatches `desktop-release.yml` with the new tag via the
workflow-dispatch API using `github.token` (requires adding `actions: write` to
`promote-production`'s permissions and updating `tests/scripts/test_release_channels.py`
+ the §3.7 audit allowlists accordingly). The `release: published` trigger stays
as a fallback for releases published manually in the UI (human-token events do
fire workflows), guarded to skip drafts/prereleases.

Job graph:

```
resolve-release          (ubuntu, contents:read)
  └─ package matrix      (macos-15 / windows-2025 / ubuntu-24.04, contents:read,
     │                    environment: desktop-signing → signing secrets)
     │   build → sign → notarize+staple (mac) → verify → SHA256SUMS
     │   → upload workflow artifact
  └─ attach-assets       (ubuntu, contents:write, environment: desktop-signing)
        download all → re-verify digests → build desktop asset manifest
        → upload assets to the SAME GitHub Release (idempotent)
```

Rationale:

- **Dispatch-on-publish** gives exactly "shipping a release starts the pipeline".
  The production promotion gains only a single post-publish dispatch step; desktop
  packaging (30–60 min incl. notarization) runs decoupled, and a desktop failure
  never blocks or corrupts the Python release — it is re-runnable via
  `workflow_dispatch` against the same tag. Because `release-channels.yml` is
  contract-tested and a shared surface, this small edit lands in the same
  serialized WP-A PR with its tests updated.
- **Build-once is preserved in spirit:** desktop installers are built exactly once,
  from the immutable release tag's SHA. The existing unsigned matrix on `main`
  remains the *pre-release verification* that packaging works at (or near) that
  SHA; the release build is the *only* signed build.
  - Rejected alternative — build desktop artifacts in `release-channels.yml`
    `build-candidate`: would put 10× macOS + 2× Windows runners on every PR/main
    push and force signing secrets into the beta path. Cost and exposure, no gain.
  - Rejected alternative — sign the already-built unsigned `main` artifacts at
    promotion time: signing and notarization rewrite the bytes anyway, so
    byte-identical promotion is impossible for installers; "re-sign later" adds a
    second bespoke pipeline with murkier provenance, not less.
- `release: published` does not fire for draft releases; `publish_release.py`
  publishes non-draft, so the trigger fires exactly once per production release.
  Guard the workflow to skip prereleases unless explicitly dispatched.

### 3.2 Signing and notarization per platform

| Platform | v1 approach |
| --- | --- |
| macOS | Sign with a **Developer ID Application** certificate (the maintainer already has an Apple Developer account for TestFlight — same team). Secrets: `CSC_LINK` (base64 `.p12`) + `CSC_KEY_PASSWORD` (electron-builder's standard variables — not new inventions), and notarize with the **App Store Connect API key** pattern already implemented in `scripts/notarize.mjs` (`APPLE_API_KEY`, `APPLE_API_KEY_ID`, `APPLE_API_ISSUER` — the same credential type the TestFlight workflow already uses on Apple's side). Hardened runtime + entitlements are already configured. After build: `codesign --verify --deep --strict`, `spctl --assess`, `xcrun stapler validate` as explicit verification steps. |
| Windows | Code signing requires an externally procured certificate; classic OV/EV tokens don't fit hosted CI. **Decision for maintainer (work package H1):** Azure Trusted Signing (recommended: ~$10/mo, CI-friendly) vs. SSL.com eSigner vs. ship v1 unsigned. **Implementation constraint:** `win.signAndEditExecutable: false` is deliberately load-bearing — it disables electron-builder's signtool path, whose `winCodeSign` download breaks 7-Zip on non-admin Windows; `after-pack.mjs` already stamps exe identity via rcedit instead. Do **not** flip that flag: sign the built `.exe`/`.msi` artifacts in a **separate post-packaging step** (signtool / Azure Trusted Signing client against the finished installers), then checksum. The workflow treats Windows signing as **config-gated**: if signing secrets are configured, sign; if not, the release job **fails loudly unless `allow_unsigned_windows` was explicitly acknowledged** (a silent unsigned production release is worse than a failed one). Document the SmartScreen implications on the downloads page while unsigned. |
| Linux | No code signing (platform norm). Integrity via `SHA256SUMS` published with the release. Sigstore/cosign attestation is deferred (§3.7). |

The release matrix **must not set** `CSC_IDENTITY_AUTO_DISCOVERY: "false"` (that
line stays only in the verification workflow). A release build on macOS with
missing/invalid signing identity must fail, not silently produce an unsigned dmg —
the packaging step asserts the signature exists before checksumming.

### 3.3 Provenance and integrity for desktop assets

Mirror the Python candidate pattern with a new
**`scripts/ci/desktop_release_assets.py`** (same zone and style as
`release_candidate.py`, with tests in `tests/scripts/test_desktop_release_assets.py`):

- `collect`: after packaging on each OS, record `{repository, tag, source_sha,
  desktop_app_version, files: {name, size, sha256}}` into a per-platform manifest;
  write `SHA256SUMS` (the packaging matrix already computes these — reuse that
  logic, don't duplicate it).
- `verify`: in `attach-assets`, re-hash every downloaded artifact against the
  per-platform manifests before anything touches the release.
- `attach`: upload assets + merged `desktop-release-manifest.json` + combined
  `SHA256SUMS.desktop` to the existing release via the GitHub API. **Idempotent**:
  a re-run verifies digests of already-attached assets and replaces only on
  mismatch; it never duplicates and never deletes Python assets. Follow
  `publish_release.py`'s error-handling discipline (its tests pin down "failed
  attempt cleans up only what it created").
- Contract tests for `desktop-release.yml` itself (job graph, trigger types,
  permissions blocks, environment names), matching the existing
  `test_release_channels.py` convention.

### 3.4 Website downloads page

**`website/src/pages/download.tsx`**, modeled on the existing `ios.tsx`:

- Cards for macOS (Apple silicon), Windows x64, Linux (AppImage / deb / rpm),
  plus a link to the existing iOS/TestFlight page.
- **Latest-release resolution uses the site's existing two-layer pattern** (the
  skills pages already do exactly this — `website/scripts/prebuild.mjs` writes
  `website/static/api/*.json` with live-fetch-and-fallback, pages hydrate from the
  static JSON and refresh client-side):
  1. *Build layer:* prebuild writes `static/api/latest-release.json` from the
     GitHub Releases API, keeping the previous copy on any fetch failure so
     deploys never go flaky. The site already redeploys twice daily via
     `skills-index.yml`'s cron, bounding staleness even with zero JS.
  2. *Client layer:* on mount, refresh from
     `https://api.github.com/repos/ObliviousOdin/fabric/releases/latest`
     (CORS-open, unauthenticated, 60 req/h/IP — ample for a docs page), match
     asset names by the known `Fabric-<version>-<os>-<arch>.<ext>` template,
     render version + direct download links + checksum link. On failure, the
     build-layer data (or a static "browse all releases" link) stands.
  No release-triggered site rebuild is required, and the page can never hard-fail.
  - Rejected alternative — rebuild the site on `release: published` with a baked
    version: more moving parts, a failure mode where the site lags the release,
    and the trigger-chain caveat of §3.1 — for no user-visible gain over the
    two-layer pattern.
  - Rejected alternative — duplicate "stable-named" assets (`Fabric-latest-…`):
    duplicate bytes and ambiguous checksums.
- Register the new route in the brand audit's protected discovery paths
  (`PUBLIC_SITE_DISCOVERY_PATHS` / `BUILT_PUBLIC_DISCOVERY_PATHS` in
  `scripts/fabric-brand-audit.py`) so identity violations on it fail closed, and
  use only canonical repository URLs (`NONCANONICAL_REPOSITORY_RE` is enforced).
- Install + verify documentation (new `website/docs/user-guide/install-desktop.md`
  or extension of the existing desktop guide): per-OS install steps, `shasum -a
  256 -c` verification, Gatekeeper note (signed + notarized ⇒ no warning), and the
  SmartScreen caveat while Windows is unsigned.
- Must pass the existing gates: `fabric-brand-audit --mode public` (source *and*
  rendered build), site typecheck/build, no invented `FABRIC_*` tokens in the new
  markdown.

### 3.5 Versioning

Desktop app version (`apps/desktop/package.json`, currently `0.21.0`) stays
**independent semver** and is **not** stamped from the CalVer release tag:

- Windows MSI `ProductVersion` requires major ≤ 255 — CalVer `2026.7.15` would
  break the MSI target. Mapping schemes (`26.7.15`) invite collision/confusion.
- The desktop app has its own compatibility surface (Electron major, auto-update
  semantics later) that CalVer can't express.

The linkage is recorded instead: `desktop-release-manifest.json` binds
`{tag ⇄ desktop_app_version ⇄ source_sha}`, and the downloads page displays both.
**Release-prep rule** (added to `RELEASING.md`): a production release that includes
desktop changes since the last release must bump `apps/desktop/package.json`
version on `main` first; the `resolve-release` job warns when the desktop version
already exists in a prior release's manifest (duplicate-version guard, since
electron-builder artifact names embed the version).

### 3.6 Secrets and environment policy

- New GitHub environment **`desktop-signing`**, protected-branch/tag only,
  holding: `CSC_LINK`, `CSC_KEY_PASSWORD`, `APPLE_API_KEY`, `APPLE_API_KEY_ID`,
  `APPLE_API_ISSUER` (+ Windows signing secrets when procured). Not reachable
  from PR-triggered workflows; `release:` and `workflow_dispatch` events only.
- Job permissions: matrix jobs `contents: read`; only `attach-assets` gets
  `contents: write`. All actions SHA-pinned (repo convention). No secrets in the
  brand-contract or unsigned verification paths.
- The signing keys are **repo-level release credentials**; rotation and revocation
  notes land in `SECURITY.md` (work package D2 docs).

### 3.7 Audit-contract changes (deliberate, same PR as the workflow)

`scripts/public-release-audit.py` enforces a **workflow-surface contract** that the
new workflow intersects at four points. These are conscious contract extensions —
each lands in the same PR as `desktop-release.yml`, with
`tests/scripts/test_public_release_audit.py` updated to pin the new rules, and the
diff called out for maintainer review (guardrails §8: security boundary):

1. **Workflow allowlist** — `EXPECTED_PUBLIC_WORKFLOWS` (a six-file frozenset)
   rejects any new workflow file. Add `desktop-release.yml`.
2. **Secrets ban** — `UNSAFE_WORKFLOW_RE` rejects *any* `secrets.` reference in
   audited workflows; today zero workflows reference secrets (`publish_release.py`
   authenticates with `github.token`). Signing certificates can only be delivered
   via `secrets.*`, so the audit gains a **per-file exemption scoped to
   `desktop-release.yml`** listing the exact allowed secret names (mirroring the
   existing `ALLOWED_WRITE_PERMISSIONS` per-file design). Anything else stays
   banned.
3. **Write-permission allowlist** — `ALLOWED_WRITE_PERMISSIONS` gains
   `"desktop-release.yml": {"contents"}` (attach job only), and
   `"release-channels.yml"` additionally allows `actions` (the §3.1 dispatch step
   in `promote-production`).
4. **Canonical fragments & the publish gate** — `CANONICAL_REQUIREMENTS`
   (per-workflow required text fragments) pins `desktop-packaging.yml` to
   `CSC_IDENTITY_AUTO_DISCOVERY: "false"` + `--publish never` — that workflow
   stays exactly as it is (verification stays unsigned); the release audit also
   confines release publication to the single `promote-production` gate. The new
   workflow adds *assets to an existing release* and creates no release, so the
   gate rule stays intact — but `CANONICAL_REQUIREMENTS` gains pinned fragments
   for `desktop-release.yml` (its environment name, `--publish never` on the
   electron-builder invocation, the verify-before-attach step) so the new
   workflow is contract-locked like its siblings.
5. **Publish ban** — `UNSAFE_PUBLISH_RE` bans `gh release`/un-`never` `--publish`
   in workflow text. Keep the repo's established pattern: electron-builder always
   runs `--publish never`, and *all* GitHub Release manipulation happens inside
   the audited Python script (`scripts/ci/desktop_release_assets.py`, sharing
   helpers with `publish_release.py` where sensible), never inline in workflow
   YAML. No regex change needed if we follow the pattern.
6. **"Unsigned" docs lockstep** —
   `tests/contract/test_fabric_desktop_release_brand.py` asserts customer docs
   (README / installation / platform-support) describe CI desktop artifacts as
   **unsigned** with checksums. Once releases are signed, that wording splits:
   *verification builds stay unsigned; release builds are signed and notarized*.
   The docs and this contract test must change in the same PR (WP-C coordinates
   with WP-A), and the six production-desktop-release requirements already
   published in `website/docs/getting-started/platform-support.md` (including
   "checksums generated after signing") become the acceptance checklist they were
   written to be.

Also inherited from the same audit: every checkout sets
`persist-credentials: false`; every external action is pinned to a full commit
SHA; `pull_request_target`/`workflow_run` triggers are banned (`release:` is not).

### 3.8 Interaction with the existing source-based self-update

The desktop app today self-updates by git-fetching the configured branch and
rebuilding from source (`src/store/updates.ts`, `electron/update-remote.ts`,
`update-rebuild.ts` — designed for git-checkout installs; there is no
electron-updater and no `latest*.yml` feed). Packaged installers change that
contract: an installer-delivered app must **not** try to rebuild itself from a git
checkout. WP-B therefore includes: detect the packaged context (the shipped
`install-stamp.json` already distinguishes it), disable/adjust the source-update
path for packaged installs, and surface "download the new installer" messaging
instead. Full installer auto-update remains phase 2 (§3.10).

### 3.9 Patterns adopted from the iOS / TestFlight pipeline

The iOS path (Xcode Cloud + `ci_post_clone.sh`) is the repo's most mature release
pipeline; the desktop pipeline adopts its proven ideas:

- **Inject release-only values at build time; never mutate tracked sources** —
  iOS renders bundle ID / build number / commit SHA into a temporary spec; the
  desktop release workflow likewise injects signing env and channel metadata at
  build time while `run-electron-builder.mjs` keeps rejecting external configs.
- **Embed source provenance in the artifact and audit the built artifact** — iOS
  embeds `FabricSourceRevision` and asserts on the built app's plist; desktop
  already ships `install-stamp.json` (commit SHA) and the release workflow adds a
  built-artifact audit step (identity, version, signature) before checksumming.
- **Generated-file drift gates and fail-closed identity contracts** — carried
  over as: brand-contract job untouched, contract tests for the new workflow,
  fail-loud signing (§3.2).
- **Main-only cost gates with explicit rationale comments** — the release matrix
  runs only on release/dispatch events; PR signal stays on cheap Linux jobs.
- **Same Apple credential model** — the App Store Connect API-key pattern already
  implemented in `notarize.mjs` is the same credential type used for TestFlight,
  so the maintainer manages one Apple credential family.
- **Automate what iOS does manually** — the iOS provenance ledger
  (`IOS_RELEASES.md`) is hand-maintained and demonstrably lossy; the desktop
  equivalent (`desktop-release-manifest.json`) is machine-generated and attached
  to the release itself.

### 3.10 Explicitly deferred (phase 2, separate PRs)

- **Auto-update** (electron-updater + `latest*.yml` feeds on GitHub Releases).
  Signed builds are the prerequisite; the desktop codebase already has update
  machinery around the CLI (`electron/update-*.ts` tests) whose interaction with
  installer-level auto-update needs its own design note.
- **Build attestations** (`actions/attest-build-provenance`, SLSA provenance) and
  sigstore signatures for Linux artifacts.
- **macOS x64 / Windows arm64 / Linux arm64** targets — add runners/matrix entries
  once the arm64/x64 demand is real.
- **Beta desktop channel** (pre-release GitHub Releases fed from `main`).
- **Doc reconciliation:** `CONTRIBUTING.md` references a `supply-chain-audit.yml`
  workflow that no longer exists — fix alongside the RELEASING.md updates.

## 4. Work packages (for parallel agents)

Ordering constraint: `.github/workflows/**` is a shared surface (guardrails §2.1)
— WP-A lands before anything else touches workflows. WP-B, WP-C, WP-D are zone-
disjoint and fully parallel. H1 is human-only and gates the first real signed
release, not the code.

| WP | Zone | Deliverable | Depends on |
| --- | --- | --- | --- |
| **WP-A** | Release/packaging | `desktop-release.yml` + `scripts/ci/desktop_release_assets.py` + contract tests + the §3.7 audit-contract extensions (`public-release-audit.py` + its tests, same PR) + `RELEASING.md` update (desktop section, runbook, re-run/backfill instructions) | — |
| **WP-B** | Desktop | Signing readiness in `apps/desktop`: wire signing env plumbing through `run-electron-builder.mjs`, post-packaging Windows sign step (keep `signAndEditExecutable: false` — §3.2), post-build signature assertion script (`codesign`/`spctl`/`stapler` checks on mac; `Get-AuthenticodeSignature` on win when enabled), packaged-install update-path adjustment (§3.8), local signing docs | — |
| **WP-C** | Docs site | `download.tsx` + `prebuild.mjs` latest-release layer + navbar entry + install/verify docs page + brand-audit discovery-path registration + the "unsigned" docs-wording flip with its contract test (§3.7.6, coordinated with WP-A) | — |
| **WP-D** | Docs site / security | `SECURITY.md` desktop-signing key-management section; downloads-page trust copy | — |
| **H1** | Human (maintainer) | Export Developer ID cert (.p12), create App Store Connect API key, create `desktop-signing` environment + secrets, pick Windows signing vendor (or explicitly accept unsigned v1) | — |
| **WP-E** | Release/packaging | End-to-end dry run: dispatch `desktop-release.yml` against a prerelease test tag, verify signed/notarized artifacts on all three OSes, verify downloads page resolves them; fix fallout; final runbook | WP-A, WP-B, H1 |

Every WP follows the repo contract: task branch, §6 pre-flight for its zone,
PrimeOdin commit identity, no self-merge, HANDOFF block in the PR, and — because
desktop packaging and the release workflow are cost-gated off PRs — explicit
`workflow_dispatch` verification noted in the PR before merge.

## 5. Acceptance criteria

1. Maintainer runs the existing production promotion (dispatch + approval). Within
   ~1 hour, the GitHub Release additionally carries: signed+notarized+stapled
   `Fabric-<v>-mac-arm64.dmg`/`.zip`, `Fabric-<v>-win-x64.exe`/`.msi` (signed, or
   explicitly acknowledged unsigned), `Fabric-<v>-linux-x86_64.AppImage`,
   `-amd64.deb`, `-x86_64.rpm`, `SHA256SUMS.desktop`, and
   `desktop-release-manifest.json` — with zero manual steps beyond the existing
   approval.
2. A fresh macOS machine opens the dmg with no Gatekeeper warning; `spctl
   --assess` passes; checksums match the published sums.
3. `https://obliviousodin.github.io/fabric/download` shows the new version and
   working links within one page load of the release (no site rebuild required).
4. A failed desktop run neither blocks nor mutates the Python release, and
   re-dispatching against the same tag converges (idempotent attach).
5. All existing gates stay green: workflow contract tests, brand/identity/public
   audits, docs token audit, commit identity audit.

## 6. Risks

| Risk | Mitigation |
| --- | --- |
| Notarization outage/latency at release time | Decoupled workflow; re-run via dispatch; Python release unaffected |
| Signing secrets misconfigured → unsigned mac artifact ships | Release build asserts signature/staple before checksumming; fails loudly |
| Windows cert procurement stalls | Config-gated signing; explicit acknowledged-unsigned path; SmartScreen documented |
| GitHub API rate limit on downloads page | Static fallback link to releases page; template-based asset matching |
| Desktop version collision across releases | Duplicate-version guard in `resolve-release` |
| Workflow file drift vs. contract tests | New workflow ships with its own contract tests in the same PR |
