from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from cli import FabricCLI, _rich_text_from_ansi
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



    def test_narrow_terminals_compact_voice_prompt_fragments(self):
        cli = _make_cli_stub()
        cli._voice_mode = True

        with patch.object(FabricCLI, "_get_tui_terminal_width", return_value=50):
            assert cli._get_tui_prompt_fragments() == [("class:voice-prompt", "🎤 ")]

    def test_narrow_terminals_compact_voice_recording_prompt_fragments(self):
        cli = _make_cli_stub()
        cli._voice_recording = True
        cli._voice_recorder = SimpleNamespace(current_rms=3000)

        with patch.object(FabricCLI, "_get_tui_terminal_width", return_value=50):
            frags = cli._get_tui_prompt_fragments()

        assert frags[0][0] == "class:voice-recording"
        assert frags[0][1].startswith("●")
        assert "❯" not in frags[0][1]

    def test_icon_only_skin_symbol_still_visible_in_special_states(self):
        cli = _make_cli_stub()
        cli._secret_state = {"response_queue": object()}

        with patch("fabric_cli.skin_engine.get_active_prompt_symbol", return_value="⚔ "):
            assert cli._get_tui_prompt_fragments() == [("class:sudo-prompt", "🔑 ⚔ ")]





class TestAnsiRichTextHelper:
    def test_preserves_literal_brackets(self):
        text = _rich_text_from_ansi("[notatag] literal")
        assert text.plain == "[notatag] literal"

    def test_strips_ansi_but_keeps_plain_text(self):
        text = _rich_text_from_ansi("\x1b[31mred\x1b[0m")
        assert text.plain == "red"
