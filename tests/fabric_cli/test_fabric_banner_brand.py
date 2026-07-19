"""Banner/status brand resolution tests."""

from __future__ import annotations


def test_banner_version_label_is_fabric():
    from fabric_cli.banner import format_banner_version_label, VERSION, RELEASE_DATE

    label = format_banner_version_label()
    assert label.startswith(f"Fabric v{VERSION}")
    assert RELEASE_DATE in label


def test_product_and_vendor_labels():
    from fabric_cli.fabric_brand import product_label, vendor_label

    assert product_label() == "Fabric"
    assert vendor_label() == "Fabric"
