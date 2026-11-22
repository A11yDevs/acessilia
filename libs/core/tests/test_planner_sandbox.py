"""The planner's file tools write only under the sandbox their caller gives
(ADR-0016, step 6)."""

from __future__ import annotations

import json

import pytest
from core_config_support import paths_config
from pddl_support import build_element, build_manifest, build_obligation

from acessilia_core.planning.planner_agent import SANDBOX_DIRNAME, PlannerAgent


def _manifest_file(directory):
    obligation = build_obligation("describe-image", ["p-1"], ["human-review"])
    obligation.selected = True
    manifest = build_manifest([build_element("p-1", "paragraph", text="Text.")], [obligation])
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "manifest.json"
    path.write_text(json.dumps(manifest.model_dump(mode="json", by_alias=True)), encoding="utf-8")
    return path


def test_the_file_tools_work_inside_the_given_sandbox(tmp_path) -> None:
    sandbox = paths_config(data_dir=tmp_path).data_dir / SANDBOX_DIRNAME
    manifest = _manifest_file(sandbox)

    result = PlannerAgent(sandbox_dir=sandbox).compile_manifest_file(
        str(manifest), str(sandbox / "out" / "problem.pddl")
    )

    assert (sandbox / "out" / "problem.pddl").is_file()
    assert result["problem_path"] == str((sandbox / "out" / "problem.pddl").resolve())


@pytest.mark.parametrize("escape", ["../outside.pddl", "/etc/problem.pddl", "~/problem.pddl"])
def test_a_path_out_of_the_sandbox_is_refused(tmp_path, escape) -> None:
    sandbox = tmp_path / SANDBOX_DIRNAME
    manifest = _manifest_file(sandbox)
    target = escape if escape.startswith(("/", "~")) else str(sandbox / escape)

    with pytest.raises(ValueError, match="sandbox"):
        PlannerAgent(sandbox_dir=sandbox).compile_manifest_file(str(manifest), target)


def test_the_file_tools_refuse_to_run_without_a_sandbox(tmp_path) -> None:
    """No path is guessed from where the code lives: an installed package has
    no repository around it."""
    manifest = _manifest_file(tmp_path)

    with pytest.raises(RuntimeError, match="sandbox_dir"):
        PlannerAgent().compile_manifest_file(str(manifest), str(tmp_path / "problem.pddl"))
    with pytest.raises(RuntimeError, match="sandbox_dir"):
        PlannerAgent().generate_nominal_plan_files(str(manifest), str(tmp_path / "out"))


def test_planning_in_memory_needs_no_sandbox() -> None:
    obligation = build_obligation("describe-image", ["p-1"], ["human-review"])
    obligation.selected = True
    manifest = build_manifest([build_element("p-1", "paragraph", text="Text.")], [obligation])

    _, plan = PlannerAgent().plan(manifest, selected_roots=[obligation.id])

    assert plan.steps


def _tool_names(planner):
    return [tool.__name__ for tool in planner.agent.tools[0].tools]


def test_the_agent_is_offered_the_file_tools_only_with_a_sandbox(tmp_path) -> None:
    """An Agno agent must not be offered a tool that always fails (review of #569)."""
    file_tools = {"compile_manifest_file", "generate_nominal_plan_files"}

    assert not file_tools & set(_tool_names(PlannerAgent()))
    assert file_tools <= set(_tool_names(PlannerAgent(sandbox_dir=tmp_path / SANDBOX_DIRNAME)))
    assert {"inspect_domain", "validate_problem_text"} <= set(_tool_names(PlannerAgent()))
