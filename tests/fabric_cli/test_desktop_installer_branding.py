"""Cross-platform contracts for the Fabric desktop install handoff."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_posix_installer_uses_only_fabric_desktop_names():
    source = (REPO_ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")

    forbidden_identity = "her" + "mes"
    assert 'release/linux-unpacked/Fabric"' in source
    assert 'release/linux-arm64-unpacked/Fabric"' in source
    assert 'release/mac-arm64/Fabric.app"' in source
    assert 'release/mac/Fabric.app"' in source
    assert f"release/linux-unpacked/{forbidden_identity}" not in source.lower()
    assert 'release/linux-unpacked/fabric"' not in source
    assert "Fabric desktop app" in source


def test_windows_installer_uses_fabric_and_creates_fabric_shortcuts():
    source = (REPO_ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")

    forbidden_identity = "her" + "mes"
    assert r"release\win-unpacked\Fabric.exe" in source
    assert rf"release\win-unpacked\{forbidden_identity}.exe" not in source.lower()
    assert "Fabric.lnk" in source
    assert "$sc.Description = 'Fabric'" in source
    assert f"{forbidden_identity}.lnk" not in source.lower()
