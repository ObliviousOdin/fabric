#!/bin/sh
# Xcode Cloud post-clone step for the Fabric iOS app.
#
# Keep this entrypoint in the project-adjacent ci_scripts directory. Xcode
# Cloud discovers custom scripts beside the selected project/workspace.
#
# The generic Xcode project bootstrap is committed because Xcode Cloud validates
# the project path before custom scripts run. This script regenerates that
# project from apps/mobile/ios/project.yml after cloning, applying release-only
# bundle/build values through a temporary manifest. Point the workflow at:
#     project:  apps/mobile/ios/FabricMobile.xcodeproj
#     scheme:   Fabric
#
# Signing is handled by Xcode Cloud + App Store Connect, so no signing secret
# ever lives in this repository. This keeps the repo's "no secrets in CI"
# posture intact while still producing signed TestFlight builds.
set -eu

XCODEGEN_VERSION="2.46.0"
XCODEGEN_SHA256="c83c7bd70255b0ddf4116dadce16bdf0e5939165b43a544e124de294ec84aa27"

# Xcode Cloud exports CI_PRIMARY_REPOSITORY_PATH. The fallback walks from this
# required project-adjacent ci_scripts directory to the repository root so the
# same hook is also runnable by hand from a normal checkout.
repo_root="${CI_PRIMARY_REPOSITORY_PATH:-$(cd "$(dirname "$0")/../../../.." && pwd)}"
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

source_revision=""
if [ -n "$bundle_id" ]; then
  # Release provenance must describe an immutable tracked tree. Untracked local
  # app inputs can enter the archive because project.yml recursively includes
  # Fabric/. Reject both ordinary and ignored untracked paths there, then reject
  # tracked changes, so HEAD describes every source/resource XcodeGen can package.
  if ! git -C "$repo_root" diff --quiet --ignore-submodules -- \
    || ! git -C "$repo_root" diff --cached --quiet --ignore-submodules --; then
    echo "iOS release generation requires a clean tracked checkout" >&2
    exit 2
  fi
  if ! grep -Fqx '      - Fabric' "$generated_spec"; then
    echo "The recursive iOS app source root changed; update ci_post_clone.sh before releasing" >&2
    exit 2
  fi
  untracked_app_inputs="$({
    git -C "$repo_root" ls-files --others --exclude-standard -- apps/mobile/ios/Fabric
    git -C "$repo_root" ls-files --others --ignored --exclude-standard -- apps/mobile/ios/Fabric
  } | LC_ALL=C sort -u)"
  if [ -n "$untracked_app_inputs" ]; then
    echo "iOS release generation found untracked app source or resources under apps/mobile/ios/Fabric:" >&2
    printf '%s\n' "$untracked_app_inputs" >&2
    echo "Commit or remove every recursive app input before generating a release" >&2
    exit 2
  fi
  source_revision="$(git -C "$repo_root" rev-parse --verify 'HEAD^{commit}' 2>/dev/null || true)"
  if ! printf '%s\n' "$source_revision" | grep -Eq '^[0-9a-f]{40}([0-9a-f]{24})?$'; then
    echo "iOS release generation could not resolve an exact Git commit" >&2
    exit 2
  fi

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

if [ -n "$source_revision" ]; then
  if ! grep -Fq 'FabricSourceRevision: development' "$generated_spec"; then
    echo "The source iOS revision marker changed; update ci_post_clone.sh before releasing" >&2
    exit 2
  fi
  echo "Embedding source revision $source_revision in the generated project"
  next_spec="$work/project.revision.yml"
  sed "s#FabricSourceRevision: development#FabricSourceRevision: $source_revision#g" \
    "$generated_spec" > "$next_spec"
  if grep -Fq 'FabricSourceRevision: development' "$next_spec" \
    || ! grep -Fq "FabricSourceRevision: $source_revision" "$next_spec"; then
    echo "The source iOS revision was not applied completely" >&2
    exit 2
  fi
  mv "$next_spec" "$generated_spec"
fi

"$xcodegen_bin" generate \
  --spec "$generated_spec" \
  --project "$ios_dir" \
  --project-root "$ios_dir"
echo "XcodeGen generated FabricMobile.xcodeproj from an immutable source manifest"
