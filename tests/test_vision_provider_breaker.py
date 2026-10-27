"""A provider that fails is tried again once, and one that stays down is not
called for every remaining object.

006.pdf v5 lost every picture after slide 10 to a provider that went down
partway through the job, and each of them still paid up to two call
deadlines before it degraded.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.agents.output_schemas import DataOutput, VisionOutput
from backend.agents.pddl_orchestrator import (
    _enrich_picture_descriptions,
    _enrich_table_structures,
)
from backend.agents.provider_breaker import ProviderBreaker
from backend.config.settings import settings
from tests.pddl_support import build_element as _element
from tests.pddl_support import build_manifest as _manifest

_DESCRIPTION = VisionOutput(
    kind="description",
    description="An illustrated periodic table.",
    language="pt-BR",
    confidence=0.9,
)

# Validation rejects an empty description; construct one to stand for an
# answer that came back blank.
_EMPTY = VisionOutput.model_construct(
    kind="description",
    description="",
    formula_latex=None,
    language="pt-BR",
    confidence=0.1,
    mentioned_elements=[],
    warnings=[],
)

_TABLE = DataOutput(
    kind="table",
    rows=[
        {"cells": [{"text": "Element", "scope": "col"}, {"text": "Mass", "scope": "col"}]},
        {"cells": [{"text": "H"}, {"text": "1"}]},
    ],
    language="pt-BR",
    confidence=0.9,
)


@pytest.fixture(autouse=True)
def _one_call_at_a_time(monkeypatch):
    """Serial calls, so the order of failures and answers is the script's."""
    monkeypatch.setattr(settings, "vision_concurrency", 1)
    monkeypatch.setattr(settings, "vision_breaker_threshold", 2)


def _vision(monkeypatch, answers):
    """Answer each vision call with the next of ``answers`` (None is a failure)."""
    calls = []

    class FakeVision:
        def __init__(self, mode: str) -> None:
            self.mode = mode

        async def describe_region(self, *, errors=None, **kwargs):
            calls.append(kwargs)
            answer = answers[len(calls) - 1]
            if answer is None and errors is not None:
                errors.append("TimeoutError: no answer")
            return answer

    monkeypatch.setattr("backend.agents.pddl_orchestrator.VisionAgent", FakeVision)
    monkeypatch.setattr(
        "backend.agents.pddl_orchestrator._extract_picture_bytes",
        lambda *_args, **_kwargs: (b"image-bytes", 1),
    )
    return calls


def _data(monkeypatch, answers):
    """Answer each table reading with the next of ``answers`` (None is a failure)."""
    calls = []

    class FakeDataAgent:
        async def process_region(self, **kwargs):
            calls.append(kwargs)
            return answers[len(calls) - 1]

    monkeypatch.setattr("backend.agents.pddl_orchestrator.DataAgent", FakeDataAgent)
    return calls


def _pictures(count):
    return _manifest([_element(f"pic-{n}", "picture") for n in range(1, count + 1)], [])


def test_the_breaker_opens_after_failures_in_a_row_and_an_answer_closes_it():
    breaker = ProviderBreaker(2)
    breaker.record(False)
    breaker.record(True)
    breaker.record(False)
    assert not breaker.open
    breaker.record(False)
    assert breaker.open
    assert breaker.skip_detail() == "skipped: the provider failed 2 calls in a row"

    breaker.probe()
    assert not breaker.open
    breaker.record(False)
    assert breaker.open

    breaker.probe()
    breaker.record(True)
    assert not breaker.open


def test_a_threshold_of_zero_never_opens_the_breaker():
    breaker = ProviderBreaker(0)
    for _ in range(10):
        breaker.record(False)
    assert not breaker.open


@pytest.mark.asyncio
async def test_pictures_the_provider_failed_are_described_on_the_second_pass(
    monkeypatch, tmp_path
):
    # The provider fails on pic-2 and pic-3 and is back for the second pass.
    calls = _vision(monkeypatch, [_DESCRIPTION, None, None, _DESCRIPTION, _DESCRIPTION])
    manifest = _pictures(3)

    await _enrich_picture_descriptions(manifest, tmp_path / "doc.pdf", mode="medio")

    assert len(calls) == 5
    assert all(p.metadata.get("vision_description_complete") for p in manifest.elements)
    assert not any("vision_failure_reason" in p.metadata for p in manifest.elements)


@pytest.mark.asyncio
async def test_a_provider_that_stays_down_costs_the_threshold_and_one_probe(
    monkeypatch, tmp_path
):
    calls = _vision(monkeypatch, [None] * 10)
    manifest = _pictures(5)

    await _enrich_picture_descriptions(manifest, tmp_path / "doc.pdf", mode="medio")

    # Two failures open the breaker; the second pass probes once and stops.
    assert len(calls) == 3
    reasons = [p.metadata["vision_failure_reason"] for p in manifest.elements]
    assert reasons == ["model_failed"] * 5
    details = [p.metadata["vision_failure_detail"] for p in manifest.elements]
    assert details[0] == "TimeoutError: no answer"
    assert details[-1] == "skipped: the provider failed 2 calls in a row"


@pytest.mark.asyncio
async def test_an_empty_answer_is_asked_again_but_does_not_open_the_breaker(
    monkeypatch, tmp_path
):
    calls = _vision(monkeypatch, [_EMPTY, _EMPTY, _EMPTY, _DESCRIPTION, _DESCRIPTION, _EMPTY])
    manifest = _pictures(3)

    await _enrich_picture_descriptions(manifest, tmp_path / "doc.pdf", mode="medio")

    # Every picture reached the model on both passes: an empty answer is an answer.
    assert len(calls) == 6
    complete = [bool(p.metadata.get("vision_description_complete")) for p in manifest.elements]
    assert complete == [True, True, False]
    assert manifest.elements[2].metadata["vision_failure_reason"] == "empty_description"


@pytest.mark.asyncio
async def test_a_breaker_opened_by_the_pictures_skips_the_tables(monkeypatch, tmp_path):
    _vision(monkeypatch, [None] * 10)
    data_calls = _data(monkeypatch, [_TABLE] * 3)
    pictures = _pictures(2)
    tables = _manifest([_element("t-1", "table", text="")], [])
    breaker = ProviderBreaker(settings.vision_breaker_threshold)

    await _enrich_picture_descriptions(
        pictures, tmp_path / "doc.pdf", mode="medio", breaker=breaker
    )
    await _enrich_table_structures(tables, Path(tmp_path / "doc.pdf"), breaker=breaker)

    # The table's second pass is the probe, and the provider answers it.
    assert len(data_calls) == 1
    table = tables.elements[0]
    assert "table_read_failure" not in table.metadata
    assert table.metadata["table_row_count"] == 2


@pytest.mark.asyncio
async def test_a_table_the_provider_failed_is_read_on_the_second_pass(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "backend.agents.pddl_orchestrator._extract_picture_bytes",
        lambda *_args, **_kwargs: (b"image-bytes", 1),
    )
    data_calls = _data(monkeypatch, [None, _TABLE])
    tables = _manifest([_element("t-1", "table", text="")], [])

    await _enrich_table_structures(tables, Path(tmp_path / "doc.pdf"))

    assert len(data_calls) == 2
    assert "table_read_failure" not in tables.elements[0].metadata
    assert tables.elements[0].metadata["table_row_count"] == 2
