"""The walk over obligation dependencies, shared by the manifest model and the
PDDL compiler (#783).

The model checks the whole graph when a manifest is built; the compiler checks
the selected closure again, because a replan changes the manifest in place.
Both use this walk, so they find the same cycle and the same unknown
dependency. Each caller words its own message.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence


class DependencyCycleError(ValueError):
    """A cycle in the dependencies, as a closed path: ``a -> b -> a``."""

    def __init__(self, cycle: Sequence[str]) -> None:
        self.cycle = tuple(cycle)
        super().__init__(" -> ".join(self.cycle))


class UnknownDependencyError(ValueError):
    """An obligation that depends on an id the graph does not have."""

    def __init__(self, obligation_id: str, dependency: str) -> None:
        self.obligation_id = obligation_id
        self.dependency = dependency
        super().__init__(f"{obligation_id} -> {dependency}")


def dependency_closure(
    dependencies: Mapping[str, Sequence[str]],
    roots: Iterable[str],
) -> list[str]:
    """The roots and their transitive dependencies, sorted.

    Raises ``DependencyCycleError`` for the first cycle reached (in sorted
    root order) and ``UnknownDependencyError`` naming the obligation whose
    dependency is missing, not the root that reached it.
    """
    closure: set[str] = set()
    path: list[str] = []

    def visit(obligation_id: str) -> None:
        if obligation_id in path:
            raise DependencyCycleError(path[path.index(obligation_id):] + [obligation_id])
        if obligation_id in closure:
            return
        path.append(obligation_id)
        for dependency in dependencies[obligation_id]:
            if dependency not in dependencies:
                raise UnknownDependencyError(obligation_id, dependency)
            visit(dependency)
        path.pop()
        closure.add(obligation_id)

    for root in sorted(roots):
        visit(root)
    return sorted(closure)
