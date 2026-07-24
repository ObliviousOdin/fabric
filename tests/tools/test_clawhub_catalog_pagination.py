"""Regression coverage for resilient ClawHub catalog pagination."""

import json

import httpx

import tools.skills_hub as hub


def _response(payload: dict, status_code: int = 200) -> hub._BoundedHttpResponse:
    return hub._BoundedHttpResponse(
        status_code=status_code,
        headers={},
        content=json.dumps(payload).encode(),
    )


def test_catalog_walk_retries_transient_page_then_caches_complete_catalog(monkeypatch):
    source = hub.ClawHubSource()
    responses = iter([
        httpx.ConnectError("temporary upstream failure"),
        _response({"items": [{"slug": "first"}], "nextCursor": "page-2"}),
        _response({"items": [{"slug": "second"}]}),
    ])
    observed_params = []
    writes = []

    def get_catalog_page(*_args, **kwargs):
        observed_params.append(kwargs["params"])
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(hub, "_bounded_http_get", get_catalog_page)
    monkeypatch.setattr(hub, "_read_index_cache", lambda _key: None)
    monkeypatch.setattr(
        hub,
        "_write_index_cache",
        lambda key, payload: writes.append((key, payload)),
    )
    monkeypatch.setattr(hub.time, "sleep", lambda _seconds: None)

    catalog = source._load_catalog_index()

    assert [skill.identifier for skill in catalog] == ["first", "second"]
    assert observed_params == [
        {"limit": 200},
        {"limit": 200},
        {"limit": 200, "cursor": "page-2"},
    ]
    assert len(writes) == 1
    assert writes[0][0] == "clawhub_catalog_v1"
    assert [entry["identifier"] for entry in writes[0][1]] == ["first", "second"]


def test_unbounded_catalog_walk_discards_partial_results_after_retry_exhaustion(monkeypatch):
    source = hub.ClawHubSource()
    responses = iter([
        _response({"items": [{"slug": "first"}], "nextCursor": "page-2"}),
        _response({}, status_code=503),
        _response({}, status_code=503),
        _response({}, status_code=503),
    ])
    writes = []

    def get_catalog_page(*_args, **_kwargs):
        return next(responses)

    monkeypatch.setattr(hub, "_bounded_http_get", get_catalog_page)
    monkeypatch.setattr(hub, "_read_index_cache", lambda _key: None)
    monkeypatch.setattr(
        hub,
        "_write_index_cache",
        lambda key, payload: writes.append((key, payload)),
    )
    monkeypatch.setattr(hub.time, "sleep", lambda _seconds: None)

    assert source._load_catalog_index() == []
    assert writes == []


def test_catalog_walk_accepts_bounded_rich_metadata_without_retaining_it(monkeypatch):
    source = hub.ClawHubSource()
    oversized_metadata = "x" * (hub.MAX_HUB_STRING_BYTES + 1)

    monkeypatch.setattr(
        hub,
        "_bounded_http_get",
        lambda *_args, **_kwargs: _response(
            {
                "items": [
                    {
                        "slug": "rich-metadata",
                        "summary": "small summary",
                        "unusedRichMetadata": oversized_metadata,
                    }
                ]
            }
        ),
    )
    monkeypatch.setattr(hub, "_read_index_cache", lambda _key: None)
    monkeypatch.setattr(hub, "_write_index_cache", lambda *_args: None)

    catalog = source._load_catalog_index()

    assert [skill.identifier for skill in catalog] == ["rich-metadata"]
    assert catalog[0].description == "small summary"
