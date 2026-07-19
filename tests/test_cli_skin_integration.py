from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from rich.console import Console

from cli import FabricCLI, _build_compact_banner, _rich_text_from_ansi
from fabric_cli.banner import build_welcome_banner
from fabric_cli.skin_engine import get_active_skin, set_active_skin


def _make_cli_stub():
    cli = FabricCLI.__new__(FabricCLI)
    cli._sudo_state = None
    cli._secret_state = None
    cli._approval_state = None
    cli._clarify_state = None
    cli._clarify_freetext = False
    cli._command_running = False
    cli._agent_running = False
    cli._voice_recording = False
    cli._voice_processing = False
    cli._voice_mode = False
    cli._command_spinner_frame = lambda: "⟳"
    cli._tui_style_base = {
        "prompt": "#fff",
        "input-area": "#fff",
        "input-rule": "#aaa",
        "prompt-working": "#888 italic",
    }
    cli._app = SimpleNamespace(style=None)
    cli._invalidate = MagicMock()
    return cli


class TestCliSkinPromptIntegration:
    def test_default_prompt_fragments_use_default_symbol(self):
        cli = _make_cli_stub()

        set_active_skin("default")
        assert cli._get_tui_prompt_fragments() == [("class:prompt", "❯ ")]



    def test_icon_only_skin_symbol_still_visible_in_special_states(self):
        cli = _make_cli_stub()
        cli._secret_state = {"response_queue": object()}

        with patch("fabric_cli.skin_engine.get_active_prompt_symbol", return_value="⚔ "):
            assert cli._get_tui_prompt_fragments() == [("class:sudo-prompt", "🔑 ⚔ ")]





class TestCompactBannerSkinIntegration:
    def test_default_compact_banner_uses_fabric_branding(self):
        set_active_skin("default")

        with patch("cli.shutil.get_terminal_size", return_value=SimpleNamespace(columns=90)), \
             patch.dict(_build_compact_banner.__globals__, {"format_banner_version_label": lambda: "Fabric v0.1.0 (test)"}):
            banner = _build_compact_banner()

        assert "Fabric" in banner
        assert "FABRIC" not in banner
        assert "NOUS" not in banner



    def test_compact_banner_shows_version_label(self):
        set_active_skin("default")

        with patch("cli.shutil.get_terminal_size", return_value=SimpleNamespace(columns=90)), \
             patch.dict(_build_compact_banner.__globals__, {"format_banner_version_label": lambda: "Fabric v1.0 (test) · build abc12345"}):
            banner = _build_compact_banner()

        assert "build abc12345" in banner


class TestDefaultFabricBannerIntegration:
    def test_default_skin_supplies_canonical_fabric_art(self):
        skin = set_active_skin("default")

        assert skin.get_branding("agent_name") == "Fabric"
        assert skin.get_branding("response_label") == " Fabric "
        assert "Fabric" in skin.get_branding("welcome")
        assert "├────╮  fabric" in skin.banner_logo
        assert "╰──────────────╮" in skin.banner_logo
        assert "│╱────╯•" in skin.banner_hero
        assert "█" not in skin.banner_logo
        assert "NOUS" not in skin.banner_logo.upper()

    def test_theme_only_skins_inherit_fabric_identity_and_art(self):
        default = set_active_skin("default")
        mono = set_active_skin("mono")
        try:
            assert mono.get_branding("agent_name") == "Fabric"
            assert mono.banner_logo == default.banner_logo
            assert mono.banner_hero == default.banner_hero
        finally:
            set_active_skin("default")

    def test_full_default_banner_renders_fabric_mark_and_fabric_logo(self):
        set_active_skin("default")
        console = Console(record=True, width=120, force_terminal=False)

        with patch(
            "fabric_cli.banner.shutil.get_terminal_size",
            return_value=SimpleNamespace(columns=120),
        ), patch(
            "model_tools.check_tool_availability", return_value=([], [])
        ), patch(
            "fabric_cli.banner.get_available_skills", return_value={}
        ), patch(
            "fabric_cli.banner.get_update_result", return_value=0
        ), patch(
            "fabric_cli.banner.get_latest_release_tag", return_value=None
        ), patch(
            "tools.mcp_tool.get_mcp_status", return_value=[]
        ):
            build_welcome_banner(
                console,
                model="gpt-5",
                cwd="/tmp/project",
                tools=[],
                enabled_toolsets=["skills"],
                session_id="demo",
            )

        rendered = console.export_text()
        assert "├────╮  fabric" in rendered
        assert "╰──────────────╮" in rendered
        assert "█" not in rendered
        assert "Fabric v" in rendered
        assert "Fabric" in rendered
        assert "NOUS" not in rendered.upper()


class TestAnsiRichTextHelper:
    def test_preserves_literal_brackets(self):
        text = _rich_text_from_ansi("[notatag] literal")
        assert text.plain == "[notatag] literal"

    def test_strips_ansi_but_keeps_plain_text(self):
        text = _rich_text_from_ansi("\x1b[31mred\x1b[0m")
        assert text.plain == "red"
