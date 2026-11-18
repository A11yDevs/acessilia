from __future__ import annotations

import pytest

from scripts import manifest, pddl_pipeline


def test_manifest_cli_help_exits_zero() -> None:
    with pytest.raises(SystemExit) as excinfo:
        manifest.main(["--help"])
    assert excinfo.value.code == 0


def test_pddl_pipeline_cli_help_exits_zero(capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        pddl_pipeline.main(["--help"])
    assert excinfo.value.code == 0
    # The program's name after the PMV rename (review of #584).
    assert capsys.readouterr().out.startswith("usage: a11y-pddl-pipeline ")
