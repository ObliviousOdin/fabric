#!/bin/sh
# Xcode Cloud post-clone step for the Fabric iOS app.
#
# The Xcode project is generated from apps/mobile/ios/project.yml by XcodeGen
# and is deliberately NOT committed (it is derived output). Xcode Cloud must
# therefore generate it after cloning and before the build resolves the
# project. Point your Xcode Cloud workflow at:
#     project:  apps/mobile/ios/FabricMobile.xcodeproj
#     scheme:   Fabric
#
# Signing is handled by Xcode Cloud + App Store Connect, so no signing secret
# ever lives in this repository. This keeps the repo's "no secrets in CI"
# posture intact while still producing signed TestFlight builds.
set -eu

XCODEGEN_VERSION="2.46.0"
XCODEGEN_SHA256="c83c7bd70255b0ddf4116dadce16bdf0e5939165b43a544e124de294ec84aa27"

# Xcode Cloud exports CI_PRIMARY_REPOSITORY_PATH; fall back to this script's
# parent so the script is also runnable by hand from a normal checkout.
repo_root="${CI_PRIMARY_REPOSITORY_PATH:-$(cd "$(dirname "$0")/.." && pwd)}"
ios_dir="$repo_root/apps/mobile/ios"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

archive="$work/xcodegen.tar.gz"
curl --fail --location --silent --show-error \
  --output "$archive" \
  "https://github.com/yonaskolb/XcodeGen/archive/refs/tags/${XCODEGEN_VERSION}.tar.gz"
printf '%s  %s\n' "$XCODEGEN_SHA256" "$archive" | shasum --algorithm 256 --check

src="$work/src"
mkdir -p "$src"
tar -xzf "$archive" -C "$src" --strip-components=1
swift build --package-path "$src" --disable-sandbox --configuration release

cd "$ios_dir"
"$src/.build/release/xcodegen" generate
echo "XcodeGen generated FabricMobile.xcodeproj in $ios_dir"
