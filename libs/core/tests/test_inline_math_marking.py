"""The core writes the inline math of PDF prose as $…$ from the text layer's fonts (#265)."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from core_config_support import core_config, document_config, toolbox_config
from pddl_support import build_element, build_manifest, build_orchestrator

from acessilia_core.manifest.models import BoundingBox, PageDescriptor, Provenance
from acessilia_core.pipeline import orchestrator as pddl
from acessilia_core.pipeline.enrichment import inline_math as inline_math_stage
from acessilia_core.ports import RunPorts

HEIGHT = 792.0


def _span(text, font, x, size=11.96, baseline=225.96):
    width = max(len(text), 1) * size * 0.5
    return {
        "text": text, "font": font, "size": size, "flags": 4,
        "bbox": [x, baseline - size * 0.75, x + width, baseline + size * 0.25],
        "origin": [x, baseline],
    }


def _page(*lines):
    return {"page_number": 1, "width": 612.0, "height": HEIGHT, "rotation": 0,
            "lines": [{"bbox": [0, 0, 0, 0], "spans": list(line)} for line in lines]}


PARAGRAPH_LINE = [
    _span("inicial", "CMR12", 60), _span("´e", "CMR12", 110), _span("s", "CMMI12", 130),
    _span("0", "CMR8", 137, size=7.97, baseline=227.76), _span("∈", "CMSY10", 145),
    _span("R", "MSBM10", 155), _span(",", "CMR12", 163), _span("h", "CMMI12", 175),
    _span("̸", "CMSY10", 183), _span("= 0", "CMR12", 183),
]
#: A display formula below the paragraph: its spans must not reach the paragraph.
DISPLAY_LINE = [_span("x", "CMMI12", 200, baseline=300.0), _span("= 1", "CMR12", 210, baseline=300.0)]


def _element(element_id, element_type, text, top, bottom, left=50.0, right=560.0, reading_order=1):
    element = build_element(element_id, element_type, text=text, reading_order=reading_order)
    # Docling boxes come with a bottom-left origin.
    element.provenance = [Provenance(page_number=1, bbox=BoundingBox(
        left=left, top=HEIGHT - top, right=right, bottom=HEIGHT - bottom, coord_origin="BOTTOMLEFT"))]
    return element


def _manifest():
    paragraph = _element("p1", "paragraph", "inicial ´ e s 0 ∈ R , h = 0", 210, 232)
    slash = _element("slash", "paragraph", "̸", 214, 228, left=181, right=186, reading_order=2)
    formula = _element("f1", "formula", "x = 1", 290, 305, reading_order=3)
    manifest = build_manifest([paragraph, slash, formula], [])
    manifest.pages = [PageDescriptor(page_number=1, height=HEIGHT, width=612.0,
                                     element_ids=["p1", "slash", "f1"])]
    return manifest


#: The run's Toolbox config: the reader passes it, not one built from the settings.
RUN_TOOLBOX = toolbox_config(use_remote_cache=False)


@pytest.fixture
def spans(monkeypatch):
    calls = []

    async def fetch(source_path, pages, *, toolbox, artifact_id=None, client=None):
        assert toolbox is RUN_TOOLBOX
        calls.append(pages)
        return {1: _page(PARAGRAPH_LINE, DISPLAY_LINE)}

    monkeypatch.setattr("acessilia_core.toolbox.text_spans.fetch_text_spans", fetch)
    return calls


def _run(manifest, detection="fonts"):
    document = document_config(inline_math_detection=detection)
    return asyncio.run(
        inline_math_stage._mark_inline_math(
            manifest,
            Path("/tmp/amostra.pdf"),
            document,
            inline_math_stage._TextSpanReader(manifest, Path("/tmp/amostra.pdf"), RUN_TOOLBOX),
        )
    )


def test_prose_gets_its_inline_math_and_formulas_are_left_alone(spans):
    manifest = _manifest()

    counts = _run(manifest)

    paragraph, _, formula = manifest.elements
    assert paragraph.text == r"inicial ´ e $s_0\in\mathbb{R}$, $h\neq0$"
    assert paragraph.metadata["inline_math_detection"] == {"marked": 2, "unmatched": 0}
    assert formula.text == "x = 1"
    assert counts == {"elements": 1, "marked": 2, "unmatched": 0}
    assert spans == [[1]]
    assert manifest.extractor.configuration["inline_math_detection"] == "fonts"


def test_the_composed_slash_is_claimed_so_the_reattachment_skips_it(spans):
    manifest = _manifest()

    _run(manifest)

    slash = manifest.elements[1]
    assert slash.metadata["negation_overlay"] == {"outcome": "inline-math", "host": "p1"}


def test_an_unavailable_capability_leaves_the_text(monkeypatch, spans):
    from acessilia_sdk.toolbox.errors import ToolboxError

    async def failing(*args, **kwargs):
        raise ToolboxError("document.text.spans is not in the catalogue")

    monkeypatch.setattr("acessilia_core.toolbox.text_spans.fetch_text_spans", failing)
    manifest = _manifest()

    assert _run(manifest)["marked"] == 0
    assert manifest.elements[0].text == "inicial ´ e s 0 ∈ R , h = 0"
    assert manifest.extractor.configuration["inline_math_detection"] == "unavailable"


def test_off_does_not_call_the_toolbox(monkeypatch, spans):
    manifest = _manifest()

    _run(manifest, detection="off")

    assert spans == []
    assert manifest.elements[0].text == "inicial ´ e s 0 ∈ R , h = 0"


def test_other_media_are_skipped(spans):
    manifest = _manifest()
    manifest.source.media_type = "image/png"

    _run(manifest)

    assert spans == []


# Characterization of the span geometry (#402), written on develop before it
# moved to docstruct.text.inline_math.


def _top_left(manifest):
    for element in manifest.elements:
        box = element.provenance[0].bbox
        element.provenance[0].bbox = BoundingBox(
            left=box.left, top=HEIGHT - box.top, right=box.right, bottom=HEIGHT - box.bottom,
            coord_origin="TOPLEFT")
    return manifest


def test_a_top_left_box_reads_the_same_spans(spans):
    manifest = _top_left(_manifest())

    _run(manifest)

    paragraph, slash, _ = manifest.elements
    assert paragraph.text == r"inicial ´ e $s_0\in\mathbb{R}$, $h\neq0$"
    assert slash.metadata["negation_overlay"] == {"outcome": "inline-math", "host": "p1"}


def _fetch_page(monkeypatch, **changes):
    async def fetch(source_path, pages, *, toolbox, artifact_id=None, client=None):
        return {1: {**_page(PARAGRAPH_LINE, DISPLAY_LINE), **changes}}

    monkeypatch.setattr("acessilia_core.toolbox.text_spans.fetch_text_spans", fetch)


def test_a_rotated_page_is_left_out(monkeypatch, spans):
    _fetch_page(monkeypatch, rotation=90)
    manifest = _manifest()

    assert _run(manifest) == {"elements": 0, "marked": 0, "unmatched": 0}
    assert "inline_math_detection" not in manifest.elements[0].metadata


def test_a_bottom_left_box_takes_the_manifest_height_when_the_spans_have_none(monkeypatch, spans):
    _fetch_page(monkeypatch, height=None)
    manifest = _manifest()

    assert _run(manifest)["marked"] == 2

    _fetch_page(monkeypatch, height=None)
    manifest = _manifest()
    manifest.pages[0].height = None

    assert _run(manifest)["marked"] == 0


def test_a_box_of_unknown_origin_is_left_out(spans):
    manifest = _manifest()
    for element in manifest.elements:
        element.provenance[0].bbox.coord_origin = "UNKNOWN"

    assert _run(manifest)["marked"] == 0


# The second pass, after the plan inserted the blocks `rescue-omitted` restores (#599).

SOURCE = Path("/tmp/amostra.pdf")
FLAT = "inicial ´ e s 0 ∈ R , h = 0"


def _first_pass(manifest, ports, detection="fonts"):
    """The prose step before planning, through the run's shared reader."""
    asyncio.run(
        inline_math_stage._mark_inline_math(
            manifest,
            SOURCE,
            document_config(inline_math_detection=detection),
            inline_math_stage.run_text_spans(ports, manifest, SOURCE, RUN_TOOLBOX),
        )
    )


def _after_execution(manifest, ports, baseline=None, detection="fonts"):
    """What ``execute`` runs after the plan: both steps over the run's reader (#599)."""
    asyncio.run(
        inline_math_stage._mark_inline_math_after_execution(
            manifest,
            baseline or manifest,
            SOURCE,
            document_config(inline_math_detection=detection),
            ports,
            RUN_TOOLBOX,
        )
    )


def test_the_second_pass_marks_only_the_block_the_plan_added(spans):
    ports = RunPorts.none()
    manifest = _manifest()
    _first_pass(manifest, ports)
    marked_before, _, _ = manifest.elements
    text_before = marked_before.text
    assert marked_before.metadata["inline_math_detection"] == {"marked": 2, "unmatched": 0}

    baseline = manifest.model_copy(deep=True)
    restored = _element("p2", "paragraph", FLAT, 210, 232, reading_order=4)
    manifest.elements.append(restored)

    _after_execution(manifest, ports, baseline)

    assert marked_before.text == text_before
    assert marked_before.metadata["inline_math_detection"] == {"marked": 2, "unmatched": 0}
    assert restored.text == r"inicial ´ e $s_0\in\mathbb{R}$, $h\neq0$"
    assert restored.metadata["inline_math_detection"] == {"marked": 2, "unmatched": 0}
    assert spans == [[1]], "the reader reuses the page it already fetched"


def test_a_reader_that_failed_is_not_asked_again(monkeypatch):
    from acessilia_sdk.toolbox.errors import ToolboxError

    calls = []

    async def failing(source_path, pages, *, toolbox, artifact_id=None, client=None):
        calls.append(pages)
        raise ToolboxError("document.text.spans is not in the catalogue")

    monkeypatch.setattr("acessilia_core.toolbox.text_spans.fetch_text_spans", failing)
    ports = RunPorts.none()
    planning = _manifest()
    _first_pass(planning, ports)
    assert planning.extractor.configuration["inline_math_detection"] == "unavailable"
    executed = planning.model_copy(deep=True)

    _after_execution(executed, ports)

    assert calls == [[1]], "a capability that failed is not asked again"
    assert executed.extractor.configuration["inline_math_detection"] == "unavailable"


def test_a_page_the_second_pass_cannot_read_is_recorded_on_the_executed_manifest(
    monkeypatch,
):
    from acessilia_sdk.toolbox.errors import ToolboxError

    calls = []

    async def fetch(source_path, pages, *, toolbox, artifact_id=None, client=None):
        calls.append(pages)
        if pages != [1]:
            raise ToolboxError("document.text.spans failed after planning")
        return {1: _page(PARAGRAPH_LINE, DISPLAY_LINE)}

    monkeypatch.setattr("acessilia_core.toolbox.text_spans.fetch_text_spans", fetch)
    ports = RunPorts.none()
    planning = _manifest()
    _first_pass(planning, ports)
    assert planning.extractor.configuration["inline_math_detection"] == "fonts"

    executed = planning.model_copy(deep=True)
    restored = _element("p2", "paragraph", FLAT, 210, 232, reading_order=4)
    restored.page_number = 2
    restored.provenance[0].page_number = 2
    executed.elements.append(restored)
    executed.pages.append(
        PageDescriptor(page_number=2, height=HEIGHT, width=612.0, element_ids=["p2"])
    )

    _after_execution(executed, ports)

    assert calls == [[1], [2]], "page 1 is reused; page 2 is the one that fails"
    assert restored.text == FLAT
    assert planning.extractor.configuration["inline_math_detection"] == "fonts"
    assert executed.extractor.configuration["inline_math_detection"] == "unavailable"


def test_the_second_pass_builds_a_reader_when_the_run_resumed(monkeypatch):
    from acessilia_sdk.toolbox.errors import ToolboxError

    async def failing(*_args, **_kwargs):
        raise ToolboxError("document.text.spans is not in the catalogue")

    monkeypatch.setattr("acessilia_core.toolbox.text_spans.fetch_text_spans", failing)
    manifest = _manifest()

    _after_execution(manifest, RunPorts.none())

    assert manifest.elements[0].text == FLAT
    assert manifest.extractor.configuration["inline_math_detection"] == "unavailable"


def test_off_does_not_call_the_toolbox_in_the_second_pass(spans):
    manifest = _manifest()

    _after_execution(manifest, RunPorts.none(), detection="off")

    assert spans == []
    assert manifest.elements[0].text == FLAT


def test_the_pipeline_marks_a_block_the_plan_restored(monkeypatch, tmp_path):
    """Through ``execute``: the block rescue-omitted inserts gets its `$…$` (#599)."""
    from types import SimpleNamespace

    from acessilia_core.agents.model_calls import current_model_calls
    from docstruct.canonical import build_canonical_document

    calls = []

    async def fetch(source_path, pages, *, toolbox, artifact_id=None, client=None):
        calls.append(pages)
        return {1: _page(PARAGRAPH_LINE, DISPLAY_LINE)}

    async def no_media(*_args, **_kwargs):
        return None, {}

    async def no_stage(*_args, **_kwargs):
        return None

    monkeypatch.setattr("acessilia_core.toolbox.text_spans.fetch_text_spans", fetch)
    monkeypatch.setattr(pddl, "_inspect_media", no_media)
    for name in (
        "_classify_formula_regions",
        "_enrich_picture_descriptions",
        "_enrich_formula_latex",
    ):
        monkeypatch.setattr(pddl, name, no_stage)

    planning = _manifest()
    orchestrator = build_orchestrator()
    orchestrator.information_structural = SimpleNamespace(process=lambda *_a, **_k: planning)

    async def run_plan(*_args, **_kwargs):
        executed = planning.model_copy(deep=True)
        executed.elements.append(
            _element(
                "p2", "paragraph", "inicial ´ e s 0 ∈ R , h = 0", 210, 232, reading_order=4
            )
        )
        executed.pages[0].element_ids.append("p2")
        return executed, SimpleNamespace(
            replan_required=False, status="completed", execution_id="exec-599"
        )

    monkeypatch.setattr(orchestrator, "_run_plan", run_plan)

    payload = asyncio.run(
        orchestrator.execute(
            tmp_path / "amostra.pdf",
            tmp_path,
            structured_output=True,
            config=core_config(),
            model_calls=current_model_calls(),
            ports=RunPorts.none(),
        )
    )

    restored = next(
        block for page in payload["pages"] for block in page["blocks"] if block["id"] == "p2"
    )
    assert restored["text"] == r"inicial ´ e $s_0\in\mathbb{R}$, $h\neq0$"
    assert calls == [[1]]

    class _Enricher:
        def normalize(self, latex):
            return latex

        def to_mathml(self, latex):
            return f"<math>{latex}</math>"

        def verbalize(self, latex):
            return f"Formula: {latex}"

        def verbalize_inline(self, latex):
            return f"fala {latex}"

    document = build_canonical_document(payload, title="t", math_enricher=_Enricher())
    block = next(
        block for section in document["sections"] for block in section["blocks"]
        if block["id"] == "p2"
    )
    entries = block["metadata"]["inline_math"]
    assert [entry["source"] for entry in entries] == [
        r"s_0\in\mathbb{R}",
        r"h\neq0",
    ]
    assert all(entry.get("mathml") and entry.get("speech") for entry in entries)
