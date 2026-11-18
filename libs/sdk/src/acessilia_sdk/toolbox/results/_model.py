"""Runtime for the bounded, generated Toolbox result bindings.

Only the standard library is used. Rules are compiled and checked at development
time; this module neither loads schemas nor resolves references at runtime.
"""

from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass, field, fields
from typing import Any, ClassVar, Self


@dataclass(frozen=True)
class ResultModel:
    """A generated result; use ``from_dict`` to validate untrusted JSON.

    Optional fields read as None when absent. ``to_dict`` preserves absence,
    explicit nulls and extension fields. Direct construction is not validation;
    it serializes every declared field, like an ordinary dataclass.
    """

    _present: frozenset[str] | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _extensions: dict[str, Any] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )
    _rule: ClassVar[dict[str, Any]]
    _models: ClassVar[dict[str, type[ResultModel]]]

    @classmethod
    def from_dict(cls, data: Any) -> Self:
        return decode(data, cls._rule, cls._models, cls.__name__)

    def to_dict(self) -> dict[str, Any]:
        result = {name: to_json(value) for name, value in self._extensions.items()}
        result.update(
            {
                f.name: to_json(getattr(self, f.name))
                for f in fields(self)
                if not f.name.startswith("_")
                and (self._present is None or f.name in self._present)
            }
        )
        return result


def to_json(value: Any) -> Any:
    if isinstance(value, ResultModel):
        return value.to_dict()
    if isinstance(value, list):
        return [to_json(item) for item in value]
    if isinstance(value, dict):
        return {name: to_json(item) for name, item in value.items()}
    return copy.deepcopy(value)


def _equal(left: Any, right: Any) -> bool:
    # JSON booleans are not numbers, despite Python's True == 1.
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    return left == right


def decode(
    value: Any,
    rule: dict[str, Any],
    models: dict[str, type[ResultModel]],
    path: str,
    *,
    strict: bool = False,
) -> Any:
    def fail(message: str) -> None:
        raise ValueError(f"{path}: {message}")

    types = rule["type"]
    number = isinstance(value, (int, float)) and not isinstance(value, bool)
    if isinstance(value, float) and not math.isfinite(value):
        fail("expected a finite JSON number")
    valid = (
        ("null" in types and value is None)
        or ("string" in types and isinstance(value, str))
        or ("boolean" in types and isinstance(value, bool))
        or ("number" in types and number)
        or (
            "integer" in types
            and number
            and (isinstance(value, int) or value.is_integer())
        )
        or ("array" in types and isinstance(value, list))
        or (
            "object" in types
            and isinstance(value, dict)
            and all(isinstance(k, str) for k in value)
        )
    )
    if not valid:
        fail(f"expected {' or '.join(types)}")
    if "const" in rule and not _equal(value, rule["const"]):
        fail("unexpected constant")
    if "enum" in rule and not any(_equal(value, item) for item in rule["enum"]):
        fail("value outside enum")
    if number:
        for key, bad in [
            ("minimum", lambda x: value < x),
            ("maximum", lambda x: value > x),
            ("exclusiveMinimum", lambda x: value <= x),
            ("exclusiveMaximum", lambda x: value >= x),
        ]:
            if key in rule and bad(rule[key]):
                fail(f"violates {key}")
        if "integer" in types:
            value = int(value)
    if isinstance(value, str):
        for key, bad in [
            ("minLength", lambda n: len(value) < n),
            ("maxLength", lambda n: len(value) > n),
        ]:
            if key in rule and bad(rule[key]):
                fail(f"violates {key}")
        if "pattern" in rule and re.search(rule["pattern"], value) is None:
            fail("does not match pattern")
    if isinstance(value, list):
        for key, bad in [
            ("minItems", lambda n: len(value) < n),
            ("maxItems", lambda n: len(value) > n),
        ]:
            if key in rule and bad(rule[key]):
                fail(f"violates {key}")
        return [
            decode(item, rule["items"], models, f"{path}[{i}]", strict=strict)
            for i, item in enumerate(value)
        ]
    if isinstance(value, dict):
        missing = set(rule.get("required", [])) - value.keys()
        if missing:
            fail(f"missing required properties {sorted(missing)}")
        properties = rule.get("properties", {})
        result = {
            name: decode(
                item, properties[name], models, f"{path}.{name}", strict=strict
            )
            for name, item in value.items()
            if name in properties
        }
        extra_rule = rule.get("additionalProperties", True)
        if strict and extra_rule is False and value.keys() - properties.keys():
            fail("unknown properties")
        extra = {
            name: (
                decode(item, extra_rule, models, f"{path}.{name}", strict=strict)
                if isinstance(extra_rule, dict)
                else copy.deepcopy(item)
            )
            for name, item in value.items()
            if name not in properties
        }
        # Forward compatibility: additionalProperties:false documents the
        # producer contract; readers retain extensions without validating them.
        if "model" in rule:
            instance = models[rule["model"]](**result)
            object.__setattr__(instance, "_present", frozenset(result))
            object.__setattr__(instance, "_extensions", extra)
            return instance
        return {**result, **extra}
    return value
