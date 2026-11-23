"""The pipeline compatibility modules share one deprecated-attribute shim."""

from __future__ import annotations

import pytest

from acessilia_core.pipeline import table_ast, validators


@pytest.mark.parametrize("module", [table_ast, validators])
def test_unknown_attributes_are_attribute_errors(module) -> None:
    with pytest.raises(AttributeError, match="has no attribute 'missing'"):
        getattr(module, "missing")
