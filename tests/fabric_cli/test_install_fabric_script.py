"""Contract tests for the public Fabric installer."""

from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALLER = REPO_ROOT / "scripts" / "install.sh"


def test_install_fabric_script_is_valid_shell():
    result = subprocess.run(["bash", "-n", str(INSTALLER)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_installer_help_is_fabric_only():
    result = subprocess.run(["bash", str(INSTALLER), "--help"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "Fabric Installer" in result.stdout
    assert "fabric setup" not in result.stderr
    forbidden_identity = "her" + "mes"
    assert f"{forbidden_identity} Installer" not in result.stdout


def test_installer_uses_one_home_and_one_launcher():
    content = INSTALLER.read_text(encoding="utf-8")

    assert 'FABRIC_HOME="${FABRIC_HOME:-$HOME/.fabric}"' in content
    assert 'rm -f "$command_link_dir/fabric"' in content
    assert 'cat > "$command_link_dir/fabric" <<EOF' in content
    forbidden_identity = "her" + "mes"
    assert f'"$command_link_dir/{forbidden_identity}"' not in content.lower()


def test_installer_creates_only_canonical_state_directories():
    content = INSTALLER.read_text(encoding="utf-8")

    assert '"$FABRIC_HOME"/cache/{images,audio,documents}' in content
    assert '"$FABRIC_HOME/platforms/pairing"' in content
    retired_paths = (
        '"$FABRIC_HOME/' + 'pairing"',
        "image" + "_cache",
        "audio" + "_cache",
    )
    assert not any(path in content for path in retired_paths)
