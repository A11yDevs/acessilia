"""Operations: fixed sequences of Toolbox capabilities and docstruct algorithms.

An operation runs its steps in a fixed order with explicit parameters, and
reports what each step did (ADR-0017). It decides nothing a caller could want
differently: which inputs to read, what to do with a result, when to retry or
fall back stay with the caller. Each operation is a module of this package.
"""

__all__: list[str] = []
