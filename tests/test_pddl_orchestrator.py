from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from backend.agents.pddl_orchestrator import build_pddl_structured_payload
from backend.pipeline.canonical_builder import build_canonical_document
from core.manifest.models import (
    ExtractorRun,
    ManifestElement,
    ManifestSummary,
    Obligation,
    PageDescriptor,
    ProcessingManifest,
    SourceDocument,
)
from core.planning.models import DomainIdentity, NominalPlan, PlanStep


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
