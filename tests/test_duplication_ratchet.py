"""The #656 duplication ratchet keeps the accepted remainder from growing."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_duplication_ratchet.py"


def _module():
    spec = importlib.util.spec_from_file_location("check_duplication_ratchet", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _function(path: str, qualname: str) -> dict[str, str]:
    return {"path": path, "qualname": qualname}


def _group(*functions: dict[str, str]) -> dict[str, object]:
    return {"functions": list(functions)}


def _payload(groups: list[dict[str, object]], **totals: int) -> dict[str, object]:
    return {
        "groups": groups,
        "totals": {
            "groups": totals.get("groups", len(groups)),
            "functions_in_groups": totals.get(
                "functions_in_groups", sum(len(group["functions"]) for group in groups)
            ),
            "lines_in_groups": totals.get("lines_in_groups", 6 * len(groups)),
        },
    }


def test_the_accepted_remainder_passes() -> None:
    module = _module()
    allowed = {
        "groups": [["a.py:f", "b.py:g"]],
        "totals": {"groups": 1, "functions_in_groups": 2, "lines_in_groups": 6},
    }
    current = _payload([_group(_function("a.py", "f"), _function("b.py", "g"))])

    assert module.violations(allowed, current) == []


def test_a_new_group_is_refused_even_when_totals_do_not_grow() -> None:
    module = _module()
    allowed = {
        "groups": [["a.py:f", "b.py:g"]],
        "totals": {"groups": 1, "functions_in_groups": 2, "lines_in_groups": 6},
    }
    current = _payload([_group(_function("c.py", "h"), _function("d.py", "i"))])

    assert module.violations(allowed, current) == [
        "new duplicate group: c.py:h, d.py:i"
    ]


def test_total_growth_is_refused() -> None:
    module = _module()
    allowed = {
        "groups": [["a.py:f", "b.py:g"]],
        "totals": {"groups": 1, "functions_in_groups": 2, "lines_in_groups": 6},
    }
    current = _payload(
        [_group(_function("a.py", "f"), _function("b.py", "g"))],
        lines_in_groups=7,
    )

    assert module.violations(allowed, current) == ["lines_in_groups grew: 7 > 6"]


def test_an_improvement_is_allowed() -> None:
    module = _module()
    allowed = {
        "groups": [["a.py:f", "b.py:g"]],
        "totals": {"groups": 1, "functions_in_groups": 2, "lines_in_groups": 6},
    }

    assert module.violations(allowed, _payload([])) == []
