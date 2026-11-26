"""A picture left undescribed records why, for the operator, and stays retryable.

006.pdf delivered slides 11 and 14 with no description and nothing but the log
saying why. The reason now goes to the element's metadata and the
describe-image warning; the reader gets one neutral alt text.
"""

from __future__ import annotations

import pytest
from core_config_support import model_config, toolbox_config, vision_config
from pddl_support import (
    build_element as _element,
    build_manifest as _manifest,
    build_obligation as _obligation,
)

from acessilia_core.agents.output_schemas import VisionOutput
from acessilia_core.i18n import t
from acessilia_core.pipeline.elements import (
    MSG_UNDESCRIBED_PICTURE_ALT,
    _element_to_block,
)
from acessilia_core.pipeline.enrichment.pictures import _enrich_picture_descriptions
from acessilia_core.pipeline.handlers.content import _handle_vision_description_method

_DESCRIPTION = VisionOutput(
    kind="description",
    description="An illustrated periodic table.",
    language="pt-BR",
    confidence=0.9,
)


def _patch(monkeypatch, answer, *, image=b"image-bytes", error=None):
    """Answer every call with ``answer`` (``error`` reported when it is None)."""
    calls = []

    class FakeVision:
        def __init__(self, mode: str, *, region_cache, toolbox, models) -> None:
            self.mode = mode

        async def describe_region(self, *, errors=None, **kwargs):
            calls.append(kwargs)
            if answer is None and error and errors is not None:
                errors.append(error)
            return answer

    monkeypatch.setattr("acessilia_core.pipeline.enrichment.pictures.VisionAgent", FakeVision)
    monkeypatch.setattr(
        "acessilia_core.pipeline.enrichment.pictures._extract_picture_bytes",
        lambda *_args, **_kwargs: (image, 1),
    )
    return calls


async def _enrich(manifest, tmp_path):
    await _enrich_picture_descriptions(manifest, tmp_path / "doc.pdf", mode="medio", vision=vision_config(), toolbox=toolbox_config(), models=model_config(), region_cache=None)
    return manifest.elements[0]


@pytest.mark.asyncio
async def test_a_failed_call_records_the_reason_and_the_error(monkeypatch, tmp_path):
    calls = _patch(monkeypatch, None, error="TimeoutError: provider gave up")
    manifest = _manifest(
        [_element("pic-1", "picture")],
        [_obligation("describe-image", ["pic-1"], ["vision-description"])],
    )

    picture = await _enrich(manifest, tmp_path)

    # The call, and one more after the stage's wait: retrying within a call
    # is the vision agent's job, not this caller's.
    assert len(calls) == 2
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
async def test_a_failure_keeps_the_answer_a_previous_fold_folded(monkeypatch, tmp_path):
    """A failed later attempt drops the certification, not the description.

    The stage only re-asks a picture whose completion flag is gone (a restored
    manifest), so its text and vision metadata are an earlier answer's. The
    failure records that this attempt added nothing; discarding the earlier
    answer would lose the only description the manifest has (#681).
    """
    _patch(monkeypatch, _DESCRIPTION)
    manifest = _manifest([_element("pic-1", "picture")], [])
    picture = await _enrich(manifest, tmp_path)
    folded = {
        key: picture.metadata[key]
        for key in (
            "vision_language",
            "vision_confidence",
            "vision_elements",
            "vision_warnings",
        )
    }
    assert picture.metadata["vision_description_complete"] is True

    # The flag a restored manifest may have lost; the description remains.
    picture.metadata.pop("vision_description_complete")
    _patch(monkeypatch, None)
    picture = await _enrich(manifest, tmp_path)

    assert picture.text == "An illustrated periodic table."
    for key, value in folded.items():
        assert picture.metadata[key] == value
    assert "vision_description_complete" not in picture.metadata
    assert picture.metadata["vision_failure_reason"] == "model_failed"
    assert _element_to_block(picture)["alt_text"] == "An illustrated periodic table."


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
