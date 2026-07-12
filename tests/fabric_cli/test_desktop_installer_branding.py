"""Cross-platform contracts for the Fabric desktop install handoff."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_posix_installer_prefers_fabric_and_keeps_legacy_fallbacks():
    source = (REPO_ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")

    assert source.index('release/linux-unpacked/Fabric"') < source.index(
        'release/linux-unpacked/Hermes"'
    )
    assert source.index('release/mac-arm64/Fabric.app"') < source.index(
        'release/mac-arm64/Hermes.app"'
    )
    assert "Fabric desktop app" in source


def test_windows_installer_prefers_fabric_and_creates_fabric_shortcuts():
    source = (REPO_ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")

    assert source.index(r"release\win-unpacked\Fabric.exe") < source.index(
        r"release\win-unpacked\Hermes.exe"
    )
    assert "Fabric.lnk" in source
    assert "$sc.Description = 'Fabric'" in source
    assert "Hermes.lnk" not in source
