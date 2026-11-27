"""Local admission pressure is a typed, retryable deferral (#828).

A rejected model call never reached the provider: it says the application's
runner is full, not that the method, the provider or the answer is at fault.
The method result and the execution report carry that distinction, the
executor keeps the method available instead of recording it as tried, and the
replan retries the same action within its recovery budget. A provider outage,
a timeout and a semantically insufficient result stay ordinary failures.
"""

from __future__ import annotations

from pddl_support import (
    build_element,
    build_manifest,
    build_obligation,
    build_orchestrator,
)
from test_changed_obligations import _run

from acessilia_core.agents.model_calls import ModelCallClosed, ModelCallRejected
from acessilia_core.execution.executor import ExecutorAgent, MethodRegistry
from acessilia_core.execution.models import MethodResult
from acessilia_core.manifest.models import ProcessingManifest
from acessilia_core.planning.domain_bundle import DomainBundle
from acessilia_core.planning.planner_agent import PlannerAgent


def _manifest() -> ProcessingManifest:
    obligation = build_obligation(
        "review-structure", ["a"], ["vision-description", "human-review"]
    )
    obligation.method_costs = {"vision-description": 1, "human-review": 100}
    return build_manifest([build_element("a", "paragraph", text="a")], [obligation])


def _obligation(manifest: ProcessingManifest):
    return next(item for item in manifest.obligations if item.id == "o-1")


def _plan(manifest: ProcessingManifest):
    _, plan = PlannerAgent().plan(manifest)
    return plan


def _executor(handler) -> ExecutorAgent:
    registry = MethodRegistry()
    registry.register("vision-description", handler)
    registry.register("human-review", lambda _m, _o: MethodResult(success=True, validated=True))
    return ExecutorAgent(registry, domain=DomainBundle.load())


def _step(report, obligation_id: str = "o-1"):
    return next(step for step in report.steps if step.obligation_id == obligation_id)


def _deferring(_manifest: ProcessingManifest, _obligation_id: str) -> MethodResult:
    return MethodResult(
        success=False,
        validated=False,
        failure_kind="admission_rejected",
        message="model-call execution capacity is full",
    )


def test_a_typed_rejection_defers_without_recording_the_method_as_tried() -> None:
    manifest = _manifest()
    updated, report = _executor(_deferring).execute(_plan(manifest), manifest)

    step = _step(report)
    assert step.status == "failed"
    assert step.failure_kind == "admission_rejected"
    assert "capacity is full" in (step.message or "")
    assert report.status == "replan-required"

    obligation = _obligation(updated)
    assert obligation.status == "pending"
    assert obligation.attempts == []

    # The replan still sees the same method available: the rejection did not
    # turn it into a tried method or escalate the obligation to human review.
    replanned = _plan(updated)
    attempt = next(
        item for item in replanned.steps if item.obligation_id == "o-1"
    )
    assert attempt.method == "vision-description"


def test_a_raised_rejection_defers_the_same_way() -> None:
    manifest = _manifest()

    def rejecting(_manifest: ProcessingManifest, _obligation_id: str) -> MethodResult:
        raise ModelCallRejected("model-call execution capacity is full")

    updated, report = _executor(rejecting).execute(_plan(manifest), manifest)

    assert _step(report).failure_kind == "admission_rejected"
    assert _obligation(updated).attempts == []
    assert _obligation(updated).status == "pending"


def test_a_closed_runner_is_still_an_execution_failure() -> None:
    """Shutdown is lifecycle, not capacity: its method must not be retried."""
    manifest = _manifest()

    def closed(_manifest: ProcessingManifest, _obligation_id: str) -> MethodResult:
        raise ModelCallClosed("application shutdown")

    updated, report = _executor(closed).execute(_plan(manifest), manifest)

    assert _step(report).failure_kind is None
    assert _obligation(updated).attempts[0].status == "failed"
    assert _obligation(updated).attempts[0].method == "vision-description"


def test_an_ordinary_failure_keeps_its_own_policy() -> None:
    """No typed kind: the method is recorded as tried and the replan may use
    the alternative, as a provider or execution failure always did."""
    manifest = _manifest()

    def failed(_manifest: ProcessingManifest, _obligation_id: str) -> MethodResult:
        return MethodResult(success=False, validated=False, message="provider timeout")

    updated, report = _executor(failed).execute(_plan(manifest), manifest)

    assert _step(report).failure_kind is None
    obligation = _obligation(updated)
    assert obligation.attempts[0].status == "failed"
    replanned = _plan(updated)
    attempt = next(item for item in replanned.steps if item.obligation_id == "o-1")
    assert attempt.method == "human-review"


def test_the_replan_retries_a_deferred_action_within_its_budget(monkeypatch, tmp_path) -> None:
    """The first plan is deferred; the failure replan runs the same method
    again and completes once capacity is available."""
    calls: list[str] = []
    manifest = _manifest()
    orchestrator = build_orchestrator(max_replans=1)

    def first_deferred(_manifest: ProcessingManifest, obligation_id: str) -> MethodResult:
        calls.append(obligation_id)
        if len(calls) == 1:
            return _deferring(_manifest, obligation_id)
        return MethodResult(success=True, validated=True)

    orchestrator.executor.registry.register("vision-description", first_deferred)

    _run(orchestrator, manifest, tmp_path, monkeypatch)

    assert calls == ["o-1", "o-1"]
