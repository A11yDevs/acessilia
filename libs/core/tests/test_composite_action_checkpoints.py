"""Checkpoints inside a composite action (#836).

The document's picture descriptions, formula LaTeX and table enrichment are
each one planned action over many elements. To the planner each is atomic;
its persistence is not: after each finished object the method saves the
manifest it is enriching into the run's execution checkpoint, and a crash
in the middle of the step resumes from it, so the work already done is not
paid again.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from core_config_support import core_config
from pddl_support import (
    build_element,
    build_manifest,
    build_obligation,
    build_orchestrator,
)

from acessilia_core.agents.model_calls import current_model_calls
from acessilia_core.agents.output_schemas import DataOutput, VisionOutput
from acessilia_core.pipeline import orchestrator as pddl, preflight
from acessilia_core.pipeline.checkpointing import STEP_PROGRESS_KEY, resumed_manifest
from acessilia_core.pipeline.enrichment import (
    pictures as picture_stage,
    tables as table_stage,
)
from acessilia_core.pipeline.handlers import formula_regions as regions_method
from acessilia_core.ports import PHASE_EXECUTION, NoRegionCache, RunPorts

#: Serial, and no wait before the retry pass, so the calls are in order.
CONFIG = core_config(vision={"concurrency": 1, "retry_pass_delay_seconds": 0})
_PROSE = "A paragraph with enough words to make the document read as text, not as a picture."


class Crash(BaseException):
    """The process dying: not an error any step handles."""


class MemoryCheckpoints:
    """A ``JobCheckpoints`` kept in memory, as the service's would be on disk."""

    job_id = "memory-job"
    options: dict = {}

    def __init__(self) -> None:
        self.phases: dict[str, dict] = {}

    def load(self, phase):
        return deepcopy(self.phases.get(phase))

    def save(self, phase, payload):
        self.phases[phase] = deepcopy(payload)

    def remove(self, phase):
        self.phases.pop(phase, None)


def _left(checkpoints, prefix: str, done: str) -> list[str]:
    """The elements the saved step progress has not finished, in document order.

    What a crash interrupts is a matter of timing: with the concurrency at 1
    the next object can still start while the crash cancels the step. So the
    tests check the contract instead of a fixed list: the resumed run does
    exactly what the saved progress left, never what it finished."""
    progress = checkpoints.phases[PHASE_EXECUTION][STEP_PROGRESS_KEY]
    return [
        element["id"] for element in progress["manifest"]["elements"]
        if element["id"].startswith(prefix) and not element["metadata"].get(done)
    ]


def _run(monkeypatch, manifest, checkpoints, *, classify=False):
    """One job run; ``classify`` runs the real formula region step (M4)."""
    async def nothing(*_args, **_kwargs):
        return None

    monkeypatch.setattr(preflight, "inspect_source_media", nothing)
    if not classify:
        monkeypatch.setattr(regions_method, "_classify_formula_regions", nothing)
    orchestrator = build_orchestrator(max_replans=1)
    orchestrator.information_structural = SimpleNamespace(process=lambda *a, **k: deepcopy(manifest))
    return asyncio.run(orchestrator.execute(
        Path("/tmp/doc.pdf"), Path("/tmp"),
        structured_output=True, config=CONFIG, model_calls=current_model_calls(),
        ports=RunPorts(region_cache=NoRegionCache(), checkpoints=checkpoints, operations=None),
    ))


def _pictures(count: int):
    ids = [f"p-{index}" for index in range(1, count + 1)]
    obligations = []
    for element_id in ids:
        obligation = build_obligation("describe-image", [element_id], ["vision-description", "human-review"])
        obligation.id = f"describe-{element_id}"
        obligation.method_costs = {"vision-description": 20, "human-review": 100}
        obligations.append(obligation)
    elements = [build_element("prose", "paragraph", text=_PROSE)]
    elements += [build_element(element_id, "picture", text="") for element_id in ids]
    return build_manifest(elements, obligations)


def _vision(monkeypatch, *, crash_on: str | None):
    calls: list[str] = []

    class Vision:
        def __init__(self, mode, *, region_cache, toolbox, models):
            pass

        async def describe_region(self, *, image_bytes, **_kwargs):
            element_id = image_bytes.decode()
            calls.append(element_id)
            if element_id == crash_on:
                raise Crash()
            return VisionOutput(kind="description", description=f"Picture {element_id}.", language="en", confidence=0.9)

    monkeypatch.setattr(picture_stage, "VisionAgent", Vision)
    monkeypatch.setattr(
        picture_stage, "_extract_picture_bytes",
        lambda source, element, fallback, *rest, **_kwargs: (element.id.encode(), fallback or 1),
    )
    return calls


def test_a_crash_mid_step_resumes_without_describing_the_pictures_again(monkeypatch) -> None:
    """Five pictures; the process dies on the fourth. The resumed run
    describes only what the saved progress left (the fourth, and the fifth
    unless it finished before the crash cancelled the step), and completes."""
    checkpoints = MemoryCheckpoints()
    first = _vision(monkeypatch, crash_on="p-4")

    with pytest.raises((Crash, BaseExceptionGroup)):
        _run(monkeypatch, _pictures(5), checkpoints)

    assert first[:4] == ["p-1", "p-2", "p-3", "p-4"]
    assert checkpoints.phases[PHASE_EXECUTION][STEP_PROGRESS_KEY]["obligation_id"] == "obligation-describe-images"
    left = _left(checkpoints, "p-", "vision_description_complete")
    assert left[0] == "p-4"

    second = _vision(monkeypatch, crash_on=None)
    payload = _run(monkeypatch, _pictures(5), checkpoints)

    assert second == left
    assert payload["canonical_metadata"]["pddl_execution_status"] == "completed"
    assert STEP_PROGRESS_KEY not in checkpoints.phases.get(PHASE_EXECUTION, {})


def _tables(count: int):
    ids = [f"t-{index}" for index in range(1, count + 1)]
    obligations = []
    for element_id in ids:
        obligation = build_obligation("linearize-table", [element_id], ["pandoc-table", "human-review"])
        obligation.id = f"linearize-{element_id}"
        obligation.method_costs = {"pandoc-table": 15, "human-review": 100}
        obligations.append(obligation)
    elements = [build_element("prose", "paragraph", text=_PROSE)]
    elements += [build_element(element_id, "table", text=f"cells of {element_id}") for element_id in ids]
    return build_manifest(elements, obligations)


def _reader(monkeypatch, *, crash_on: str | None):
    calls: list[str] = []

    class Agent:
        def __init__(self, **_kwargs):
            pass

        async def process_region(self, **kwargs):
            text = kwargs["fallback_text"]
            calls.append(text)
            if text == crash_on:
                raise Crash()
            return DataOutput(
                kind="table",
                rows=[{"cells": [{"text": "Name", "scope": "col"}]}, {"cells": [{"text": text, "scope": "none"}]}],
                language="en", confidence=0.85, warnings=[],
            )

    monkeypatch.setattr(table_stage, "DataAgent", Agent)
    monkeypatch.setattr(
        table_stage, "_extract_picture_bytes",
        lambda source, element, fallback, *rest, **_kwargs: (b"img", fallback or 1),
    )
    return calls


def test_a_crash_mid_step_resumes_without_reading_the_tables_again(monkeypatch) -> None:
    """A document with many tables (#836's acceptance): eight tables, the
    process dies on the sixth; the resumed run reads only what the saved
    progress left."""
    checkpoints = MemoryCheckpoints()
    first = _reader(monkeypatch, crash_on="cells of t-6")

    with pytest.raises((Crash, BaseExceptionGroup)):
        _run(monkeypatch, _tables(8), checkpoints)

    assert first[:6] == [f"cells of t-{index}" for index in range(1, 7)]
    left = _left(checkpoints, "t-", "table_ast")
    assert left[0] == "t-6"
    second = _reader(monkeypatch, crash_on=None)
    payload = _run(monkeypatch, _tables(8), checkpoints)

    assert second == [f"cells of {element_id}" for element_id in left]
    assert payload["canonical_metadata"]["pddl_execution_status"] == "completed"


def _formulas(count: int):
    ids = [f"f-{index}" for index in range(1, count + 1)]
    obligations = []
    for element_id in ids:
        obligation = build_obligation("verbalize-formula", [element_id], ["human-review"])
        obligation.id = f"verbalize-{element_id}"
        obligations.append(obligation)
    elements = [build_element("prose", "paragraph", text=_PROSE)]
    elements += [build_element(element_id, "formula", text="") for element_id in ids]
    return build_manifest(elements, obligations)


def test_a_crash_mid_step_resumes_without_recognizing_the_formulas_again(monkeypatch) -> None:
    """The formula LaTeX (M3): four formulas, the process dies on the third;
    the resumed run reads only what the saved progress left."""
    from pddl_support import install_formula_recognizer

    from acessilia_core.pipeline.enrichment import formulas as formula_stage

    calls: list[str] = []
    crash = {"on": "f-3"}

    def recognize(image, **_kwargs):
        element_id = image.decode()
        calls.append(element_id)
        if element_id == crash["on"]:
            raise Crash()
        return [{"latex": r"\frac{a}{b}"}]

    install_formula_recognizer(monkeypatch, recognize)
    monkeypatch.setattr(
        formula_stage, "_formula_recognition_crop", lambda _source, element, **_kwargs: (element.id.encode(), 1)
    )
    checkpoints = MemoryCheckpoints()

    with pytest.raises((Crash, BaseExceptionGroup)):
        _run(monkeypatch, _formulas(4), checkpoints)

    assert calls[:3] == ["f-1", "f-2", "f-3"]
    left = _left(checkpoints, "f-", "formula_recognition")
    assert left[0] == "f-3"
    calls.clear()
    crash["on"] = None
    # The verbalizations escalate to human review; with readable LaTeX they
    # do not fail the job, which is not what this test is about.
    _run(monkeypatch, _formulas(4), checkpoints)

    assert calls == left


def test_a_crash_mid_step_resumes_without_classifying_the_regions_again(monkeypatch) -> None:
    """The formula region classification (M4): five regions, the process
    dies on the third; the resumed run asks only about what was left."""
    from acessilia_core.pipeline.enrichment import formulas as formula_stage
    from acessilia_core.pipeline.handlers import formula_recognition as formula_method

    calls: list[str] = []
    crash = {"on": "f-3"}

    class Vision:
        def __init__(self, mode, *, region_cache, toolbox, models):
            pass

        async def describe_region(self, *, image_bytes, **_kwargs):
            element_id = image_bytes.decode()
            calls.append(element_id)
            if element_id == crash["on"]:
                raise Crash()
            return VisionOutput(kind="formula", description="", formula_latex="x", language="und", confidence=0.9)

    async def nothing(*_args, **_kwargs):
        return 0

    monkeypatch.setattr(formula_stage, "VisionAgent", Vision)
    monkeypatch.setattr(
        formula_stage, "_formula_recognition_crop", lambda _source, element, **_kwargs: (element.id.encode(), 1)
    )
    monkeypatch.setattr(formula_method, "_enrich_formula_latex", nothing)
    manifest = _formulas(5)
    for element in manifest.elements:
        if element.type == "formula":
            element.text = "x plus y"
    checkpoints = MemoryCheckpoints()

    with pytest.raises((Crash, BaseExceptionGroup)):
        _run(monkeypatch, manifest, checkpoints, classify=True)

    assert calls[:3] == ["f-1", "f-2", "f-3"]
    left = _left(checkpoints, "f-", "formula_classification")
    assert left[0] == "f-3"
    calls.clear()
    crash["on"] = None
    _run(monkeypatch, manifest, checkpoints, classify=True)

    assert calls == left


def test_a_resume_after_the_classification_changed_obligations_plans_them(monkeypatch) -> None:
    """#862 review, item 2.2: ``f-1`` is a drawing (its formula obligations
    become a ``describe-image``) and ``f-2`` an uncertain region (its
    ``verbalize-formula`` keeps only ``human-review``); then the process
    dies on ``f-3``. The resumed run asks only about what was left, plans
    and validates the drawing's ``describe-image`` (selected on the
    restore, #857), and sends ``f-2`` to human review, not to ``mathml``."""
    from acessilia_core.execution.models import MethodResult
    from acessilia_core.manifest.models import validate_obligation_graph
    from acessilia_core.pipeline.enrichment import formulas as formula_stage
    from acessilia_core.pipeline.handlers import formula_recognition as formula_method

    calls: list[str] = []
    crash = {"on": "f-3"}
    answers = {
        "f-1": VisionOutput(kind="description", description="A ring of atoms.", language="en", confidence=0.9),
        "f-2": VisionOutput(kind="description", description="Unclear.", language="en", confidence=0.4,
                            classification_uncertain=True),
    }

    class Vision:
        def __init__(self, mode, *, region_cache, toolbox, models):
            pass

        async def describe_region(self, *, image_bytes, **_kwargs):
            element_id = image_bytes.decode()
            calls.append(element_id)
            if element_id == crash["on"]:
                raise Crash()
            return answers.get(element_id) or VisionOutput(
                kind="formula", description="", formula_latex="x", language="und", confidence=0.9
            )

    async def nothing(*_args, **_kwargs):
        return 0

    mathml: list[str] = []
    real = pddl.PddlAccessibilityOrchestrator._run_executor

    def run_executor(self, config, ports):
        executor = real(self, config, ports)
        executor.registry.register(
            "mathml", lambda _m, obligation_id: mathml.append(obligation_id) or MethodResult(success=True, validated=True)
        )
        return executor

    monkeypatch.setattr(pddl.PddlAccessibilityOrchestrator, "_run_executor", run_executor)
    monkeypatch.setattr(formula_stage, "VisionAgent", Vision)
    monkeypatch.setattr(
        formula_stage, "_formula_recognition_crop", lambda _source, element, **_kwargs: (element.id.encode(), 1)
    )
    monkeypatch.setattr(formula_method, "_enrich_formula_latex", nothing)
    ids = ["f-1", "f-2", "f-3", "f-4"]
    verbalize = []
    for element_id in ids:
        obligation = build_obligation("verbalize-formula", [element_id], ["mathml", "human-review"])
        obligation.id = f"verbalize-{element_id}"
        obligation.method_costs = {"mathml": 10, "human-review": 100}
        verbalize.append(obligation)
    manifest = build_manifest(
        [build_element("prose", "paragraph", text=_PROSE)]
        + [build_element(element_id, "formula", text="x plus y") for element_id in ids],
        verbalize,
    )
    checkpoints = MemoryCheckpoints()

    with pytest.raises((Crash, BaseExceptionGroup)):
        _run(monkeypatch, manifest, checkpoints, classify=True)
    left = _left(checkpoints, "f-", "formula_classification")
    assert left[0] == "f-3" and "f-1" not in left and "f-2" not in left

    calls.clear()
    crash["on"] = None
    payload = _run(monkeypatch, manifest, checkpoints, classify=True)

    assert calls == left
    assert "verbalize-f-1" not in mathml and "verbalize-f-2" not in mathml
    assert {"verbalize-f-3", "verbalize-f-4"} <= set(mathml)
    assert "A ring of atoms." in payload["text"]
    # The last execution checkpoint holds the manifest the resumed run left.
    from acessilia_core.manifest.models import ProcessingManifest

    delivered = ProcessingManifest.model_validate(checkpoints.phases["execution"]["manifest"])
    validate_obligation_graph(delivered)
    describe = [item for item in delivered.obligations if item.kind == "describe-image" and item.target_ids == ["f-1"]]
    assert describe and describe[0].selected and describe[0].status == "satisfied"
    verbalize_f2 = next(item for item in delivered.obligations if item.id == "verbalize-f-2")
    assert verbalize_f2.admissible_methods == ["human-review"]


# The review of #857.


def test_a_second_crash_in_the_same_step_keeps_the_resumed_progress(monkeypatch) -> None:
    """Item 2: the resumed run's progress is saved from its first object,
    so a second crash in the same step loses nothing the resumed run did."""
    checkpoints = MemoryCheckpoints()
    _vision(monkeypatch, crash_on="p-3")
    with pytest.raises((Crash, BaseExceptionGroup)):
        _run(monkeypatch, _pictures(5), checkpoints)
    first_left = _left(checkpoints, "p-", "vision_description_complete")
    assert first_left[0] == "p-3"

    second = _vision(monkeypatch, crash_on="p-5")
    with pytest.raises((Crash, BaseExceptionGroup)):
        _run(monkeypatch, _pictures(5), checkpoints)
    second_left = _left(checkpoints, "p-", "vision_description_complete")

    # The resume starts with what the first crash left; what it described
    # before the second crash (p-3 at least) stayed saved.
    assert second[: len(first_left)] == first_left
    assert second_left[0] == "p-5" and "p-3" not in second_left

    third = _vision(monkeypatch, crash_on=None)
    payload = _run(monkeypatch, _pictures(5), checkpoints)

    assert third == second_left
    assert payload["canonical_metadata"]["pddl_execution_status"] == "completed"


def _formula_first(monkeypatch, *, crash_on: str | None):
    """The vision model reads ``p-1`` as a formula and describes the rest."""
    calls: list[str] = []

    class Vision:
        def __init__(self, mode, *, region_cache, toolbox, models):
            pass

        async def describe_region(self, *, image_bytes, **_kwargs):
            element_id = image_bytes.decode()
            calls.append(element_id)
            if element_id == crash_on:
                raise Crash()
            if element_id == "p-1":
                return VisionOutput(kind="formula", description="", formula_latex=r"\frac{a}{b}",
                                    language="und", confidence=0.9)
            return VisionOutput(kind="description", description=f"Picture {element_id}.", language="en", confidence=0.9)

    monkeypatch.setattr(picture_stage, "VisionAgent", Vision)
    monkeypatch.setattr(
        picture_stage, "_extract_picture_bytes",
        lambda source, element, fallback, *rest, **_kwargs: (element.id.encode(), fallback or 1),
    )
    return calls


def _verbalizing(monkeypatch):
    from acessilia_core.execution.models import MethodResult

    verbalized: list[str] = []

    def mathml(_manifest, obligation_id):
        verbalized.append(obligation_id)
        return MethodResult(success=True, validated=True)

    real = pddl.PddlAccessibilityOrchestrator._run_executor

    def run_executor(self, config, ports):
        executor = real(self, config, ports)
        executor.registry.register("mathml", mathml)
        return executor

    monkeypatch.setattr(pddl.PddlAccessibilityOrchestrator, "_run_executor", run_executor)

    async def nothing(*_args, **_kwargs):
        return 0

    from acessilia_core.pipeline.handlers import formula_recognition as formula_method

    monkeypatch.setattr(formula_method, "_enrich_formula_latex", nothing)
    return verbalized


def test_an_obligation_the_interrupted_step_found_is_planned_on_the_resume(monkeypatch) -> None:
    """Item 1: ``p-1`` read as a formula gets ``verbalize-formula``, then the
    process dies on ``p-3``. The resumed run selects that obligation, as the
    step would have, so it is planned and verbalized instead of being left
    out of a job reported as completed."""
    checkpoints = MemoryCheckpoints()
    verbalized = _verbalizing(monkeypatch)
    _formula_first(monkeypatch, crash_on="p-3")
    with pytest.raises((Crash, BaseExceptionGroup)):
        _run(monkeypatch, _pictures(3), checkpoints)
    progress = checkpoints.phases[PHASE_EXECUTION][STEP_PROGRESS_KEY]["manifest"]
    assert any(item["kind"] == "verbalize-formula" for item in progress["obligations"])

    _formula_first(monkeypatch, crash_on=None)
    payload = _run(monkeypatch, _pictures(3), checkpoints)

    assert payload["canonical_metadata"]["pddl_execution_status"] == "completed"
    assert verbalized == ["obligation-verbalize-formula-p-1"]


def test_a_crash_between_the_handler_and_its_step_checkpoint_loses_no_discovery(monkeypatch) -> None:
    """Item 3: the step finished (every object saved in its progress), and
    the process died writing the step's own checkpoint, before the
    selection ``_select_discovered`` made reached it."""
    checkpoints = MemoryCheckpoints()
    verbalized = _verbalizing(monkeypatch)
    _formula_first(monkeypatch, crash_on=None)
    save = checkpoints.save

    def dies_on_the_step_checkpoint(phase, payload):
        if phase == PHASE_EXECUTION and len(payload.get("results") or []) == 2 and STEP_PROGRESS_KEY not in payload:
            raise Crash()
        save(phase, payload)

    checkpoints.save = dies_on_the_step_checkpoint
    with pytest.raises((Crash, BaseExceptionGroup)):
        _run(monkeypatch, _pictures(3), checkpoints)
    checkpoints.save = save

    payload = _run(monkeypatch, _pictures(3), checkpoints)

    assert payload["canonical_metadata"]["pddl_execution_status"] == "completed"
    assert verbalized == ["obligation-verbalize-formula-p-1"]


def test_the_progress_of_another_step_is_never_resumed_from() -> None:
    """Only the step the plan runs next resumes from the saved progress."""
    plan = SimpleNamespace(steps=[
        SimpleNamespace(obligation_id=None),
        SimpleNamespace(obligation_id="obligation-describe-images"),
        SimpleNamespace(obligation_id="describe-p-1"),
    ])
    state = {"manifest": {"m": "finished"}, "results": [{}],
             STEP_PROGRESS_KEY: {"obligation_id": "obligation-describe-images", "manifest": {"m": "mid-step"}}}

    assert resumed_manifest(state, plan)["m"] == "mid-step"
    assert resumed_manifest({**state, "results": [{}, {}]}, plan) == {"m": "finished"}
    assert resumed_manifest({"manifest": {"m": "finished"}, "results": [{}]}, plan) == {"m": "finished"}
