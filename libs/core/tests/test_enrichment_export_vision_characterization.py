"""Characterization tests for export/pandoc_exporter.py, pipeline/enrichment/{inline_math,formulas}.py, pipeline/handlers/inspection.py, and agents/vision_agent.py (#612, PR 10).

Pins key boundaries of the decomposed helpers so ``core alone`` exercises them
directly alongside the root export/vision/formula/inspection suites.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from acessilia_core.agents import vision_agent
from acessilia_core.agents.output_schemas import RunIncompleteError, VisionOutput
from acessilia_core.agents.provider_breaker import ProviderBreaker
from acessilia_core.agents.vision_agent import VisionAgent
from acessilia_core.export import pandoc_exporter
from acessilia_core.manifest.models import BoundingBox, Provenance
from acessilia_core.pipeline.enrichment import formulas as formula_enrichment
from acessilia_core.pipeline.enrichment.inline_math import (
    _is_prose_inline_math_candidate,
    _is_table_inline_math_candidate,
    _table_text_cells,
)
from acessilia_core.pipeline.handlers.inspection import (
    _resolve_region_page_number,
    _validated_region_clip,
)
from acessilia_sdk.toolbox.errors import ToolboxInvalidInput
from core_config_support import document_config, model_config, toolbox_config, vision_config
from pddl_support import build_element, build_manifest


class TestPdfUaMathBisectorCharacterization:
    def test_recovers_single_bad_formula_using_suspect_partition(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        math_nodes = [
            {"t": "Math", "c": [{"t": "InlineMath"}, f"x_{i}"]} for i in range(4)
        ]
        ast = {"blocks": [{"t": "Para", "c": math_nodes}]}
        calls: list[int] = []

        def fake_export(candidate_ast: dict, output_path: Path, **_kw) -> dict:
            remaining = pandoc_exporter.count_math_nodes(candidate_ast)
            calls.append(remaining)
            # Only formula index 2 is bad: once degraded, render succeeds.
            c = candidate_ast["blocks"][0]["c"]
            if c[2]["t"] == "Math":
                raise ToolboxInvalidInput("bad latex")
            output_path.write_bytes(b"%PDF")
            return {}

        monkeypatch.setattr(pandoc_exporter, "toolbox_export_pdf_ua", fake_export)
        monkeypatch.setattr(
            pandoc_exporter, "unconverted_math_indices", lambda _ast, **_kw: {2}
        )

        out = tmp_path / "out.pdf"
        pandoc_exporter._recover_pdf_ua_math(
            ast,
            out,
            lang="en",
            toolbox=toolbox_config(),
            initial_error=ToolboxInvalidInput("initial"),
            max_bisect_attempts=4,
        )
        assert out.read_bytes() == b"%PDF"
        # Suspect partition isolates index 2 in a single retry render.
        assert calls == [3]

    def test_zero_budget_or_no_math_reraises_initial_error(self, tmp_path: Path) -> None:
        err = ToolboxInvalidInput("no math")
        with pytest.raises(ToolboxInvalidInput, match="no math"):
            pandoc_exporter._recover_pdf_ua_math(
                {"blocks": []},
                tmp_path / "out.pdf",
                lang="en",
                toolbox=toolbox_config(),
                initial_error=err,
            )


class TestInlineMathAndInspectionHelpersCharacterization:
    def test_inline_math_candidate_predicates_and_table_cells(self) -> None:
        boxed = Provenance(
            page_number=1,
            bbox=BoundingBox(left=0, top=0, right=10, bottom=10, coord_origin="TOPLEFT"),
        )
        prose_ok = build_element("p1", "paragraph", text="a + b").model_copy(
            update={"provenance": [boxed]}
        )
        prose_done = prose_ok.model_copy(
            update={"metadata": {"inline_math_detection": {"marked": 0, "unmatched": 0}}}
        )
        assert _is_prose_inline_math_candidate(prose_ok) is True
        assert _is_prose_inline_math_candidate(prose_done) is False

        table = build_element(
            "t1",
            "table",
            text="",
            metadata={
                "table_ast": {
                    "header": [{"cells": [{"text": "H1"}, {"text": None}]}],
                    "body": ["bad-row", {"cells": [{"text": "B1"}]}],
                }
            },
        ).model_copy(update={"provenance": [boxed]})
        assert _is_table_inline_math_candidate(table) is True
        assert [c["text"] for c in _table_text_cells(table)] == ["H1", "B1"]

    def test_region_page_and_clip_validators_reject_invalid_inputs(self) -> None:
        inconsistent = build_element("u1", "unknown", text="").model_copy(
            update={
                "page_number": 2,
                "provenance": [Provenance(page_number=1)],
            }
        )
        with pytest.raises(ValueError, match="inconsistent"):
            _resolve_region_page_number(inconsistent)

        unknown_origin = build_element("u2", "unknown", text="").model_copy(
            update={
                "page_number": 1,
                "provenance": [
                    Provenance(
                        page_number=1,
                        bbox=BoundingBox(
                            left=0, top=0, right=10, bottom=10, coord_origin="UNKNOWN"
                        ),
                    )
                ],
            }
        )
        with pytest.raises(ValueError, match="origin is unknown"):
            _validated_region_clip(unknown_origin)

        non_finite = build_element("u3", "unknown", text="").model_copy(
            update={
                "page_number": 1,
                "provenance": [
                    Provenance(
                        page_number=1,
                        bbox=BoundingBox(
                            left=float("nan"),
                            top=0,
                            right=10,
                            bottom=10,
                            coord_origin="TOPLEFT",
                        ),
                    )
                ],
            }
        )
        with pytest.raises(ValueError, match="finite"):
            _validated_region_clip(non_finite)


class TestFormulaEnrichmentAndVisionRetryCharacterization:
    @pytest.mark.asyncio
    async def test_enrich_formula_latex_falls_back_to_vision_and_reclassifies_drawing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        f_el = build_element("element-f1", "formula", text="").model_copy(
            update={"page_number": 1}
        )
        manifest = build_manifest([f_el], [])

        monkeypatch.setattr(
            formula_enrichment,
            "_formula_recognition_crop",
            lambda *_a, **_kw: (b"png-bytes", 1),
        )
        monkeypatch.setattr(
            formula_enrichment,
            "toolbox_recognize_formula",
            lambda *_a, **_kw: [],
        )

        class FakeVision:
            def __init__(self, **_kw) -> None:
                pass

            async def describe_region(self, **_kw) -> VisionOutput:
                return VisionOutput(
                    kind="description",
                    description="Molecular diagram of benzene ring.",
                    language="en",
                    confidence=0.95,
                )

        monkeypatch.setattr(formula_enrichment, "VisionAgent", FakeVision)
        await formula_enrichment._enrich_formula_latex(
            manifest,
            tmp_path / "doc.pdf",
            mode="medio",
            document=document_config(),
            vision=vision_config(),
            toolbox=toolbox_config(),
            models=model_config(),
            region_cache=None,
            breaker=ProviderBreaker(3),
        )
        assert f_el.type == "picture"
        assert f_el.text == "Molecular diagram of benzene ring."
        assert f_el.metadata["formula_classification"]["reason"] == "recognition_fallback"

    @pytest.mark.asyncio
    async def test_vision_retry_runner_retries_timeout_and_rate_limit_without_spending_attempts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = 0

        class FakeAgent:
            def __init__(self, **_kw) -> None:
                pass

            def run(self, **_kw):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise TimeoutError("stalled")
                if calls == 2:
                    raise RunIncompleteError("error", "HTTP 429 rate limit exceeded")
                return SimpleNamespace(
                    content=VisionOutput(
                        kind="description",
                        description="A clear chart showing steady growth.",
                        language="en",
                        confidence=0.9,
                    )
                )

        async def no_sleep(_delay: float) -> None:
            pass

        monkeypatch.setattr(vision_agent, "Agent", FakeAgent)
        monkeypatch.setattr(vision_agent, "get_agno_model", lambda *_a, **_kw: object())
        monkeypatch.setattr(vision_agent.asyncio, "sleep", no_sleep)

        class InlineRunner:
            async def run(self, fn, **_kw):
                return fn()

        agent = VisionAgent(
            mode="medio",
            region_cache=None,
            toolbox=toolbox_config(),
            models=model_config(),
            model_calls=InlineRunner(),
        )
        result = await agent.describe_region(
            image_bytes=b"img", classification="embedded_image", page_num=1, total_pages=1
        )
        assert result is not None
        assert result.description == "A clear chart showing steady growth."
        assert calls == 3
