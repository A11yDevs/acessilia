from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from acessilia_core.execution.messages import (  # noqa: E402
    MSG_EXECUTION_REPORT_SCHEMA_DESCRIPTION,
    MSG_EXECUTION_STEP_FAILURE_KIND_REQUIRES_FAILED,
    MSG_METHOD_RESULT_DUPLICATE_ARTIFACT_IDS,
    MSG_METHOD_RESULT_FAILURE_KIND_REQUIRES_FAILURE,
    MSG_METHOD_RESULT_SUCCESS_REQUIRES_VALIDATION,
)
from acessilia_core.i18n import t  # noqa: E402
from acessilia_core.manifest.models import Artifact  # noqa: E402

EXECUTION_SCHEMA_VERSION: Literal["1.1.0"] = "1.1.0"
EXECUTION_SCHEMA_ID = "urn:a11y-devs:schema:execution-report:1.1.0"

ReportMode = Literal["live", "dry-run"]
ReportStatus = Literal[
    "completed",
    "failed",
    "dry-run-completed",
    "replan-required",
]
StepStatus = Literal["succeeded", "failed", "simulated", "skipped"]
#: Why a method did not produce a usable result when the caller must not treat
#: it as a genuine method failure (#828). ``admission_rejected`` means the
#: local model-call runner was full: capacity, not provider health or a
#: semantic result. The executor keeps the obligation and the method available
#: so the replan can retry the same action within its recovery budget, while a
#: provider outage, a timeout or an insufficient answer stay ordinary failures.
MethodFailureKind = Literal["admission_rejected"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MethodResult(StrictModel):
    success: bool
    validated: bool = False
    message: str | None = None
    artifacts: list[Artifact] = Field(default_factory=list)
    #: Set only with ``success=False``: a retryable failure the executor must
    #: not count as the method having been tried.
    failure_kind: MethodFailureKind | None = None

    @model_validator(mode="after")
    def success_requires_validation(self) -> "MethodResult":
        if self.success and not self.validated:
            raise ValueError(t(MSG_METHOD_RESULT_SUCCESS_REQUIRES_VALIDATION))
        if self.failure_kind is not None and (self.success or self.validated):
            raise ValueError(t(MSG_METHOD_RESULT_FAILURE_KIND_REQUIRES_FAILURE))
        artifact_ids = [artifact.id for artifact in self.artifacts]
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError(t(MSG_METHOD_RESULT_DUPLICATE_ARTIFACT_IDS))
        return self


class ExecutionStepResult(StrictModel):
    index: int = Field(ge=0)
    action: str = Field(min_length=1)
    status: StepStatus
    obligation_id: str | None = None
    method: str | None = None
    started_at: datetime
    completed_at: datetime
    message: str | None = None
    artifact_ids: list[str] = Field(default_factory=list)
    #: A retryable failure the planner must tell from a provider or execution
    #: failure (#828). Absent on an ordinary step.
    failure_kind: MethodFailureKind | None = None

    @model_validator(mode="after")
    def failure_kind_requires_failed_status(self) -> "ExecutionStepResult":
        if self.failure_kind is not None and self.status != "failed":
            raise ValueError(t(MSG_EXECUTION_STEP_FAILURE_KIND_REQUIRES_FAILED))
        return self


class ExecutionReport(StrictModel):
    schema_ref: str = Field(default=EXECUTION_SCHEMA_ID, alias="$schema")
    #: 1.0.0 reports are read as historical records; new reports use 1.1.0.
    schema_version: Literal["1.0.0", "1.1.0"] = EXECUTION_SCHEMA_VERSION
    execution_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    manifest_id: str = Field(min_length=1)
    manifest_revision_before: int = Field(ge=1)
    manifest_revision_after: int = Field(ge=1)
    started_at: datetime
    completed_at: datetime
    mode: ReportMode
    status: ReportStatus
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
            "description": MSG_EXECUTION_REPORT_SCHEMA_DESCRIPTION,
        },
    )
