"""Installer contracts for the canonical WhatsApp credential directory."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_shell_installer_uses_canonical_whatsapp_session_path() -> None:
    installer = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")

    assert (
        'WHATSAPP_SESSION="$FABRIC_HOME/platforms/whatsapp/session/creds.json"'
        in installer
    )


def test_powershell_installer_uses_canonical_whatsapp_session_path() -> None:
    installer = (ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")

    assert (
        '$whatsappSession = "$FabricHome\\platforms\\whatsapp\\session\\creds.json"'
        in installer
    )
