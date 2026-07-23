# Desktop release pipeline — multi-platform installers, website downloads, release-triggered automation

**Status:** Reviewed draft (v2). Six-lens engineering review incorporated — see §8.
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
   latest release that actually has installers,

while preserving the release invariants this repo already enforces: build-once /
promote-exact-bytes, provenance manifests, SHA-pinned actions, least-privilege
`permissions:`, environment gating, and macOS/Windows cost gates.

## 2. Current state (verified against the tree)

| Surface | State today |
| --- | --- |
| `desktop-packaging.yml` | Brand contract on PRs; full mac/win/linux packaging matrix on pushes to `main` + dispatch. Builds are **explicitly unsigned** (`CSC_IDENTITY_AUTO_DISCOVERY: "false"`), artifact names verified, per-platform `SHA256SUMS` written by an inline Node heredoc (lines 141-207), artifacts uploaded as `*-unsigned` with 14-day retention. Nothing ships to users. The workflow text is pinned by `CANONICAL_REQUIREMENTS` in `public-release-audit.py` and by `tests/contract/test_fabric_desktop_release_brand.py`. |
| `apps/desktop` | electron-builder 26 config via `run-electron-builder.mjs` (rejects external configs; merges `branding/fabric.json`). Signing scaffolding present but dormant: `afterSign: scripts/notarize.mjs` **staples only the `.app`** (before the dmg/zip are built), `hardenedRuntime: true`, entitlements, `win.signAndEditExecutable: false` (deliberately load-bearing — see §3.2), `after-pack.mjs` rcedit-stamps identity only (no signing), `scripts/notarize-artifact.mjs` can notarize+staple a standalone dmg but is never invoked. Version `0.21.0` (independent semver). Artifact name `Fabric-<version>-<os>-<arch>.<ext>` where **arch is per-target** (dmg/zip→`arm64`, exe/msi→`x64`, AppImage→`x86_64`, deb→`amd64`, rpm→`x86_64`). `write-build-stamp.mjs` ships `install-stamp.json` (commit SHA) inside the app, and **prefers `$GITHUB_SHA` over the checkout** (lines 48-58). |
| `release-channels.yml` | Alpha (PR) → beta (push to `main`) → production (dispatch + `production` environment approval). Python wheel/sdist only. Provenance manifest binds bytes to repo/SHA/version; production **never rebuilds** — promotes exact beta bytes, `publish_release.py` creates an annotated CalVer tag (`vYYYY.M.D[.N]`) at `source_sha` and a **non-draft `--latest`** GitHub Release via `gh` under `github.token`. Only the production job has `contents: write`. Behavior is contract-tested (`tests/scripts/test_release_channels.py`, run via the explicit file list at lines 70-77). |
| Website | Docusaurus SSG → GitHub Pages (`https://obliviousodin.github.io/fabric/`), deployed by `docs-pages.yml` on `main` pushes touching docs paths, and rebuilt twice daily by `skills-index.yml`'s cron. `website/src/pages/ios.tsx` is a hand-written TestFlight download page (the pattern to extend). Build-time data uses `prebuild.mjs` (live-fetch → fall back to the **published** Pages copy); pages hydrate from same-origin `static/api/*.json` on mount. **No page refreshes from an external API client-side today.** No desktop downloads page. |
| iOS / TestFlight | Distribution via Xcode Cloud (`apps/mobile/ios/ci_scripts/`); signing lives Apple-side, not in GitHub secrets. GitHub CI builds the simulator app on `main` only, with generated-project drift gates and built-artifact metadata audits. |
| Audits | `public-release-audit.py` enforces a **workflow-surface contract**: a six-file allowlist (`EXPECTED_PUBLIC_WORKFLOWS`), a blanket ban on any `secrets.` reference, a per-file write-permission allowlist, banned publish verbs (`gh release`, non-`never` `--publish`), SHA-pinned actions, `persist-credentials: false`. Zero workflows reference secrets today; all GitHub auth uses `github.token`. Brand/identity audits scan all `*.md` and the rendered site. Commit identity is enforced (PrimeOdin, no AI attribution). |

**Gap summary:** the repo can already *build* all three desktop platforms and
*release* Python artifacts with strong provenance. Missing is the bridge:
signing/notarization in CI, attaching desktop artifacts to the production release,
a downloads page, and the trigger that connects them — plus the deliberate audit,
versioning, and update-path changes those require.

## 3. Design

### 3.1 Topology — one new workflow, dispatched by the release

Add **`.github/workflows/desktop-release.yml`**:

```yaml
on:
  workflow_dispatch:
    inputs:
      release_tag:      # required; the production CalVer tag to package
      force_replace:    # boolean, default false (see §3.3)
      force_rebuild:    # boolean, default false (see §3.5)

concurrency:
  group: desktop-release-${{ inputs.release_tag }}
  cancel-in-progress: false
```

**Trigger is `workflow_dispatch` only — dispatched with `ref: <release_tag>`.**
Three facts force this exact shape:

1. **Our own releases cannot fire `release:`.** `publish_release.py` creates the
   release with `github.token`; events caused by `GITHUB_TOKEN` never create
   workflow runs (documented GitHub anti-recursion rule). A `release: published`
   trigger would fire **zero** times for the automated path — it is pure attack
   surface, so it is **omitted**. (It can be added later, guarded to
   non-draft/non-prerelease, purely for releases a human publishes with a PAT;
   that is deferred, §3.10.)
2. **The dispatch must use `ref: <tag>`, not `ref: main`.** `write-build-stamp.mjs`
   prefers `$GITHUB_SHA`/`$GITHUB_REF_NAME` over the checked-out tree, so a
   `dispatch@main` run would stamp **main's** commit into the shipped
   `install-stamp.json` even after checking out the tag — the installer would
   bootstrap a backend at the wrong SHA (the exact GUI/backend skew §3.8 guards
   against). Dispatching at `ref: <tag>` makes `$GITHUB_SHA` resolve to the tag
   commit **and** runs the tag's own audited workflow definition.
3. **The environment gate is ref-based (§3.6), and a tag ref lets us scope it to
   the `v20*` tag pattern.**

**How the dispatch happens:** the final step of `promote-production` (inside the
audited `scripts/ci/` path, *after* the release is verified live) calls the
workflow-dispatch API for `desktop-release.yml` with `ref: <new tag>` and
`inputs.release_tag = <new tag>`, using `github.token`. This requires adding
`actions: write` to `promote-production`'s permissions and to the audit's
`ALLOWED_WRITE_PERMISSIONS["release-channels.yml"]`, and updating
`tests/scripts/test_release_channels.py`. Because `release-channels.yml` is a
contract-tested shared surface, this edit lands in the serialized WP-A PR.

- **Dispatch failure policy:** if the dispatch step fails after the release is
  live, `promote-production` cannot simply be re-run (`publish_release.py` refuses
  a pre-existing tag). The documented remedy (WP-A runbook) is a **manual
  `workflow_dispatch` of `desktop-release.yml`** with the tag.
- **Backfill caveat:** the dispatch API only sees a workflow file present on the
  ref. A tag created **before** `desktop-release.yml` merged to `main` cannot be
  dispatched at its own ref. Backfilling such a tag is a documented fallback:
  dispatch at `ref: main` (accepting main's workflow definition and the
  install-stamp caveat, which for a backfilled tag is acceptable because the stamp
  is only re-derived, not re-shipped to prior downloaders) with `release_tag` set,
  and the `v20*`-plus-`main` deployment policy of §3.6.

Job graph:

```
resolve-release        (ubuntu, contents:read, no signing env)
  │  fetch release by tag via API → require it exists, non-draft, non-prerelease,
  │  matches production TAG_RE; download the Python release's provenance manifest;
  │  assert tag commit SHA == manifest source_sha and repository matches;
  │  assert $GITHUB_SHA == tag commit; emit pinned SHA + desktop_version outputs;
  │  duplicate-version decision (§3.5)
  └─ package matrix     (macos-15 / windows-2025 / ubuntu-24.04)
     │  checkout pinned SHA · npm ci + build with NO signing env
     │  · package step: electron-builder --publish never, signing secrets passed
     │    ONLY in this step's env (§3.2) · sign/notarize/staple · verify signatures
     │    · SHA256SUMS · upload workflow artifact
     └─ attach-assets   (ubuntu, contents:write, environment: desktop-signing only
                          if a token beyond github.token is needed — else no env)
           download all → re-verify digests vs per-platform manifests →
           immutable attach (§3.3) → final re-list + full-set verify
```

**Why build-at-release-tag (not in `release-channels.yml`):** desktop packaging
(30–60 min incl. notarization wait) is decoupled so a desktop failure never blocks
or corrupts the Python release, and it is re-runnable. The unsigned `main` matrix
in `desktop-packaging.yml` stays as *pre-release verification* that packaging
works; the release build is the *only* signed build.
  - Rejected — build in `release-channels.yml` `build-candidate`: forces signing
    secrets into the beta path and every PR onto expensive runners.
  - Rejected — sign the already-built unsigned `main` artifacts at promotion:
    signing/notarization rewrite the bytes, so byte-identical promotion is
    impossible for installers anyway; "re-sign later" just adds a second pipeline
    with murkier provenance.

**Footprint / cost:** the repo is **public**, so GitHub-hosted standard runners
(`ubuntu-24.04`, `macos-15`, `windows-2025`) bill **$0**; per-release footprint is
~3 jobs (one macOS ≤60 min dominated by the notarization wait, one Windows, one
Linux), constrained by concurrency/queue, not dollars. The 10×/2× multipliers in
existing workflow comments apply only if the repo goes private. The build-on-every-
PR alternative is rejected on **secret-exposure, queue-time, and convention**
grounds, not billing.

### 3.2 Signing and notarization per platform

Signing secrets are passed **only in the env of the specific packaging/sign
step** — never job-level — so the Developer ID `.p12` and App Store Connect key
are not exposed to `npm ci`, the hundreds of dependency lifecycle scripts, or the
renderer build. `npm ci` and `npm run build` run first with no signing env.

**macOS** (Developer ID Application cert — same Apple team as TestFlight):
- Secrets: `CSC_LINK` (base64 `.p12`) + `CSC_KEY_PASSWORD` (electron-builder's
  standard variables), and a **dedicated, minimal-role** App Store Connect API key
  (`APPLE_API_KEY`/`_KEY_ID`/`_ISSUER`) created **solely for notarization** — not
  the broad TestFlight key (blast-radius, §3.6).
- `notarize.mjs` (afterSign) staples the **`.app`** only. To satisfy a stapled
  **dmg**, run `notarize-artifact.mjs <dmg>` as a post-build pass (a second
  `notarytool submit`). **A `.zip` cannot be stapled** — it carries the stapled
  `.app` inside, which satisfies offline Gatekeeper assessment. Verification pins
  the object of each check: `codesign --verify --strict` + `spctl --assess`
  against the `.app`; `stapler validate` the `.app` (and the dmg if the extra pass
  is adopted) — **never** `stapler validate` a zip.
- **Nested Mach-O signing:** hardened-runtime notarization rejects any unsigned
  nested executable. The verification script must `codesign --verify` every Mach-O
  under `Contents/` including `app.asar.unpacked` — call out **`spawn-helper`**
  (node-pty's extensionless Mach-O, staged by `stage-native-deps.mjs`) by name, the
  classic first-signed-build failure.
- **Fail-loud, not silent-skip:** `notarize.mjs` currently returns success when the
  API-key trio is only *partially* set. WP-B adds a **require-notarization release
  switch** (an env flag set by `desktop-release.yml`; WP-B picks the concrete name
  at implementation time so it lands in code and docs together, per the repo's
  "no doc-only config tokens" rule) that makes it **throw** on missing/partial
  credentials. Checksums are computed **after**
  stapling. The **release matrix must not set** `CSC_IDENTITY_AUTO_DISCOVERY:
  "false"` (that stays only in the verification workflow).

**Windows** — signing must reach the **payload**, not just the wrapper:
- Keep `win.signAndEditExecutable: false` (flipping it re-enables electron-builder's
  `winCodeSign` download that breaks 7-Zip on non-admin Windows — load-bearing per
  `set-exe-identity.mjs`). Instead, when signing secrets are configured, sign the
  packed `Fabric.exe` and bundled native binaries **in the `afterPack` hook, after
  the rcedit stamp and before NSIS/MSI assembly** (e.g. signtool / Azure Trusted
  Signing client), then sign the finished `.exe`/`.msi` installers as a second
  pass. Every signing operation uses an **RFC3161 timestamp** (`/tr`) so signatures
  survive certificate expiry; verification asserts timestamp presence via
  `Get-AuthenticodeSignature`.
- **Uninstaller caveat:** only electron-builder's own sign path signs the NSIS
  uninstaller. v1 documents the uninstaller as unsigned (or adopts electron-builder
  26's `win.azureSignOptions`, evaluated in WP-B) — either way the "signed" claim
  in acceptance criterion 1 enumerates exactly which files are signed.
- **Config-gated with a standing, auditable acknowledgment:** if signing secrets
  are absent, the release job **fails loudly** unless a repository variable
  `vars.ALLOW_UNSIGNED_WINDOWS == 'true'` is set (readable by any trigger type —
  a per-dispatch input cannot travel through the automated dispatch). That var is
  documented in `RELEASING.md` and removed when the cert lands. Until then the
  automated flow either carries the standing acknowledgment (unsigned Windows,
  SmartScreen documented) or the Windows job is expected-red — acceptance
  criterion 1 notes this.

**Linux** — no code signing (platform norm); integrity via `SHA256SUMS`.
Sigstore/attestation deferred (§3.10).

### 3.3 Provenance and integrity for desktop assets

New **`scripts/ci/desktop_release_assets.py`** (same zone/style as
`release_candidate.py`, sharing helpers where sensible, tests in
`tests/scripts/test_desktop_release_assets.py`):

- `collect`: after packaging, record `{repository, tag, source_sha,
  desktop_app_version, files:[{name, size, sha256, ext, arch}]}` per platform and
  write `SHA256SUMS`. **The checksum/name-verification logic lives inline in
  `desktop-packaging.yml`'s heredoc, which §3.7.4 keeps frozen** — so `collect`
  **re-implements** the expected-name/hash matrix, and a test asserts both
  implementations agree on the ext→arch matrix. (Extracting the heredoc into a
  shared script is a larger pinned-workflow change; deferred.)
- `verify`: in `attach-assets`, re-hash every downloaded artifact against the
  per-platform manifests before anything touches the release.
- `attach` — **immutable semantics** (signed/notarized builds are *never*
  byte-identical across runs, so "replace on mismatch" would silently swap already-
  published, already-downloaded installers):
  - Already-attached asset **present**: verify its recorded digest and **skip**.
  - Digest **mismatch**: **fail loudly** by default. Replacement requires the
    explicit `force_replace` dispatch input, and the replacement (old→new digests,
    run id) is recorded in `desktop-release-manifest.json`.
  - **Ordering + atomicity:** verify *all* new artifacts inside the workflow first;
    upload installers, then upload `desktop-release-manifest.json` and the combined
    `SHA256SUMS-desktop.txt` **last**; a final step re-lists the release's assets
    and verifies the complete set against the merged manifest, failing loudly on
    any partial/mixed state. (GitHub's asset API rejects duplicate names with 422,
    so any replace is delete-then-upload — hence the all-or-nothing verify and the
    `concurrency` group in §3.1 to prevent two runs racing the same release.)
- The combined checksum file is **`SHA256SUMS-desktop.txt`** (not `.desktop`,
  which collides with freedesktop launcher files); per-platform `SHA256SUMS` are
  attached alongside so a user can verify a single download.
- Contract tests for `desktop-release.yml` (trigger, `ref`, concurrency group,
  permissions blocks, environment name, `--publish never`, verify-before-attach,
  signature-assertion steps) — pinned in `CANONICAL_REQUIREMENTS` and run **in
  CI** (see §3.7 execution-path note).

### 3.4 Website downloads page

**`website/src/pages/download.tsx`**, modeled on `ios.tsx`. This is the site's
**first client-side external-API refresh** — new code with novel failure modes,
not a copy of an existing pattern (the skills pages fetch only same-origin static
JSON; `prebuild.mjs`'s live-fetch is build-time only). Two layers:

1. **Build layer** (proven `prebuild.mjs` mechanism): prebuild writes
   `static/api/latest-release.json` by fetching the GitHub API **with
   `github.token`** (add `GITHUB_TOKEN: ${{ github.token }}` env to the build
   steps in `docs-pages.yml`/`skills-index.yml` — this is `github.token`, not a
   `secrets.*` reference, so the §3.7 ban is untouched; unauthenticated fetches
   from shared runner IPs are rate-limited). On failure it fetches the
   **currently-published** `https://obliviousodin.github.io/fabric/api/latest-release.json`
   (there is no on-disk previous copy in a fresh checkout), and the client tolerates
   a 404 on the very first deploy. The twice-daily cron bounds staleness even with
   JS disabled.
2. **Client layer:** on mount, refresh from the GitHub API (CORS-open,
   unauthenticated 60 req/h/IP). Novel failure modes it must handle explicitly:
   rate-limit 403 (JSON error body), offline, and **no-matching-assets**.

**Resolve "newest release that carries desktop assets," not `/releases/latest`.**
The Python release is published `--latest` 30–60 min *before* desktop assets attach
(and indefinitely if the desktop run fails), so `/releases/latest` routinely
returns a version with no installers — and a 200-with-no-matching-assets is **not**
a fetch failure, so neither fallback would engage. Instead fetch
`/releases?per_page=10`, pick the first release whose assets match the desktop
template (or that carries `desktop-release-manifest.json`), and render an explicit
"installers for vX are publishing…" state (showing the previous version's still-
downloadable installers) when the newest release lacks them.

**Asset matching keys on (os, extension), from the manifest — arch is per-target.**
`<arch>` varies by file (dmg/zip→`arm64`, exe/msi→`x64`, AppImage→`x86_64`,
deb→`amd64`, rpm→`x86_64`) and `<version>` is the desktop semver, **not** the
CalVer tag — a tag-keyed matcher finds nothing. Read the ext→arch mapping and
version from `desktop-release-manifest.json`'s file list rather than reconstructing
names. (The repo's own `platform-support.md` already fell into this trap with
never-existent `linux-x64` names — WP-C fixes those, §3.7.6.)

**UX/docs correctness:**
- **macOS is Apple-silicon-only** (arm64). Browser detection cannot distinguish
  Intel from Apple silicon (`navigator.platform` reports `MacIntel` on both), so
  the mitigation is **copy**, not detection: label the card "Apple silicon (M1 or
  later)" with an "Intel Mac? Install from source" link.
- **Gatekeeper wording:** a downloaded, notarized app **still shows the standard
  first-open confirmation dialog**; notarization only removes the hard
  "unidentified developer / malware" block. Docs and acceptance criterion 2 say
  exactly that — not "no warning."
- **Verify command:** `shasum -a 256 --ignore-missing -c SHA256SUMS-desktop.txt`
  (bare `-c` errors on every file the user didn't download); `Get-FileHash` for
  Windows; and point users at the per-platform sums too.
- Install/verify docs: new `website/docs/user-guide/install-desktop.md` (or an
  extension of the existing desktop guide).
- Register the route in the brand audit's protected discovery paths
  (`PUBLIC_SITE_DISCOVERY_PATHS` / `BUILT_PUBLIC_DISCOVERY_PATHS`) and use only
  canonical repo URLs (`NONCANONICAL_REPOSITORY_RE` is enforced). Must pass
  `fabric-brand-audit --mode public` (source + rendered) and the docs token audit.

### 3.5 Versioning and the duplicate-version gate

Desktop version (`apps/desktop/package.json`, `0.21.0`) stays **independent
semver**, not stamped from the CalVer tag: Windows MSI `ProductVersion` requires
major ≤ 255 (CalVer `2026.7.15` breaks it), and the desktop app has its own
compatibility surface. The linkage is recorded in `desktop-release-manifest.json`
(`tag ⇄ desktop_app_version ⇄ source_sha`) and shown on the downloads page.

Because artifact names embed only the desktop version, two production releases with
no desktop change would otherwise ship same-filename, different-bytes installers.
**Two enforcement points:**

1. **Pre-publish gate (cheap to fix):** `validate-production-source` (or a
   release-prep check) in `release-channels.yml` **fails the promotion — before the
   Python release exists —** when `apps/desktop/package.json`'s version already
   appears in a prior release's desktop manifest. The fix is still cheap there
   (bump on `main`, new beta, re-dispatch).
2. **In-pipeline decision (not warn-only):** `resolve-release` **skips the
   packaging matrix and attaches nothing** (succeeding) when the desktop version
   already shipped in a prior release's manifest, unless `force_rebuild` is set.
   This keeps §3.1's "built exactly once" true and is why the downloads page must
   resolve "newest release *with* desktop assets" (§3.4).

**Release-prep rule** (added to `RELEASING.md`): a production release that includes
desktop changes since the last release must bump `apps/desktop/package.json` first.

### 3.6 Secrets and environment policy

- New GitHub environment **`desktop-signing`** holding the signing secrets. GitHub
  environments **cannot filter by event type** — protection is a **deployment
  branch/tag policy** (+ optional reviewers). Set the policy to **tag pattern
  `v20*`** (matches the `ref: <tag>` dispatch) **plus branch `main`** only for the
  backfill path (§3.1), with the tradeoff noted. PR runs (`refs/pull/N/merge`) are
  excluded as a *consequence* of that policy, not by event filtering.
- The real guard against another workflow claiming the environment is the **audit
  layer**: extend `public-release-audit.py` so `environment: desktop-signing` (like
  the §3.7.2 secrets exemption) is permitted **only** in `desktop-release.yml`,
  pinned by tests.
- **Tag immutability:** git tags are mutable by any push-access principal, and
  `resolve-release` binds `tag → source_sha` (§3.1) but a force-moved tag could
  still feed attacker source to a signed build. **Add a repository ruleset
  restricting create/update/delete on `v20*` tags** — an H1 deliverable.
- Job permissions: matrix jobs `contents: read`; only `attach-assets` gets
  `contents: write`. Actions SHA-pinned; `persist-credentials: false`; no secrets
  in the brand-contract or unsigned verification paths.
- Signing keys are **repo-level release credentials**; rotation/revocation land in
  `SECURITY.md` (WP-D).

### 3.7 Audit-contract changes (deliberate, same PR as the workflow)

`public-release-audit.py` enforces a workflow-surface contract the new workflow
intersects at **six** points (each lands in WP-A's PR with
`tests/scripts/test_public_release_audit.py` updated, flagged for maintainer review
— guardrails §8):

1. **Workflow allowlist** — add `desktop-release.yml` to `EXPECTED_PUBLIC_WORKFLOWS`.
2. **Secrets ban** — `UNSAFE_WORKFLOW_RE` rejects *any* `secrets.` reference. Add a
   **per-file exemption scoped to `desktop-release.yml`** listing the exact allowed
   secret names (mirroring the `ALLOWED_WRITE_PERMISSIONS` per-file design).
   Everything else stays banned.
3. **Write-permission allowlist** — add `"desktop-release.yml": {"contents"}`
   (attach job) and add `actions` to `"release-channels.yml"` (§3.1 dispatch step).
4. **Canonical fragments** — `desktop-packaging.yml` stays frozen
   (`CSC_IDENTITY_AUTO_DISCOVERY: "false"` + `--publish never`). Add pinned
   fragments for `desktop-release.yml`: environment name, `--publish never`,
   `concurrency` group, verify-before-attach, and the **codesign/spctl/stapler +
   `Get-AuthenticodeSignature` signature-assertion steps** so a later edit can't
   silently delete the fail-loud checks.
5. **Publish ban** — keep the pattern: electron-builder always `--publish never`;
   *all* GitHub Release manipulation happens inside the audited Python script,
   never inline in YAML. No regex change.
6. **Environment-scope audit** — permit `environment: desktop-signing` only in
   `desktop-release.yml` (§3.6).

**Test execution path (critical):** nothing runs the full `tests/scripts` tree on
PRs — `public-ci.yml` discovers only `test_*audit.py`, and `release-channels.yml`
runs an explicit file list. So WP-A **must append**
`tests/scripts/test_desktop_release_assets.py` and the new workflow-contract module
to `release-channels.yml`'s `build-candidate` `scripts/run_tests.sh` invocation
(the same edit that adds the dispatch step), or name them `test_*audit.py` so
`public-ci` discovers them. The plan states where each test runs.

**"Unsigned" docs lockstep** —
`tests/contract/test_fabric_desktop_release_brand.py` asserts customer docs
(README / installation / platform-support) call CI desktop artifacts **unsigned**.
Once releases are signed, that wording splits: *verification builds stay unsigned;
release builds are signed and notarized.* Because `docs-pages.yml` deploys
`website/**` on every `main` push, flipping this wording **before a signed release
exists** would publish a false claim — so the flip + its contract-test change are a
**separate serialized deliverable (WP-F) gated on WP-E** (§4), not part of the
parallel docs work.

### 3.8 Interaction with the source-based self-update

Packaged installers change the update contract, but **not by disabling updates
wholesale**. The apply flow today is one sequence: `fabric update` (backend) →
`fabric desktop --build-only` (GUI rebuild) → bundle swap/relaunch
(`electron/main.ts`), and the skew toast's "align" action
(`src/store/updates.ts`, `REQUIRED_BACKEND_CONTRACT`) calls the same path. A
packaged install's backend is still a git checkout by design and **must** keep
self-updating. WP-B therefore splits the pipeline for packaged installs:

- **Keep** the `fabric update` backend stage and the skew-toast align action.
- **Skip** the `--build-only` GUI rebuild and the mac ditto-swap / linux relaunch
  stages; land the GUI portion on a terminal **"download the new installer"** state.
- Add a test asserting a packaged-context apply **never reaches the swap script**.

**Detecting the packaged context precisely:** `install-stamp.json`'s `source`
field records where the build *ran* (`'ci'` vs `'local'`), not how it was
*delivered* — a maintainer's laptop `npm run dist` build reads `'local'` and would
be misclassified, and a `fabric desktop` local source build (which MUST keep the
rebuild+swap path) reads the same field. So `desktop-release.yml` stamps an
**explicit** field (`channel: 'release'` / `packagedInstaller: true`, with a
`schemaVersion` bump handled in `loadInstallStamp`); §3.8's branch keys off that,
not the `source` proxy.

### 3.9 Patterns adopted from the iOS / TestFlight pipeline

- **Inject release-only values at build time; never mutate tracked sources** (iOS
  renders values into a temp spec) — the release workflow injects signing env and
  the `channel` stamp at build time while `run-electron-builder.mjs` keeps
  rejecting external configs.
- **Embed source provenance and audit the built artifact** — `install-stamp.json`
  carries the (now correct, §3.1) tag SHA; the release workflow audits the built
  artifact's identity/version/signature before checksumming.
- **Generated-file drift gates + fail-closed identity contracts** — brand-contract
  job untouched; new workflow ships contract tests; fail-loud signing (§3.2).
- **Main/tag-only cost gates with explicit rationale comments.**
- **Same Apple credential *type*** (App Store Connect API key) — but a **dedicated
  minimal-role key**, not the shared TestFlight key (§3.2/§3.6).
- **Automate what iOS does by hand** — the iOS provenance ledger (`IOS_RELEASES.md`)
  is hand-maintained and lossy; `desktop-release-manifest.json` is machine-generated
  and attached to the release.

### 3.10 Explicitly deferred (phase 2, separate PRs)

- **Installer auto-update** (electron-updater + `latest*.yml` feeds). Signed builds
  are the prerequisite; its interaction with the §3.8 source-update path needs its
  own design note.
- A guarded **`release: published`** trigger for human/PAT-published releases.
- **Build attestations** (`actions/attest-build-provenance`, SLSA) + sigstore for
  Linux artifacts.
- **macOS x64 / Windows arm64 / Linux arm64** targets.
- **Beta desktop channel** (pre-release GitHub Releases from `main`).
- **Immutable-releases tradeoff** note: with the §3.3 immutable-attach rule,
  correcting a bad installer means a new release, not an in-place swap.
- **Doc reconciliation:** `CONTRIBUTING.md` references a non-existent
  `supply-chain-audit.yml` — fix alongside the `RELEASING.md` updates.

## 4. Work packages (for parallel agents)

`.github/workflows/**`, `apps/shared/**`, and audit gates are shared surfaces
(guardrails §2.1) — WP-A lands first and serially. Zones per guardrails §2:
Release/packaging, Desktop (`apps/desktop/**` incl. its `README.md`), Docs-site
(`website/**`, `docs/**`).

| WP | Zone | Deliverable | Depends on |
| --- | --- | --- | --- |
| **WP-A** | Release/packaging | `desktop-release.yml` (§3.1) + `scripts/ci/desktop_release_assets.py` + the `release-channels.yml` dispatch step & pre-publish version gate + the §3.7 audit changes + **wiring the new tests into a CI run path** + `RELEASING.md` (desktop runbook, dispatch-failure remedy, backfill, `ALLOW_UNSIGNED_WINDOWS`) + a new **Release/packaging §6 pre-flight block** in `AGENT_GUARDRAILS.md` | — |
| **WP-B** | Desktop | Signing readiness (§3.2): step-scoped env plumbing through `run-electron-builder.mjs`; `afterPack` Windows payload signing (keep `signAndEditExecutable: false`) + post-packaging installer signing + RFC3161; mac nested-Mach-O + `spawn-helper` + dmg (`notarize-artifact.mjs`) handling; require-notarization fail-loud switch; signature-assertion scripts; the §3.8 packaged-update split + explicit `channel` stamp; local signing docs in `apps/desktop/README.md` | — |
| **WP-C** | Docs site | `download.tsx` (§3.4) + `prebuild.mjs` latest-release layer + `docs-pages.yml`/`skills-index.yml` `GITHUB_TOKEN` env + navbar entry + install/verify docs describing the pipeline **conditionally** (no "signed" claim yet) + fix the wrong `linux-x64` names in `platform-support.md` | serialized w/ WP-A for the **brand-audit discovery-path** edit (shared gate, §2.1) |
| **WP-D** | Docs / security | `SECURITY.md` desktop-signing key-management: `.p12` + API-key rotation cadence, Apple revocation runbook incl. shipped-builds blast radius, rotation triggers (any `desktop-signing` run from an unexpected ref/actor) | — |
| **H1** | Human (maintainer) | **First: verify Azure Trusted Signing eligibility** (individual vs. org validation; Microsoft restricts public-trust onboarding — pre-rank SSL.com eSigner / acknowledged-unsigned fallback). Export Developer ID `.p12`; create a **dedicated minimal-role** App Store Connect API key; create `desktop-signing` env + secrets with the §3.6 policy; create the `v20*` tag ruleset | — |
| **WP-E** | Release/packaging | End-to-end dry run: dispatch `desktop-release.yml` against a test tag; verify signed/notarized artifacts on all three OSes; verify the downloads page resolves them **via a per-tag override** (`/releases/latest` never returns a prerelease — use `/releases/tags/<tag>` or a dev query param); babysit the first live run (guardrails §4.2/§7.3); final runbook | WP-A, WP-B, WP-C, H1 |
| **WP-F** | Docs / release | The §3.7 **"unsigned → signed" docs-wording flip** + its `test_fabric_desktop_release_brand.py` change (serialized; lands only once a signed release exists) | WP-E |

**Per-WP pre-flight (guardrails §6):**
- **WP-A** (no §6 block exists for this zone today — WP-A adds one): `ruff check .`,
  `scripts/run_tests.sh tests/scripts/`, `python3 scripts/public-release-audit.py`,
  `scripts/fabric_identity_audit.py`, `scripts/fabric-brand-audit.py --mode public`.
  **Pre-merge verification** = contract tests + audits + a `release-channels.yml`
  `channel=alpha` dispatch on the branch. `desktop-release.yml`'s **first live run
  is necessarily post-merge** (the dispatch API doesn't see a workflow file until
  it's on `main`, and `desktop-signing` doesn't exist until H1) — flagged in the
  HANDOFF "Not verified" block and babysat in WP-E.
- **WP-B** the Desktop §6 block (typecheck/lint/`test:desktop`/`dist:linux` smoke).
- **WP-C** the Docs-site §6 block **plus** the Python audit block (its edits touch
  `scripts/fabric-brand-audit.py` and docs the brand contract test scans).

Every WP: task branch, PrimeOdin identity, no self-merge, HANDOFF block, and the
cost-gate note that native builds don't run on PRs (guardrails §4.2).

## 5. Acceptance criteria

1. Running the existing production promotion (dispatch + approval) results, within
   ~1 hour and with no manual step beyond the approval, in the GitHub Release also
   carrying: mac `arm64` `.dmg` (signed, notarized, **stapled**) + `.zip`
   (containing the notarized, stapled `.app`); Windows `x64` `.exe`/`.msi` — signed
   **including the packaged `Fabric.exe`** with RFC3161 timestamps (or explicitly
   acknowledged unsigned via `ALLOW_UNSIGNED_WINDOWS`, with the uninstaller's status
   stated); Linux `.AppImage`(x86_64)/`.deb`(amd64)/`.rpm`(x86_64);
   `SHA256SUMS-desktop.txt` + per-platform sums + `desktop-release-manifest.json`.
2. A fresh macOS machine opens the dmg **with no unidentified-developer/malware
   block** (the standard first-open confirmation still appears); `spctl --assess`
   passes; checksums match.
3. `…/fabric/download` shows working installer links for the newest release **that
   has desktop assets** within one page load; during the publish→attach window it
   shows the previous version's installers plus a "publishing…" note.
4. A failed desktop run neither blocks nor mutates the Python release; re-dispatching
   the same tag **converges** — already-attached assets are verified and skipped;
   any digest mismatch fails loudly unless `force_replace` is set.
5. All existing gates stay green: workflow contract tests (now actually executed),
   brand/identity/public audits, docs token audit, commit identity audit.

## 6. Risks

| Risk | Mitigation |
| --- | --- |
| Notarization outage/latency | Decoupled workflow; re-dispatch; Python release unaffected |
| Signing secrets misconfigured → un-notarized artifact ships | require-notarization switch throws; signature-assertion steps pinned in `CANONICAL_REQUIREMENTS` |
| Signing secrets exposed to dependency scripts | Step-scoped env, never job-level (§3.2) |
| Windows cert procurement stalls (Azure eligibility) | H1 verifies eligibility first; SSL.com/acknowledged-unsigned fallback pre-ranked |
| Tag force-moved after release | `resolve-release` binds tag→provenance SHA; `v20*` tag ruleset (H1) |
| Post-publication asset swap | Immutable attach; `force_replace` required + recorded (§3.3) |
| Concurrent runs corrupt the release | `concurrency` group, `cancel-in-progress: false` (§3.1) |
| Downloads page empty during publish window | Resolve newest release *with* assets; previous-version fallback (§3.4) |
| GitHub API rate limit | Build layer uses `github.token`; static published-JSON fallback; client 403/404 tolerant |
| Wrong commit stamped in installer | Dispatch at `ref: <tag>`; `resolve-release` asserts `$GITHUB_SHA == tag SHA` (§3.1) |
| New contract tests never run | WP-A wires them into `release-channels.yml`'s test list (§3.7) |
| Docs claim "signed" before a signed release exists | Wording flip isolated to WP-F, gated on WP-E |

## 7. Open questions for the maintainer

1. **Windows v1:** procure a signing cert now (Azure eligibility permitting) or
   ship v1 unsigned with the documented SmartScreen caveat and
   `ALLOW_UNSIGNED_WINDOWS=true`?
2. **Stapled dmg:** adopt the extra `notarize-artifact.mjs` pass (second notarytool
   submit, more time) or ship the stapled-app-inside-dmg only?
3. **Python-only releases:** confirm the §3.5 choice — skip the packaging matrix
   when the desktop version already shipped (recommended), vs. bump the desktop
   version on every production release.

## 8. Engineering review (summary)

A six-lens review panel (release engineering, security & signing, GitHub Actions
semantics & cost, website/distribution UX, repo-guardrails compliance, and
electron-builder specifics) reviewed the v1 draft; each reviewer verified the
draft's claims against the actual tree. The adversarial verification pass was cut
short by an org spend limit, so the confirmed findings below were **verified
manually against the repo** before folding in. Material changes v1 → v2:

- **Trigger corrected** (release engineering / Actions / security): our own
  releases can't fire `release:` (GITHUB_TOKEN) → `workflow_dispatch` at
  `ref: <tag>`; that ref also fixes the **wrong-commit `install-stamp.json`**
  blocker and the environment tag-policy (§3.1, §3.6).
- **Environment model corrected** (security): GitHub environments can't filter by
  event type → deployment tag/branch policy + audit-scoped `environment:` + `v20*`
  tag ruleset; step-scoped (not job-scoped) signing secrets (§3.2, §3.6).
- **Attach semantics corrected** (release eng / security): signed builds are never
  byte-identical → immutable attach with ordering, all-or-nothing verify,
  `concurrency`, and `force_replace` (§3.3).
- **Signing depth corrected** (electron-builder): Windows payload `Fabric.exe`
  signed in `afterPack` + RFC3161, not just the installer wrapper; mac nested
  Mach-O / `spawn-helper` / dmg-vs-zip stapling; fail-loud notarization (§3.2).
- **Downloads page corrected** (website): resolve newest-release-with-assets not
  `/releases/latest`; ext→arch matching from the manifest; `github.token` build
  fetch + published-JSON fallback; Gatekeeper/Intel/`--ignore-missing`/filename
  corrections (§3.4).
- **Versioning gate made enforcing** (release eng): pre-publish gate + in-pipeline
  skip, not warn-only (§3.5).
- **Update path corrected** (electron-builder): keep backend self-update, skip only
  GUI rebuild/swap; explicit `channel` stamp not the `source` proxy (§3.8).
- **Work packages corrected** (guardrails): zone/dependency fixes, test-execution
  path, WP-A §6 block, WP-F split for the docs-wording flip, cost framing (public
  repo → $0) (§3.7, §4).
