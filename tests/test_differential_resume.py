"""A run that dies mid-step and resumes from its checkpoints (#874).

The differential fixtures (#849) compare a run with older cores. A resume
compares a run with itself: the same case run without interruption is the
oracle. The fake Toolbox interrupts the run at its N-th vision or
``math.recognize`` request, with a ``BaseException`` no step handler
catches; the run then starts again from the checkpoints the service writes
(``FileJobCheckpoints``, in a temporary data directory), read by a new
instance, as a restarted worker would.

Two steps save their progress inside the step (``step_progress``, #836):
the picture descriptions (M1) and the formula LaTeX (M3). For each, the
interrupted run must have saved what it was answered, and the resumed run
must deliver the canonical document of the uninterrupted run, asking for
exactly what the interrupted run had not been answered: nothing twice, of
any kind (the formula case's VLM classifications too), nothing missing.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from tests.differential import build_cases
from tests.differential.fake_toolbox import Interrupted
from tests.differential.runner import run_case

E = build_cases.element
PROSE = build_cases.PROSE

#: Three pictures, described one at a time (``VISION_CONCURRENCY=1``).
PICTURES = {
    "description": "Three pictures, for the resume of the descriptions (M1).",
    "environment": {"VISION_CONCURRENCY": "1"},
    "elements": [
        E("p1", "paragraph", PROSE * 3, 60, 170, 1),
        E("pic1", "picture", "", 180, 300, 2),
        E("pic2", "picture", "", 310, 430, 3),
        E("pic3", "picture", "", 440, 560, 4),
        E("p2", "paragraph", PROSE * 2, 580, 700, 5),
    ],
    "vision": {
        "pic1": {"description": "A bench with an oscilloscope."},
        "pic2": {"description": "A cart on a ramp."},
        "pic3": {"description": "A chart of the speed over time."},
    },
}

#: Two formulas without LaTeX markup, classified then read one at a time.
FORMULAS = {
    "description": "Two formulas to read, for the resume of the formula LaTeX (M3).",
    "environment": {"VISION_CONCURRENCY": "1"},
    "elements": [
        E("p1", "paragraph", PROSE * 3, 60, 170, 1),
        E("f1", "formula", "s ( t ) = t 3", 180, 200, 2),
        E("f2", "formula", "v ( t ) = 3 t 2", 210, 230, 3),
        E("p2", "paragraph", PROSE * 2, 240, 350, 4),
    ],
    "vision": {
        "f1": {"kind": "formula", "formula_latex": "s(t) = t^3", "description": "s of t equals t cubed"},
        "f2": {"kind": "formula", "formula_latex": "v(t) = 3t^2", "description": "v of t equals 3 t squared"},
    },
    "latex": {"f1": "s(t) = t^{3}", "f2": "v(t) = 3t^{2}"},
}


def _described(element: dict[str, Any]) -> bool:
    return bool(element.get("text"))


def _recognized(element: dict[str, Any]) -> bool:
    return "formula_recognition" in (element.get("metadata") or {})


def _interruption(error: BaseException) -> Interrupted:
    """The :class:`Interrupted` ``error`` is, alone or inside the exception
    groups of the core's concurrent stages; a group that also holds another
    failure is not an interruption, and fails the test."""
    if isinstance(error, Interrupted):
        return error
    assert isinstance(error, BaseExceptionGroup), f"the run died of {error!r}, not of the interruption"
    interrupted, rest = error.split(Interrupted)
    assert rest is None, f"the run died of {rest!r} besides the interruption"
    assert interrupted is not None
    return _interruption(interrupted.exceptions[0])


def _dies(case: Path, **kwargs: Any) -> Interrupted:
    with pytest.raises(BaseException) as error:  # noqa: B017 - checked by _interruption
        run_case(case, **kwargs)
    return _interruption(error.value)


def test_an_interruption_beside_another_failure_is_not_accepted() -> None:
    """#898 review: an unexpected error next to the interruption must not
    pass for it."""
    alone = Interrupted("dies", [])
    assert _interruption(BaseExceptionGroup("stage", [BaseExceptionGroup("inner", [alone])])) is alone
    with pytest.raises(AssertionError, match="besides the interruption"):
        _interruption(BaseExceptionGroup("stage", [Interrupted("dies", []), ValueError("invalid state")]))
    with pytest.raises(AssertionError, match="not of the interruption"):
        _interruption(ValueError("invalid state"))


def _case(tmp_path: Path, name: str, spec: dict[str, Any]) -> Path:
    target = tmp_path / name / "case.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(build_cases.build(name, spec), ensure_ascii=False), encoding="utf-8")
    return target


@pytest.fixture
def job_checkpoints(tmp_path, monkeypatch):
    """A new ``FileJobCheckpoints`` of one job at each call, on files under a
    temporary data directory, with the service's options."""
    from backend.config.settings import settings
    from backend.services.job_checkpoint import FileJobCheckpoints
    from backend.services.run_ports import checkpoint_options

    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    return lambda: FileJobCheckpoints("differential-resume", checkpoint_options())


@pytest.mark.parametrize(
    ("spec", "interrupt", "obligation", "saved"),
    [
        (PICTURES, ("vlm", 2), "obligation-describe-images", _described),
        (FORMULAS, ("math.recognize", 2), "obligation-recognize-formulas", _recognized),
    ],
    ids=["picture-descriptions", "formula-latex"],
)
def test_a_resumed_run_delivers_what_an_uninterrupted_one_does(
    tmp_path, job_checkpoints, spec, interrupt, obligation, saved
) -> None:
    """The run dies at the second request of the step, after its first
    answer was saved; the resume finishes it without asking again for any
    answer the interrupted run had, and delivers the same document."""
    case = _case(tmp_path, "resume", spec)
    whole = run_case(case)
    toolbox: dict[str, Any] = {}
    kind = interrupt[0]

    interrupted = _dies(case, checkpoints=job_checkpoints(), interrupt=interrupt, toolbox_store=toolbox)

    # What the interrupted run saved, read back from the files: the step is
    # still open, and its progress holds the answers of that kind it had.
    state = job_checkpoints().load("execution")
    assert state is not None and "step_progress" in state, "the interrupted run saved no step progress"
    progress = state["step_progress"]
    assert progress["obligation_id"] == obligation
    [step] = [item for item in progress["manifest"]["obligations"] if item["id"] == obligation]
    assert step["status"] != "satisfied"
    targets = {element for served_kind, element in whole["served"] if served_kind == kind}
    elements = {item["id"]: item for item in progress["manifest"]["elements"] if item["id"] in targets}
    answered = {element for served_kind, element in interrupted.served if served_kind == kind}
    assert answered and answered < targets
    assert {element for element, item in elements.items() if saved(item)} == answered

    resumed = run_case(case, checkpoints=job_checkpoints(), toolbox_store=toolbox)

    assert whole["unhandled"] == resumed["unhandled"] == []
    assert resumed["canonical"] == whole["canonical"]
    assert resumed["canonical"]["metadata"]["pddl_unsatisfied_obligations"] == []
    assert (resumed["cacheable"], resumed["refused"]) == (whole["cacheable"], whole["refused"]) == (True, [])
    # Every answer, of every kind, once across the two runs: the resume asks
    # for none the interrupted run had, and for every other one.
    assert Counter(map(tuple, interrupted.served)) + Counter(map(tuple, resumed["served"])) == Counter(
        map(tuple, whole["served"])
    )


def test_a_run_without_checkpoints_starts_over(tmp_path) -> None:
    """The control: the same interruption with no checkpoints leaves nothing
    to resume from, so a second run asks for every answer again."""
    case = _case(tmp_path, "control", PICTURES)
    interrupted = _dies(case, interrupt=("vlm", 2))
    again = run_case(case)

    assert interrupted.served == [("vlm", "pic1")]
    assert [element for kind, element in again["served"] if kind == "vlm"] == ["pic1", "pic2", "pic3"]
