"""The #656 duplication ratchet keeps the accepted remainder from growing."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

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


def _payload(
    groups: list[dict[str, object]],
    *,
    groups_total: int | None = None,
    functions_total: int | None = None,
) -> dict[str, object]:
    return {
        "groups": groups,
        "totals": {
            "groups": len(groups) if groups_total is None else groups_total,
            "functions_in_groups": (
                sum(len(group["functions"]) for group in groups)
                if functions_total is None
                else functions_total
            ),
        },
    }


def _allowed() -> dict[str, object]:
    return {
        "groups": [["a.py:f", "b.py:g"]],
        "totals": {"groups": 1, "functions_in_groups": 2},
    }


def _write_allowlist(path: Path, data: object) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def test_the_accepted_remainder_passes() -> None:
    module = _module()
    current = _payload([_group(_function("a.py", "f"), _function("b.py", "g"))])

    assert module.violations(_allowed(), current) == []


def test_a_new_group_is_refused_even_when_totals_do_not_grow() -> None:
    module = _module()
    current = _payload([_group(_function("c.py", "h"), _function("d.py", "i"))])

    assert module.violations(_allowed(), current) == [
        "new duplicate group: c.py:h, d.py:i",
        "stale allowlist group: a.py:f, b.py:g",
    ]


def test_an_allowed_group_that_disappears_is_stale() -> None:
    module = _module()

    assert module.violations(_allowed(), _payload([])) == [
        "stale allowlist group: a.py:f, b.py:g"
    ]


def test_a_group_that_grows_is_refused() -> None:
    module = _module()
    current = _payload(
        [
            _group(
                _function("a.py", "f"),
                _function("b.py", "g"),
                _function("c.py", "h"),
            )
        ]
    )

    assert module.violations(_allowed(), current) == [
        "new duplicate group: a.py:f, b.py:g, c.py:h",
        "stale allowlist group: a.py:f, b.py:g",
        "functions_in_groups grew: 3 > 2",
    ]


def test_total_growth_is_refused() -> None:
    module = _module()
    current = _payload(
        [_group(_function("a.py", "f"), _function("b.py", "g"))],
        functions_total=3,
    )

    assert module.violations(_allowed(), current) == [
        "functions_in_groups grew: 3 > 2"
    ]


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"groups": []},
        {"groups": [["a.py:f"]], "totals": {"groups": 1, "functions_in_groups": 1}},
        {"groups": [["a.py:f", "b.py:g"]], "totals": {"groups": 1}},
        {
            "groups": [["a.py:f", "b.py:g"]],
            "totals": {"groups": 2, "functions_in_groups": 2},
        },
        {
            "groups": [["a.py:f", "b.py:g"]],
            "totals": {"groups": 1, "functions_in_groups": 3},
        },
        {
            "groups": [["a.py:f", "b.py:g"]],
            "totals": {"groups": True, "functions_in_groups": 2},
        },
    ],
)
def test_a_malformed_allowlist_is_refused(tmp_path, data) -> None:
    module = _module()
    path = tmp_path / "allowlist.json"
    _write_allowlist(path, data)

    with pytest.raises(ValueError, match=r"allowlist|groups|totals"):
        module.load_allowlist(path)


def test_main_reports_the_failure_path(monkeypatch, tmp_path, capsys) -> None:
    module = _module()
    path = tmp_path / "allowlist.json"
    _write_allowlist(path, _allowed())
    monkeypatch.setattr(module, "ALLOWLIST", path)
    monkeypatch.setattr(
        module.quality,
        "collect",
        lambda _rev: {
            "duplication": _payload(
                [_group(_function("c.py", "h"), _function("d.py", "i"))]
            )
        },
    )

    assert module.main([]) == 1
    output = capsys.readouterr().out
    assert "::error::duplication ratchet: new duplicate group" in output
    assert "stale allowlist group" in output


def test_main_passes_the_accepted_remainder(monkeypatch, tmp_path, capsys) -> None:
    module = _module()
    path = tmp_path / "allowlist.json"
    _write_allowlist(path, _allowed())
    monkeypatch.setattr(module, "ALLOWLIST", path)
    monkeypatch.setattr(
        module.quality,
        "collect",
        lambda _rev: {
            "duplication": _payload(
                [_group(_function("a.py", "f"), _function("b.py", "g"))]
            )
        },
    )

    assert module.main([]) == 0
    assert "Duplication ratchet passed" in capsys.readouterr().out


def test_main_reports_a_malformed_allowlist(monkeypatch, tmp_path, capsys) -> None:
    module = _module()
    path = tmp_path / "allowlist.json"
    _write_allowlist(path, {})
    monkeypatch.setattr(module, "ALLOWLIST", path)

    assert module.main([]) == 2
    assert "::error::duplication ratchet" in capsys.readouterr().out
