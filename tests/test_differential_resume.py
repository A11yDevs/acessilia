"""A run that dies mid-step and resumes from its checkpoints (#874).

The differential fixtures (#849) compare a run with older cores. A resume
compares a run with itself: the same case run without interruption is the
oracle. The fake Toolbox interrupts the run at its N-th vision or
``math.recognize`` request, with a ``BaseException`` no handler catches, as
a process death would; the run then starts again over the same checkpoints
(``JobCheckpoints``, kept here in memory, every payload through JSON as a
file would be).

Two steps save their progress inside the step (``step_progress``, #836):
the picture descriptions (M1) and the formula LaTeX (M3). For each, the
resumed run must deliver the canonical document of the uninterrupted run,
and must not ask again for what the interrupted run had already answered.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.differential import build_cases
from tests.differential.fake_toolbox import Interrupted
from tests.differential.runner import run_case


class MemoryCheckpoints:
    """``JobCheckpoints`` in memory; each payload goes through JSON."""

    job_id = "differential-resume"
    options: dict[str, Any] = {}

    def __init__(self) -> None:
        self.payloads: dict[str, str] = {}

    def load(self, phase: str) -> dict[str, Any] | None:
        payload = self.payloads.get(phase)
        return json.loads(payload) if payload is not None else None

    def save(self, phase: str, payload: dict[str, Any]) -> None:
        self.payloads[phase] = json.dumps(payload)

    def remove(self, phase: str) -> None:
        self.payloads.pop(phase, None)


E = build_cases._element
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


def _dies(case: Path, **kwargs: Any) -> None:
    """Run ``case`` and require that it died of :class:`Interrupted`, alone
    or inside the exception group of the core's concurrent stages."""

    def interrupted(error: BaseException) -> bool:
        if isinstance(error, Interrupted):
            return True
        return isinstance(error, BaseExceptionGroup) and any(interrupted(item) for item in error.exceptions)

    with pytest.raises(BaseException) as error:  # noqa: B017 - checked below
        run_case(case, **kwargs)
    assert interrupted(error.value), f"the run died of {error.value!r}, not of the interruption"


def _case(tmp_path: Path, name: str, spec: dict[str, Any]) -> Path:
    target = tmp_path / name / "case.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(build_cases.build(name, spec), ensure_ascii=False), encoding="utf-8")
    return target


@pytest.mark.parametrize(
    ("spec", "interrupt", "answered_before"),
    [
        (PICTURES, ("vlm", 2), [("vlm", "pic1")]),
        (FORMULAS, ("math.recognize", 2), [("math.recognize", "f1")]),
    ],
    ids=["picture-descriptions", "formula-latex"],
)
def test_a_resumed_run_delivers_what_an_uninterrupted_one_does(tmp_path, spec, interrupt, answered_before) -> None:
    """The run dies at the second request of the step, after its first
    answer was saved; the resume finishes it without asking for that answer
    again, and delivers the same canonical document."""
    case = _case(tmp_path, "resume", spec)
    whole = run_case(case)
    checkpoints, toolbox = MemoryCheckpoints(), {}

    _dies(case, checkpoints=checkpoints, interrupt=interrupt, toolbox_store=toolbox)
    assert checkpoints.payloads, "the interrupted run saved no checkpoint"
    resumed = run_case(case, checkpoints=checkpoints, toolbox_store=toolbox)

    assert whole["unhandled"] == resumed["unhandled"] == []
    assert resumed["canonical"] == whole["canonical"]
    kind = interrupt[0]
    asked_again = [item for item in resumed["served"] if tuple(item) in answered_before]
    assert asked_again == [], f"the resume asked again for {asked_again}"
    whole_answers = sorted(element for served_kind, element in whole["served"] if served_kind == kind)
    resumed_answers = sorted(element for served_kind, element in resumed["served"] if served_kind == kind)
    assert resumed_answers == sorted(set(whole_answers) - {element for _, element in answered_before})


def test_a_run_without_checkpoints_starts_over() -> None:
    """The control: the same interruption with no checkpoints leaves nothing
    to resume from, so a second run asks for every answer again."""
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        case = _case(Path(directory), "control", PICTURES)
        _dies(case, interrupt=("vlm", 2))
        again = run_case(case)

    assert [element for kind, element in again["served"] if kind == "vlm"] == ["pic1", "pic2", "pic3"]
