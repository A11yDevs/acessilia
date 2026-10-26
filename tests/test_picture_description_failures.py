"""A picture left undescribed records why, for the operator, and stays retryable.

006.pdf delivered slides 11 and 14 with no description and nothing but the log
saying why. The reason now goes to the element's metadata and the
describe-image warning; the reader gets one neutral alt text.
"""

from __future__ import annotations

import pytest

from backend.agents.output_schemas import VisionOutput
from backend.agents.pddl_orchestrator import (
    MSG_UNDESCRIBED_PICTURE_ALT,
    _element_to_block,
    _enrich_picture_descriptions,
    _handle_vision_description_method,
)
from backend.i18n import t
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

# Validation rejects an empty description; construct one to stand for a
# salvaged answer that came back blank.
_EMPTY = VisionOutput.model_construct(
    kind="description",
    description="",
    formula_latex=None,
    language="pt-BR",
    confidence=0.1,
    mentioned_elements=[],
    warnings=[],
)


def _patch(monkeypatch, answer, *, image=b"image-bytes", error=None):
    """Answer every call with ``answer`` (``error`` reported when it is None)."""
    calls = []

    class FakeVision:
        def __init__(self, mode: str) -> None:
            self.mode = mode

        async def describe_region(self, *, errors=None, **kwargs):
            calls.append(kwargs)
            if answer is None and error and errors is not None:
                errors.append(error)
            return answer

    monkeypatch.setattr("backend.agents.pddl_orchestrator.VisionAgent", FakeVision)
    monkeypatch.setattr(
        "backend.agents.pddl_orchestrator._extract_picture_bytes",
        lambda *_args, **_kwargs: (image, 1),
    )
    return calls


async def _enrich(manifest, tmp_path):
    await _enrich_picture_descriptions(manifest, tmp_path / "doc.pdf", mode="medio")
    return manifest.elements[0]


@pytest.mark.asyncio
async def test_a_failed_call_records_the_reason_and_the_error(monkeypatch, tmp_path):
    calls = _patch(monkeypatch, None, error="TimeoutError: provider gave up")
    manifest = _manifest(
        [_element("pic-1", "picture")],
        [_obligation("describe-image", ["pic-1"], ["vision-description"])],
    )

    picture = await _enrich(manifest, tmp_path)

    # One call: retrying is the vision agent's job, not this caller's.
    assert len(calls) == 1
    assert picture.metadata["vision_failure_reason"] == "model_failed"
    assert picture.metadata["vision_failure_detail"] == "TimeoutError: provider gave up"
    assert "vision_description_complete" not in picture.metadata
    assert _element_to_block(picture)["alt_text"] == t(MSG_UNDESCRIBED_PICTURE_ALT)
    result = _handle_vision_description_method(manifest, "o-1")
    assert not result.success
    assert "pic-1 (model_failed)" in result.message


@pytest.mark.asyncio
async def test_a_picture_that_cannot_be_cropped_is_reported(monkeypatch, tmp_path):
    calls = _patch(monkeypatch, _DESCRIPTION, image=None)
    manifest = _manifest([_element("pic-1", "picture")], [])

    picture = await _enrich(manifest, tmp_path)

    assert calls == []
    assert picture.metadata["vision_failure_reason"] == "crop_unavailable"
    assert _element_to_block(picture)["alt_text"] == t(MSG_UNDESCRIBED_PICTURE_ALT)


@pytest.mark.asyncio
async def test_an_empty_answer_keeps_meaningful_text_the_extractor_had(
    monkeypatch, tmp_path
):
    _patch(monkeypatch, _EMPTY)
    manifest = _manifest(
        [_element("pic-1", "picture", text="Periodic table of the elements")], []
    )

    picture = await _enrich(manifest, tmp_path)

    assert picture.text == "Periodic table of the elements"
    assert _element_to_block(picture)["alt_text"] == "Periodic table of the elements"
    assert picture.metadata["vision_description_complete"] is True
    assert "vision_failure_reason" not in picture.metadata


@pytest.mark.parametrize(
    "element_type, text",
    [("paragraph", "body"), ("picture", "1a,")],
    ids=["extractor-placeholder", "ocr-noise"],
)
@pytest.mark.asyncio
async def test_an_empty_answer_never_turns_extractor_noise_into_alt_text(
    monkeypatch, tmp_path, element_type, text
):
    _patch(monkeypatch, _EMPTY)
    manifest = _manifest([_element("pic-1", element_type, text=text)], [])
    if element_type != "picture":
        # A non-picture is only sent for description as a placeholder of a
        # mostly visual page; describe it directly here.
        manifest.elements[0].type = "picture"

    picture = await _enrich(manifest, tmp_path)

    assert _element_to_block(picture)["alt_text"] == t(MSG_UNDESCRIBED_PICTURE_ALT)
    assert picture.metadata["vision_failure_reason"] == "empty_description"
    assert "vision_description_complete" not in picture.metadata


@pytest.mark.asyncio
async def test_a_failed_picture_is_described_on_a_later_pass(monkeypatch, tmp_path):
    _patch(monkeypatch, None)
    manifest = _manifest([_element("pic-1", "picture")], [])
    await _enrich(manifest, tmp_path)

    _patch(monkeypatch, _DESCRIPTION)
    picture = await _enrich(manifest, tmp_path)

    assert picture.text == "An illustrated periodic table."
    assert picture.metadata["vision_description_complete"] is True
    assert "vision_failure_reason" not in picture.metadata
    assert "vision_failure_detail" not in picture.metadata


@pytest.mark.asyncio
async def test_a_described_picture_is_not_sent_again(monkeypatch, tmp_path):
    calls = _patch(monkeypatch, _DESCRIPTION)
    manifest = _manifest(
        [
            _element(
                "pic-1",
                "picture",
                text="Already described.",
                metadata={"vision_description_complete": True},
            )
        ],
        [],
    )

    picture = await _enrich(manifest, tmp_path)

    assert calls == []
    assert picture.text == "Already described."
