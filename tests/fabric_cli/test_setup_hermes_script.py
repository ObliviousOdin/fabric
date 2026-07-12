from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[2]
SETUP_SCRIPT = REPO_ROOT / "scripts" / "install.sh"


def test_fabric_install_script_is_valid_shell():
    result = subprocess.run(["bash", "-n", str(SETUP_SCRIPT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_fabric_install_script_has_termux_path():
    content = SETUP_SCRIPT.read_text(encoding="utf-8")

    assert "is_termux()" in content
    assert ".[termux-all]" in content
    assert "constraints-termux.txt" in content
    assert "${PREFIX:-}" in content


def test_setup_script_advertises_only_fabric_cli_and_modern_home():
    content = SETUP_SCRIPT.read_text(encoding="utf-8")

    assert 'HERMES_BIN="$INSTALL_DIR/venv/bin/fabric"' in content
    assert 'cat > "$command_link_dir/fabric"' in content
    assert 'cat > "$command_link_dir/hermes"' not in content
    assert "$HOME/.fabric" in content
    assert "Start chatting" in content
    assert "Start chatting: hermes" not in content
