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

if [ -n "${FABRIC_XCODEGEN_BIN:-}" ]; then
  xcodegen_bin="$FABRIC_XCODEGEN_BIN"
  if [ ! -x "$xcodegen_bin" ]; then
    echo "FABRIC_XCODEGEN_BIN is not executable: $xcodegen_bin" >&2
    exit 2
  fi
else
  archive="$work/xcodegen.tar.gz"
  curl --fail --location --silent --show-error \
    --output "$archive" \
    "https://github.com/yonaskolb/XcodeGen/archive/refs/tags/${XCODEGEN_VERSION}.tar.gz"
  printf '%s  %s\n' "$XCODEGEN_SHA256" "$archive" | shasum --algorithm 256 --check

  src="$work/src"
  mkdir -p "$src"
  tar -xzf "$archive" -C "$src" --strip-components=1
  swift build --package-path "$src" --disable-sandbox --configuration release
  xcodegen_bin="$src/.build/release/xcodegen"
fi

cd "$ios_dir"

# Release overrides are rendered into a temporary spec. The tracked manifest is
# never edited, so a local run and an Xcode Cloud run share the same clean-source
# invariant. Xcode Cloud provides CI_BUILD_NUMBER automatically; local release
# operators can set FABRIC_IOS_BUILD_NUMBER explicitly.
generated_spec="$work/project.release.yml"
cp project.yml "$generated_spec"

bundle_id="${FABRIC_IOS_BUNDLE_ID:-}"
build_number="${FABRIC_IOS_BUILD_NUMBER:-${CI_BUILD_NUMBER:-}}"

# Validate each supplied value before checking whether the pair is complete, so
# a malformed release value produces the precise actionable error.
if [ -n "$bundle_id" ] && ! printf '%s\n' "$bundle_id" | grep -Eq '^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$'; then
  echo "FABRIC_IOS_BUNDLE_ID must be a reverse-DNS identifier" >&2
  exit 2
fi
if [ -n "$build_number" ]; then
  case "$build_number" in
    *[!0-9]*)
      echo "FABRIC_IOS_BUILD_NUMBER/CI_BUILD_NUMBER must be a positive integer" >&2
      exit 2
      ;;
  esac
  if [ "$build_number" -lt 1 ]; then
    echo "FABRIC_IOS_BUILD_NUMBER/CI_BUILD_NUMBER must be at least 1" >&2
    exit 2
  fi
fi

# A release identity is one atomic contract. Refuse a partial override so an
# archive cannot accidentally use the public development bundle with a release
# build number, or the App Store bundle with the reusable development build.
if [ -n "$bundle_id" ] && [ -z "$build_number" ]; then
  echo "FABRIC_IOS_BUNDLE_ID requires FABRIC_IOS_BUILD_NUMBER or CI_BUILD_NUMBER" >&2
  exit 2
fi
if [ -z "$bundle_id" ] && [ -n "$build_number" ]; then
  echo "FABRIC_IOS_BUILD_NUMBER/CI_BUILD_NUMBER requires FABRIC_IOS_BUNDLE_ID" >&2
  exit 2
fi

if [ -n "$bundle_id" ]; then
  if ! grep -Fq 'io.github.obliviousodin.fabric.mobile' "$generated_spec"; then
    echo "The source iOS bundle marker changed; update ci_post_clone.sh before releasing" >&2
    exit 2
  fi
  echo "Applying the configured iOS bundle identifier to the generated project"
  next_spec="$work/project.bundle.yml"
  sed "s#io\\.github\\.obliviousodin\\.fabric\\.mobile#$bundle_id#g" \
    "$generated_spec" > "$next_spec"
  if grep -Fq 'io.github.obliviousodin.fabric.mobile' "$next_spec"; then
    echo "The configured iOS bundle identifier was not applied completely" >&2
    exit 2
  fi
  mv "$next_spec" "$generated_spec"
fi

if [ -n "$build_number" ]; then
  if ! grep -Eq 'CURRENT_PROJECT_VERSION: "[0-9][0-9]*"' "$generated_spec"; then
    echo "The source iOS build marker changed; update ci_post_clone.sh before releasing" >&2
    exit 2
  fi
  echo "Applying iOS build number $build_number to the generated project"
  next_spec="$work/project.build.yml"
  sed "s#CURRENT_PROJECT_VERSION: \"[0-9][0-9]*\"#CURRENT_PROJECT_VERSION: \"$build_number\"#" \
    "$generated_spec" > "$next_spec"
  if ! grep -Fq "CURRENT_PROJECT_VERSION: \"$build_number\"" "$next_spec"; then
    echo "The configured iOS build number was not applied" >&2
    exit 2
  fi
  mv "$next_spec" "$generated_spec"
fi

"$xcodegen_bin" generate \
  --spec "$generated_spec" \
  --project "$ios_dir" \
  --project-root "$ios_dir"
echo "XcodeGen generated FabricMobile.xcodeproj from an immutable source manifest"
