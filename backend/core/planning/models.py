from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from backend.i18n import t  # noqa: E402
from frontend.telegram.messages import (  # noqa: E402
    MSG_ACTION_REJECTS_EXECUTION_PARAMETERS,
    MSG_PLANNING_COMPARISON_SCHEMA_DESCRIPTION,
    MSG_COMPARISON_OUTCOME_KEY_MISMATCH,
    MSG_COMPARISON_REQUIRES_BOTH_BACKENDS,
    MSG_EXECUTE_OBLIGATION_MISSING_FIELDS,
    MSG_EXPECTED_TOTAL_COST_MISMATCH,
    MSG_NOMINAL_PLAN_SCHEMA_DESCRIPTION,
    MSG_NOMINAL_PLAN_MUST_END_COMPLETE_JOB,
    MSG_PLANNER_OUTCOME_FAILED_MUST_NOT_PASS_VALIDATION,
    MSG_PLANNER_OUTCOME_FAILED_REQUIRES_ERROR,
    MSG_PLANNER_OUTCOME_SOLVED_MUST_NOT_CARRY_ERROR,
    MSG_PLANNER_OUTCOME_SOLVED_REQUIRES_FIELDS,
    MSG_PLANNER_OUTCOME_MUST_PASS_VALIDATION,
    MSG_PLAN_CONTAINS_UNSELECTED_OBLIGATION,
    MSG_PLAN_INDICES_CONSECUTIVE_FROM_ZERO,
)


PLAN_SCHEMA_VERSION = "1.0.0"
PLAN_SCHEMA_ID = "urn:a11y-devs:schema:nominal-plan:1.0.0"
COMPARISON_SCHEMA_VERSION = "1.0.0"
COMPARISON_SCHEMA_ID = (
    "urn:a11y-devs:schema:planning-comparison:1.0.0"
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DomainIdentity(StrictModel):
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    domain_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    description_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class PlanStep(StrictModel):
    index: int = Field(ge=0)
    action: Literal["start-job", "execute-obligation", "complete-job"]
    obligation_id: str | None = None
    obligation_kind: str | None = None
    method: str | None = None
    expected_cost: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_parameters(self) -> "PlanStep":
        execution_fields = (
            self.obligation_id,
            self.obligation_kind,
            self.method,
        )
        if self.action == "execute-obligation":
            if any(value is None for value in execution_fields):
                raise ValueError(t(MSG_EXECUTE_OBLIGATION_MISSING_FIELDS))
        elif any(value is not None for value in execution_fields):
            raise ValueError(
                t(MSG_ACTION_REJECTS_EXECUTION_PARAMETERS).format(action=self.action)
            )
        return self


class NominalPlan(StrictModel):
    schema_ref: str = Field(default=PLAN_SCHEMA_ID, alias="$schema")
    schema_version: Literal["1.0.0"] = PLAN_SCHEMA_VERSION
    plan_id: str = Field(min_length=1)
    generated_at: datetime
    status: Literal["nominal"] = "nominal"
    manifest_id: str = Field(min_length=1)
    manifest_revision: int = Field(ge=1)
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    domain: DomainIdentity
    problem_name: str = Field(min_length=1)
    problem_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    planner: str = Field(min_length=1)
    metric: Literal["minimize-total-cost"] = "minimize-total-cost"
    selected_obligations: list[str]
    expected_total_cost: int = Field(ge=0)
    steps: list[PlanStep]

    @model_validator(mode="after")
    def validate_plan(self) -> "NominalPlan":
        indexes = [step.index for step in self.steps]
        if indexes != list(range(len(self.steps))):
            raise ValueError(t(MSG_PLAN_INDICES_CONSECUTIVE_FROM_ZERO))
        if not self.steps or self.steps[-1].action != "complete-job":
            raise ValueError(t(MSG_NOMINAL_PLAN_MUST_END_COMPLETE_JOB))
        calculated = sum(step.expected_cost for step in self.steps)
        if calculated != self.expected_total_cost:
            raise ValueError(
                t(MSG_EXPECTED_TOTAL_COST_MISMATCH).format(
                    declared=self.expected_total_cost,
                    calculated=calculated,
                )
            )
        selected = set(self.selected_obligations)
        planned = {
            step.obligation_id
            for step in self.steps
            if step.action == "execute-obligation"
        }
        if not planned.issubset(selected):
            raise ValueError(t(MSG_PLAN_CONTAINS_UNSELECTED_OBLIGATION))
        return self

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": PLAN_SCHEMA_ID,
            "title": "NominalPlan",
            "description": (
                t(MSG_NOMINAL_PLAN_SCHEMA_DESCRIPTION)
            ),
        },
    )


PlannerBackend = Literal["internal", "fast-downward"]
PlannerSelection = Literal["internal", "fast-downward", "both"]
StatisticValue = int | float | str | bool


class PlannerOutcome(StrictModel):
    """Resultado observável de uma execução de backend."""

    backend: PlannerBackend
    status: Literal["solved", "failed"]
    planner: str
    runtime_ms: int = Field(ge=0)
    plan_file: str | None = None
    plan_id: str | None = None
    expected_total_cost: int | None = Field(default=None, ge=0)
    step_count: int | None = Field(default=None, ge=0)
    execution_step_count: int | None = Field(default=None, ge=0)
    validation_passed: bool = False
    statistics: dict[str, StatisticValue] = Field(default_factory=dict)
    error_type: str | None = None
    error_message: str | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> "PlannerOutcome":
        solved_fields = (
            self.plan_file,
            self.plan_id,
            self.expected_total_cost,
            self.step_count,
            self.execution_step_count,
        )
        if self.status == "solved":
            if any(value is None for value in solved_fields):
                raise ValueError(
                    t(MSG_PLANNER_OUTCOME_SOLVED_REQUIRES_FIELDS)
                )
            if not self.validation_passed:
                raise ValueError(t(MSG_PLANNER_OUTCOME_MUST_PASS_VALIDATION))
            if self.error_type is not None or self.error_message is not None:
                raise ValueError(t(MSG_PLANNER_OUTCOME_SOLVED_MUST_NOT_CARRY_ERROR))
        else:
            if self.error_type is None or self.error_message is None:
                raise ValueError(t(MSG_PLANNER_OUTCOME_FAILED_REQUIRES_ERROR))
            if self.validation_passed:
                raise ValueError(t(MSG_PLANNER_OUTCOME_FAILED_MUST_NOT_PASS_VALIDATION))
        return self


class ComparisonDetails(StrictModel):
    verdict: Literal["identical", "equivalent", "different", "inconclusive"]
    both_solved: bool
    same_expected_total_cost: bool | None = None
    cost_delta_fast_downward_minus_internal: int | None = None
    same_selected_obligations: bool | None = None
    same_executed_obligations: bool | None = None
    same_method_selection: bool | None = None
    same_action_multiset: bool | None = None
    same_action_sequence: bool | None = None
    internal_only_steps: list[str] = Field(default_factory=list)
    fast_downward_only_steps: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class PlanningComparison(StrictModel):
    """Normalized comparison report used by differential planner studies."""

    schema_ref: str = Field(default=COMPARISON_SCHEMA_ID, alias="$schema")
    schema_version: Literal["1.0.0"] = COMPARISON_SCHEMA_VERSION
    comparison_id: str = Field(min_length=1)
    generated_at: datetime
    requested_planner: Literal["both"] = "both"
    preferred_backend: PlannerBackend
    manifest_id: str = Field(min_length=1)
    manifest_revision: int = Field(ge=1)
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    domain: DomainIdentity
    problem_name: str = Field(min_length=1)
    problem_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    outcomes: dict[PlannerBackend, PlannerOutcome]
    comparison: ComparisonDetails

    @model_validator(mode="after")
    def validate_report(self) -> "PlanningComparison":
        if set(self.outcomes) != {"internal", "fast-downward"}:
            raise ValueError(t(MSG_COMPARISON_REQUIRES_BOTH_BACKENDS))
        for backend, outcome in self.outcomes.items():
            if backend != outcome.backend:
                raise ValueError(
                    t(MSG_COMPARISON_OUTCOME_KEY_MISMATCH).format(
                        key=backend,
                        backend=outcome.backend,
                    )
                )
        return self

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": COMPARISON_SCHEMA_ID,
            "title": "PlanningComparison",
            "description": (
                t(MSG_PLANNING_COMPARISON_SCHEMA_DESCRIPTION)
            ),
        },
    )
