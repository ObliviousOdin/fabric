"""Banner/status brand resolution tests."""

from __future__ import annotations


def test_banner_version_label_is_fabric_when_branded(monkeypatch):
    monkeypatch.setenv("FABRIC_BRAND", "1")
    from fabric_cli.banner import format_banner_version_label, VERSION, RELEASE_DATE

    label = format_banner_version_label()
    assert label.startswith(f"Fabric v{VERSION}")
    assert "Hermes" not in label
    assert RELEASE_DATE in label


def test_banner_version_label_stays_fabric_when_legacy_brand_toggle_is_off(monkeypatch):
    monkeypatch.setenv("FABRIC_BRAND", "0")
    from fabric_cli.banner import format_banner_version_label, VERSION

    label = format_banner_version_label()
    assert label.startswith(f"Fabric v{VERSION}")
    assert "Hermes" not in label


def test_product_and_vendor_labels(monkeypatch):
    monkeypatch.setenv("FABRIC_BRAND", "1")
    from fabric_cli.fabric_brand import product_label, vendor_label

    assert product_label() == "Fabric"
    assert vendor_label() == "Fabric"
