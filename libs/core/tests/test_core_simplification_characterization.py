"""Characterization tests for the four simplified core functions (#612).

Covers:
- ``ToolboxManifestExtractor._extract_with`` dual degradation and identical-provider skip;
- ``apply_page_routes`` partial routing, unpaged elements, page descriptors and summary;
- ``ExecutorAgent._execute_step`` handler exceptions vs rejected results, artifact retention and replan flags;
- ``_absorb_near_pictures`` single-picture labels, preserved single captions and side-by-side merges.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from acessilia_sdk.toolbox import (
    ToolboxProviderUnavailable,
    ToolboxTimeout,
    ToolboxUnavailable,
)

from acessilia_core.execution.executor import ExecutorAgent, MethodRegistry, _json_sha256
from acessilia_core.execution.models import MethodResult
from acessilia_core.manifest import toolbox_extractor as extractor_module
from acessilia_core.manifest.models import (
    Artifact,
    BoundingBox,
    ManifestElement,
    Provenance,
)
from acessilia_core.manifest.slides import _absorb_near_pictures
from acessilia_core.manifest.toolbox_extractor import ToolboxManifestExtractor
from acessilia_core.pipeline.fusion import apply_page_routes
from acessilia_core.planning.models import DomainIdentity, NominalPlan, PlanStep
from core_config_support import fusion_config, toolbox_config
from pddl_support import NOW, build_element, build_manifest, build_obligation


# ---------------------------------------------------------------------------
# 1. ToolboxManifestExtractor._extract_with
# ---------------------------------------------------------------------------


class _FakeStructureClient:
    def __init__(
        self,
        *,
        provider: str,
        base_url: str,
        result: dict[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.provider = provider
        self.base_url = base_url
        self._result = result
        self._error = error
        self.closed = False

    async def extract_structure(self, **_kwargs: Any) -> dict[str, Any]:
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result

    async def close(self) -> None:
        self.closed = True


def _structure_payload(provider: str, text: str) -> dict[str, Any]:
    return {
        "status": "succeeded",
        "provider": provider,
        "document": {
            "pages": [
                {
                    "page_number": 1,
                    "width": 600.0,
                    "height": 800.0,
                    "element_ids": ["e-1"],
                }
            ],
            "elements": [
                {
                    "id": "e-1",
                    "type": "paragraph",
                    "text": text,
                    "page_number": 1,
                    "reading_order": 1,
                }
            ],
        },
        "provenance": {
            "provider_version": f"{provider}-1.0",
            "cache_key": f"ck-{provider}",
        },
    }


@pytest.mark.asyncio
async def test_extract_with_primary_ok_and_secondary_failure_degrades_to_primary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    primary = _FakeStructureClient(
        provider="docling",
        base_url="http://primary.test",
        result=_structure_payload("docling", "Primary text"),
    )
    secondary = _FakeStructureClient(
        provider="mineru",
        base_url="http://secondary.test",
        error=ToolboxTimeout("secondary timed out"),
    )
    monkeypatch.setattr(
        extractor_module,
        "make_toolbox_client",
        lambda _cls, _cfg, *, provider: secondary,
    )

    extraction = await ToolboxManifestExtractor()._extract_with(
        primary,
        None,
        pdf,
        use_artifact_store=False,
        fusion_config=fusion_config(mode="dual", secondary_provider="mineru"),
        toolbox_config=toolbox_config(use_artifact_store=False),
        data_dir=tmp_path,
        operations=None,
    )

    assert secondary.closed is True
    assert extraction.document["fusion"] == {
        "status": "degraded",
        "providers": ["docling"],
        "failed_providers": ["mineru"],
        "reason": "ToolboxTimeout",
    }
    assert extraction.document["document"]["elements"][0]["text"] == "Primary text"
    assert extraction.configuration["toolbox_provider"] == "docling"
    assert extraction.configuration["toolbox_base_url"] == "http://primary.test"
    assert extraction.configuration["extraction_degraded"] is True
    assert extraction.configuration["extraction_failures"] == {"mineru": "ToolboxTimeout"}


@pytest.mark.asyncio
async def test_extract_with_primary_failure_and_secondary_ok_degrades_to_secondary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    primary = _FakeStructureClient(
        provider="docling",
        base_url="http://primary.test",
        error=ToolboxProviderUnavailable("docling down"),
    )
    secondary = _FakeStructureClient(
        provider="mineru",
        base_url="http://secondary.test",
        result=_structure_payload("mineru", "Secondary text"),
    )
    monkeypatch.setattr(
        extractor_module,
        "make_toolbox_client",
        lambda _cls, _cfg, *, provider: secondary,
    )

    extraction = await ToolboxManifestExtractor()._extract_with(
        primary,
        None,
        pdf,
        use_artifact_store=False,
        fusion_config=fusion_config(mode="dual", secondary_provider="mineru"),
        toolbox_config=toolbox_config(use_artifact_store=False),
        data_dir=tmp_path,
        operations=None,
    )

    assert secondary.closed is True
    assert extraction.document["fusion"] == {
        "status": "degraded",
        "providers": ["mineru"],
        "failed_providers": ["docling"],
        "reason": "ToolboxProviderUnavailable",
    }
    assert extraction.document["document"]["elements"][0]["text"] == "Secondary text"
    assert extraction.configuration["toolbox_provider"] == "mineru"
    assert extraction.configuration["toolbox_base_url"] == "http://secondary.test"
    assert extraction.configuration["extraction_degraded"] is True
    assert extraction.configuration["extraction_failures"] == {
        "docling": "ToolboxProviderUnavailable"
    }


@pytest.mark.asyncio
async def test_extract_with_both_providers_failing_raises_toolbox_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    primary = _FakeStructureClient(
        provider="docling",
        base_url="http://primary.test",
        error=ToolboxProviderUnavailable("docling down"),
    )
    secondary = _FakeStructureClient(
        provider="mineru",
        base_url="http://secondary.test",
        error=ToolboxTimeout("mineru timeout"),
    )
    monkeypatch.setattr(
        extractor_module,
        "make_toolbox_client",
        lambda _cls, _cfg, *, provider: secondary,
    )

    with pytest.raises(ToolboxUnavailable) as exc_info:
        await ToolboxManifestExtractor()._extract_with(
            primary,
            None,
            pdf,
            use_artifact_store=False,
            fusion_config=fusion_config(mode="dual", secondary_provider="mineru"),
            toolbox_config=toolbox_config(use_artifact_store=False),
            data_dir=tmp_path,
            operations=None,
        )

    assert secondary.closed is True
    endpoints = [endpoint for endpoint, _ in exc_info.value.causes]
    assert endpoints == ["http://primary.test (docling)", "http://secondary.test (mineru)"]


@pytest.mark.asyncio
async def test_extract_with_identical_dual_providers_skips_fusion(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    primary = _FakeStructureClient(
        provider="docling",
        base_url="http://primary.test",
        result=_structure_payload("docling", "Only primary"),
    )

    extraction = await ToolboxManifestExtractor()._extract_with(
        primary,
        None,
        pdf,
        use_artifact_store=False,
        fusion_config=fusion_config(mode="dual", secondary_provider="docling"),
        toolbox_config=toolbox_config(use_artifact_store=False),
        data_dir=tmp_path,
        operations=None,
    )

    assert extraction.document["fusion"] == {
        "status": "skipped",
        "providers": ["docling"],
        "failed_providers": [],
        "reason": "identical-providers",
    }
    assert "extraction_degraded" not in extraction.configuration


# ---------------------------------------------------------------------------
# 2. apply_page_routes
# ---------------------------------------------------------------------------


def test_apply_page_routes_merges_routed_pages_unpaged_elements_and_summary() -> None:
    primary_res = {
        "status": "succeeded",
        "document": {
            "pages": [
                {"page_number": 1, "width": 600.0, "height": 800.0, "element_ids": ["p-1"]},
                {"page_number": 2, "width": 600.0, "height": 800.0, "element_ids": ["p-2"]},
                {"page_number": 3, "width": 600.0, "height": 800.0, "element_ids": ["p-3"]},
            ],
            "elements": [
                {"id": "p-1", "type": "paragraph", "text": "P1", "page_number": 1, "reading_order": 1},
                {"id": "p-2", "type": "paragraph", "text": "P2 primary", "page_number": 2, "reading_order": 2},
                {"id": "p-3", "type": "paragraph", "text": "P3 primary", "page_number": 3, "reading_order": 3},
                {"id": "p-unpaged", "type": "paragraph", "text": "Unpaged", "reading_order": 4},
            ],
            "summary": {"page_count": 3, "element_count": 4, "element_types": {"paragraph": 4}},
        },
    }
    secondary_res = {
        "status": "succeeded",
        "document": {
            "pages": [
                {"page_number": 2, "width": 600.0, "height": 800.0, "element_ids": ["s-2"]},
            ],
            "elements": [
                {"id": "s-2", "type": "table", "text": "P2 secondary", "page_number": 2, "reading_order": 1},
            ],
        },
    }
    # Page 2 has secondary elements; page 3 is preferred for mineru but has none -> stays primary.
    evidence = [
        {"page_number": 1, "stats": {"route": "docling"}},
        {"page_number": 2, "stats": {"route": "mineru"}},
        {"page_number": 3, "stats": {"route": "mineru"}},
    ]

    routed_res, replaced = apply_page_routes(
        primary_res, secondary_res, evidence, secondary_provider="mineru"
    )
    doc = routed_res["document"]

    assert set(replaced) == {2}
    assert [e["id"] for e in replaced[2]] == ["p-2"]
    assert [e["reading_order"] for e in doc["elements"]] == [1, 2, 3, 4]
    assert [e["text"] for e in doc["elements"]] == ["P1", "P2 secondary", "P3 primary", "Unpaged"]
    assert doc["pages"][1]["element_ids"] == [doc["elements"][1]["id"]]
    assert doc["summary"]["page_count"] == 3
    assert doc["summary"]["element_count"] == 4
    assert doc["summary"]["element_types"] == {"paragraph": 3, "table": 1}
    assert evidence[1]["stats"]["applied"] == "mineru"
    assert "applied" not in evidence[2]["stats"]


# ---------------------------------------------------------------------------
# 3. ExecutorAgent._execute_step
# ---------------------------------------------------------------------------


def _single_obligation_plan(
    executor: ExecutorAgent, manifest, obligation_id: str, method: str
) -> NominalPlan:
    return NominalPlan(
        plan_id="plan-1",
        generated_at=NOW,
        manifest_id=manifest.manifest_id,
        manifest_revision=manifest.revision,
        manifest_sha256=_json_sha256(manifest.model_dump(mode="json", by_alias=True)),
        domain=DomainIdentity(
            name=executor.domain.name,
            version=executor.domain.version,
            domain_sha256=executor.domain.domain_sha256,
            description_sha256=executor.domain.description_sha256,
        ),
        problem_name="test-problem",
        problem_sha256="2" * 64,
        planner="internal",
        selected_obligations=[obligation_id],
        expected_total_cost=5,
        steps=[
            PlanStep(index=0, action="start-job"),
            PlanStep(
                index=1,
                action="execute-obligation",
                obligation_id=obligation_id,
                obligation_kind="normalize-text",
                method=method,
                expected_cost=5,
            ),
            PlanStep(index=2, action="complete-job"),
        ],
    )


def test_execute_step_exception_sets_pending_and_replan_when_alternative_exists() -> None:
    element = build_element("el-1", "paragraph", text="Text")
    obligation = build_obligation("normalize-text", ["el-1"], ["method-a", "method-b"])
    obligation.selected = True
    manifest = build_manifest([element], [obligation])
    manifest.status = "planned"

    registry = MethodRegistry()
    registry.register("method-a", lambda _m, _oid: (_ for _ in ()).throw(ValueError("boom")))
    registry.register("method-b", lambda _m, _oid: MethodResult(success=True, validated=True))
    executor = ExecutorAgent(registry=registry)

    updated, report = executor.execute(
        _single_obligation_plan(executor, manifest, "o-1", "method-a"),
        manifest,
    )

    assert report.replan_required is True
    assert updated.obligations[0].status == "pending"
    assert updated.obligations[0].attempts[0].status == "failed"
    assert "ValueError: boom" in (updated.obligations[0].attempts[0].message or "")


def test_execute_step_rejected_result_retains_artifacts_and_marks_failed_without_alternatives() -> None:
    element = build_element("el-1", "paragraph", text="Text")
    obligation = build_obligation("normalize-text", ["el-1"], ["method-a"])
    obligation.selected = True
    manifest = build_manifest([element], [obligation])
    manifest.status = "planned"

    artifact = Artifact(
        id="art-debug",
        kind="debug-dump",
        path="/tmp/debug.json",
        media_type="application/json",
    )
    registry = MethodRegistry()
    registry.register(
        "method-a",
        lambda _m, _oid: MethodResult(
            success=False,
            validated=False,
            message="rejected output",
            artifacts=[artifact],
        ),
    )
    executor = ExecutorAgent(registry=registry)

    updated, report = executor.execute(
        _single_obligation_plan(executor, manifest, "o-1", "method-a"),
        manifest,
    )

    assert report.replan_required is False
    assert updated.obligations[0].status == "failed"
    step_result = next(s for s in report.steps if s.action == "execute-obligation")
    assert step_result.status == "failed"
    assert step_result.artifact_ids == ["art-debug"]
    assert [a.id for a in updated.artifacts] == ["art-debug"]


# ---------------------------------------------------------------------------
# 4. _absorb_near_pictures
# ---------------------------------------------------------------------------


def _slide_el(
    element_id: str,
    element_type: str,
    *,
    text: str | None = None,
    box: tuple[float, float, float, float],
    reading_order: int,
) -> ManifestElement:
    left, top, right, bottom = box
    return ManifestElement(
        id=element_id,
        type=element_type,
        raw_label=element_type,
        reading_order=reading_order,
        hierarchy_level=1,
        text=text,
        page_number=1,
        provenance=[
            Provenance(
                page_number=1,
                bbox=BoundingBox(
                    left=left,
                    top=top,
                    right=right,
                    bottom=bottom,
                    coord_origin="TOPLEFT",
                ),
            )
        ],
    )


def test_absorb_near_pictures_takes_label_keeps_single_caption_and_merges_side_by_side() -> None:
    def fractions(el: ManifestElement) -> tuple[float, float, float, float] | None:
        if not el.provenance or el.provenance[0].bbox is None:
            return None
        b = el.provenance[0].bbox
        return (b.left / 100.0, b.top / 100.0, b.right / 100.0, b.bottom / 100.0)

    # Single picture with a nearby short label (absorbed) and a caption (kept).
    solo = _slide_el("pic-solo", "picture", box=(10, 10, 40, 35), reading_order=1)
    solo_label = _slide_el("lbl-solo", "paragraph", text="Input", box=(15, 36, 30, 40), reading_order=2)
    solo_caption = _slide_el(
        "cap-solo", "caption", text="Figure 1: System overview", box=(10, 41, 40, 45), reading_order=3
    )

    kept_solo = _absorb_near_pictures([solo, solo_label, solo_caption], fractions)
    assert [e.id for e in kept_solo] == ["pic-solo", "cap-solo"]
    assert solo.metadata["figure_labels"] == ["Input"]
    assert solo.metadata["figure_label_ids"] == ["lbl-solo"]
    assert solo.provenance[0].bbox.bottom == 40.0

    # Two side-by-side pictures spanned by a shared caption row -> merged into first.
    left_pic = _slide_el("pic-a", "picture", box=(10, 50, 45, 75), reading_order=1)
    right_pic = _slide_el("pic-b", "picture", box=(55, 50, 90, 75), reading_order=2)
    spanning_caption = _slide_el(
        "cap-row", "caption", text="Left | Right", box=(12, 76, 88, 80), reading_order=3
    )

    kept_merged = _absorb_near_pictures([left_pic, right_pic, spanning_caption], fractions)
    assert [e.id for e in kept_merged] == ["pic-a"]
    assert left_pic.metadata["merged_picture_ids"] == ["pic-b"]
    assert "Left | Right" in left_pic.metadata["figure_labels"]
    assert left_pic.provenance[0].bbox.right == 90.0
    assert left_pic.provenance[0].bbox.bottom == 80.0
