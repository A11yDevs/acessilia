from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from acessilia_core.i18n import t
from acessilia_core.i18n.log_messages import (
    MSG_PLANNER_NOT_STARTED,
    MSG_TIMESTAMPS_MIXED_TIMEZONES,
)
from acessilia_core.manifest.dependencies import (
    DependencyCycleError,
    dependency_closure,
)
from docstruct.manifest import (  # noqa: F401  (msgids re-exported for the catalogs)
    MSG_CHAR_RANGE_REVERSED,
    MSG_DUPLICATE_ELEMENT_IDS,
    MSG_DUPLICATE_PAGE_NUMBERS,
    MSG_ELEMENT_UNKNOWN_PAGE,
    MSG_PAGE_DUPLICATE_ELEMENT_IDS,
    MSG_PAGE_UNKNOWN_ELEMENTS,
    MSG_PARENT_CYCLE,
    MSG_PARENT_REF_MISMATCH,
    MSG_PROVENANCE_UNKNOWN_PAGE,
    MSG_SELF_PARENT,
    MSG_UNKNOWN_PARENT,
    document_invariant_findings,
)

SCHEMA_VERSION: Literal["1.1.0"] = "1.1.0"
SCHEMA_ID = "urn:a11y-devs:schema:processing-manifest:1.1.0"

ElementType = Literal[
    "title",
    "heading",
    "paragraph",
    "list_item",
    "table",
    "picture",
    "formula",
    "code",
    "caption",
    "footnote",
    "page_header",
    "page_footer",
    "checkbox",
    "key_value",
    "form",
    "group",
    "unknown",
]
Severity = Literal["info", "warning", "error"]
ObligationStatus = Literal["candidate", "pending", "in_progress", "satisfied", "failed"]
AttemptStatus = Literal["succeeded", "failed", "rejected"]


def _check_comparable(started: datetime, completed: datetime) -> None:
    """Refuse an interval that mixes an aware and a naive timestamp.

    Comparing them raises ``TypeError``, which pydantic does not turn into a
    ``ValidationError``.
    """
    if (started.utcoffset() is None) != (completed.utcoffset() is None):
        raise ValueError(t(MSG_TIMESTAMPS_MIXED_TIMEZONES))


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BoundingBox(StrictModel):
    left: float
    top: float
    right: float
    bottom: float
    coord_origin: Literal["TOPLEFT", "BOTTOMLEFT", "UNKNOWN"] = "UNKNOWN"


class Provenance(StrictModel):
    page_number: int = Field(ge=1)
    bbox: BoundingBox | None = None
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)


class SourceDocument(StrictModel):
    document_id: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    path: str = Field(min_length=1)
    media_type: str = Field(min_length=1)
    byte_size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class ExtractorRun(StrictModel):
    name: str = Field(default="docling", min_length=1)
    version: str = Field(min_length=1)
    started_at: datetime
    completed_at: datetime
    duration_ms: int = Field(ge=0)
    configuration: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_interval(self) -> ExtractorRun:
        _check_comparable(self.started_at, self.completed_at)
        return self


class PageDescriptor(StrictModel):
    page_number: int = Field(ge=1)
    width: float | None = Field(default=None, gt=0)
    height: float | None = Field(default=None, gt=0)
    element_ids: list[str] = Field(default_factory=list)


class ManifestElement(StrictModel):
    id: str = Field(min_length=1)
    type: ElementType
    raw_label: str = Field(min_length=1)
    reading_order: int = Field(ge=1)
    hierarchy_level: int = Field(ge=0)
    text: str | None = None
    source_ref: str | None = None
    parent_ref: str | None = None
    parent_id: str | None = None
    page_number: int | None = Field(default=None, ge=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    provenance: list[Provenance] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Observation(StrictModel):
    id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    severity: Severity
    message: str = Field(min_length=1)
    target_ids: list[str] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)


class ObligationAttempt(StrictModel):
    method: str = Field(min_length=1)
    status: AttemptStatus
    started_at: datetime
    completed_at: datetime
    message: str | None = None
    artifact_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_interval(self) -> ObligationAttempt:
        _check_comparable(self.started_at, self.completed_at)
        if self.completed_at < self.started_at:
            raise ValueError(t(MSG_PLANNER_NOT_STARTED))
        return self


class Obligation(StrictModel):
    id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    status: ObligationStatus = "candidate"
    selected: bool = False
    target_ids: list[str] = Field(min_length=1)
    dependencies: list[str] = Field(default_factory=list)
    admissible_methods: list[str] = Field(default_factory=list)
    method_costs: dict[str, int] = Field(default_factory=dict)
    attempts: list[ObligationAttempt] = Field(default_factory=list)
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_methods(self) -> Obligation:
        methods = set(self.admissible_methods)
        unknown = set(self.method_costs) - methods
        if unknown:
            raise ValueError(
                "Custos definidos para métodos não admissíveis: "
                f"{sorted(unknown)}"
            )
        if any(cost < 0 for cost in self.method_costs.values()):
            raise ValueError("Custos de métodos devem ser não negativos")
        return self


class Artifact(StrictModel):
    id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    path: str = Field(min_length=1)
    media_type: str = Field(min_length=1)
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class ManifestSummary(StrictModel):
    page_count: int = Field(ge=0)
    element_count: int = Field(ge=0)
    observation_count: int = Field(ge=0)
    obligation_count: int = Field(ge=0)
    element_types: dict[str, int] = Field(default_factory=dict)


def _ensure_unique_ids(items: Sequence[Any], message: str) -> set[str]:
    ids = [item.id for item in items]
    known = set(ids)
    if len(ids) != len(known):
        raise ValueError(message)
    return known


def _validate_observation_targets(
    observations: list[Observation], known_elements: set[str]
) -> None:
    for observation in observations:
        unknown = set(observation.target_ids) - known_elements
        if unknown:
            raise ValueError(
                f"Observação {observation.id} referencia alvos inexistentes: "
                f"{sorted(unknown)}"
            )


def _validate_obligation_attempts(
    obligation: Obligation, known_artifacts: set[str]
) -> None:
    for attempt in obligation.attempts:
        if attempt.method not in obligation.admissible_methods:
            raise ValueError(
                f"Tentativa de método não admissível em {obligation.id}: "
                f"{attempt.method}"
            )
        unknown_artifacts = set(attempt.artifact_ids) - known_artifacts
        if unknown_artifacts:
            raise ValueError(
                f"Tentativa em {obligation.id} referencia artefatos "
                f"inexistentes: {sorted(unknown_artifacts)}"
            )


def _validate_obligation_references(
    obligations: list[Obligation],
    *,
    known_elements: set[str],
    known_obligations: set[str],
    known_artifacts: set[str],
) -> None:
    for obligation in obligations:
        unknown_targets = set(obligation.target_ids) - known_elements
        if unknown_targets:
            raise ValueError(
                f"Obrigação {obligation.id} referencia alvos inexistentes: "
                f"{sorted(unknown_targets)}"
            )
        unknown_dependencies = set(obligation.dependencies) - known_obligations
        if unknown_dependencies:
            raise ValueError(
                f"Obrigação {obligation.id} referencia dependências inexistentes: "
                f"{sorted(unknown_dependencies)}"
            )
        if obligation.id in obligation.dependencies:
            raise ValueError(f"Obrigação {obligation.id} depende de si mesma")
        _validate_obligation_attempts(obligation, known_artifacts)


def _validate_obligation_dag(obligations: list[Obligation]) -> None:
    dependency_graph = {
        obligation.id: obligation.dependencies for obligation in obligations
    }
    try:
        dependency_closure(dependency_graph, dependency_graph)
    except DependencyCycleError as error:
        raise ValueError(
            f"Ciclo detectado nas dependências de obrigações: {error}"
        ) from error


def _validate_satisfied_predecessors(obligations: list[Obligation]) -> None:
    obligation_by_id = {obligation.id: obligation for obligation in obligations}
    for obligation in obligations:
        if obligation.status != "satisfied":
            continue
        unsatisfied = [
            dependency
            for dependency in obligation.dependencies
            if obligation_by_id[dependency].status != "satisfied"
        ]
        if unsatisfied:
            raise ValueError(
                f"Obrigação satisfeita {obligation.id} possui predecessoras "
                f"insatisfeitas: {unsatisfied}"
            )


def _validate_summary_counts(manifest: ProcessingManifest) -> None:
    expected_counts = {
        "page_count": len(manifest.pages),
        "element_count": len(manifest.elements),
        "observation_count": len(manifest.observations),
        "obligation_count": len(manifest.obligations),
    }
    for field, expected in expected_counts.items():
        if getattr(manifest.summary, field) != expected:
            raise ValueError(
                f"summary.{field}={getattr(manifest.summary, field)}; esperado {expected}"
            )


class ProcessingManifest(StrictModel):
    schema_ref: str = Field(default=SCHEMA_ID, alias="$schema")
    schema_version: Literal["1.1.0"] = SCHEMA_VERSION
    manifest_id: str = Field(min_length=1)
    revision: int = Field(default=1, ge=1)
    status: Literal["extracted", "planned", "processing", "completed", "failed"] = (
        "extracted"
    )
    created_at: datetime
    source: SourceDocument
    extractor: ExtractorRun
    title: str = Field(min_length=1)
    language: str = Field(min_length=2)
    pages: list[PageDescriptor]
    elements: list[ManifestElement]
    observations: list[Observation] = Field(default_factory=list)
    obligations: list[Obligation] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    summary: ManifestSummary

    @model_validator(mode="after")
    def validate_references(self) -> ProcessingManifest:
        if self.extractor.completed_at < self.extractor.started_at:
            raise ValueError("A extração terminou antes de começar")

        # Document invariants are docstruct's (#203, #404): unique element ids,
        # existing non-self parents, an acyclic hierarchy, unique page numbers,
        # pages that list known elements without repeating one, existing page
        # references when pages are described, parent_ref/source_ref agreement
        # and provenance character ranges that do not end before they start.
        if findings := document_invariant_findings(self.pages, self.elements):
            msgid, kwargs = findings[0]
            raise ValueError(t(msgid).format(**kwargs))

        _ensure_unique_ids(self.observations, "IDs de observações duplicados")
        known_obligations = _ensure_unique_ids(
            self.obligations, "IDs de obrigações duplicados"
        )
        known_artifacts = _ensure_unique_ids(
            self.artifacts, "IDs de artefatos duplicados"
        )

        known_elements = {element.id for element in self.elements}
        _validate_observation_targets(self.observations, known_elements)
        _validate_obligation_references(
            self.obligations,
            known_elements=known_elements,
            known_obligations=known_obligations,
            known_artifacts=known_artifacts,
        )
        _validate_obligation_dag(self.obligations)
        _validate_satisfied_predecessors(self.obligations)
        _validate_summary_counts(self)
        return self

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": SCHEMA_ID,
            "title": "ProcessingManifest",
            # Verbatim: the description of processing-manifest 1.1.0 as first
            # published. The core and the Toolbox publish this same text (#203).
            "description": (
                "Manifesto operacional gerado pelo extrator estrutural do Acessília."
            ),
        },
    )
