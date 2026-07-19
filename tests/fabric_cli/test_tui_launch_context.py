import json
import os

import pytest

from fabric_cli.tui_launch_context import (
    TuiLaunchContext,
    consume_tui_launch_context,
    write_tui_launch_context,
)


def test_launch_context_round_trip_is_owner_only_and_consumed():
    expected = TuiLaunchContext(
        cwd="/workspace",
        model="nous/test-model",
        provider="nous",
        toolsets=("web", "terminal"),
        skills=("review",),
        resume="session-1",
        gateway_url="ws://127.0.0.1/api/ws?token=secret",
    )

    path = write_tui_launch_context(expected)
    try:
        if os.name != "nt":
            assert path.stat().st_mode & 0o777 == 0o600

        assert consume_tui_launch_context(path) == expected
        assert not path.exists()
    finally:
        path.unlink(missing_ok=True)


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits only")
def test_launch_context_rejects_non_private_descriptor():
    path = write_tui_launch_context(TuiLaunchContext(model="private/model"))
    path.chmod(0o644)

    with pytest.raises(PermissionError, match="owner-only"):
        consume_tui_launch_context(path)

    assert not path.exists()


def test_launch_context_rejects_malformed_field_types():
    path = write_tui_launch_context(TuiLaunchContext())
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["gateway_url"] = ["not", "a", "string"]
    path.write_text(json.dumps(payload), encoding="utf-8")
    if os.name != "nt":
        path.chmod(0o600)

    with pytest.raises(ValueError, match="gateway_url"):
        consume_tui_launch_context(path)

    assert not path.exists()
