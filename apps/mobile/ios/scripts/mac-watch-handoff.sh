#!/bin/sh
# macOS verification handoff for the Fabric Watch companion (WATCH.md §7).
#
# The watch targets were authored in a Linux environment that cannot run
# XcodeGen or compile Swift, so the committed FabricMobile.xcodeproj is
# intentionally BEHIND project.yml on this branch. This script is the
# sanctioned way to close that gap on a Mac:
#
#   1. regenerate the project from the tracked manifest (the same pinned
#      XcodeGen flow Xcode Cloud uses),
#   2. re-run the generation contract tests,
#   3. build the watch app for the watch simulator,
#   4. build and run the iOS unit tests (compiles the shared relay bridge
#      and executes FabricTests, including WatchRelayContractTests),
#   5. print exactly what to commit.
#
# Run from anywhere inside the repo on a Mac with full Xcode installed:
#     sh apps/mobile/ios/scripts/mac-watch-handoff.sh
#
# DO NOT merge the branch until this has passed and the regenerated project
# (plus the generated watch Info.plist/entitlements files) is committed —
# the iOS CI job only runs on main (AGENT_GUARDRAILS.md §4.2), so merging
# early turns main red, not the PR.
set -eu

if [ "$(uname -s)" != "Darwin" ]; then
  echo "This handoff requires macOS with Xcode (watchOS SDK + simulators)." >&2
  exit 2
fi
if ! command -v xcodebuild >/dev/null 2>&1; then
  echo "xcodebuild not found. Install full Xcode and select it with xcode-select." >&2
  exit 2
fi

script_dir="$(cd "$(dirname "$0")" && pwd)"
ios_dir="$(cd "$script_dir/.." && pwd)"
repo_root="$(cd "$ios_dir/../../.." && pwd)"

echo "==> [1/5] Regenerating FabricMobile.xcodeproj from project.yml"
"$ios_dir/ci_scripts/ci_post_clone.sh"

echo "==> [2/5] Running the project-generation contract tests"
python3 "$repo_root/tests/scripts/test_ios_project_generation.py"

echo "==> [3/5] Building the FabricWatch scheme for the watch simulator"
xcodebuild build \
  -project "$ios_dir/FabricMobile.xcodeproj" \
  -scheme FabricWatch \
  -destination "generic/platform=watchOS Simulator" \
  CODE_SIGNING_ALLOWED=NO \
  -quiet

echo "==> [4/5] Building + running the iOS unit tests (includes the relay bridge)"
xcodebuild test \
  -project "$ios_dir/FabricMobile.xcodeproj" \
  -scheme Fabric \
  -destination "platform=iOS Simulator,name=iPhone 16" \
  -only-testing:FabricTests \
  CODE_SIGNING_ALLOWED=NO \
  -quiet

echo "==> [5/5] Done. Review and commit the regenerated project artifacts:"
git -C "$repo_root" status --short -- \
  "apps/mobile/ios/FabricMobile.xcodeproj" \
  "apps/mobile/ios/Fabric/Info.plist" \
  "apps/mobile/ios/FabricWatch/Info.plist" \
  "apps/mobile/ios/FabricWatch/FabricWatch.entitlements" \
  "apps/mobile/ios/FabricWatchWidgets/Info.plist" \
  "apps/mobile/ios/FabricWatchWidgets/FabricWatchWidgets.entitlements"

cat <<'NEXT'

Everything above must be committed on this branch (the committed project
must byte-match what the generator produces — AGENT_GUARDRAILS.md §5.5).

Remaining follow-ups tracked in apps/mobile/ios/WATCH_HANDOFF.md:
  - mobile.yml: extend the main-branch generation diff check and add the
    FabricWatch simulator build (shared surface — coordinate per §2.1).
  - Register the app group from project.yml in the signing team's account
    before any device/TestFlight build.
  - Physical-device pass per WATCH.md §7 before any slice is called shipped.
NEXT
