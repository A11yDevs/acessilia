from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from backend.agents.pddl_orchestrator import build_pddl_structured_payload
from backend.agents.pddl_orchestrator import _rows_from_visual_table_text
from backend.agents.pddl_orchestrator import _table_element_has_structured_content
from backend.pipeline.canonical_builder import build_canonical_document
from backend.core.manifest.models import (
    ExtractorRun,
    ManifestElement,
    ManifestSummary,
    Obligation,
    PageDescriptor,
    ProcessingManifest,
    SourceDocument,
)
from backend.core.planning.models import DomainIdentity, NominalPlan, PlanStep


def _sample_manifest() -> ProcessingManifest:
    now = datetime(2026, 7, 31, tzinfo=timezone.utc)
    return ProcessingManifest(
        manifest_id="manifest-integration-1",
        created_at=now,
        source=SourceDocument(
            document_id="doc-integration",
            filename="amostra.pdf",
            path="/tmp/amostra.pdf",
            media_type="application/pdf",
            byte_size=1,
            sha256="a" * 64,
        ),
        extractor=ExtractorRun(
            version="2.0.0",
            started_at=now,
            completed_at=now,
            duration_ms=1,
            configuration={"ocr": False},
        ),
        title="Documento de Integracao",
        language="pt-BR",
        pages=[PageDescriptor(page_number=1, element_ids=["el-1", "el-2"])],
        elements=[
            ManifestElement(
                id="el-1",
                type="heading",
                raw_label="heading",
                source_ref="#/texts/0",
                reading_order=1,
                hierarchy_level=1,
                text="Introducao",
                page_number=1,
            ),
            ManifestElement(
                id="el-2",
                type="paragraph",
                raw_label="paragraph",
                reading_order=2,
                hierarchy_level=1,
                text="Texto de exemplo.",
                page_number=1,
            ),
        ],
        obligations=[
            Obligation(
                id="o-1",
                kind="describe-image",
                target_ids=["el-2"],
                admissible_methods=["human-review"],
                method_costs={"human-review": 5},
                rationale="Obrigacao de teste",
            )
        ],
        summary=ManifestSummary(
            page_count=1,
            element_count=2,
            observation_count=0,
            obligation_count=1,
            element_types={"heading": 1, "paragraph": 1},
        ),
    )


def _sample_plan() -> NominalPlan:
    now = datetime(2026, 7, 31, tzinfo=timezone.utc)
    return NominalPlan(
        plan_id="plan-integration-1",
        generated_at=now,
        manifest_id="manifest-integration-1",
        manifest_revision=1,
        manifest_sha256="b" * 64,
        domain=DomainIdentity(
            name="acessilia-obligations",
            version="2.2",
            domain_sha256="c" * 64,
            description_sha256="d" * 64,
        ),
        problem_name="manifest-integration-1",
        problem_sha256="e" * 64,
        planner="internal-reference",
        selected_obligations=["o-1"],
        expected_total_cost=0,
        steps=[
            PlanStep(index=0, action="start-job", expected_cost=0),
            PlanStep(index=1, action="complete-job", expected_cost=0),
        ],
    )


def _sample_manifest_without_page_element_ids() -> ProcessingManifest:
    now = datetime(2026, 7, 31, tzinfo=timezone.utc)
    return ProcessingManifest(
        manifest_id="manifest-integration-2",
        created_at=now,
        source=SourceDocument(
            document_id="doc-image-only",
            filename="imagem.jpeg",
            path="/tmp/imagem.jpeg",
            media_type="image/jpeg",
            byte_size=1,
            sha256="f" * 64,
        ),
        extractor=ExtractorRun(
            version="2.0.0",
            started_at=now,
            completed_at=now,
            duration_ms=1,
            configuration={"ocr": False},
        ),
        title="Imagem sem element_ids",
        language="pt-BR",
        pages=[PageDescriptor(page_number=1, element_ids=[])],
        elements=[
            ManifestElement(
                id="el-img-1",
                type="picture",
                raw_label="picture",
                source_ref="#/pictures/0",
                reading_order=1,
                hierarchy_level=1,
                text="Céu alaranjado ao pôr do sol sobre a cidade.",
                page_number=1,
            ),
        ],
        obligations=[],
        summary=ManifestSummary(
            page_count=1,
            element_count=1,
            observation_count=0,
            obligation_count=0,
            element_types={"picture": 1},
        ),
    )


def test_build_pddl_structured_payload_is_compatible_with_canonical_builder():
    payload = build_pddl_structured_payload(
        file_path=Path("/tmp/amostra.pdf"),
        manifest=_sample_manifest(),
        plan=_sample_plan(),
        planner_backend="internal",
        execution_report=None,
        comparison=None,
    )

    assert payload["page_count"] == 1
    assert payload["mode"] == "pddl-internal"
    assert payload["pages"]
    assert payload["pages"][0]["blocks"][0]["type"] == "heading"
    assert payload["canonical_metadata"]["pipeline_engine"] == "pddl"

    canonical = build_canonical_document(
        payload,
        title="Documento de Integracao",
        source_name="amostra.pdf",
        source_path="/tmp/amostra.pdf",
        metadata=payload["canonical_metadata"],
        technical_warnings=payload["technical_warnings"],
    )

    assert canonical["sections"]
    assert canonical["metadata"]["pipeline_engine"] == "pddl"
    block_metadata = payload["pages"][0]["blocks"][0].get("metadata", {})
    assert block_metadata.get("source_ref") == "/texts/0"


def test_build_pddl_structured_payload_falls_back_to_page_number_when_element_ids_missing():
    payload = build_pddl_structured_payload(
        file_path=Path("/tmp/imagem.jpeg"),
        manifest=_sample_manifest_without_page_element_ids(),
        plan=_sample_plan(),
        planner_backend="internal",
        execution_report=None,
        comparison=None,
    )

    assert payload["pages"]
    assert payload["pages"][0]["blocks"]
    first_block = payload["pages"][0]["blocks"][0]
    assert first_block["type"] == "image"
    assert "Céu alaranjado" in first_block["alt_text"]
    assert payload["pages"][0]["text"]


def test_build_pddl_structured_payload_maps_callout_metadata_to_note_block():
    now = datetime(2026, 7, 31, tzinfo=timezone.utc)
    manifest = ProcessingManifest(
        manifest_id="manifest-callout",
        created_at=now,
        source=SourceDocument(
            document_id="doc-callout",
            filename="callout.pdf",
            path="/tmp/callout.pdf",
            media_type="application/pdf",
            byte_size=1,
            sha256="1" * 64,
        ),
        extractor=ExtractorRun(
            version="2.0.0",
            started_at=now,
            completed_at=now,
            duration_ms=1,
            configuration={"ocr": False},
        ),
        title="Callout",
        language="pt-BR",
        pages=[PageDescriptor(page_number=1, element_ids=["el-1"])],
        elements=[
            ManifestElement(
                id="el-1",
                type="paragraph",
                raw_label="paragraph",
                reading_order=1,
                hierarchy_level=1,
                text="Conteúdo da caixa de atenção.",
                page_number=1,
                metadata={
                    "callout_id": "callout-p1-g1",
                    "callout_role": "content",
                    "callout_type": "warning",
                    "callout_title": "Atenção",
                },
            )
        ],
        obligations=[],
        summary=ManifestSummary(
            page_count=1,
            element_count=1,
            observation_count=0,
            obligation_count=0,
            element_types={"paragraph": 1},
        ),
    )

    payload = build_pddl_structured_payload(
        file_path=Path("/tmp/callout.pdf"),
        manifest=manifest,
        plan=_sample_plan(),
        planner_backend="internal",
        execution_report=None,
        comparison=None,
    )

    block = payload["pages"][0]["blocks"][0]
    assert block["type"] == "warning"
    assert block["title"] == "Atenção"
    assert "caixa de atenção" in block["text"]


def test_build_pddl_structured_payload_keeps_callout_title_only_once():
    now = datetime(2026, 7, 31, tzinfo=timezone.utc)
    manifest = ProcessingManifest(
        manifest_id="manifest-callout-repeat",
        created_at=now,
        source=SourceDocument(
            document_id="doc-callout-repeat",
            filename="callout-repeat.pdf",
            path="/tmp/callout-repeat.pdf",
            media_type="application/pdf",
            byte_size=1,
            sha256="2" * 64,
        ),
        extractor=ExtractorRun(
            version="2.0.0",
            started_at=now,
            completed_at=now,
            duration_ms=1,
            configuration={"ocr": False},
        ),
        title="Callout Repeat",
        language="pt-BR",
        pages=[PageDescriptor(page_number=1, element_ids=["el-1", "el-2"])],
        elements=[
            ManifestElement(
                id="el-1",
                type="paragraph",
                raw_label="paragraph",
                reading_order=1,
                hierarchy_level=1,
                text="Primeiro parágrafo da caixa.",
                page_number=1,
                metadata={
                    "callout_id": "callout-p1-g1",
                    "callout_role": "content",
                    "callout_type": "note",
                    "callout_title": "Precisa mesmo?",
                },
            ),
            ManifestElement(
                id="el-2",
                type="paragraph",
                raw_label="paragraph",
                reading_order=2,
                hierarchy_level=1,
                text="Segundo parágrafo da caixa.",
                page_number=1,
                metadata={
                    "callout_id": "callout-p1-g1",
                    "callout_role": "content",
                    "callout_type": "note",
                    "callout_title": "Precisa mesmo?",
                },
            ),
        ],
        obligations=[],
        summary=ManifestSummary(
            page_count=1,
            element_count=2,
            observation_count=0,
            obligation_count=0,
            element_types={"paragraph": 2},
        ),
    )

    payload = build_pddl_structured_payload(
        file_path=Path("/tmp/callout-repeat.pdf"),
        manifest=manifest,
        plan=_sample_plan(),
        planner_backend="internal",
        execution_report=None,
        comparison=None,
    )

    blocks = payload["pages"][0]["blocks"]
    assert blocks[0]["type"] == "note"
    assert blocks[0].get("title") == "Precisa mesmo?"
    assert blocks[1]["type"] == "note"
    assert "title" not in blocks[1]


def test_build_pddl_structured_payload_creates_table_ast_from_plain_table_text():
    now = datetime(2026, 7, 31, tzinfo=timezone.utc)
    manifest = ProcessingManifest(
        manifest_id="manifest-table-plain",
        created_at=now,
        source=SourceDocument(
            document_id="doc-table-plain",
            filename="table-plain.pdf",
            path="/tmp/table-plain.pdf",
            media_type="application/pdf",
            byte_size=1,
            sha256="3" * 64,
        ),
        extractor=ExtractorRun(
            version="2.0.0",
            started_at=now,
            completed_at=now,
            duration_ms=1,
            configuration={"ocr": False},
        ),
        title="Tabela",
        language="pt-BR",
        pages=[PageDescriptor(page_number=1, element_ids=["el-1"])],
        elements=[
            ManifestElement(
                id="el-1",
                type="table",
                raw_label="table",
                reading_order=1,
                hierarchy_level=1,
                text="A | B",
                page_number=1,
            )
        ],
        obligations=[],
        summary=ManifestSummary(
            page_count=1,
            element_count=1,
            observation_count=0,
            obligation_count=0,
            element_types={"table": 1},
        ),
    )

    payload = build_pddl_structured_payload(
        file_path=Path("/tmp/table-plain.pdf"),
        manifest=manifest,
        plan=_sample_plan(),
        planner_backend="internal",
        execution_report=None,
        comparison=None,
    )

    block = payload["pages"][0]["blocks"][0]
    assert block["type"] == "table"
    assert block["rows"] == [["A | B"]]
    assert block["table_ast"]["body"][0]["cells"][0]["text"] == "A | B"


def test_build_pddl_structured_payload_preserves_table_ast_from_metadata():
    now = datetime(2026, 7, 31, tzinfo=timezone.utc)
    manifest = ProcessingManifest(
        manifest_id="manifest-table-ast",
        created_at=now,
        source=SourceDocument(
            document_id="doc-table-ast",
            filename="table-ast.pdf",
            path="/tmp/table-ast.pdf",
            media_type="application/pdf",
            byte_size=1,
            sha256="4" * 64,
        ),
        extractor=ExtractorRun(
            version="2.0.0",
            started_at=now,
            completed_at=now,
            duration_ms=1,
            configuration={"ocr": False},
        ),
        title="Tabela AST",
        language="pt-BR",
        pages=[PageDescriptor(page_number=1, element_ids=["el-1"])],
        elements=[
            ManifestElement(
                id="el-1",
                type="table",
                raw_label="table",
                reading_order=1,
                hierarchy_level=1,
                text="",
                page_number=1,
                metadata={
                    "table_ast": {
                        "caption": "Resumo",
                        "header": [
                            {
                                "cells": [
                                    {"text": "Coluna", "header": True, "scope": "col"},
                                    {"text": "Valor", "header": True, "scope": "col"},
                                ]
                            }
                        ],
                        "body": [
                            {
                                "cells": [
                                    {"text": "Taxa"},
                                    {"text": "10%"},
                                ]
                            }
                        ],
                    }
                },
            )
        ],
        obligations=[],
        summary=ManifestSummary(
            page_count=1,
            element_count=1,
            observation_count=0,
            obligation_count=0,
            element_types={"table": 1},
        ),
    )

    payload = build_pddl_structured_payload(
        file_path=Path("/tmp/table-ast.pdf"),
        manifest=manifest,
        plan=_sample_plan(),
        planner_backend="internal",
        execution_report=None,
        comparison=None,
    )

    block = payload["pages"][0]["blocks"][0]
    assert block["type"] == "table"
    assert block["table_ast"]["caption"] == "Resumo"
    assert block["rows"][0] == ["Coluna", "Valor"]
    assert block["rows"][1] == ["Taxa", "10%"]


def test_rows_from_visual_table_text_parses_markdown_table() -> None:
    ocr_text = """
    | Coluna | Valor |
    | --- | --- |
    | Taxa | 10% |
    | Juros | 2% |
    """

    rows = _rows_from_visual_table_text(ocr_text)

    assert rows == [
        ["Coluna", "Valor"],
        ["Taxa", "10%"],
        ["Juros", "2%"],
    ]


def test_rows_from_visual_table_text_parses_delimited_lines() -> None:
    ocr_text = "Nome;Nota\nAna;9,5\nBeto;8,0"

    rows = _rows_from_visual_table_text(ocr_text)

    assert rows == [
        ["Nome", "Nota"],
        ["Ana", "9,5"],
        ["Beto", "8,0"],
    ]


def test_table_element_has_structured_content_rejects_placeholder_table_ast() -> None:
    element = ManifestElement(
        id="el-table-1",
        type="table",
        raw_label="table",
        reading_order=1,
        hierarchy_level=1,
        text="",
        page_number=1,
        metadata={
            "table_ast": {
                "body": [
                    {
                        "cells": [
                            {"text": "Tabela detectada"},
                        ]
                    }
                ]
            }
        },
    )

    assert _table_element_has_structured_content(element) is False
