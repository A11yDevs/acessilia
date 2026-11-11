"""Reading the text layer's spans in batches (#402).

Characterization of ``backend.tools.text_spans.fetch_text_spans``, written on
develop before the batching moved to ``ToolboxPdfClient``. The inline math
steps call it; their tests replace it whole.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from acessilia_sdk.toolbox.clients.pdf import TEXT_SPANS_MAX_PAGES, ToolboxPdfClient
from acessilia_sdk.toolbox.errors import ToolboxError

from backend.tools import text_spans


class _FakeSpansClient(ToolboxPdfClient):
    """A real client whose one ``document.text.spans`` call is replaced."""

    def __init__(self, fail_on_call: int | None = None) -> None:
        super().__init__(base_url="http://localhost:8002", provider="pymupdf-pdf", timeout_seconds=30)
        self.calls: list[dict] = []
        self.closed = 0
        self._fail_on_call = fail_on_call

    async def text_spans(self, file_path=None, artifact_id=None, *, pages=None, use_remote_cache=None):
        self.calls.append({"file_path": file_path, "artifact_id": artifact_id, "pages": list(pages),
                           "use_remote_cache": use_remote_cache})
        if self._fail_on_call == len(self.calls):
            raise ToolboxError("document.text.spans failed")
        return {"coord_origin": "TOPLEFT",
                "pages": [{"page_number": page, "lines": [], "call": len(self.calls)} for page in pages]}

    async def close(self) -> None:
        self.closed += 1


@pytest.fixture
def owned(monkeypatch):
    made: list[tuple] = []
    client = _FakeSpansClient()

    def make(cls, **kwargs):
        made.append((cls.__name__, kwargs))
        return client

    monkeypatch.setattr("backend.tools.toolbox_client.make_toolbox_client", make)
    from backend.config.settings import settings
    monkeypatch.setattr(settings, "toolbox_use_remote_cache", False)
    return client, made


def _fetch(pages, **kwargs):
    return asyncio.run(text_spans.fetch_text_spans(Path("/tmp/a.pdf"), pages, **kwargs))


def test_pages_are_asked_sorted_once_each_in_batches(owned) -> None:
    client, _ = owned
    pages = list(range(TEXT_SPANS_MAX_PAGES + 5, 0, -1)) + [3, 3]

    by_page = _fetch(pages)

    assert [call["pages"] for call in client.calls] == [
        list(range(1, TEXT_SPANS_MAX_PAGES + 1)),
        list(range(TEXT_SPANS_MAX_PAGES + 1, TEXT_SPANS_MAX_PAGES + 6)),
    ]
    assert sorted(by_page) == list(range(1, TEXT_SPANS_MAX_PAGES + 6))
    assert by_page[TEXT_SPANS_MAX_PAGES + 1]["call"] == 2


def test_no_pages_no_call(owned) -> None:
    client, _ = owned

    assert _fetch([]) == {}
    assert client.calls == [] and client.closed == 1


def test_an_owned_client_follows_the_settings_and_is_closed(owned) -> None:
    client, made = owned

    _fetch([1], artifact_id="art-1")

    assert made == [("ToolboxPdfClient", {"resend_file_on_missing_artifact": True})]
    assert client.calls == [{"file_path": Path("/tmp/a.pdf"), "artifact_id": "art-1", "pages": [1],
                             "use_remote_cache": False}]
    assert client.closed == 1


def test_without_an_artifact_the_file_is_not_resent(owned) -> None:
    _, made = owned

    _fetch([1])

    assert made == [("ToolboxPdfClient", {"resend_file_on_missing_artifact": False})]


def test_an_owned_client_is_closed_when_a_batch_fails(monkeypatch, owned) -> None:
    client = _FakeSpansClient(fail_on_call=2)
    monkeypatch.setattr("backend.tools.toolbox_client.make_toolbox_client", lambda cls, **kw: client)

    with pytest.raises(ToolboxError):
        _fetch(list(range(1, TEXT_SPANS_MAX_PAGES + 2)))

    assert client.closed == 1


def test_a_given_client_is_used_and_left_open(owned) -> None:
    _, made = owned
    given = _FakeSpansClient()

    _fetch([2], client=given)

    assert made == [] and given.closed == 0 and given.calls[0]["pages"] == [2]


def test_a_page_repeated_in_a_later_answer_replaces_the_earlier(monkeypatch, owned) -> None:
    class Repeating(_FakeSpansClient):
        async def text_spans(self, **kwargs):
            document = await super().text_spans(**kwargs)
            document["pages"].append({"page_number": 1, "lines": [], "call": len(self.calls)})
            return document

    client = Repeating()
    monkeypatch.setattr("backend.tools.toolbox_client.make_toolbox_client", lambda cls, **kw: client)

    assert _fetch(list(range(1, TEXT_SPANS_MAX_PAGES + 2)))[1]["call"] == 2
