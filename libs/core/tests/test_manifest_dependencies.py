"""The dependency walk shared by the manifest model and the compiler (#783)."""
from __future__ import annotations

import pytest

from acessilia_core.manifest.dependencies import (
    DependencyCycleError,
    UnknownDependencyError,
    dependency_closure,
)


def test_the_closure_is_the_roots_and_their_predecessors():
    graph = {"a": [], "b": ["a"], "c": ["b"], "d": []}
    assert dependency_closure(graph, ["c"]) == ["a", "b", "c"]


def test_a_cycle_is_reported_as_a_closed_path():
    with pytest.raises(DependencyCycleError) as error:
        dependency_closure({"r": ["a"], "a": ["b"], "b": ["a"]}, ["r"])
    assert error.value.cycle == ("a", "b", "a")


def test_an_unknown_dependency_names_its_parent():
    with pytest.raises(UnknownDependencyError) as error:
        dependency_closure({"r": ["a"], "a": ["nope"]}, ["r"])
    assert (error.value.obligation_id, error.value.dependency) == ("a", "nope")


def test_the_model_reports_the_same_cycle_as_the_compiler():
    from acessilia_core.manifest.models import _validate_obligation_dag

    class _Item:
        def __init__(self, obligation_id, dependencies):
            self.id, self.dependencies = obligation_id, dependencies

    with pytest.raises(ValueError, match="a -> b -> a"):
        _validate_obligation_dag([_Item("a", ["b"]), _Item("b", ["a"])])
