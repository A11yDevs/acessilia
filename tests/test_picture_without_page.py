"""A picture of a source without pages (DOCX, HTML) no longer fails the job.

Homologation of develop d7b147b: any DOCX or HTML with an image failed whole
with "describe-image (page not identified)". Their pictures have no page for
``pdf.render`` to crop, so ``_extract_picture_bytes`` gave up, the picture was
reported as a crop failure, and ``_blocks_delivery`` read the only picture left
undescribed as a vision model that is down.

The picture is now read from the image the extraction embedded in it
(``metadata["src"]``, a data URI), and one with no image at all is delivered
with the generic alt text and a pending human review instead of failing.
"""

from __future__ import annotations

import base64
import io
from types import SimpleNamespace

import pytest
from PIL import Image

from backend.agents import pddl_orchestrator as pddl
from backend.agents.output_schemas import VisionOutput
from backend.core.pipeline.elements import MSG_UNDESCRIBED_PICTURE_ALT, _element_to_block
from backend.core.pipeline.enrichment.common import _extract_picture_bytes
from backend.core.pipeline.enrichment.pictures import _enrich_picture_descriptions
from backend.core.pipeline.handlers.content import _handle_vision_description_method
from backend.core.manifest.models import Obligation
from backend.i18n import t
from tests.pddl_support import build_element, build_manifest, build_orchestrator
from backend.core.pipeline.enrichment import common as enrichment_common

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

_DESCRIPTION = VisionOutput(
    kind="description",
    description="Bar chart of attendance by weekday.",
    language="pt-BR",
    confidence=0.9,
)


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 4), "navy").save(buffer, "PNG")
    return buffer.getvalue()


def _data_uri(content: bytes, media_type: str = "image/png") -> str:
    return f"data:{media_type};base64," + base64.b64encode(content).decode("ascii")


def _pageless_picture(element_id: str = "pic-1", *, src: str | None = None):
    """A picture as the Toolbox extracts it from a DOCX or HTML: no page, no box."""
    element = build_element(
        element_id, "picture", metadata={"src": src} if src is not None else None
    )
    element.page_number = None
    element.provenance = []
    return element


def _pageless_manifest(elements, obligations=()):
    manifest = build_manifest(list(elements), list(obligations))
    manifest.pages = []
    manifest.summary.page_count = 0
    manifest.source.filename = "qa_word.docx"
    manifest.source.media_type = DOCX
    return manifest


def _fake_vision(monkeypatch, answer=_DESCRIPTION):
    calls = []

    class FakeVision:
        def __init__(self, mode: str) -> None:
            self.mode = mode

        async def describe_region(self, *, errors=None, **kwargs):
            calls.append(kwargs)
            return answer

    monkeypatch.setattr("backend.core.pipeline.enrichment.pictures.VisionAgent", FakeVision)
    return calls


# --- _extract_picture_bytes -------------------------------------------------


def test_a_pageless_picture_is_read_from_its_embedded_image(
    fake_toolbox_render, tmp_path
):
    png = _png()

    image, page = _extract_picture_bytes(
        tmp_path / "qa_word.docx", _pageless_picture(src=_data_uri(png)), None,
        media_type=DOCX,
    )

    assert image == png
    assert page == 0
    # Nothing to render: a DOCX has no page for pdf.render.
    assert fake_toolbox_render.requests == []


def test_a_pageless_picture_without_an_embedded_image_has_no_bytes(
    fake_toolbox_render, tmp_path
):
    image, page = _extract_picture_bytes(
        tmp_path / "qa_word.docx", _pageless_picture(), None, media_type=DOCX
    )

    assert (image, page) == (None, 0)
    assert fake_toolbox_render.requests == []


@pytest.mark.parametrize(
    "src",
    [
        "https://example.test/chart.png",
        "data:image/svg+xml;base64," + base64.b64encode(b"<svg/>").decode(),
        "data:image/png,not-base64",
        "data:image/png;base64,***",
        "data:image/png;base64,",
        "data:text/html;base64," + base64.b64encode(b"<p>x</p>").decode(),
        "image/png;base64," + base64.b64encode(_png()).decode(),
    ],
    ids=["remote-url", "svg", "not-base64", "invalid-base64", "empty", "not-an-image", "no-data-prefix"],
)
def test_only_an_embedded_raster_image_is_decoded(fake_toolbox_render, tmp_path, src):
    """A remote URL is never fetched, and what a vision model cannot read is not sent."""
    image, page = _extract_picture_bytes(
        tmp_path / "qa_pagina.html", _pageless_picture(src=src), None,
        media_type="text/html",
    )

    assert (image, page) == (None, 0)
    assert fake_toolbox_render.requests == []


def test_an_embedded_image_above_the_size_bound_is_not_decoded(
    monkeypatch, fake_toolbox_render, tmp_path
):
    monkeypatch.setattr(enrichment_common, "_EMBEDDED_PICTURE_MAX_BYTES", 16)

    image, _ = _extract_picture_bytes(
        tmp_path / "qa_word.docx", _pageless_picture(src=_data_uri(b"x" * 64)), None,
        media_type=DOCX,
    )

    assert image is None


@pytest.mark.parametrize("size,accepted", [(16, True), (17, False), (18, False)])
def test_the_size_bound_applies_to_the_decoded_bytes(
    monkeypatch, fake_toolbox_render, tmp_path, size, accepted
):
    """17 and 18 bytes share the base64 length of 16, so the encoded length alone is not enough."""
    monkeypatch.setattr(enrichment_common, "_EMBEDDED_PICTURE_MAX_BYTES", 16)

    image, _ = _extract_picture_bytes(
        tmp_path / "qa_word.docx", _pageless_picture(src=_data_uri(b"x" * size)), None,
        media_type=DOCX,
    )

    assert (image is not None) is accepted


def test_the_data_uri_prefix_is_case_insensitive(fake_toolbox_render, tmp_path):
    src = "DATA:IMAGE/PNG;BASE64," + base64.b64encode(_png()).decode()

    image, _ = _extract_picture_bytes(
        tmp_path / "qa_word.docx", _pageless_picture(src=src), None, media_type=DOCX,
    )

    assert image == _png()


# --- _enrich_picture_descriptions --------------------------------------------


@pytest.mark.asyncio
async def test_a_docx_picture_with_an_embedded_image_is_described(
    monkeypatch, fake_toolbox_render, tmp_path
):
    png = _png()
    calls = _fake_vision(monkeypatch)
    manifest = _pageless_manifest([_pageless_picture(src=_data_uri(png))])

    await _enrich_picture_descriptions(
        manifest, tmp_path / "qa_word.docx", mode="medio"
    )

    picture = manifest.elements[0]
    assert [call["image_bytes"] for call in calls] == [png]
    assert calls[0]["page_num"] == 0
    assert picture.text == "Bar chart of attendance by weekday."
    assert picture.metadata["vision_description_complete"] is True
    assert "vision_failure_reason" not in picture.metadata
    # No page was invented for it.
    assert picture.page_number is None
    assert fake_toolbox_render.requests == []


@pytest.mark.asyncio
async def test_a_pageless_picture_without_an_image_is_not_sent_to_the_model(
    monkeypatch, fake_toolbox_render, tmp_path
):
    calls = _fake_vision(monkeypatch)
    manifest = _pageless_manifest(
        [_pageless_picture()],
        [
            Obligation(
                id="o-1", kind="describe-image", target_ids=["pic-1"],
                admissible_methods=["vision-description", "human-review"],
                method_costs={"vision-description": 20, "human-review": 100},
                rationale="test",
            )
        ],
    )

    await _enrich_picture_descriptions(
        manifest, tmp_path / "qa_word.docx", mode="medio"
    )

    picture = manifest.elements[0]
    assert calls == []
    # Not a crop failure: there is no page to crop, so a retry would not help.
    assert picture.metadata["vision_failure_reason"] == "image_unavailable"
    assert _element_to_block(picture)["alt_text"] == t(MSG_UNDESCRIBED_PICTURE_ALT)
    result = _handle_vision_description_method(manifest, "o-1")
    assert not result.success
    assert "pic-1 (image_unavailable)" in result.message


@pytest.mark.asyncio
async def test_a_paged_picture_whose_crop_failed_is_still_a_crop_failure(
    monkeypatch, tmp_path
):
    """A PDF page the Toolbox could not render keeps its retryable reason."""
    _fake_vision(monkeypatch)
    monkeypatch.setattr(
        "backend.core.pipeline.enrichment.pictures._extract_picture_bytes",
        lambda *_args, **_kwargs: (None, 3),
    )
    manifest = build_manifest([build_element("pic-1", "picture")], [])

    await _enrich_picture_descriptions(manifest, tmp_path / "doc.pdf", mode="medio")

    assert manifest.elements[0].metadata["vision_failure_reason"] == "crop_unavailable"


# --- delivery ----------------------------------------------------------------


def _describe_obligation(element_id: str) -> Obligation:
    return Obligation(
        id=f"o-describe-{element_id}",
        kind="describe-image",
        target_ids=[element_id],
        admissible_methods=["vision-description", "human-review"],
        method_costs={"vision-description": 20, "human-review": 100},
        rationale="Describe the image",
    )


def _undescribed_docx(reason: str):
    """A DOCX with a heading and one picture the vision stage left with ``reason``."""
    heading = build_element("heading-1", "heading", text="Report", reading_order=1)
    heading.page_number = None
    picture = _pageless_picture("image")
    picture.reading_order = 2
    picture.metadata["vision_failure_reason"] = reason
    return _pageless_manifest([heading, picture], [_describe_obligation("image")])


async def _run(manifest, monkeypatch, tmp_path):
    orchestrator = build_orchestrator(max_replans=2)
    orchestrator.information_structural = SimpleNamespace(
        process=lambda *a, **k: manifest
    )

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(pddl, "inspect_source_media", noop)
    monkeypatch.setattr(pddl, "_enrich_picture_descriptions", noop)
    monkeypatch.setattr(pddl, "_enrich_table_structures", noop)
    return await orchestrator.execute(
        tmp_path / "qa_word.docx", tmp_path, structured_output=True
    )


@pytest.mark.asyncio
async def test_a_docx_whose_only_picture_has_no_image_is_delivered_for_review(
    monkeypatch, tmp_path
):
    payload = await _run(_undescribed_docx("image_unavailable"), monkeypatch, tmp_path)

    metadata = payload["canonical_metadata"]
    [open_obligation] = metadata["pddl_unsatisfied_obligations"]
    assert open_obligation["id"] == "o-describe-image"
    assert open_obligation["escalated"] is True
    assert open_obligation["recovery"] == "human-review"
    assert "describe-image" in metadata["pddl_unsatisfied_summary"]
    alt_texts = [
        block["alt_text"]
        for page in payload["pages"]
        for block in page["blocks"]
        if block["type"] == "image"
    ]
    assert alt_texts == [t(MSG_UNDESCRIBED_PICTURE_ALT)]
    # A Toolbox that forwards the embedded image would describe it: not cached.
    assert metadata["pddl_visual_failures"] == {"pictures": {"image_unavailable": 1}}
    assert payload["cacheable"] is False


@pytest.mark.parametrize("reason", ["crop_unavailable", "model_failed"])
@pytest.mark.asyncio
async def test_a_single_picture_the_model_or_the_render_failed_still_fails(
    monkeypatch, tmp_path, reason
):
    """Unchanged: no picture described because the model or the Toolbox is down."""
    with pytest.raises(RuntimeError, match="describe-image"):
        await _run(_undescribed_docx(reason), monkeypatch, tmp_path)
