Homebrew packaging notes for Fabric.

The checked-in formula is source-only until the first signed public release.
Install it locally with `brew install --HEAD ./packaging/homebrew/fabric-agent.rb`.

Key choices:
- The first stable formula should target a signed, semver-named sdist attached to a GitHub release.
- `faster-whisper` now lives in the `voice` extra, which keeps wheel-only transitive dependencies out of the base Homebrew formula.
- Bundled and optional skills are installed into `libexec` as immutable distribution data and resolved from there directly; their executable trust roots are not wrapper-configurable. The wrapper keeps `FABRIC_MANAGED=homebrew` so upgrades remain owned by Homebrew.

Typical update flow:
1. Bump the formula `url`, `version`, and `sha256`.
2. Refresh Python resources with `brew update-python-resources --print-only fabric-agent`.
3. Keep `ignore_packages: %w[certifi cryptography pydantic]`.
4. Verify `brew audit --new --strict fabric-agent` and `brew test fabric-agent`.
