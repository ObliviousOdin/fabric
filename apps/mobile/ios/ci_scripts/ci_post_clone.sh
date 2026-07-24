#!/bin/sh
# Xcode Cloud post-clone step for the Fabric iOS app.
#
# Keep this entrypoint in the project-adjacent ci_scripts directory. Xcode
# Cloud discovers custom scripts beside the selected project/workspace.
#
# The generic Xcode project bootstrap is committed because Xcode Cloud validates
# the project path before custom scripts run. This script regenerates that
# project from apps/mobile/ios/project.yml after cloning, applying release-only
# bundle/build values through a temporary manifest. Pass --bootstrap to generate
# only the generic project for drift verification. Point the workflow at:
#     project:  apps/mobile/ios/FabricMobile.xcodeproj
#     scheme:   Fabric
#
# Signing is handled by Xcode Cloud + App Store Connect, so no signing secret
# ever lives in this repository. This keeps the repo's "no secrets in CI"
# posture intact while still producing signed TestFlight builds.
set -eu

XCODEGEN_VERSION="2.46.0"
XCODEGEN_SHA256="c83c7bd70255b0ddf4116dadce16bdf0e5939165b43a544e124de294ec84aa27"
RUSTUP_VERSION="1.29.0"
RUSTUP_AARCH64_APPLE_SHA256="aeb4105778ca1bd3c6b0e75768f581c656633cd51368fa61289b6a71696ac7e1"
RUSTUP_X86_64_APPLE_SHA256="33cf85df9142bc6d29cbc62fa5ca1d4c29622cddb55213a4c1a43c457fb9b2d7"

# Xcode Cloud exports CI_PRIMARY_REPOSITORY_PATH. The fallback walks from this
# required project-adjacent ci_scripts directory to the repository root so the
# same hook is also runnable by hand from a normal checkout.
repo_root="${CI_PRIMARY_REPOSITORY_PATH:-$(cd "$(dirname "$0")/../../../.." && pwd)}"
ios_dir="$repo_root/apps/mobile/ios"

bootstrap_only=false
if [ "$#" -gt 0 ]; then
  if [ "$#" -ne 1 ] || [ "$1" != "--bootstrap" ]; then
    echo "Usage: ci_post_clone.sh [--bootstrap]" >&2
    exit 2
  fi
  bootstrap_only=true
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
# macOS exposes its temporary root through /var, which is a symlink to
# /private/var. Cargo and proc-macro helpers canonicalize that prefix
# differently; mixing the logical and physical paths makes UniFFI's Askama
# templates resolve beneath a duplicated /private/var path. Keep every Rust
# bootstrap path physical from the start.
work="$(cd "$work" && pwd -P)"

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

if [ "$bootstrap_only" = true ]; then
  # Keep this separate from the archive generation below. Xcode Cloud opens the
  # committed bootstrap before it can run this hook, so CI must be able to
  # regenerate and diff the no-artifact project on its own.
  env \
    -u XCODEGEN_INCLUDE_LINK_CORE \
    -u XCODEGEN_LINK_OVERLAY_PATH \
    -u XCODEGEN_LINK_CORE_PACKAGE_PATH \
    "$xcodegen_bin" generate \
      --spec "$ios_dir/project.yml" \
      --project "$ios_dir" \
      --project-root "$ios_dir"
  echo "XcodeGen generated the generic FabricMobile.xcodeproj bootstrap"
  exit 0
fi

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

# Fabric Link's MLS state machine is a reviewed Rust/OpenMLS binary shared by
# Python, iOS, Android, and the browser. The generated Swift source and
# XCFramework are intentionally ignored build products, so every Xcode Cloud
# clone must reproduce them from Cargo.lock before Xcode resolves the local
# package. Bootstrap rustup into this job's private temporary directory rather
# than trusting or mutating a runner-global toolchain.
rust_arch="$(uname -m)"
case "$rust_arch" in
  arm64|aarch64)
    rust_target="aarch64-apple-darwin"
    rustup_sha256="$RUSTUP_AARCH64_APPLE_SHA256"
    ;;
  x86_64)
    rust_target="x86_64-apple-darwin"
    rustup_sha256="$RUSTUP_X86_64_APPLE_SHA256"
    ;;
  *)
    echo "Unsupported Xcode Cloud Rust bootstrap architecture: $rust_arch" >&2
    exit 2
    ;;
esac

rustup_init="$work/rustup-init"
curl --fail --location --silent --show-error \
  --output "$rustup_init" \
  "https://static.rust-lang.org/rustup/archive/${RUSTUP_VERSION}/${rust_target}/rustup-init"
printf '%s  %s\n' "$rustup_sha256" "$rustup_init" | shasum --algorithm 256 --check
chmod 700 "$rustup_init"
export CARGO_HOME="$work/cargo"
export RUSTUP_HOME="$work/rustup"
export PATH="$CARGO_HOME/bin:$PATH"
"$rustup_init" -y --profile minimal --default-toolchain none --no-modify-path
"$repo_root/apps/fabric-link-core/apple/build-xcframework.sh"

# Xcode Cloud validates the committed bootstrap before it gets here. Confirm the
# freshly-built local binary target is now resolvable before we generate the
# archive project that depends on it, so missing or malformed artifacts fail at
# the producer with an actionable log instead of later during Xcode setup.
if ! swift package --package-path "$repo_root/apps/fabric-link-core/apple" describe \
  > "$work/fabric-link-package.txt" 2>&1; then
  cat "$work/fabric-link-package.txt" >&2
  echo "Fabric Link XCFramework is not a resolvable Swift package after staging" >&2
  exit 2
fi

XCODEGEN_INCLUDE_LINK_CORE=true \
XCODEGEN_LINK_OVERLAY_PATH="$ios_dir/project.fabric-link.yml" \
XCODEGEN_LINK_CORE_PACKAGE_PATH="$repo_root/apps/fabric-link-core/apple" \
"$xcodegen_bin" generate \
  --spec "$generated_spec" \
  --project "$ios_dir" \
  --project-root "$ios_dir"
echo "XcodeGen generated FabricMobile.xcodeproj from an immutable source manifest"
