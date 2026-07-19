"""Contract tests for the Windows installer's Fabric state layout."""

from pathlib import Path


INSTALLER = Path(__file__).resolve().parents[1] / "scripts" / "install.ps1"


def test_installer_creates_only_canonical_state_directories() -> None:
    content = INSTALLER.read_text(encoding="utf-8")

    assert '"$FabricHome\\platforms\\pairing"' in content
    assert '"$FabricHome\\cache\\images"' in content
    assert '"$FabricHome\\cache\\audio"' in content
    assert '"$FabricHome\\cache\\documents"' in content

    retired_paths = (
        '"$FabricHome\\' + 'pairing"',
        "image" + "_cache",
        "audio" + "_cache",
        "document" + "_cache",
    )
    assert not any(path in content for path in retired_paths)
