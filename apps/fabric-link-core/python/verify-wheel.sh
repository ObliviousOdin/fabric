#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd -- "${script_dir}/../../.." && pwd)"
if [[ -n "${PYTHON:-}" ]]; then
    python_bin="${PYTHON}"
elif [[ -x "${repository_root}/.venv/bin/python" ]]; then
    python_bin="${repository_root}/.venv/bin/python"
else
    python_bin="python3"
fi
if [[ -n "${FABRIC_LINK_CORE_WHEEL_OUT:-}" ]]; then
    wheel_dir="${FABRIC_LINK_CORE_WHEEL_OUT}"
    mkdir -p -- "${wheel_dir}"
else
    wheel_dir="$(mktemp -d "${TMPDIR:-/tmp}/fabric-link-core-wheel.XXXXXX")"
fi
sdist_dir="$(mktemp -d "${TMPDIR:-/tmp}/fabric-link-core-sdist.XXXXXX")"
venv_dir="$(mktemp -d "${TMPDIR:-/tmp}/fabric-link-core-venv.XXXXXX")"

cd "${script_dir}"
command -v uv >/dev/null || {
    echo "uv is required to build the standards-based Fabric Link wheel" >&2
    exit 1
}
uv build --wheel --out-dir "${wheel_dir}"
if uv build --sdist --out-dir "${sdist_dir}" >/dev/null 2>&1; then
    echo "fabric-link-core must not produce a source distribution" >&2
    exit 1
fi

shopt -s nullglob
wheels=("${wheel_dir}"/*.whl)
if [[ ${#wheels[@]} -ne 1 ]]; then
    echo "Expected one Fabric Link core wheel, found ${#wheels[@]}" >&2
    exit 1
fi

"${python_bin}" -m venv "${venv_dir}"
venv_python="${venv_dir}/bin/python"
if [[ ! -x "${venv_python}" ]]; then
    venv_python="${venv_dir}/Scripts/python.exe"
fi
"${venv_python}" -m pip install --disable-pip-version-check --no-deps "${wheels[0]}"

case "$(uname -s)" in
    Darwin)
        library_name="libfabric_link_core.dylib"
        ;;
    Linux)
        library_name="libfabric_link_core.so"
        ;;
    MINGW*|MSYS*|CYGWIN*)
        library_name="fabric_link_core.dll"
        ;;
    *)
        echo "Unsupported native wheel verification host: $(uname -s)" >&2
        exit 1
        ;;
esac

FABRIC_LINK_CORE_LIBRARY="${library_name}" "${venv_python}" - <<'PY'
import os
from pathlib import Path

import fabric_link_core as core

assert core.fabric_link_protocol_version() == 3
assert core.fabric_link_ciphersuite() == "MLS_128_DHKEMX25519_AES128GCM_SHA256_Ed25519"
root = Path(core.__file__).parent
assert (root / os.environ["FABRIC_LINK_CORE_LIBRARY"]).is_file()
assert (root / "fabric_link_core_licenses" / "LICENSE").is_file()
assert (root / "fabric_link_core_licenses" / "NOTICE").is_file()
print(f"PASS installed Fabric Link native wheel: {core.__file__}")
PY
