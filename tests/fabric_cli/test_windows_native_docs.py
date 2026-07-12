from pathlib import Path


def test_windows_native_install_path_docs_match_installer() -> None:
    doc = Path("website/docs/user-guide/windows-native.md").read_text()
    install = Path("scripts/install.ps1").read_text()

    assert "%LOCALAPPDATA%\\fabric\\fabric-agent\\venv\\Scripts" in doc
    assert "Get-Command fabric" in doc
    assert "%LOCALAPPDATA%\\fabric\\fabric-agent\\venv\\Scripts\\fabric.exe" in doc
    assert '"$env:LOCALAPPDATA\\fabric\\fabric-agent"' in install
    assert '"$InstallDir\\venv\\Scripts"' in install
