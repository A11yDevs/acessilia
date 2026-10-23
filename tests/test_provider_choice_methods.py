"""v2.3 methods that choose between the two providers of FUSION_MODE=dual.

table-smart-fusion, skeleton-order and agreement-rule read the secondary
provider's extraction that the structure extractor keeps as a manifest artifact
(kind ``provider-extraction``, content hash recorded).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.agents.pddl_orchestrator import (
    PddlAccessibilityOrchestrator,
    _handle_agreement_rule_method,
    _handle_skeleton_order_method,
    _handle_table_smart_fusion_method,
)
from backend.core.manifest.builder import (
    DEFAULT_METHOD_COSTS,
    SECONDARY_EXTRACTION_ARTIFACT_ID,
    SECONDARY_EXTRACTION_KIND,
)
from backend.core.manifest.models import (
    Artifact,
    BoundingBox,
    ExtractorRun,
    ManifestElement,
    ManifestSummary,
    Obligation,
    PageDescriptor,
    ProcessingManifest,
    Provenance,
    SourceDocument,
)
from backend.core.planning.planner_agent import PlannerAgent

NOW = datetime(2026, 10, 16, tzinfo=timezone.utc)
W, H = 600.0, 800.0
LEFT = (40, 100, 280, 300)
RIGHT = (320, 100, 560, 300)
BOTTOM = (40, 400, 560, 600)


def _el(element_id, kind, text, box, order, metadata=None) -> ManifestElement:
    left, top, right, bottom = box
    return ManifestElement(
        id=element_id,
        type=kind,
        raw_label=kind,
        reading_order=order,
        hierarchy_level=1,
        text=text,
        page_number=1,
        provenance=[
            Provenance(
                page_number=1,
                bbox=BoundingBox(
                    left=left, top=top, right=right, bottom=bottom, coord_origin="TOPLEFT"
                ),
            )
        ],
        metadata=metadata or {},
    )


def _raw(kind, text, box, order, metadata=None) -> dict:
    """A Toolbox element as the secondary provider returns it (BOTTOMLEFT)."""
    left, top, right, bottom = box
    return {
        "id": f"m-{order}",
        "type": kind,
        "text": text,
        "reading_order": order,
        "page_number": 1,
        "provenance": [
            {
                "page_number": 1,
                "bbox": {
                    "left": left,
                    "top": H - top,
                    "right": right,
                    "bottom": H - bottom,
                    "coord_origin": "BOTTOMLEFT",
                },
            }
        ],
        "metadata": metadata or {},
    }


def _manifest(
    tmp_path: Path,
    elements: list[ManifestElement],
    kind: str,
    methods: list[str],
    secondary: list[dict],
    *,
    primary: str = "docling",
    secondary_provider: str = "mineru",
) -> ProcessingManifest:
    content = json.dumps(
        {
            "provider": secondary_provider,
            "document": {
                "document": {
                    "pages": [{"page_number": 1, "width": W, "height": H}],
                    "elements": secondary,
                }
            },
        }
    ).encode()
    path = tmp_path / "secondary.json"
    path.write_bytes(content)
    return ProcessingManifest(
        manifest_id="manifest-provider-choice",
        created_at=NOW,
        source=SourceDocument(
            document_id="doc",
            filename="doc.pdf",
            path=str(tmp_path / "doc.pdf"),
            media_type="application/pdf",
            byte_size=1,
            sha256="a" * 64,
        ),
        extractor=ExtractorRun(
            version="1",
            started_at=NOW,
            completed_at=NOW,
            duration_ms=1,
            configuration={"toolbox_provider": primary},
        ),
        title="Doc",
        language="pt-BR",
        pages=[
            PageDescriptor(
                page_number=1, width=W, height=H, element_ids=[e.id for e in elements]
            )
        ],
        elements=elements,
        obligations=[
            Obligation(
                id="o-1",
                kind=kind,
                target_ids=[e.id for e in elements],
                admissible_methods=methods,
                method_costs={m: DEFAULT_METHOD_COSTS[m] for m in methods},
                rationale="test",
            )
        ],
        artifacts=[
            Artifact(
                id=SECONDARY_EXTRACTION_ARTIFACT_ID,
                kind=SECONDARY_EXTRACTION_KIND,
                path=str(path),
                media_type="application/json",
                sha256=hashlib.sha256(content).hexdigest(),
            )
        ],
        summary=ManifestSummary(
            page_count=1,
            element_count=len(elements),
            observation_count=0,
            obligation_count=1,
            element_types={},
        ),
    )


SIMPLE_AST = {"body": [{"cells": [{"text": "a"}, {"text": "b"}]}]}
SPAN_AST = {"body": [{"cells": [{"text": "a", "colspan": 2}]}]}
MINERU_AST = {"body": [{"cells": [{"text": "A"}, {"text": "B"}]}]}


class TestTableSmartFusion:
    def _run(self, tmp_path, primary_ast, secondary, **kwargs):
        table = _el("t-1", "table", "a | b", LEFT, 1, {"table_ast": primary_ast})
        manifest = _manifest(
            tmp_path,
            [table],
            "select-table-source",
            ["table-smart-fusion", "human-review"],
            secondary,
            **kwargs,
        )
        return manifest, table, _handle_table_smart_fusion_method(manifest, "o-1")

    def test_adopts_the_paired_mineru_table(self, tmp_path) -> None:
        _, table, result = self._run(
            tmp_path,
            SIMPLE_AST,
            [_raw("table", "A | B", LEFT, 1, {"table_ast": MINERU_AST})],
        )

        assert result.success and result.validated
        assert table.text == "A | B"
        assert table.metadata["table_ast"] == MINERU_AST
        assert table.metadata["table_source"] == "mineru"
        assert table.metadata["table_source_reason"] == "preference-mineru"

    def test_keeps_docling_when_its_table_has_spans(self, tmp_path) -> None:
        _, table, result = self._run(
            tmp_path,
            SPAN_AST,
            [_raw("table", "A | B", LEFT, 1, {"table_ast": MINERU_AST})],
        )

        assert result.success
        assert table.text == "a | b"
        assert table.metadata["table_ast"] == SPAN_AST
        assert table.metadata["table_source_reason"] == "primary-has-spans"

    def test_keeps_docling_when_mineru_has_no_table_there(self, tmp_path) -> None:
        _, table, result = self._run(
            tmp_path, SIMPLE_AST, [_raw("paragraph", "texto", BOTTOM, 1)]
        )

        assert result.success
        assert table.metadata["table_source_reason"] == "no-secondary-table"

    def test_adoption_without_secondary_ast_drops_the_primary_ast(self, tmp_path) -> None:
        """Docling's AST would otherwise win over the adopted MinerU text."""
        table = _el(
            "t-1",
            "table",
            "a | b",
            LEFT,
            1,
            {"table_ast": SIMPLE_AST, "table_row_count": 1, "table_has_header": False},
        )
        manifest = _manifest(
            tmp_path,
            [table],
            "select-table-source",
            ["table-smart-fusion", "human-review"],
            [_raw("table", "A | B", LEFT, 1)],
        )

        result = _handle_table_smart_fusion_method(manifest, "o-1")

        assert result.success
        assert table.text == "A | B"
        assert not {"table_ast", "table_row_count", "table_has_header"} & set(
            table.metadata
        )
        assert table.metadata["table_source"] == "mineru"

    def test_a_single_mineru_table_elsewhere_is_not_paired(self, tmp_path) -> None:
        _, table, result = self._run(
            tmp_path,
            SIMPLE_AST,
            [_raw("table", "outra tabela", BOTTOM, 1, {"table_ast": MINERU_AST})],
        )

        assert result.success
        assert table.text == "a | b"
        assert table.metadata["table_ast"] == SIMPLE_AST
        assert table.metadata["table_source_reason"] == "no-secondary-match"

    def test_a_single_table_on_each_side_pairs_without_position(self, tmp_path) -> None:
        table = _el("t-1", "table", "a | b", LEFT, 1, {"table_ast": SIMPLE_AST})
        table.provenance = []
        manifest = _manifest(
            tmp_path,
            [table],
            "select-table-source",
            ["table-smart-fusion", "human-review"],
            [_raw("table", "outra tabela", BOTTOM, 1, {"table_ast": MINERU_AST})],
        )

        _handle_table_smart_fusion_method(manifest, "o-1")

        assert table.metadata["table_ast"] == MINERU_AST
        assert table.metadata["table_source_reason"] == "preference-mineru"

    def test_ignores_secondary_blocks_with_a_malformed_page(self, tmp_path) -> None:
        broken = _raw("table", "A | B", LEFT, 1, {"table_ast": MINERU_AST})
        broken["page_number"] = "um"
        broken["provenance"][0]["page_number"] = None
        _, table, result = self._run(tmp_path, SIMPLE_AST, [broken])

        assert result.success
        assert table.metadata["table_source_reason"] == "no-secondary-table"

    def test_pairs_by_position_not_order(self, tmp_path) -> None:
        """With two MinerU tables, the one at the same place is chosen."""
        _, table, _ = self._run(
            tmp_path,
            SIMPLE_AST,
            [
                _raw("table", "outra", RIGHT, 1, {"table_ast": SIMPLE_AST}),
                _raw("table", "A | B", LEFT, 2, {"table_ast": MINERU_AST}),
            ],
        )
        assert table.text == "A | B"

    def test_refuses_an_uncalibrated_provider_pair(self, tmp_path) -> None:
        _, table, result = self._run(
            tmp_path,
            SIMPLE_AST,
            [_raw("table", "A | B", LEFT, 1, {"table_ast": MINERU_AST})],
            secondary_provider="nougat",
        )

        assert not result.success
        assert "calibrada" in result.message
        assert table.text == "a | b"

    def test_refuses_a_replaced_artifact(self, tmp_path) -> None:
        table = _el("t-1", "table", "a | b", LEFT, 1, {"table_ast": SIMPLE_AST})
        manifest = _manifest(
            tmp_path,
            [table],
            "select-table-source",
            ["table-smart-fusion", "human-review"],
            [_raw("table", "A | B", LEFT, 1, {"table_ast": MINERU_AST})],
        )
        Path(manifest.artifacts[0].path).write_text('{"provider": "mineru"}')

        result = _handle_table_smart_fusion_method(manifest, "o-1")

        assert not result.success
        assert "sha256 diverge" in result.message
        assert table.text == "a | b"


class TestSkeletonOrder:
    def test_follows_the_secondary_reading_order(self, tmp_path) -> None:
        right = _el("e-right", "paragraph", "coluna direita", RIGHT, 1)
        left = _el("e-left", "paragraph", "coluna esquerda", LEFT, 2)
        manifest = _manifest(
            tmp_path,
            [right, left],
            "refine-reading-order",
            ["skeleton-order", "human-review"],
            [
                _raw("paragraph", "coluna esquerda", LEFT, 1),
                _raw("paragraph", "coluna direita", RIGHT, 2),
            ],
        )

        result = _handle_skeleton_order_method(manifest, "o-1")

        assert result.success and result.validated
        assert (left.reading_order, right.reading_order) == (1, 2)
        assert manifest.pages[0].element_ids == ["e-left", "e-right"]

    def test_unpaired_element_stays_after_its_predecessor(self, tmp_path) -> None:
        a = _el("e-a", "paragraph", "bloco a", LEFT, 1)
        x = _el("e-x", "paragraph", "só no primário", BOTTOM, 2)
        b = _el("e-b", "paragraph", "bloco b", RIGHT, 3)
        manifest = _manifest(
            tmp_path,
            [a, x, b],
            "refine-reading-order",
            ["skeleton-order", "human-review"],
            [_raw("paragraph", "bloco b", RIGHT, 1), _raw("paragraph", "bloco a", LEFT, 2)],
        )

        _handle_skeleton_order_method(manifest, "o-1")

        assert sorted([a, x, b], key=lambda e: e.reading_order) == [b, a, x]

    def test_confirms_an_order_the_skeleton_agrees_with(self, tmp_path) -> None:
        left = _el("e-left", "paragraph", "coluna esquerda", LEFT, 1)
        right = _el("e-right", "paragraph", "coluna direita", RIGHT, 2)
        manifest = _manifest(
            tmp_path,
            [left, right],
            "refine-reading-order",
            ["skeleton-order", "human-review"],
            [
                _raw("paragraph", "coluna esquerda", LEFT, 1),
                _raw("paragraph", "coluna direita", RIGHT, 2),
            ],
        )

        result = _handle_skeleton_order_method(manifest, "o-1")

        assert result.success
        assert "confirmada" in result.message
        assert (left.reading_order, right.reading_order) == (1, 2)

    def test_fails_when_the_skeleton_does_not_match_the_page(self, tmp_path) -> None:
        left = _el("e-left", "paragraph", "coluna esquerda", LEFT, 1)
        right = _el("e-right", "paragraph", "coluna direita", RIGHT, 2)
        manifest = _manifest(
            tmp_path,
            [left, right],
            "refine-reading-order",
            ["skeleton-order", "human-review"],
            [_raw("paragraph", "nada a ver", BOTTOM, 1)],
        )

        result = _handle_skeleton_order_method(manifest, "o-1")

        assert not result.success
        assert (left.reading_order, right.reading_order) == (1, 2)


class TestAgreementRule:
    def _manifest(self, tmp_path, secondary):
        elements = [
            _el("p-1", "paragraph", "Texto da página com conteúdo suficiente para o roteador decidir.", LEFT, 1),
        ]
        return _manifest(
            tmp_path,
            elements,
            "adjudicate-page",
            ["agreement-rule", "human-review"],
            secondary,
        )

    def test_keeps_the_primary_page(self, tmp_path) -> None:
        manifest = self._manifest(
            tmp_path,
            [_raw("paragraph", "Texto da página com conteúdo parecido para o roteador decidir.", LEFT, 1)],
        )

        result = _handle_agreement_rule_method(manifest, "o-1")

        assert result.success and result.validated
        assert manifest.elements[0].metadata["page_route"] == {
            "choice": "docling",
            "reason": "default_docling",
        }

    def test_rerouted_page_is_recorded_and_escalated(self, tmp_path) -> None:
        """MinerU wins on a table only it found; the page is not swapped."""
        manifest = self._manifest(
            tmp_path,
            [
                _raw("paragraph", "Texto da página com conteúdo parecido para o roteador decidir.", LEFT, 1),
                _raw("table", "A | B", BOTTOM, 2),
            ],
        )
        text_before = manifest.elements[0].text

        result = _handle_agreement_rule_method(manifest, "o-1")

        assert not result.success
        assert "only_mineru_table" in result.message
        assert manifest.elements[0].metadata["page_route"]["choice"] == "mineru"
        assert manifest.elements[0].text == text_before

    def test_escalation_reaches_human_review_through_replanning(self, tmp_path) -> None:
        manifest = self._manifest(
            tmp_path,
            [
                _raw("paragraph", "Texto da página com conteúdo parecido para o roteador decidir.", LEFT, 1),
                _raw("table", "A | B", BOTTOM, 2),
            ],
        )
        executor = PddlAccessibilityOrchestrator._build_executor()

        _, plan = PlannerAgent().plan(manifest, selected_roots=["o-1"])
        assert [s.method for s in plan.steps if s.method] == ["agreement-rule"]
        manifest, report = executor.execute(plan, manifest, dry_run=False)
        assert report.replan_required

        _, replan = PlannerAgent().plan(manifest, selected_roots=["o-1"])
        assert [s.method for s in replan.steps if s.method] == ["human-review"]


@pytest.mark.parametrize(
    "handler",
    [
        _handle_table_smart_fusion_method,
        _handle_skeleton_order_method,
        _handle_agreement_rule_method,
    ],
)
def test_without_the_secondary_artifact_the_method_fails(handler, tmp_path) -> None:
    element = _el("t-1", "table", "a | b", LEFT, 1, {"table_ast": SIMPLE_AST})
    manifest = _manifest(
        tmp_path, [element], "select-table-source", ["human-review"], []
    )
    manifest.artifacts = []

    result = handler(manifest, "o-1")

    assert not result.success
    assert "secundário ausente" in result.message


class TestVlmPairwiseJudge:
    """The judge itself is the Toolbox's; these fake its answer."""

    TEXT = "Texto da página com conteúdo suficiente para o juiz comparar."

    @pytest.fixture(autouse=True)
    def _toolbox_render(self, fake_toolbox_render):
        """Pages are rendered by the Toolbox (pdf.render@2); never reach a real one."""
        return fake_toolbox_render

    def _manifest(self, tmp_path, primary=TEXT, secondary=TEXT + " (variante)"):
        import fitz

        doc = fitz.open()
        page = doc.new_page(width=W, height=H)
        page.insert_text((40, 120), self.TEXT)
        doc.save(tmp_path / "doc.pdf")
        doc.close()
        return _manifest(
            tmp_path,
            [_el("p-1", "paragraph", primary, LEFT, 1)],
            "adjudicate-page",
            ["vlm-pairwise-judge", "human-review"],
            [_raw("paragraph", secondary, LEFT, 1)],
        )

    def _fake_judge(self, monkeypatch, p_b, document=None):
        seen = {}

        def judge(image, candidate_a, candidate_b):
            seen.update(image=image, a=candidate_a, b=candidate_b)
            if document is not None:
                return {"document": document}
            return {"document": {"pB": p_b, "pB_ab": p_b, "pA_ba": 1 - p_b, "model": "qwen3-vl-8b"}}

        monkeypatch.setattr("backend.agents.pddl_orchestrator._judge_page", judge)
        return seen

    def test_keeps_the_primary_page(self, tmp_path, monkeypatch) -> None:
        from backend.agents.pddl_orchestrator import _handle_vlm_pairwise_judge_method

        manifest = self._manifest(tmp_path)
        seen = self._fake_judge(monkeypatch, 0.1)

        result = _handle_vlm_pairwise_judge_method(manifest, "o-1")

        assert result.success and result.validated
        assert seen["image"].startswith(b"\x89PNG")
        assert seen["a"] == self.TEXT and seen["b"] == self.TEXT + " (variante)"
        judgement = manifest.elements[0].metadata["page_judgement"]
        assert judgement["choice"] == "docling" and judgement["pB"] == 0.1

    def _routed_manifest(self, tmp_path):
        """Page 1 was taken from MinerU; docling's version is kept in the artifact."""
        import hashlib

        manifest = self._manifest(tmp_path, primary=self.TEXT + " (mineru)")
        manifest.elements[0].metadata["provider"] = "mineru"
        [artifact] = [a for a in manifest.artifacts if a.kind == "provider-extraction"]
        stored = json.loads(Path(artifact.path).read_bytes())
        stored["replaced_primary_pages"] = {"1": [_raw("paragraph", self.TEXT, LEFT, 1)]}
        content = json.dumps(stored).encode()
        Path(artifact.path).write_bytes(content)
        artifact.sha256 = hashlib.sha256(content).hexdigest()
        return manifest

    @pytest.mark.parametrize(("p_b", "confirmed"), [(0.1, True), (0.9, False)])
    def test_a_page_taken_from_mineru_is_judged_against_docling(
        self, tmp_path, monkeypatch, p_b, confirmed
    ) -> None:
        from backend.agents.pddl_orchestrator import _handle_vlm_pairwise_judge_method

        manifest = self._routed_manifest(tmp_path)
        seen = self._fake_judge(monkeypatch, p_b)

        result = _handle_vlm_pairwise_judge_method(manifest, "o-1")

        assert seen["a"] == self.TEXT + " (mineru)" and seen["b"] == self.TEXT
        judgement = manifest.elements[0].metadata["page_judgement"]
        assert judgement["content"] == "mineru"
        assert judgement["choice"] == ("mineru" if confirmed else "docling")
        assert result.success is confirmed

    def test_preferred_secondary_is_recorded_and_escalated(self, tmp_path, monkeypatch) -> None:
        from backend.agents.pddl_orchestrator import _handle_vlm_pairwise_judge_method

        manifest = self._manifest(tmp_path)
        self._fake_judge(monkeypatch, 0.9)

        result = _handle_vlm_pairwise_judge_method(manifest, "o-1")

        assert not result.success
        assert "pB=0.90" in result.message
        assert manifest.elements[0].metadata["page_judgement"]["choice"] == "mineru"
        assert manifest.elements[0].text == self.TEXT

    def test_toolbox_failure_lets_the_planner_move_on(self, tmp_path, monkeypatch) -> None:
        from backend.agents.pddl_orchestrator import _handle_vlm_pairwise_judge_method
        from backend.tools.toolbox_client import ToolboxProviderUnavailable

        manifest = self._manifest(tmp_path)

        def down(*_args):
            raise ToolboxProviderUnavailable("VLM offline")

        monkeypatch.setattr("backend.agents.pddl_orchestrator._judge_page", down)

        result = _handle_vlm_pairwise_judge_method(manifest, "o-1")

        assert not result.success
        assert "indisponível" in result.message

    @pytest.mark.parametrize(
        "document",
        [{}, {"pB": None}, {"pB": "n/a"}, {"pB": 1.5}, {"pB": -0.1}],
        ids=["missing", "null", "not-a-number", "above-one", "below-zero"],
    )
    def test_answer_without_valid_pb_fails_instead_of_keeping_the_primary(
        self, tmp_path, monkeypatch, document
    ) -> None:
        from backend.agents.pddl_orchestrator import _handle_vlm_pairwise_judge_method

        manifest = self._manifest(tmp_path)
        self._fake_judge(monkeypatch, None, document=document)

        result = _handle_vlm_pairwise_judge_method(manifest, "o-1")

        assert not result.success and not result.validated
        assert "pB válido" in result.message
        assert "page_judgement" not in manifest.elements[0].metadata

    def test_agreeing_pages_keep_the_primary_without_calling_the_judge(
        self, tmp_path, monkeypatch
    ) -> None:
        from backend.agents.pddl_orchestrator import _handle_vlm_pairwise_judge_method

        manifest = self._manifest(tmp_path, secondary=self.TEXT)
        seen = self._fake_judge(monkeypatch, 0.9)

        result = _handle_vlm_pairwise_judge_method(manifest, "o-1")

        assert result.success and result.validated
        assert not seen
        judgement = manifest.elements[0].metadata["page_judgement"]
        assert judgement == {
            "content": "docling", "choice": "docling", "pB": None, "reason": "agree",
        }

    def test_page_without_both_transcriptions_is_not_judged(self, tmp_path, monkeypatch) -> None:
        from backend.agents.pddl_orchestrator import _handle_vlm_pairwise_judge_method

        manifest = self._manifest(tmp_path, secondary="")
        seen = self._fake_judge(monkeypatch, 0.1)

        result = _handle_vlm_pairwise_judge_method(manifest, "o-1")

        assert not result.success
        assert "Sem páginas com as duas transcrições" in result.message
        assert not seen

    def test_rejected_call_is_not_reported_as_unavailable(self, tmp_path, monkeypatch) -> None:
        from backend.agents.pddl_orchestrator import _handle_vlm_pairwise_judge_method
        from backend.tools.toolbox_client import ToolboxAuthenticationError

        manifest = self._manifest(tmp_path)

        def rejected(*_args):
            raise ToolboxAuthenticationError("401")

        monkeypatch.setattr("backend.agents.pddl_orchestrator._judge_page", rejected)

        result = _handle_vlm_pairwise_judge_method(manifest, "o-1")

        assert not result.success
        assert "recusou" in result.message and "ToolboxAuthenticationError" in result.message

    def test_unexpected_judge_error_is_not_labelled_as_rendering(
        self, tmp_path, monkeypatch
    ) -> None:
        from backend.agents.pddl_orchestrator import _handle_vlm_pairwise_judge_method

        manifest = self._manifest(tmp_path)

        def broken(*_args):
            raise TypeError("resposta inesperada")

        monkeypatch.setattr("backend.agents.pddl_orchestrator._judge_page", broken)

        with pytest.raises(TypeError):
            _handle_vlm_pairwise_judge_method(manifest, "o-1")

    def test_long_page_is_flagged_as_truncated(self, tmp_path, monkeypatch) -> None:
        from backend.agents.pddl_orchestrator import (
            _JUDGE_MAX_CHARS,
            _handle_vlm_pairwise_judge_method,
        )

        words = [f"palavra{i}" for i in range(_JUDGE_MAX_CHARS // 8)]
        manifest = self._manifest(
            tmp_path, primary=" ".join(words), secondary=" ".join(reversed(words))
        )
        self._fake_judge(monkeypatch, 0.1)

        _handle_vlm_pairwise_judge_method(manifest, "o-1")

        assert manifest.elements[0].metadata["page_judgement"]["truncated"] is True

    def test_judge_page_sends_the_png_through_the_adjudicate_client(
        self, tmp_path, monkeypatch
    ) -> None:
        from backend.agents.pddl_orchestrator import _judge_page

        calls = {}

        class FakeClient:
            async def judge_page(self, candidate_a, candidate_b, file_path=None, **kwargs):
                calls.update(a=candidate_a, b=candidate_b, kwargs=kwargs)
                calls["bytes"] = file_path.read_bytes()
                calls["suffix"] = file_path.suffix
                return {"document": {"pB": 0.3}}

            async def close(self):
                calls["closed"] = True

        from acessilia_sdk.toolbox.clients import ToolboxAdjudicateClient

        def fake_factory(client_cls, **overrides):
            calls["client_cls"] = client_cls
            return FakeClient()

        monkeypatch.setattr(
            "backend.tools.toolbox_client.make_toolbox_client", fake_factory
        )

        result = _judge_page(b"\x89PNG-fake", "A", "B")

        assert result == {"document": {"pB": 0.3}}
        assert calls["bytes"] == b"\x89PNG-fake" and calls["suffix"] == ".png"
        assert (calls["a"], calls["b"]) == ("A", "B")
        assert calls["closed"]
        assert calls["client_cls"] is ToolboxAdjudicateClient

    def test_rendered_page_fits_the_server_slot(self, tmp_path) -> None:
        import fitz

        from backend.agents.pddl_orchestrator import _JUDGE_PAGE_MAX_SIDE, _render_page_png

        self._manifest(tmp_path)
        pixmap = fitz.Pixmap(_render_page_png(tmp_path / "doc.pdf", 1))
        assert max(pixmap.width, pixmap.height) <= _JUDGE_PAGE_MAX_SIDE
