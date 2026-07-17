"""Desktop distribution identity stays bound to the Fabric brand manifest."""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DESKTOP_ROOT = ROOT / "apps" / "desktop"
BRAND_PATH = DESKTOP_ROOT / "branding" / "fabric.json"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "desktop-packaging.yml"

CUSTOMER_GUIDES = (
    DESKTOP_ROOT / "README.md",
    ROOT / "website" / "docs" / "index.mdx",
    ROOT / "website" / "docs" / "getting-started" / "installation.md",
    ROOT / "website" / "docs" / "getting-started" / "platform-support.md",
    ROOT / "website" / "docs" / "getting-started" / "updating.md",
    ROOT / "website" / "docs" / "user-guide" / "desktop.md",
    ROOT / "website" / "docs" / "user-guide" / "windows-native.md",
    ROOT / "website" / "docs" / "user-guide" / "windows-wsl-quickstart.md",
)

REQUIRED_PUBLIC_ROUTE = "https://github.com/ObliviousOdin/fabric"
FORBIDDEN_CUSTOMER_ROUTES = (
    "github.com/NousResearch/fabric-agent",
    "raw.githubusercontent.com/NousResearch/fabric-agent",
)


def _brand() -> dict[str, object]:
    return json.loads(BRAND_PATH.read_text(encoding="utf-8"))


def test_fabric_manifest_owns_native_desktop_identity_and_assets() -> None:
    brand = _brand()

    assert brand["schemaVersion"] == 1
    assert brand["productName"] == "Fabric"
    assert brand["desktopName"] == "Fabric"
    assert brand["vendorName"] == "Fabric"
    assert brand["appId"] == "io.github.obliviousodin.fabric"
    assert brand["executableName"] == "Fabric"
    assert brand["artifactName"] == "Fabric"
    assert brand["releaseNotesUrl"] == (
        "https://github.com/ObliviousOdin/fabric/releases"
    )

    protocols = brand["protocols"]
    assert isinstance(protocols, list)
    assert [item["scheme"] for item in protocols if item.get("primary")] == ["fabric"]
    assert "hermes" in [item["scheme"] for item in protocols if item.get("legacy")]

    assets = brand["assets"]
    assert isinstance(assets, dict)
    for field in ("png", "ico", "icns", "publicPng"):
        relative = assets[field]
        path = DESKTOP_ROOT / relative
        assert path.is_file(), f"missing desktop brand asset: {relative}"
        assert path.resolve().is_relative_to(DESKTOP_ROOT.resolve())
    base = DESKTOP_ROOT / assets["base"]
    assert any(
        base.with_suffix(suffix).is_file() for suffix in (".png", ".ico", ".icns")
    )


def test_customer_desktop_guides_use_fabric_routes_and_fabric_commands() -> None:
    command_pattern = re.compile(r"(?m)^[ \t]*fabric(?:[ \t]|$)", re.IGNORECASE)

    for path in CUSTOMER_GUIDES:
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(ROOT)
        assert "Fabric" in text, f"missing Fabric identity: {relative}"
        assert re.search(
            r"(?m)(?:`fabric(?:[ \t]|`)|^[ \t]*fabric(?:[ \t]|$))", text
        ), f"missing Fabric CLI guidance: {relative}"
        assert command_pattern.search(text) is None, (
            f"advertises the upstream CLI in a command block: {relative}"
        )
        assert REQUIRED_PUBLIC_ROUTE in text, f"missing public Fabric route: {relative}"
        for route in FORBIDDEN_CUSTOMER_ROUTES:
            assert route not in text, f"upstream customer route in {relative}: {route}"
        assert "com.nousresearch.fabric" not in text


def test_desktop_docs_do_not_claim_unsigned_ci_packages_are_releases() -> None:
    brand = _brand()
    release_url = brand["releaseNotesUrl"]
    artifact_stem = brand["artifactName"]

    readme = (DESKTOP_ROOT / "README.md").read_text(encoding="utf-8")
    install = (ROOT / "website/docs/getting-started/installation.md").read_text(
        encoding="utf-8"
    )
    support = (ROOT / "website/docs/getting-started/platform-support.md").read_text(
        encoding="utf-8"
    )

    for text in (readme, install, support):
        assert release_url in text
        assert artifact_stem in text
        assert "unsigned" in text.lower()
        assert "checksum" in text.lower()

    assert "APPLE_API_KEY" in readme
    assert "Authenticode" in readme
    assert "notar" in readme.lower()


def test_packaging_workflow_derives_names_and_checks_all_native_formats() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "loadDesktopBrand" in workflow
    assert "createElectronBuilderConfig" in workflow
    assert "brand.artifactName" in workflow
    assert "config.artifactName" in workflow
    assert "--publish never" in workflow
    assert re.search(r"CSC_IDENTITY_AUTO_DISCOVERY:\s+[\"']false[\"']", workflow)

    expected_lanes = {
        "macos-15": ("mac", "arm64", {"dmg": "arm64", "zip": "arm64"}),
        "windows-2025": ("win", "x64", {"exe": "x64", "msi": "x64"}),
        "ubuntu-24.04": (
            "linux",
            "x64",
            {"AppImage": "x86_64", "deb": "amd64", "rpm": "x86_64"},
        ),
    }
    for runner, (platform, arch, artifact_arches) in expected_lanes.items():
        assert f"runner: {runner}" in workflow
        assert f"platform: {platform}" in workflow
        assert f"arch: {arch}" in workflow
        expected_mapping = json.dumps(artifact_arches, separators=(",", ":"))
        assert f"artifact_arches: '{expected_mapping}'" in workflow

    assert "legacy Fabric artifacts" in workflow
    assert "SHA256SUMS" in workflow
    assert "apps/desktop/verified-artifacts/*" in workflow
    assert "apps/desktop/release/${{" not in workflow
    assert "-unsigned" in workflow
    assert (
        "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in workflow
    )


def test_apache_license_and_upstream_mit_attribution_are_preserved() -> None:
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    upstream_license_text = (ROOT / "LICENSES/MIT-hermes-agent.txt").read_text(
        encoding="utf-8"
    )
    notice_text = (ROOT / "NOTICE").read_text(encoding="utf-8")
    desktop_readme = (DESKTOP_ROOT / "README.md").read_text(encoding="utf-8")

    assert "Apache License" in license_text
    assert "MIT License" in upstream_license_text
    assert "Copyright (c) 2025 Nous Research" in upstream_license_text
    assert "Fabric Agent by Nous Research" in notice_text
    assert "Apache License 2.0" in desktop_readme
    assert "upstream MIT notice" in desktop_readme
    assert "[`NOTICE`](../../NOTICE)" in desktop_readme
