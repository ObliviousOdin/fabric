# Fabric release channels

Fabric is distributed as a Python package and desktop application, so release
promotion moves immutable package artifacts rather than deploying a long-lived
server. The `Fabric release channels` GitHub Actions workflow owns the Python
package path. Desktop packaging remains in its dedicated verification workflow.

## Promotion flow

| Channel | Trigger | Source | Result |
|---|---|---|---|
| Alpha | Pull request, or manual alpha dispatch | Exact PR/selected commit | Tested wheel and source archive retained for 14 days |
| Beta | Successful push to protected `main` | Exact merged commit | Tested wheel and source archive retained for 30 days |
| Production | Manual production dispatch plus environment approval | A successful beta workflow run | The exact beta bytes become an annotated GitHub Release |

Every candidate contains `release-manifest.json` and `SHA256SUMS`. The manifest
binds the wheel and source archive to their repository, commit SHA, embedded
package version, size, and SHA-256 digest. Promotion fails if any byte, version,
or provenance field changes.

## Test an alpha on a local machine

After the pull request's `Deploy alpha candidate` job succeeds:

```bash
gh run list --workflow "Fabric release channels" --branch <branch>
gh run download <run-id> --name "fabric-alpha-<commit-sha>"
python -m pip install ./fabric_agent-*.whl
fabric --version
fabric setup
```

Use a virtual environment for installation. Exercise the onboarding flow and
gateway lifecycle before promoting the change.

## Promote beta to production

1. Merge the tested pull request to `main`.
2. Wait for the `Deploy beta candidate` job to succeed.
3. Open **Actions → Fabric release channels → Run workflow** on `main`.
4. Choose `production`, provide the successful beta run ID, and choose a new
   CalVer tag such as `v2026.7.15`.
5. Approve the protected `production` environment deployment.

Production never rebuilds. It verifies that the source workflow was a
successful `push` run on this repository's protected `main`, downloads that
run's beta artifact, verifies it twice, creates an annotated tag at the beta
commit, and publishes those exact files as the latest GitHub Release.

## GitHub environment policy

- `alpha`: accepts feature branches and has no approval delay.
- `beta`: accepts protected branches only.
- `production`: accepts protected branches only and requires maintainer
  approval.

The workflow has read-only repository permissions by default. Only the final
production job receives `contents: write`, after the provenance gate and
environment approval. External actions are pinned to full commit SHAs.

## Desktop installers

Desktop packaging is **decoupled** from the Python release. When
`promote-production` finishes publishing the Python release, its final step
dispatches `desktop-release.yml` at `ref: <tag>` (this is why that job holds
`actions: write`). A desktop failure therefore never blocks or corrupts the
Python release, and the desktop run is re-dispatchable.

`desktop-release.yml` resolves and validates the release, packages macOS
(`arm64` `.dmg`/`.zip`), Windows (`x64` `.exe`/`.msi`), and Linux
(`.AppImage`/`.deb`/`.rpm`) installers, signs and notarizes the macOS app and
DMG, enforces the configured Windows signing policy, then
attaches them with a `desktop-release-manifest.json`, a combined
`SHA256SUMS-desktop.txt`, and per-platform `SHA256SUMS`. Attachment is
**immutable**: an already-attached installer with a matching digest is skipped,
and a digest mismatch fails loudly unless the run is dispatched with
`force_replace`.

### Signing environment

Signing secrets live in the `desktop-signing` GitHub environment, gated by a
deployment policy of **tag pattern `v20*` plus branch `main`** (the backfill
path). Only `desktop-release.yml`'s packaging job declares that environment, and
`public-release-audit.py` enforces that no other workflow may claim it or its
secrets. Add a repository ruleset restricting create/update/delete on `v20*`
tags so a force-moved tag cannot feed attacker source to a signed build.

### Desktop version bump rule

The desktop app carries its **own** semantic version in
`apps/desktop/package.json` (independent of the CalVer tag — a Windows MSI
`ProductVersion` cannot use `2026.7.15`). Because installer file names embed only
that version:

- A production release that includes **desktop changes** since the last release
  (any change under `apps/desktop`, `apps/shared`, `package.json`, or
  `package-lock.json`) **must bump** `apps/desktop/package.json` first. The
  pre-publish gate (`desktop_release_assets.py preflight`) fails the promotion —
  before the Python release exists — otherwise. Fix is cheap: bump on `main`,
  cut a new beta, re-dispatch production.
- A **Python-only** release (no desktop change) is allowed to reuse the desktop
  version; `desktop-release.yml` then skips repackaging and attaches nothing, so
  the release simply carries no new installers. The downloads page resolves the
  newest release that *has* desktop assets.

### If the desktop dispatch fails

Because `publish_release.py` refuses a pre-existing tag, `promote-production`
cannot be re-run once the release is live. Instead dispatch the desktop build
manually:

```bash
gh workflow run desktop-release.yml --ref <tag> -f release_tag=<tag>
```

**Backfill caveat:** the dispatch API only sees a workflow file present on the
ref. A tag created **before** `desktop-release.yml` merged to `main` cannot be
dispatched at its own ref — dispatch it at `--ref main` instead (accepting
main's workflow definition; the re-derived install-stamp is acceptable for a
backfilled tag). This is why the `desktop-signing` deployment policy also permits
`main`.

### Windows signing not yet available

Until a Windows code-signing certificate is provisioned, set the repository
variable `ALLOW_UNSIGNED_WINDOWS=true`. The Windows job then ships unsigned
installers (users see a SmartScreen "unknown publisher" warning) instead of
failing the Authenticode assertion. Remove the variable once the certificate
lands. macOS and Linux are unaffected. Note that even a notarized macOS app still
shows the standard first-open confirmation dialog; notarization only removes the
hard "unidentified developer / malware" block.

Packaged desktop apps resolve updates through `desktop-release-manifest.json`.
Their update button opens the correct installer download; it never silently
executes the current unsigned Windows installer. After installation, the next
launch aligns the Fabric-managed CLI/backend to the package's exact source SHA.
Source-checkout desktop builds keep the existing source update + rebuild flow.

### Verifying a download

```bash
# macOS / Linux — verify only what you downloaded:
shasum -a 256 --ignore-missing -c SHA256SUMS-desktop.txt
```

```powershell
# Windows:
Get-FileHash .\Fabric-<version>-win-x64.exe -Algorithm SHA256
```

Per-platform `SHA256SUMS` files are attached alongside so a single download can
be verified on its own.
