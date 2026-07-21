import sys
from types import SimpleNamespace
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

from fabric_cli.mobile_pairing import (
    _render_qr,
    build_pairing_page_url,
    build_pairing_uri,
    validate_pairing_base_url,
)


def test_rendered_qr_keeps_camera_scannable_quiet_zone(monkeypatch):
    class FakeQR:
        def __init__(self, *, border):
            self.border = border

        def add_data(self, data):
            assert data == "https://agent.example.test/mobile/pair"

        def make(self, *, fit):
            assert fit is True

        def print_ascii(self, *, out, invert):
            assert invert is True
            out.write("qr")

    created = []

    def make_qr(**kwargs):
        qr = FakeQR(**kwargs)
        created.append(qr)
        return qr

    monkeypatch.setitem(sys.modules, "qrcode", SimpleNamespace(QRCode=make_qr))

    assert _render_qr("https://agent.example.test/mobile/pair") == "qr"
    assert created[0].border >= 4


def test_pairing_page_keeps_token_payload_out_of_http_request():
    pairing_uri = build_pairing_uri("https://agent.example.test", token="secret/value")

    page_url = build_pairing_page_url("https://agent.example.test/", pairing_uri)
    parsed = urlsplit(page_url)

    assert parsed.scheme == "https"
    assert parsed.netloc == "agent.example.test"
    assert parsed.path == "/mobile/pair"
    assert parsed.query == ""
    assert "secret" not in parsed.path
    assert parse_qs(parsed.fragment)["pair"] == [pairing_uri]


def test_gated_pairing_page_contains_no_credential():
    pairing_uri = build_pairing_uri("https://agent.example.test")
    page_url = build_pairing_page_url("https://agent.example.test", pairing_uri)

    decoded_fragment = unquote(urlsplit(page_url).fragment)
    assert "auth=gated" in decoded_fragment
    assert "token=" not in decoded_fragment


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://fabric.example.test/", "https://fabric.example.test"),
        ("https://fabric.example.test:9443", "https://fabric.example.test:9443"),
        ("http://127.0.0.1:9119/", "http://127.0.0.1:9119"),
        ("http://localhost:9119", "http://localhost:9119"),
        ("http://[::1]:9119", "http://[::1]:9119"),
    ],
)
def test_validate_pairing_base_url_accepts_secure_origins_and_loopback(value, expected):
    assert validate_pairing_base_url(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        "fabric.example.test",
        "ftp://fabric.example.test",
        "http://192.168.1.20:9119",
        "https://user:secret@fabric.example.test",
        "https://fabric.example.test/mobile",
        "https://fabric.example.test?",
        "https://fabric.example.test#",
        "https://fabric.example.test?token=secret",
        "https://fabric.example.test:invalid",
        "https://fabric.example.test\n.evil.test",
    ],
)
def test_validate_pairing_base_url_rejects_non_origin_or_unsafe_urls(value):
    with pytest.raises(ValueError):
        validate_pairing_base_url(value)
