import io

import pytest

from fabric_cli import setup_links


def test_present_setup_link_preserves_exact_url_and_reports_success(monkeypatch):
    url = "https://auth.example.test:8443/device?code=A%2BB&next=%2Fsetup#confirm"
    rendered: list[str] = []
    opened: list[str] = []
    output = io.StringIO()

    monkeypatch.setattr(
        setup_links,
        "render_terminal_qr",
        lambda value, *, output=None: rendered.append(value) or True,
    )
    monkeypatch.setattr(
        setup_links.webbrowser,
        "open",
        lambda value: opened.append(value) or True,
    )

    result = setup_links.present_setup_link(
        url,
        label="Scan with your phone or open this link",
        open_browser=True,
        output=output,
    )

    assert output.getvalue() == (
        "  Scan with your phone or open this link: " + url + "\n"
    )
    assert rendered == [url]
    assert opened == [url]
    assert result == setup_links.LinkPresentation(
        qr_rendered=True,
        browser_opened=True,
    )


def test_present_setup_link_keeps_plain_url_when_optional_presentation_fails(
    monkeypatch,
):
    url = "https://auth.example.test/device"
    output = io.StringIO()
    monkeypatch.setattr(
        setup_links,
        "render_terminal_qr",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        setup_links.webbrowser,
        "open",
        lambda _url: (_ for _ in ()).throw(OSError("no browser")),
    )

    result = setup_links.present_setup_link(
        url,
        label="Open",
        open_browser=True,
        output=output,
    )

    assert url in output.getvalue()
    assert result == setup_links.LinkPresentation(
        qr_rendered=False,
        browser_opened=False,
    )


def test_render_terminal_qr_returns_false_when_dependency_is_missing(monkeypatch):
    monkeypatch.setattr(
        setup_links,
        "_load_qrcode",
        lambda: (_ for _ in ()).throw(ModuleNotFoundError("qrcode")),
    )

    assert (
        setup_links.render_terminal_qr(
            "https://auth.example.test/device",
            output=io.StringIO(),
        )
        is False
    )


def test_render_terminal_qr_outputs_compact_ascii():
    output = io.StringIO()

    assert setup_links.render_terminal_qr(
        "https://auth.openai.com/codex/device",
        output=output,
    )
    assert "█" in output.getvalue()
    assert len(output.getvalue().splitlines()) < 40


@pytest.mark.parametrize(
    "url",
    [
        "",
        " auth.example.test/device",
        "auth.example.test/device",
        "http://auth.example.test/device",
        "https:///device",
        "https://trusted.example@evil.example/device",
        "https://example.test/device\nspoofed",
    ],
)
def test_present_setup_link_rejects_untrusted_urls(monkeypatch, url):
    monkeypatch.setattr(
        setup_links.webbrowser,
        "open",
        lambda _url: pytest.fail("browser must not open for an invalid URL"),
    )

    with pytest.raises(ValueError, match="absolute HTTPS URL"):
        setup_links.present_setup_link(
            url,
            label="Open",
            open_browser=True,
            output=io.StringIO(),
        )
