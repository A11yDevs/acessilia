"""A picture left undescribed says why, and a provider error gets a second try.

006.pdf delivered slides 11 and 14 with "Imagem detectada sem descricao
textual." and nothing in the document or the warning explaining it: the
failure was only in the log. The same slides described fine on their own, so
the likely cause was a provider error under a whole deck's load, which ended
the call without a retry.
"""

from __future__ import annotations

import pytest

from backend.agents.output_schemas import VisionOutput
from backend.agents.pddl_orchestrator import (
    _VISION_FAILURE_REASONS,
    _element_to_block,
    _enrich_picture_descriptions,
    _handle_vision_description_method,
)
from tests.pddl_support import (
    build_element as _element,
)
from tests.pddl_support import (
    build_manifest as _manifest,
)
from tests.pddl_support import (
    build_obligation as _obligation,
)

_DESCRIPTION = VisionOutput(
    kind="description",
    description="An illustrated periodic table.",
    language="pt-BR",
    confidence=0.9,
)


def _patch(monkeypatch, answers, image=b"image-bytes"):
    """Serve ``answers`` in order from a fake vision model; return the call log."""
    calls = []

    class FakeVision:
        def __init__(self, mode: str) -> None:
            self.mode = mode

        async def describe_region(self, **kwargs):
            calls.append(kwargs)
            return answers[min(len(calls), len(answers)) - 1]

    monkeypatch.setattr("backend.agents.pddl_orchestrator.VisionAgent", FakeVision)
    monkeypatch.setattr(
        "backend.agents.pddl_orchestrator._extract_picture_bytes",
        lambda *_args, **_kwargs: (image, 1),
    )
    return calls


@pytest.mark.asyncio
async def test_a_failed_call_is_tried_once_more(monkeypatch, tmp_path):
    calls = _patch(monkeypatch, [None, _DESCRIPTION])
    manifest = _manifest([_element("pic-1", "picture")], [])

    await _enrich_picture_descriptions(manifest, tmp_path / "doc.pdf", mode="medio")

    [picture] = manifest.elements
    assert len(calls) == 2
    assert picture.text == "An illustrated periodic table."
    assert "vision_failure_reason" not in picture.metadata


@pytest.mark.asyncio
async def test_a_model_that_never_answers_is_reported_with_the_reason(
    monkeypatch, tmp_path
):
    calls = _patch(monkeypatch, [None])
    manifest = _manifest(
        [_element("pic-1", "picture")],
        [_obligation("describe-image", ["pic-1"], ["vision-description"])],
    )

    await _enrich_picture_descriptions(manifest, tmp_path / "doc.pdf", mode="medio")

    [picture] = manifest.elements
    assert len(calls) == 2
    assert picture.metadata["vision_failure_reason"] == "model_failed"
    reason = _VISION_FAILURE_REASONS["model_failed"]
    assert _element_to_block(picture)["alt_text"].endswith(f": {reason}.")
    result = _handle_vision_description_method(manifest, "o-1")
    assert not result.success
    assert f"pic-1 ({reason})" in result.message


@pytest.mark.asyncio
async def test_a_picture_that_cannot_be_cropped_is_reported(monkeypatch, tmp_path):
    calls = _patch(monkeypatch, [_DESCRIPTION], image=None)
    manifest = _manifest([_element("pic-1", "picture")], [])

    await _enrich_picture_descriptions(manifest, tmp_path / "doc.pdf", mode="medio")

    [picture] = manifest.elements
    assert calls == []
    assert picture.metadata["vision_failure_reason"] == "crop_unavailable"


@pytest.mark.asyncio
async def test_an_empty_answer_keeps_the_text_the_extractor_had(monkeypatch, tmp_path):
    # Validation rejects an empty description; construct one to stand for a
    # salvaged answer that came back blank.
    empty = VisionOutput.model_construct(
        kind="description",
        description="",
        formula_latex=None,
        language="pt-BR",
        confidence=0.1,
        mentioned_elements=[],
        warnings=[],
    )
    _patch(monkeypatch, [empty])
    manifest = _manifest(
        [_element("pic-1", "picture", text="Periodic table of the elements")], []
    )

    await _enrich_picture_descriptions(manifest, tmp_path / "doc.pdf", mode="medio")

    [picture] = manifest.elements
    assert picture.text == "Periodic table of the elements"


def test_an_undescribed_picture_without_a_recorded_reason_keeps_the_old_alt():
    picture = _element("pic-1", "picture")

    assert _element_to_block(picture)["alt_text"] == (
        "Imagem detectada sem descricao textual."
    )
