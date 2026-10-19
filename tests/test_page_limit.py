"""MAX_PAGES refuses a document that is too long, before any costly step.

The limit is checked right after the structural extraction, the first point
where the page count is always known. A refused document fails the job with a
localized message that names the page count and the limit; nothing is planned,
inspected or described.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend import i18n
from backend.agents import pddl_orchestrator as pddl
from backend.config.settings import settings
from tests.pddl_support import build_orchestrator


def _orchestrator_with_pages(count: int):
    orchestrator = build_orchestrator()
    manifest = SimpleNamespace(pages=[object()] * count)
    orchestrator.information_structural = SimpleNamespace(
        process=lambda *args, **kwargs: manifest
    )
    return orchestrator


async def _must_not_run(*args, **kwargs):
    raise AssertionError("the pipeline continued past the page limit")


@pytest.mark.asyncio
async def test_a_document_over_the_limit_fails_before_any_costly_step(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "max_pages", 2)
    monkeypatch.setattr(pddl, "inspect_source_media", _must_not_run)
    orchestrator = _orchestrator_with_pages(3)

    # Pinned, so the expected English message holds on a pt_BR machine too.
    token = i18n.set_request_locale("en_US")
    try:
        with pytest.raises(pddl.DocumentTooLargeError) as info:
            await orchestrator.executar(tmp_path / "doc.pdf", tmp_path)
    finally:
        i18n.reset_request_locale(token)

    assert str(info.value) == "The document has 3 pages, more than the limit of 2."


@pytest.mark.parametrize("count", [1, 2])
def test_documents_up_to_the_limit_pass(monkeypatch, count):
    monkeypatch.setattr(settings, "max_pages", 2)
    pddl._check_page_limit(SimpleNamespace(pages=[object()] * count))


def test_max_pages_is_read_from_the_environment(monkeypatch):
    from backend.config.settings import Settings

    monkeypatch.setenv("MAX_PAGES", "7")
    assert Settings().max_pages == 7


@pytest.mark.parametrize("value", ["0", "-1"])
def test_a_non_positive_max_pages_is_refused_at_startup(monkeypatch, value):
    from backend.config.settings import Settings

    monkeypatch.setenv("MAX_PAGES", value)
    with pytest.raises(ValueError, match="MAX_PAGES must be positive"):
        Settings()


@pytest.mark.asyncio
async def test_the_message_is_translated_with_both_numbers(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "max_pages", 50)
    monkeypatch.setattr(pddl, "inspect_source_media", _must_not_run)
    orchestrator = _orchestrator_with_pages(120)

    token = i18n.set_request_locale("pt_BR")
    try:
        with pytest.raises(pddl.DocumentTooLargeError) as info:
            await orchestrator.executar(tmp_path / "doc.pdf", tmp_path)
    finally:
        i18n.reset_request_locale(token)

    assert str(info.value) == "O documento tem 120 páginas, mais que o limite de 50."
