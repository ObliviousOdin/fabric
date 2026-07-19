"""Tests for CLI prefill config schema handling."""

from __future__ import annotations

import cli


def test_resolve_prefill_messages_file_uses_top_level_key():
    assert cli._resolve_prefill_messages_file(
        {
            "prefill_messages_file": "top.json",
            "agent": {"prefill_messages_file": "previous.json"},
        }
    ) == "top.json"


def test_resolve_prefill_messages_file_reads_previous_agent_schema():
    assert cli._resolve_prefill_messages_file(
        {"agent": {"prefill_messages_file": "previous.json"}}
    ) == "previous.json"


def test_resolve_prefill_messages_file_defaults_empty():
    assert cli._resolve_prefill_messages_file({}) == ""
