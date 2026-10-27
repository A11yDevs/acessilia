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
from backend.agents import pddl_orchestrator as pddl
from backend.agents.pddl_orchestrator import (
    _enrich_formula_latex,
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


def _vision(monkeypatch, answers, failure: str = "TimeoutError: no answer"):
    """Answer each vision call with the next of ``answers`` (None is a failure)."""
    calls = []

    class FakeVision:
        def __init__(self, mode: str) -> None:
            self.mode = mode

        async def describe_region(self, *, errors=None, **kwargs):
            calls.append(kwargs)
            answer = answers[len(calls) - 1]
            if answer is None and errors is not None:
                errors.append(failure)
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
    assert breaker.skip_detail() == "skipped: 2 vision calls in a row got no usable answer"

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
    assert details[-1] == "skipped: 2 vision calls in a row got no usable answer"


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


# A table whose ast the extractor read collapsed: flagged garbled, so both
# passes read it again from its image rather than accept the misread once.
_COLLAPSED_AST = {
    "header": [{"cells": [{"text": "Prefix", "scope": "col"}, {"text": "symbol", "scope": "col"}, {"text": "power", "scope": "col"}]}],
    "body": [
        {
            "cells": [
                {"text": "yota zeta exa peta tera giga mega kilo hecto deca"},
                {"text": "Y Z E P T G M k h da"},
                {"text": "10^24 10^21 10^18 10^15 10^12 10^9 10^6 10^3 10^2 10^1"},
            ]
        }
    ],
}


def _reading(rows: list[list[str]]) -> DataOutput:
    return DataOutput(
        kind="table",
        rows=[
            {"cells": [{"text": text, "scope": "col" if index == 0 else "none"} for text in row]}
            for index, row in enumerate(rows)
        ],
        language="pt-BR",
        confidence=0.9,
    )


@pytest.mark.asyncio
async def test_an_unused_answer_on_the_second_pass_is_not_left_as_a_failure(
    monkeypatch, tmp_path
):
    # The model answered; the job cannot use the answer (`kind` is not a
    # table), but that says the provider is up, so the failure the first pass
    # recorded must not stay on the element to keep the run out of the cache.
    unusable = DataOutput(kind="formula", latex="E=mc^2", language="pt-BR", confidence=0.9)
    data_calls = _data(monkeypatch, [None, unusable])
    monkeypatch.setattr(
        "backend.agents.pddl_orchestrator._extract_picture_bytes",
        lambda *_args, **_kwargs: (b"image-bytes", 1),
    )
    tables = _manifest([_element("t-1", "table", text="")], [])

    await _enrich_table_structures(tables, Path(tmp_path / "doc.pdf"))

    assert len(data_calls) == 2
    assert "table_read_failure" not in tables.elements[0].metadata
    assert pddl._visual_failures(tables) is None


@pytest.mark.asyncio
async def test_a_refused_reading_on_the_second_pass_clears_the_failure_and_sums_the_attempts(
    monkeypatch, tmp_path
):
    # The first pass pays three readings and gets none; the second pass gets
    # three refused ones (a different table read better than collapse, worse
    # than the words it would replace). The metadata then says the model
    # works, and the attempts add up to six, not to the second pass's three.
    not_the_table = _reading(
        [["Country", "Capital", "Currency"], ["Japan", "Tokyo", "Yen"]]
    )
    # A threshold this test does not reach, so the reads are all made.
    monkeypatch.setattr(settings, "vision_breaker_threshold", 10)
    data_calls = _data(
        monkeypatch, [None, None, None, not_the_table, not_the_table, not_the_table]
    )
    monkeypatch.setattr(
        "backend.agents.pddl_orchestrator._extract_picture_bytes",
        lambda *_args, **_kwargs: (b"image-bytes", 1),
    )
    tables = _manifest(
        [_element("t-1", "table", metadata={"table_ast": _COLLAPSED_AST})], []
    )

    await _enrich_table_structures(tables, Path(tmp_path / "doc.pdf"))

    assert len(data_calls) == 6
    table = tables.elements[0]
    assert "table_read_failure" not in table.metadata
    assert table.metadata["table_review"] == {
        "reason": "collapsed_rows", "outcome": "kept", "attempts": 6,
        "why": "only 0% of its words are in the table it would replace",
    }
    assert pddl._visual_failures(tables) is None


@pytest.mark.asyncio
async def test_a_table_skipped_by_the_breaker_is_not_cropped(monkeypatch, tmp_path):
    # The breaker is consulted before the crop: a render no call would use.
    crops = []

    def fake_crop(*_args, **_kwargs):
        crops.append(True)
        return (b"image-bytes", 1)

    monkeypatch.setattr("backend.agents.pddl_orchestrator._extract_picture_bytes", fake_crop)
    _data(monkeypatch, [None] * 10)
    tables = _manifest(
        [_element(f"t-{n}", "table", text="") for n in range(1, 4)], []
    )
    breaker = ProviderBreaker(settings.vision_breaker_threshold)
    breaker.record(False)
    breaker.record(False)

    await _enrich_table_structures(tables, Path(tmp_path / "doc.pdf"), breaker=breaker)

    # First pass: skipped before the crop. Second pass: the probe is the
    # only call made, and its failure reopens the breaker for the rest.
    assert len(crops) == 1
    failures = [t.metadata.get("table_read_failure") for t in tables.elements]
    assert failures == ["model_failed"] * 3


@pytest.mark.asyncio
async def test_a_breaker_opened_by_the_pictures_skips_the_formula_fallback(
    monkeypatch, tmp_path
):
    # Only the ``math.recognize`` outage flag decides the vision fallback
    # does not fire; the shared breaker is consulted around it, so a provider
    # the pictures declared down is not paid another deadline per formula.
    vision_calls = _vision(monkeypatch, [None] * 10)
    recognize_calls = []

    def recognize(image, *, raise_on_unavailable=False):
        recognize_calls.append(image)
        return []

    monkeypatch.setattr("backend.agents.pddl_orchestrator.toolbox_recognize_formula", recognize)
    monkeypatch.setattr(
        "backend.agents.pddl_orchestrator._formula_recognition_crop",
        lambda *_args, **_kwargs: (b"png", 1),
    )
    pictures = _manifest([_element("pic-1", "picture"), _element("pic-2", "picture")], [])
    formulas = _manifest([_element("formula-1", "formula")], [])
    breaker = ProviderBreaker(settings.vision_breaker_threshold)

    await _enrich_picture_descriptions(pictures, tmp_path / "doc.pdf", mode="medio", breaker=breaker)
    await _enrich_formula_latex(
        formulas, tmp_path / "doc.pdf", mode="medio", breaker=breaker
    )

    # Pictures: two failures to open the breaker, one probe through it. The
    # formulas: none, the breaker was open before the fallback ever ran.
    assert len(vision_calls) == 3
    assert all(call["classification"] != "formula" for call in vision_calls)
    assert len(recognize_calls) == 1
    assert formulas.elements[0].text is None


@pytest.mark.asyncio
async def test_the_second_pass_waits_the_configured_delay(monkeypatch, tmp_path):
    waits = []

    async def record_sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr("backend.agents.pddl_orchestrator.asyncio.sleep", record_sleep)
    monkeypatch.setattr(settings, "vision_retry_pass_delay_seconds", 5)
    calls = _vision(monkeypatch, [_DESCRIPTION, None, _DESCRIPTION])
    manifest = _pictures(2)

    await _enrich_picture_descriptions(manifest, tmp_path / "doc.pdf", mode="medio")

    assert waits == [5]
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_validation_failures_open_the_breaker_too(monkeypatch, tmp_path):
    """A limitation the breaker accepts: ``describe_region`` returns None both
    when a provider is down and when its answers keep failing validation, so
    a model that misreads systematically opens the breaker here as well. The
    probing first call of a retry pass bounds a wrong verdict to one call.
    """
    calls = _vision(monkeypatch, [None] * 10, failure="ValidationError after 2 tries")
    manifest = _pictures(2)

    await _enrich_picture_descriptions(manifest, tmp_path / "doc.pdf", mode="medio")

    assert len(calls) == 3  # two failures open the breaker, the second pass probes once
    details = [(p.metadata.get("vision_failure_detail") or "") for p in manifest.elements]
    assert details[0] == "ValidationError after 2 tries"
    assert details[-1].startswith("skipped:")
