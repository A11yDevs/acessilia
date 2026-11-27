"""Job goals survive partial plans and their checkpoints (#883)."""

from __future__ import annotations

import hashlib
import json

import pytest
from pddl_support import (
    build_element,
    build_manifest,
    build_obligation,
    build_orchestrator,
)

from acessilia_core.execution.models import MethodResult
from acessilia_core.manifest.models import ProcessingManifest
from acessilia_core.manifest.schema import validate_manifest
from acessilia_core.pipeline.obligations import _unsatisfied_obligations
from acessilia_core.pipeline.orchestrator import PddlAccessibilityOrchestrator
from acessilia_core.planning.planner_agent import PlannerAgent


def _job():
    obligations = [
        build_obligation("repair-heading-hierarchy", ["a"], ["human-review"]).model_copy(
            update={"id": name, "selected": True}
        )
        for name in ("o-run", "o-later")
    ]
    return build_manifest([build_element("a", "heading", text="Title")], obligations)


def _executor(calls):
    executor = build_orchestrator().executor

    def review(_manifest, obligation_id):
        calls.append(obligation_id)
        return MethodResult(success=True, validated=True)

    executor.registry.register("human-review", review)
    return executor


def test_a_partial_plan_completes_while_an_open_job_goal_stays_deferred():
    manifest = _job()
    calls = []
    executor = _executor(calls)
    _, plan = PlannerAgent().plan(manifest, selected_roots=["o-run"])
    snapshots = []

    after, report = executor.execute(plan, manifest, on_step=snapshots.append)

    assert report.status == "completed"
    assert calls == ["o-run"]
    assert after.obligations[1].selected is True
    assert after.obligations[1].status != "satisfied"
    assert after.obligations[1].deferred_reason == "outside-plan"
    assert _unsatisfied_obligations(after)[0]["deferred_reason"] == "outside-plan"
    assert all(snapshot["manifest"]["obligations"][1]["selected"] for snapshot in snapshots)
    assert manifest.obligations[1].deferred_reason is None


def test_a_later_plan_clears_the_deferral_and_satisfies_the_goal():
    manifest = _job()
    calls = []
    executor = _executor(calls)
    _, first = PlannerAgent().plan(manifest, selected_roots=["o-run"])
    after, _ = executor.execute(first, manifest)
    saved = after.model_dump(mode="json", by_alias=True)
    assert validate_manifest(saved) == []
    after = ProcessingManifest.model_validate(saved)
    assert after.obligations[1].deferred_reason == "outside-plan"
    after.status = "processing"
    _, second = PlannerAgent().plan(after, selected_roots=["o-later"])

    finished, report = executor.execute(second, after)

    assert report.status == "completed"
    assert calls == ["o-run", "o-later"]
    assert finished.obligations[1].status == "satisfied"
    assert finished.obligations[1].deferred_reason is None
    assert _unsatisfied_obligations(finished) == []


def test_a_removed_goal_is_not_recreated_by_a_partial_plan():
    manifest = _job()
    executor = _executor([])

    def remove(working, _obligation_id):
        working.obligations = [item for item in working.obligations if item.id != "o-later"]
        working.summary.obligation_count = len(working.obligations)
        return MethodResult(success=True, validated=True)

    executor.registry.register("human-review", remove)
    _, plan = PlannerAgent().plan(manifest, selected_roots=["o-run"])

    after, report = executor.execute(plan, manifest)

    assert report.status == "completed"
    assert [item.id for item in after.obligations] == ["o-run"]
    assert _unsatisfied_obligations(after) == []


def test_a_completed_partial_plan_does_not_allow_an_open_critical_goal_to_be_delivered():
    manifest = _job()
    manifest.obligations[1].kind = "review-structure"
    _, plan = PlannerAgent().plan(manifest, selected_roots=["o-run"])
    after, report = _executor([]).execute(plan, manifest)

    assert report.status == "completed"
    with pytest.raises(RuntimeError, match="review-structure"):
        PddlAccessibilityOrchestrator._check_unsatisfied(after, report)


def test_an_unselected_obligation_outside_the_plan_does_not_become_a_job_goal():
    manifest = _job()
    manifest.obligations[1].selected = False
    _, plan = PlannerAgent().plan(manifest, selected_roots=["o-run"])

    after, report = _executor([]).execute(plan, manifest)

    assert report.status == "completed"
    assert after.obligations[1].selected is False
    assert after.obligations[1].deferred_reason is None
    assert _unsatisfied_obligations(after) == []


def test_an_old_manifest_keeps_its_plan_binding_and_round_trips_unchanged():
    legacy = _job().model_dump(mode="json", by_alias=True)
    assert all("deferred_reason" not in item for item in legacy["obligations"])
    manifest = ProcessingManifest.model_validate(legacy)
    _, plan = PlannerAgent().plan(manifest, selected_roots=["o-run"])
    old_hash = hashlib.sha256(
        json.dumps(legacy, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    assert plan.manifest_sha256 == old_hash
    assert manifest.model_dump(mode="json", by_alias=True) == legacy
    assert validate_manifest(legacy) == []
    _, report = _executor([]).execute(plan, manifest)
    assert report.status == "completed"
