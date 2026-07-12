"""Unit tests for Discord one-shot setup helpers."""

from __future__ import annotations

import io
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

from plugins.platforms.discord.setup_wizard import (
    DEFAULT_BOT_PERMISSIONS,
    agent_name_soul_text,
    build_invite_url,
    looks_like_bot_token,
    validate_bot_token,
    write_agent_name_soul,
)


def test_looks_like_bot_token_accepts_dotted_token():
    token = "MTIz." + ("a" * 30) + "." + ("b" * 30)
    assert looks_like_bot_token(token)


def test_looks_like_bot_token_rejects_garbage():
    assert not looks_like_bot_token("")
    assert not looks_like_bot_token("not a token")
    assert not looks_like_bot_token("onlyonepart")


def test_build_invite_url_shape():
    url = build_invite_url("123456789012345678")
    assert url.startswith("https://discord.com/api/oauth2/authorize?")
    assert "client_id=123456789012345678" in url
    assert f"permissions={DEFAULT_BOT_PERMISSIONS}" in url
    assert "scope=bot%20applications.commands" in url


def test_build_invite_url_rejects_non_numeric():
    with pytest.raises(ValueError):
        build_invite_url("abc")


def test_validate_bot_token_success():
    payload = {
        "id": "999888777666555444",
        "username": "OpsBot",
        "bot": True,
        "discriminator": "0",
    }

    class _Resp:
        status = 200

        def read(self):
            return json.dumps(payload).encode()

        def getcode(self):
            return 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def opener(req, timeout=10.0):
        assert req.get_header("Authorization") == "Bot MTIz.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.bbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        return _Resp()

    token = "MTIz." + ("a" * 30) + "." + ("b" * 30)
    identity = validate_bot_token(token, opener=opener)
    assert identity.id == "999888777666555444"
    assert identity.username == "OpsBot"
    assert identity.invite_client_id == "999888777666555444"
    invite = build_invite_url(identity.invite_client_id)
    assert "client_id=999888777666555444" in invite


def test_validate_bot_token_unauthorized():
    def opener(req, timeout=10.0):
        raise HTTPError(
            url="https://discord.com/api/v10/users/@me",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=io.BytesIO(b'{"message":"401"}'),
        )

    token = "MTIz." + ("a" * 30) + "." + ("b" * 30)
    with pytest.raises(ValueError, match="unauthorized"):
        validate_bot_token(token, opener=opener)


def test_agent_name_soul_and_write(tmp_path: Path):
    text = agent_name_soul_text("Warehouse Ops")
    assert "Warehouse Ops" in text
    assert "Fabric" in text

    path = write_agent_name_soul(tmp_path, "Warehouse Ops")
    assert path is not None
    assert path.read_text(encoding="utf-8").startswith("# Warehouse Ops")

    # Second write without force leaves existing SOUL alone
    assert write_agent_name_soul(tmp_path, "Other") is None
    assert "Warehouse Ops" in path.read_text(encoding="utf-8")

    # force overwrites
    path2 = write_agent_name_soul(tmp_path, "Other", force=True)
    assert path2 is not None
    assert "Other" in path2.read_text(encoding="utf-8")
