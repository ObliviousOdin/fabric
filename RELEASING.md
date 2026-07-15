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
