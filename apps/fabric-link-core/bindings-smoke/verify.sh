#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
crate_dir="$(cd -- "${script_dir}/.." && pwd)"
repo_dir="$(cd -- "${crate_dir}/../.." && pwd)"
cd "${crate_dir}"

case "$(uname -s)" in
    Darwin)
        library_name="libfabric_link_core.dylib"
        ;;
    Linux)
        library_name="libfabric_link_core.so"
        ;;
    *)
        echo "Unsupported native smoke-test host: $(uname -s)" >&2
        exit 1
        ;;
esac

cargo build --locked --features bindgen
mkdir -p \
    target/generated-python \
    target/generated-swift \
    target/generated-kotlin

cargo run --locked --features bindgen --bin fabric-link-bindgen -- \
    generate "target/debug/${library_name}" \
    --language python \
    --out-dir target/generated-python \
    --no-format
cargo run --locked --features bindgen --bin fabric-link-bindgen -- \
    generate "target/debug/${library_name}" \
    --language swift \
    --out-dir target/generated-swift \
    --no-format
cargo run --locked --features bindgen --bin fabric-link-bindgen -- \
    generate "target/debug/${library_name}" \
    --language kotlin \
    --out-dir target/generated-kotlin \
    --no-format

cp "target/debug/${library_name}" target/generated-python/
export FABRIC_LINK_FIXTURE_DIR="${crate_dir}/target/cross-language-fixture"
export FABRIC_LINK_INTEROP_FIXTURE="${repo_dir}/fabric_link/fixtures/v3-interoperability.json"
mkdir -p "${FABRIC_LINK_FIXTURE_DIR}"
PYTHONPATH=target/generated-python python3 bindings-smoke/python/smoke.py

if [[ "$(uname -s)" == "Darwin" ]]; then
    command -v swiftc >/dev/null
    swiftc \
        target/generated-swift/FabricLinkCore.swift \
        bindings-smoke/swift/main.swift \
        -Xcc -fmodule-map-file=target/generated-swift/FabricLinkCoreFFI.modulemap \
        -Xcc -Itarget/generated-swift \
        -Ltarget/debug \
        -lfabric_link_core \
        -o target/fabric-link-swift-smoke
    DYLD_LIBRARY_PATH=target/debug target/fabric-link-swift-smoke
fi

if ! java -version >/dev/null 2>&1 \
    && [[ -x /opt/homebrew/opt/openjdk@17/bin/java ]]; then
    export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
    export PATH="${JAVA_HOME}/bin:${PATH}"
fi
command -v java >/dev/null
java -version >/dev/null
"${crate_dir}/../mobile/android/gradlew" \
    --no-daemon \
    -p bindings-smoke/kotlin \
    run
