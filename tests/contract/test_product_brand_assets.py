"""Cross-surface contract for generated Fabric brand asset propagation."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BRAND = ROOT / "apps" / "design-system" / "dist" / "brand"

COPIES = {
    # Web app shell and installable PWA.
    "web/public/favicon.ico": "fabric-favicon.ico",
    "web/public/icons/apple-touch-icon.png": "fabric-app-icon-180.png",
    "web/public/icons/fabric-192.png": "fabric-app-icon-192.png",
    "web/public/icons/fabric-512.png": "fabric-app-icon-512.png",
    "web/public/icons/fabric-maskable-512.png": "fabric-maskable-512.png",
    "web/public/brand/fabric-mark.svg": "fabric-mark.svg",
    "web/public/brand/fabric-mark-mono.svg": "fabric-mark-mono.svg",
    "web/public/brand/fabric-wordmark.svg": "fabric-wordmark.svg",
    "web/public/brand/fabric-wordmark-on-dark.svg": "fabric-wordmark-on-dark.svg",
    # Documentation website.
    "website/static/img/favicon.ico": "fabric-favicon.ico",
    "website/static/img/favicon-16x16.png": "fabric-mark-16.png",
    "website/static/img/favicon-32x32.png": "fabric-mark-32.png",
    "website/static/img/favicon.svg": "fabric-mark.svg",
    "website/static/img/fabric-mark.svg": "fabric-mark.svg",
    "website/static/img/logo.png": "fabric-mark-1024.png",
    "website/static/img/apple-touch-icon.png": "fabric-app-icon-180.png",
    # Electron desktop.
    "apps/desktop/assets/icon.icns": "fabric-app-icon.icns",
    "apps/desktop/assets/icon.ico": "fabric-favicon.ico",
    "apps/desktop/assets/icon.png": "fabric-app-icon-1024.png",
    "apps/desktop/public/apple-touch-icon.png": "fabric-app-icon-512.png",
    # Tauri bootstrap installer.
    "apps/bootstrap-installer/public/fabric-mark.png": "fabric-mark-512.png",
    "apps/bootstrap-installer/src-tauri/icons/32x32.png": "fabric-mark-32.png",
    "apps/bootstrap-installer/src-tauri/icons/128x128.png": "fabric-mark-128.png",
    "apps/bootstrap-installer/src-tauri/icons/512x512.png": "fabric-mark-512.png",
    "apps/bootstrap-installer/src-tauri/icons/icon.icns": "fabric-app-icon.icns",
    "apps/bootstrap-installer/src-tauri/icons/icon.ico": "fabric-favicon.ico",
    # ACP clients tint the monochrome compact mark themselves.
    "acp_registry/icon.svg": "fabric-mark-mono.svg",
}


@pytest.mark.parametrize(("destination", "source"), COPIES.items())
def test_product_asset_is_byte_identical_to_generated_contract(
    destination: str,
    source: str,
) -> None:
    assert (ROOT / destination).read_bytes() == (BRAND / source).read_bytes()


def _png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    return struct.unpack(">II", data[16:24])


def test_pwa_preserves_install_contract_and_adds_safe_zone_maskable_icon() -> None:
    manifest = json.loads((ROOT / "web/public/manifest.webmanifest").read_text())

    assert manifest["id"] == "./"
    assert manifest["start_url"] == "./chat"
    assert manifest["scope"] == "./"
    assert manifest["display"] == "standalone"
    maskable = [
        icon for icon in manifest["icons"] if "maskable" in icon["purpose"].split()
    ]
    assert maskable == [
        {
            "src": "icons/fabric-maskable-512.png",
            "sizes": "512x512",
            "type": "image/png",
            "purpose": "any maskable",
        }
    ]
    assert _png_dimensions(ROOT / "web/public/icons/fabric-maskable-512.png") == (
        512,
        512,
    )


def test_website_and_bootstrap_reference_only_propagated_brand_assets() -> None:
    website_config = (ROOT / "website/docusaurus.config.ts").read_text()
    assert 'favicon: "img/favicon.ico"' in website_config
    assert 'src: "img/fabric-mark.svg"' in website_config
    assert 'href: "/fabric/img/apple-touch-icon.png"' in website_config

    tauri = json.loads(
        (ROOT / "apps/bootstrap-installer/src-tauri/tauri.conf.json").read_text()
    )
    assert tauri["bundle"]["icon"] == [
        "icons/32x32.png",
        "icons/128x128.png",
        "icons/512x512.png",
        "icons/icon.icns",
        "icons/icon.ico",
    ]


def test_bracket_geometry_is_reserved_for_full_wordmarks() -> None:
    for name in ("fabric-wordmark.svg", "fabric-wordmark-on-dark.svg"):
        assert b'data-fabric-bracket="true"' in (BRAND / name).read_bytes()

    for name in ("fabric-mark.svg", "fabric-mark-mono.svg"):
        assert b"fabric-bracket" not in (BRAND / name).read_bytes()
