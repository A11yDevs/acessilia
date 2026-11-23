"""The pipeline compatibility modules share one deprecated-attribute shim."""

from __future__ import annotations

import inspect
import warnings

import pytest

from acessilia_core.pipeline import table_ast, validators


@pytest.mark.parametrize("module", [table_ast, validators])
def test_unknown_attributes_are_attribute_errors(module) -> None:
    with pytest.raises(AttributeError, match="has no attribute 'missing'"):
        getattr(module, "missing")


@pytest.mark.parametrize(
    ("module", "name"),
    [(table_ast, "rows_from_table_ast"), (validators, "MSG_DUPLICATE_ID")],
)
def test_deprecation_warning_points_to_the_caller(module, name) -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        line = inspect.currentframe().f_lineno + 1
        getattr(module, name)

    assert len(caught) == 1
    assert caught[0].filename == __file__
    assert caught[0].lineno == line
