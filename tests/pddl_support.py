"""Builders shared by the PDDL planning and execution tests.

Kept out of the test modules so a suite can be renamed or reorganized without
breaking the others that build manifests and orchestrators the same way.
"""

from __future__ import annotations

from datetime import datetime, timezone

from backend.agents.pddl_orchestrator import PddlAccessibilityOrchestrator
from backend.core.manifest.models import (
    ExtractorRun,
    ManifestElement,
    ManifestSummary,
    Obligation,
    PageDescriptor,
    ProcessingManifest,
    SourceDocument,
)
from backend.core.planning.planner_agent import PlannerAgent

NOW = datetime(2026, 10, 14, tzinfo=timezone.utc)


def build_manifest(
    elements: list[ManifestElement],
    obligations: list[Obligation],
) -> ProcessingManifest:
    return ProcessingManifest(
        manifest_id="manifest-actionability",
        created_at=NOW,
        source=SourceDocument(
            document_id="doc-actionability",
            filename="amostra.pdf",
            path="/tmp/amostra.pdf",
            media_type="application/pdf",
            byte_size=1,
            sha256="a" * 64,
        ),
        extractor=ExtractorRun(
            version="2.0.0",
            started_at=NOW,
            completed_at=NOW,
            duration_ms=1,
            configuration={},
        ),
        title="Actionability",
        language="pt-BR",
        pages=[PageDescriptor(page_number=1, element_ids=[e.id for e in elements])],
        elements=elements,
        obligations=obligations,
        summary=ManifestSummary(
            page_count=1,
            element_count=len(elements),
            observation_count=0,
            obligation_count=len(obligations),
            element_types={},
        ),
    )


def build_element(
    element_id: str,
    element_type: str,
    *,
    text: str | None = None,
    metadata: dict | None = None,
    reading_order: int = 1,
) -> ManifestElement:
    return ManifestElement(
        id=element_id,
        type=element_type,
        raw_label=element_type,
        reading_order=reading_order,
        hierarchy_level=1,
        text=text,
        page_number=1,
        metadata=metadata or {},
    )


def build_obligation(
    kind: str, targets: list[str], methods: list[str]
) -> Obligation:
    return Obligation(
        id="o-1",
        kind=kind,
        target_ids=targets,
        admissible_methods=methods,
        method_costs={method: 5 for method in methods},
        rationale="test",
    )


def build_orchestrator(*, max_replans: int = 0) -> PddlAccessibilityOrchestrator:
    """Orchestrator with the real registry, without running its constructor.

    The constructor builds a Toolbox-backed extractor; these tests only exercise
    planning and execution, so the extractor is irrelevant.
    """
    orchestrator = PddlAccessibilityOrchestrator.__new__(PddlAccessibilityOrchestrator)
    orchestrator.executor = PddlAccessibilityOrchestrator._build_executor()
    orchestrator.planner_backend = "internal"
    orchestrator.preferred_plan = "internal"
    orchestrator.fast_downward = None
    orchestrator.fast_downward_alias = None
    orchestrator.fast_downward_search = "astar(blind())"
    orchestrator.execute_dry_run = False
    orchestrator.max_replans = max_replans
    orchestrator.planner = PlannerAgent()
    return orchestrator
