# Fabric Link Core

This crate is the Phase 0 feasibility boundary for Fabric Link cryptography.
It pins one OpenMLS implementation for machine, native-controller, and browser
build experiments and generates Python, Swift, and Kotlin bindings from one
Rust interface.

The public interface exposes a single versioned opaque state blob rather than
individually addressable MLS secrets or ratchet internals. Callers must protect
that blob with the platform keystore boundary. Real binding-surface restart,
pair-group isolation, malformed-input, and removal behavior are exercised in
`tests/binding_state_machine.rs`.

## Verify native behavior

```bash
cargo test --locked
cargo clippy --locked --all-targets -- -D warnings
```

## Generate native bindings

Build the library, then invoke the pinned in-tree UniFFI CLI:

```bash
cargo build --locked --features bindgen
cargo run --locked --features bindgen --bin fabric-link-bindgen -- \
  generate target/debug/libfabric_link_core.dylib \
  --language python --out-dir target/generated-python
cargo run --locked --features bindgen --bin fabric-link-bindgen -- \
  generate target/debug/libfabric_link_core.dylib \
  --language swift --out-dir target/generated-swift
cargo run --locked --features bindgen --bin fabric-link-bindgen -- \
  generate target/debug/libfabric_link_core.dylib \
  --language kotlin --out-dir target/generated-kotlin
```

Use `.so` on Linux and `.dll` on Windows. Generated output is a build artifact
and is not committed.

Run the executable Python, Swift (on macOS), and Kotlin binding fixtures with:

```bash
bash bindings-smoke/verify.sh
```

Each fixture creates a controller KeyPackage in its generated language binding,
joins a host pair group, restores opaque state between every call, exchanges
encrypted application records in both directions, and applies controller
removal.

## Verify the browser compilation boundary

```bash
rustup target add wasm32-unknown-unknown
cargo build --locked --target wasm32-unknown-unknown
cargo install wasm-bindgen-cli --version 0.2.126 --locked
wasm-bindgen \
  --target web \
  --out-dir target/browser \
  --out-name fabric_link_core \
  target/wasm32-unknown-unknown/debug/fabric_link_core.wasm
```

Compiling is only the first browser gate. The browser harness creates a real
controller identity and MLS KeyPackage in WASM, joins a Welcome, exchanges MLS
application records in both directions, encrypts its evolved opaque protocol state with a
non-extractable wrapping key, restores it through IndexedDB, decrypts the next
record, and proves clear-site-data loss of persistent access under a strict CSP
with no third-party scripts.

Run that storage boundary in an installed Chrome/Chromium:

```bash
node browser-harness/run.mjs
```

Both native-binding and browser harnesses consume
`../../fabric_link/fixtures/v3-interoperability.json`. Regenerate this
deterministic v3 known-answer corpus with
`scripts/generate_fabric_link_interop.py`; CI should use `--check` to reject
protocol drift. The corpus contains fixed test-only key material and covers
canonical CBOR hashes, directional enrollment HKDF/AAD values, and AES-GCM
request/response vectors.

The runner serves only the allow-listed harness/WASM files on loopback with a
strict response-header CSP and launches a clean temporary browser profile.
`'wasm-unsafe-eval'` is the only script-policy relaxation; scripts and network
connections remain same-origin only.

## Build the Python native companion wheel

The universal `fabric-agent` wheel does not contain native cryptography. Build
the platform-specific `fabric-link-core` companion from its nested project:

```bash
cd python
uv build --wheel --out-dir dist
bash verify-wheel.sh
```

`verify-wheel.sh` installs the freshly built wheel into an isolated virtual
environment, imports the generated UniFFI module, verifies the exact protocol
and ciphersuite, and proves that its native library and required notices are
installed beside it. The companion never publishes an sdist, so unsupported
platforms cannot silently compile a different cryptographic build.
