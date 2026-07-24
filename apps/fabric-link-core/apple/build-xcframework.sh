#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
crate_dir="$(cd -- "${script_dir}/.." && pwd)"
generated_dir="${crate_dir}/target/generated-apple"
artifact_dir="${script_dir}/Artifacts"
swift_source_dir="${script_dir}/Sources/FabricLinkCore"
xcframework="${artifact_dir}/FabricLinkCoreFFI.xcframework"
toolchain="${FABRIC_LINK_RUST_TOOLCHAIN:-1.97.1}"

command -v cargo >/dev/null || {
    echo "cargo is required to build the Fabric Link Apple core" >&2
    exit 1
}
command -v rustup >/dev/null || {
    echo "rustup is required to install the pinned Fabric Link Apple targets" >&2
    exit 1
}
command -v xcodebuild >/dev/null || {
    echo "Xcode is required to package the Fabric Link Apple core" >&2
    exit 1
}
command -v lipo >/dev/null || {
    echo "lipo is required to package simulator architectures" >&2
    exit 1
}

rustup toolchain install "${toolchain}" --profile minimal
rustup target add \
    --toolchain "${toolchain}" \
    aarch64-apple-ios \
    aarch64-apple-ios-sim \
    x86_64-apple-ios

cd "${crate_dir}"
cargo "+${toolchain}" build --release --locked --features bindgen
cargo "+${toolchain}" build --release --locked --target aarch64-apple-ios
cargo "+${toolchain}" build --release --locked --target aarch64-apple-ios-sim
cargo "+${toolchain}" build --release --locked --target x86_64-apple-ios

host_library="${crate_dir}/target/release/libfabric_link_core.dylib"
test -f "${host_library}" || {
    echo "Fabric Link host library was not built: ${host_library}" >&2
    exit 1
}

mkdir -p "${generated_dir}" "${artifact_dir}" "${swift_source_dir}"
cargo "+${toolchain}" run \
    --release \
    --locked \
    --features bindgen \
    --bin fabric-link-bindgen \
    -- \
    generate "${host_library}" \
    --language swift \
    --out-dir "${generated_dir}" \
    --no-format

header="${generated_dir}/FabricLinkCoreFFI.h"
modulemap="${generated_dir}/FabricLinkCoreFFI.modulemap"
generated_swift="${generated_dir}/FabricLinkCore.swift"
for generated in "${header}" "${modulemap}" "${generated_swift}"; do
    test -s "${generated}" || {
        echo "Fabric Link generated Apple binding is missing: ${generated}" >&2
        exit 1
    }
done

work="$(mktemp -d "${TMPDIR:-/tmp}/fabric-link-apple.XXXXXX")"
trap 'rm -rf -- "${work}"' EXIT
headers="${work}/headers"
mkdir -p "${headers}"
cp "${header}" "${headers}/FabricLinkCoreFFI.h"
cp "${modulemap}" "${headers}/module.modulemap"

device_library="${crate_dir}/target/aarch64-apple-ios/release/libfabric_link_core.a"
simulator_arm_library="${crate_dir}/target/aarch64-apple-ios-sim/release/libfabric_link_core.a"
simulator_x64_library="${crate_dir}/target/x86_64-apple-ios/release/libfabric_link_core.a"
for library in "${device_library}" "${simulator_arm_library}" "${simulator_x64_library}"; do
    test -s "${library}" || {
        echo "Fabric Link Apple archive is missing: ${library}" >&2
        exit 1
    }
done

simulator_library="${work}/libfabric_link_core-simulator.a"
lipo -create \
    "${simulator_arm_library}" \
    "${simulator_x64_library}" \
    -output "${simulator_library}"

staged_xcframework="${work}/FabricLinkCoreFFI.xcframework"
xcodebuild -create-xcframework \
    -library "${device_library}" \
    -headers "${headers}" \
    -library "${simulator_library}" \
    -headers "${headers}" \
    -output "${staged_xcframework}"

rm -rf -- "${xcframework}"
mv "${staged_xcframework}" "${xcframework}"
cp "${generated_swift}" "${swift_source_dir}/FabricLinkCore.swift"

test -s "${xcframework}/Info.plist"
grep -q "func fabricLinkCreateController" \
    "${swift_source_dir}/FabricLinkCore.swift"
echo "PASS Fabric Link Apple XCFramework + Swift binding"
