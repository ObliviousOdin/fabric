from pathlib import Path

CHAT_SIDEBAR = Path(__file__).resolve().parent.parent / "web/src/components/ChatSidebar.tsx"


def test_chat_sidebar_observes_real_pty_without_creating_duplicate_session():
    """The supporting rail must not initialize a second agent/session.

    Creating a throwaway gateway session duplicated tool/MCP/memory startup and
    could report status for a different agent than the embedded TUI.  The rail
    now passively observes the PTY publisher's channel instead.
    """
    source = CHAT_SIDEBAR.read_text(encoding="utf-8")
    assert '"session.create"' not in source
    assert 'buildWsUrl("/api/events", { channel })' in source
    assert "new WebSocket(url)" in source


def test_chat_sidebar_supporting_model_info_remains_profile_scoped():
    """Read-only model metadata should still follow the Chat profile."""
    source = CHAT_SIDEBAR.read_text(encoding="utf-8")
    assert ".getModelInfo(profile)" in source
    assert "[profile]" in source
