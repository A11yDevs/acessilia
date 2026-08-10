from __future__ import annotations

import pytest

from scripts import manifest, pmv


def test_manifest_cli_help_exits_zero() -> None:
    with pytest.raises(SystemExit) as excinfo:
        manifest.main(["--help"])
    assert excinfo.value.code == 0


def test_pmv_cli_help_exits_zero() -> None:
    with pytest.raises(SystemExit) as excinfo:
        pmv.main(["--help"])
    assert excinfo.value.code == 0
