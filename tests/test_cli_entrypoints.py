from __future__ import annotations

import pytest

from scripts import manifest, pddl_pipeline


def test_manifest_cli_help_exits_zero() -> None:
    with pytest.raises(SystemExit) as excinfo:
        manifest.main(["--help"])
    assert excinfo.value.code == 0


def test_pddl_pipeline_cli_help_exits_zero() -> None:
    with pytest.raises(SystemExit) as excinfo:
        pddl_pipeline.main(["--help"])
    assert excinfo.value.code == 0
