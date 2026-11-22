"""Bounded compiler for the selected Toolbox operational result schemas.

This is a development tool, never an SDK runtime dependency. Unsupported
constraints and non-local, unresolved or recursive references fail explicitly.
"""

from __future__ import annotations

import keyword
import re
from typing import Any


class SchemaError(ValueError):
    """A selected schema cannot be compiled without dropping constraints."""


ANNOTATIONS = {
    "$schema",
    "$id",
    "title",
    "description",
    "$comment",
    "default",
    "examples",
}
COMMON = {"type", "enum", "const"}
KEYS = {
    "string": {"minLength", "maxLength", "pattern"},
    "integer": {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"},
    "number": {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"},
    "array": {"items", "minItems", "maxItems"},
    "object": {"properties", "required", "additionalProperties"},
    "boolean": set(),
    "null": set(),
}


def camel(name: str) -> str:
    return "".join(
        part[:1].upper() + part[1:] for part in re.split(r"[^a-zA-Z0-9]+", name) if part
    )


def without_models(value):
    if isinstance(value, dict):
        return {
            key: without_models(item)
            for key, item in value.items()
            if not (
                key == "model"
                and isinstance(value.get("type"), list)
                and isinstance(item, str)
            )
        }
    if isinstance(value, list):
        return [without_models(item) for item in value]
    return value


class Compiler:
    def __init__(
        self,
        *,
        emit_models: bool = True,
        nullable_branches: bool = False,
        plain_definitions: tuple[str, ...] = (),
    ):
        self.emit_models = emit_models
        self.nullable_branches = nullable_branches
        self.plain_definitions = plain_definitions
        self.reference_models: dict[str, str] = {}
        self.status_discriminator = False
        self.classes: dict[str, dict] = {}
        self.roots: dict[str, dict] = {}

    def compile(
        self,
        schema: dict,
        name: str,
        *,
        definition: str | None = None,
        reference_models: dict[str, str] | None = None,
        status_discriminator: bool = False,
    ) -> dict:
        self.reference_models = reference_models or {}
        self.status_discriminator = status_discriminator
        root = schema
        if definition is not None:
            schema = root["$defs"][definition]
        rule = self._node(schema, root, name, ())
        self.roots[name] = rule
        return rule

    def _node(
        self,
        node: Any,
        root: dict,
        name: str,
        stack: tuple[str, ...],
        plain: bool = False,
    ) -> dict:
        if not isinstance(node, dict):
            raise SchemaError(f"{name}: schema must be an object")
        if "$ref" in node:
            if set(node) - ANNOTATIONS - {"$ref"}:
                raise SchemaError(f"{name}: constraints alongside $ref are unsupported")
            ref = node["$ref"]
            if not isinstance(ref, str) or not re.fullmatch(
                r"#/(definitions|\$defs)/[^/]+", ref
            ):
                raise SchemaError(
                    f"{name}: only local definition references are supported"
                )
            if ref in stack:
                raise SchemaError(f"{name}: recursive reference {ref}")
            section, key = ref[2:].split("/")
            key = key.replace("~1", "/").replace("~0", "~")
            try:
                target = root[section][key]
            except KeyError as exc:
                raise SchemaError(f"{name}: unresolved reference {ref}") from exc
            if key in self.reference_models:
                alias = self.reference_models[key]
                if alias not in self.classes:
                    raise SchemaError(
                        f"{name}: reference model {alias} has not been selected"
                    )
                plain_compiler = Compiler(
                    emit_models=False, nullable_branches=self.nullable_branches
                )
                plain_compiler.status_discriminator = self.status_discriminator
                candidate = plain_compiler._node(target, root, name, (*stack, ref))
                if without_models(self.classes[alias]) != candidate:
                    raise SchemaError(
                        f"{name}: embedded {key} disagrees with selected {alias}"
                    )
                return self.classes[alias]
            return self._node(
                target, root, name, (*stack, ref), key in self.plain_definitions
            )
        status_required = None
        if "anyOf" in node and self.status_discriminator:
            branches = node["anyOf"]
            if node.get("type") != "object" or "status" not in node.get("required", []):
                raise SchemaError(
                    f"{name}: sync status must be a required object discriminator"
                )
            if not isinstance(branches, list) or len(branches) != 2:
                raise SchemaError(f"{name}: unsupported sync status branches")
            status_required = {}
            for branch in branches:
                if (
                    not isinstance(branch, dict)
                    or set(branch) != {"properties", "required"}
                    or set(branch["properties"]) != {"status"}
                    or set(branch["properties"]["status"]) != {"const"}
                    or not isinstance(branch["required"], list)
                    or any(
                        key not in node.get("properties", {})
                        for key in branch["required"]
                    )
                ):
                    raise SchemaError(f"{name}: unsupported sync status constraints")
                status = branch["properties"]["status"]["const"]
                if status not in ("mirrored", "skipped") or status in status_required:
                    raise SchemaError(f"{name}: unsupported sync status discriminator")
                status_required[status] = branch["required"]
            if set(status_required) != {"mirrored", "skipped"}:
                raise SchemaError(f"{name}: incomplete sync status discriminator")
            node = {key: value for key, value in node.items() if key != "anyOf"}
        if "anyOf" in node and self.nullable_branches:
            branches = node["anyOf"]
            if (
                set(node) - ANNOTATIONS - {"anyOf"}
                or not isinstance(branches, list)
                or len(branches) != 2
                or branches[1] != {"type": "null"}
            ):
                raise SchemaError(
                    f"{name}: only the manifest's nullable branches are supported"
                )
            rule = self._node(branches[0], root, name, stack, plain)
            if "null" in rule["type"]:
                raise SchemaError(f"{name}: duplicate nullable branch")
            return {**rule, "type": [*rule["type"], "null"]}
        if "type" not in node and "const" in node and isinstance(node["const"], str):
            node = {**node, "type": "string"}
        if self.nullable_branches and node.get("format") == "date-time":
            # Draft 2020-12's format is an annotation, like validator_for(schema)
            # without a FormatChecker; it is not a hidden runtime dependency.
            node = {key: value for key, value in node.items() if key != "format"}
        types = node.get("type")
        types = [types] if isinstance(types, str) else types
        if (
            not isinstance(types, list)
            or not types
            or any(t not in KEYS for t in types)
        ):
            raise SchemaError(f"{name}: unsupported type {types!r}")
        if len(set(types) - {"null"}) != 1:
            raise SchemaError(f"{name}: only nullable type unions are supported")
        allowed = ANNOTATIONS | COMMON | {"definitions", "$defs"}
        for kind in types:
            allowed |= KEYS[kind]
        unknown = set(node) - allowed
        if unknown:
            raise SchemaError(f"{name}: unsupported constraints {sorted(unknown)}")
        rule = {
            key: value
            for key, value in node.items()
            if key not in ANNOTATIONS | {"definitions", "$defs"}
        }
        rule["type"] = types
        if status_required is not None:
            rule["status_required"] = status_required
        if "pattern" in node:
            try:
                re.compile(node["pattern"])
            except re.error as exc:
                raise SchemaError(f"{name}: invalid pattern") from exc
        if "object" in types:
            props = node.get("properties", {})
            required = node.get("required", [])
            if props and set(required) - props.keys():
                raise SchemaError(f"{name}: undeclared required properties")
            rule["properties"] = {
                key: self._node(value, root, name + camel(key), stack)
                for key, value in props.items()
            }
            additional = node.get("additionalProperties", True)
            if isinstance(additional, dict):
                rule["additionalProperties"] = self._node(
                    additional, root, name + "Value", stack
                )
            elif not isinstance(additional, bool):
                raise SchemaError(f"{name}: invalid additionalProperties")
            if props and self.emit_models and not plain:
                for key in props:
                    if (
                        not key.isidentifier()
                        or keyword.iskeyword(key)
                        or key.startswith("_")
                        or key in ("to_dict", "from_dict")
                    ):
                        raise SchemaError(f"{name}: unsupported field name {key!r}")
                if name in self.classes and self.classes[name] != rule:
                    raise SchemaError(f"{name}: conflicting class name")
                rule["model"] = name
                self.classes[name] = rule
        if "array" in types:
            if "items" not in node:
                raise SchemaError(f"{name}: array requires typed items")
            rule["items"] = self._node(node["items"], root, name + "Item", stack)
        return rule

    def annotation(self, rule: dict) -> str:
        types = rule["type"]
        if "model" in rule:
            result = rule["model"]
        elif "array" in types:
            result = f"list[{self.annotation(rule['items'])}]"
        elif "object" in types:
            extra = rule.get("additionalProperties")
            result = f"dict[str, {self.annotation(extra) if isinstance(extra, dict) else 'Any'}]"
        else:
            result = {
                "string": "str",
                "integer": "int",
                "number": "float",
                "boolean": "bool",
                "null": "None",
            }[next(t for t in types if t != "null")]
        return result + (" | None" if "null" in types else "")

    def render(self, source: str) -> str:
        lines = [
            f'"""Generated from {source}; do not edit by hand."""',
            "from __future__ import annotations",
            "",
            "from dataclasses import dataclass",
            "from typing import Any",
            "",
            "from acessilia_sdk.toolbox.results._model import ResultModel",
            "",
            "",
        ]
        for name, rule in self.classes.items():
            lines += ["@dataclass(frozen=True)", f"class {name}(ResultModel):"]
            required = rule.get("required", [])
            props = rule["properties"]
            for key in [k for k in props if k in required] + [
                k for k in props if k not in required
            ]:
                annotation = self.annotation(props[key])
                if key not in required:
                    if "None" not in annotation.split(" | "):
                        annotation += " | None"
                    annotation += " = None"
                lines.append(f"    {key}: {annotation}")
            lines += ["", ""]
        lines += [
            "_MODELS = {"
            + ", ".join(f"{name!r}: {name}" for name in self.classes)
            + "}",
            "",
        ]
        for name, rule in self.classes.items():
            lines += [f"{name}._rule = {rule!r}", f"{name}._models = _MODELS"]
        for name, rule in self.roots.items():
            if "model" not in rule:
                lines += [
                    f"_{name.upper()}_RULE = {rule!r}",
                    "",
                    f"def {name}(data: Any) -> {self.annotation(rule)}:",
                    "    from acessilia_sdk.toolbox.results._model import decode",
                    f"    return decode(data, _{name.upper()}_RULE, _MODELS, {name!r})",
                    "",
                ]
        lines += ["", "__all__ = " + repr(list(self.roots)), ""]
        return "\n".join(lines)
