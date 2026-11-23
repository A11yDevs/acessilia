"""Unit tests for the shrinking docstruct allowlist check (scripts/check_docstruct_allowlist.py, #764)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts import check_docstruct_allowlist as check

ROOT = Path(__file__).resolve().parents[1]

BASE = {
    "docstruct.manifest": {"class": "contract"},
    "docstruct.fusion.judge": {
        "class": "algorithm",
        "files": {"a.py": ["decide_pair", "should_judge"], "b.py": ["should_judge"]},
    },
}


def _head(**changes) -> dict:
    head = json.loads(json.dumps(BASE))
    head.update(changes)
    return head


def test_the_same_allowlist_does_not_widen() -> None:
    assert check.widenings(BASE, BASE) == []


def test_removals_do_not_widen() -> None:
    head = _head(**{"docstruct.fusion.judge": {"class": "algorithm", "files": {"a.py": ["should_judge"]}}})
    del head["docstruct.manifest"]
    assert check.widenings(BASE, head) == []


def test_a_new_module_widens() -> None:
    head = _head(**{"docstruct.text.latex": {"class": "algorithm", "files": {"a.py": ["bare_latex"]}}})
    assert check.widenings(BASE, head) == ["new module docstruct.text.latex (algorithm)"]


def test_a_new_importer_widens() -> None:
    files = {**BASE["docstruct.fusion.judge"]["files"], "c.py": ["should_judge"]}
    head = _head(**{"docstruct.fusion.judge": {"class": "algorithm", "files": files}})
    assert check.widenings(BASE, head) == ["docstruct.fusion.judge: new importer c.py"]


def test_a_new_name_widens() -> None:
    files = {**BASE["docstruct.fusion.judge"]["files"], "b.py": ["debias", "should_judge"]}
    head = _head(**{"docstruct.fusion.judge": {"class": "algorithm", "files": files}})
    assert check.widenings(BASE, head) == ["docstruct.fusion.judge: b.py adds debias"]


def test_replacing_a_wildcard_with_names_does_not_widen() -> None:
    base = _head(**{"docstruct.text.latex": {"class": "algorithm", "files": {"a.py": ["*"]}}})
    head = _head(**{"docstruct.text.latex": {"class": "algorithm", "files": {"a.py": ["bare_latex"]}}})
    assert check.widenings(base, head) == []


def test_adding_a_wildcard_widens() -> None:
    files = {**BASE["docstruct.fusion.judge"]["files"], "b.py": ["*", "should_judge"]}
    head = _head(**{"docstruct.fusion.judge": {"class": "algorithm", "files": files}})
    assert check.widenings(BASE, head) == ["docstruct.fusion.judge: b.py adds *"]


def test_reclassifying_as_contract_widens() -> None:
    head = _head(**{"docstruct.fusion.judge": {"class": "contract"}})
    assert check.widenings(BASE, head) == ["docstruct.fusion.judge reclassified algorithm -> contract"]


def test_reclassifying_between_pinned_classes_does_not_widen() -> None:
    head = _head(**{"docstruct.fusion.judge": {**BASE["docstruct.fusion.judge"], "class": "policy"}})
    assert check.widenings(BASE, head) == []


def test_pinning_a_contract_module_does_not_widen() -> None:
    head = _head(**{"docstruct.manifest": {"class": "algorithm", "files": {"a.py": ["StructuredDocument"]}}})
    assert check.widenings(BASE, head) == []


def test_the_fixture_does_not_grow_against_head() -> None:
    """The script runs end to end: against HEAD itself, nothing grows."""
    result = subprocess.run(
        ["python", "scripts/check_docstruct_allowlist.py", "--base", "HEAD"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
