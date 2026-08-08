from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.core.manifest.models import Artifact


EXECUTION_SCHEMA_VERSION = "1.0.0"
EXECUTION_SCHEMA_ID = "urn:a11y-devs:schema:execution-report:1.0.0"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MethodResult(StrictModel):
    success: bool
    validated: bool = False
    message: str | None = None
    artifacts: list[Artifact] = Field(default_factory=list)

    @model_validator(mode="after")
    def success_requires_validation(self) -> "MethodResult":
        if self.success and not self.validated:
            raise ValueError("Um resultado bem-sucedido deve estar validado")
        artifact_ids = [artifact.id for artifact in self.artifacts]
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError("O resultado contém IDs de artefatos duplicados")
        return self


class ExecutionStepResult(StrictModel):
    index: int = Field(ge=0)
    action: str = Field(min_length=1)
    status: Literal["succeeded", "failed", "simulated", "skipped"]
    obligation_id: str | None = None
    method: str | None = None
    started_at: datetime
    completed_at: datetime
    message: str | None = None
    artifact_ids: list[str] = Field(default_factory=list)


class ExecutionReport(StrictModel):
    schema_ref: str = Field(default=EXECUTION_SCHEMA_ID, alias="$schema")
    schema_version: Literal["1.0.0"] = EXECUTION_SCHEMA_VERSION
    execution_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    manifest_id: str = Field(min_length=1)
    manifest_revision_before: int = Field(ge=1)
    manifest_revision_after: int = Field(ge=1)
    started_at: datetime
    completed_at: datetime
    mode: Literal["live", "dry-run"]
    status: Literal[
        "completed",
        "failed",
        "dry-run-completed",
        "replan-required",
    ]
    replan_required: bool
    failed_step_index: int | None = Field(default=None, ge=0)
    steps: list[ExecutionStepResult]

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": EXECUTION_SCHEMA_ID,
            "title": "ExecutionReport",
            "description": (
                "Relatório da execução confirmada ou simulada de um plano nominal."
            ),
        },
    )
