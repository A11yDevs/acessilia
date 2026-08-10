from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


SCHEMA_VERSION = "1.1.0"
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
    name: Literal["docling"] = "docling"
    version: str = Field(min_length=1)
    started_at: datetime
    completed_at: datetime
    duration_ms: int = Field(ge=0)
    configuration: dict[str, Any] = Field(default_factory=dict)


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
    def validate_interval(self) -> "ObligationAttempt":
        if self.completed_at < self.started_at:
            raise ValueError("A tentativa terminou antes de começar")
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
    def validate_methods(self) -> "Obligation":
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
    def validate_references(self) -> "ProcessingManifest":
        if self.extractor.completed_at < self.extractor.started_at:
            raise ValueError("A extração terminou antes de começar")

        element_ids = [element.id for element in self.elements]
        if len(element_ids) != len(set(element_ids)):
            raise ValueError("IDs de elementos duplicados")

        observation_ids = [observation.id for observation in self.observations]
        if len(observation_ids) != len(set(observation_ids)):
            raise ValueError("IDs de observações duplicados")

        obligation_ids = [obligation.id for obligation in self.obligations]
        if len(obligation_ids) != len(set(obligation_ids)):
            raise ValueError("IDs de obrigações duplicados")

        artifact_ids = [artifact.id for artifact in self.artifacts]
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError("IDs de artefatos duplicados")

        known_elements = set(element_ids)
        parent_graph: dict[str, str] = {}
        for element in self.elements:
            if element.parent_id is None:
                continue
            if element.parent_id not in known_elements:
                raise ValueError(
                    f"Elemento {element.id} referencia pai inexistente: "
                    f"{element.parent_id}"
                )
            if element.parent_id == element.id:
                raise ValueError(f"Elemento {element.id} é pai de si mesmo")
            parent_graph[element.id] = element.parent_id

        for element_id in parent_graph:
            ancestors: set[str] = set()
            current = element_id
            while current in parent_graph:
                if current in ancestors:
                    raise ValueError("Ciclo detectado na hierarquia de elementos")
                ancestors.add(current)
                current = parent_graph[current]

        page_numbers = [page.page_number for page in self.pages]
        if len(page_numbers) != len(set(page_numbers)):
            raise ValueError("Números de página duplicados")
        for page in self.pages:
            unknown = set(page.element_ids) - known_elements
            if unknown:
                raise ValueError(
                    f"Página {page.page_number} referencia elementos inexistentes: "
                    f"{sorted(unknown)}"
                )
        for observation in self.observations:
            unknown = set(observation.target_ids) - known_elements
            if unknown:
                raise ValueError(
                    f"Observação {observation.id} referencia alvos inexistentes: "
                    f"{sorted(unknown)}"
                )
        known_obligations = set(obligation_ids)
        for obligation in self.obligations:
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
            for attempt in obligation.attempts:
                if attempt.method not in obligation.admissible_methods:
                    raise ValueError(
                        f"Tentativa de método não admissível em {obligation.id}: "
                        f"{attempt.method}"
                    )
                unknown_artifacts = set(attempt.artifact_ids) - set(artifact_ids)
                if unknown_artifacts:
                    raise ValueError(
                        f"Tentativa em {obligation.id} referencia artefatos "
                        f"inexistentes: {sorted(unknown_artifacts)}"
                    )

        dependency_graph = {
            obligation.id: obligation.dependencies for obligation in self.obligations
        }
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(obligation_id: str) -> None:
            if obligation_id in visiting:
                raise ValueError("Ciclo detectado nas dependências de obrigações")
            if obligation_id in visited:
                return
            visiting.add(obligation_id)
            for dependency in dependency_graph.get(obligation_id, []):
                visit(dependency)
            visiting.remove(obligation_id)
            visited.add(obligation_id)

        for obligation_id in dependency_graph:
            visit(obligation_id)

        obligation_by_id = {
            obligation.id: obligation for obligation in self.obligations
        }
        for obligation in self.obligations:
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

        expected_counts = {
            "page_count": len(self.pages),
            "element_count": len(self.elements),
            "observation_count": len(self.observations),
            "obligation_count": len(self.obligations),
        }
        for field, expected in expected_counts.items():
            if getattr(self.summary, field) != expected:
                raise ValueError(
                    f"summary.{field}={getattr(self.summary, field)}; esperado {expected}"
                )
        return self

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": SCHEMA_ID,
            "title": "ProcessingManifest",
            "description": (
                "Manifesto operacional gerado pelo Agente "
                "Informacional-Estrutural do Acessília."
            ),
        },
    )
