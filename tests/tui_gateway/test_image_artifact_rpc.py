"""Live-session generated-image artifact contract."""

from __future__ import annotations

import base64
import json


def _install_session(monkeypatch, server, home, session_id="image-session"):
    monkeypatch.setattr(server, "get_fabric_home", lambda: home)
    monkeypatch.setattr(server, "_emit", lambda *_args, **_kwargs: None)
    session = {
        "edit_snapshots": {},
        "tool_progress_mode": "all",
        "tool_started_at": {},
    }
    monkeypatch.setitem(server._sessions, session_id, session)
    return session_id, session


def test_generated_image_is_registered_and_fetched_by_opaque_tool_id(monkeypatch, tmp_path):
    from tui_gateway import server

    image_dir = tmp_path / "cache" / "images"
    image_dir.mkdir(parents=True)
    image_path = image_dir / "generated.png"
    image_bytes = b"\x89PNG\r\n\x1a\nfixture"
    image_path.write_bytes(image_bytes)
    session_id, session = _install_session(monkeypatch, server, tmp_path)

    server._on_tool_complete(
        session_id,
        "image-call-1",
        "image_generate",
        {},
        json.dumps({"success": True, "image": str(image_path)}),
    )

    # The private host path is retained only in the in-memory session registry.
    assert session["generated_image_artifacts"]["image-call-1"]["path"] == str(image_path)
    listing = server._methods["artifact.list"](1, {"session_id": session_id})["result"]
    assert listing == {
        "session_id": session_id,
        "artifacts": [{
            "artifact_id": "image-call-1",
            "mime_type": "image/png",
            "byte_size": len(image_bytes),
        }],
    }
    assert str(image_path) not in repr(listing)

    fetched = server._methods["artifact.fetch"](
        2,
        {"session_id": session_id, "artifact_id": "image-call-1"},
    )["result"]
    assert fetched["artifact_id"] == "image-call-1"
    assert fetched["mime_type"] == "image/png"
    assert base64.b64decode(fetched["data_base64"]) == image_bytes
    assert str(image_path) not in repr(fetched)


def test_generated_image_fetch_rejects_unregistered_paths_and_symlinks(monkeypatch, tmp_path):
    from tui_gateway import server

    image_dir = tmp_path / "cache" / "images"
    image_dir.mkdir(parents=True)
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside")
    _, session = _install_session(monkeypatch, server, tmp_path)

    # An image result outside Fabric's generated-image cache cannot register.
    server._register_generated_image_artifact(
        session,
        "outside",
        "image_generate",
        json.dumps({"success": True, "image": str(outside)}),
    )
    assert "generated_image_artifacts" not in session

    linked = image_dir / "linked.png"
    linked.symlink_to(outside)
    server._register_generated_image_artifact(
        session,
        "linked",
        "image_generate",
        json.dumps({"success": True, "image": str(linked)}),
    )
    assert "generated_image_artifacts" not in session

    response = server._methods["artifact.fetch"](
        3,
        {"session_id": "image-session", "artifact_id": "../../outside"},
    )
    assert response["error"]["code"] == 4008
    assert str(outside) not in repr(response)


def test_generated_image_fetch_rejects_a_symlink_swap_after_validation(monkeypatch, tmp_path):
    from tui_gateway import server

    image_dir = tmp_path / "cache" / "images"
    image_dir.mkdir(parents=True)
    image_path = image_dir / "generated.png"
    image_path.write_bytes(b"safe-image")
    outside = tmp_path / "secret.txt"
    outside.write_bytes(b"secret-outside-cache")
    session_id, _ = _install_session(monkeypatch, server, tmp_path)
    server._on_tool_complete(
        session_id,
        "image-call-1",
        "image_generate",
        {},
        json.dumps({"success": True, "image": str(image_path)}),
    )

    original = server._registered_generated_image

    def swap_after_validation(path_value, session):
        artifact = original(path_value, session)
        image_path.unlink()
        image_path.symlink_to(outside)
        return artifact

    monkeypatch.setattr(server, "_registered_generated_image", swap_after_validation)
    response = server._methods["artifact.fetch"](
        4,
        {"session_id": session_id, "artifact_id": "image-call-1"},
    )

    assert response["error"]["code"] == 4008
    assert "secret-outside-cache" not in repr(response)


def test_history_projection_rehydrates_generated_image_artifact(monkeypatch, tmp_path):
    from tui_gateway import server

    image_dir = tmp_path / "cache" / "images"
    image_dir.mkdir(parents=True)
    image_path = image_dir / "history.png"
    image_path.write_bytes(b"history-image")
    monkeypatch.setattr(server, "get_fabric_home", lambda: tmp_path)
    session = {}
    messages = server._history_to_messages(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "history-image-call",
                    "function": {"name": "image_generate", "arguments": "{}"},
                }],
            },
            {
                "role": "tool",
                "tool_call_id": "history-image-call",
                "content": json.dumps({"success": True, "image": str(image_path)}),
            },
        ],
        artifact_session=session,
    )

    assert messages == [{
        "role": "tool",
        "name": "image_generate",
        "context": "Generating image",
        "image_artifact_id": "history-image-call",
    }]
    assert "history-image-call" in session["generated_image_artifacts"]
