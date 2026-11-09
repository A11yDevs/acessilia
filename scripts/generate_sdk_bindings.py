"""Generate the SDK registry's contract data from the Toolbox's published contract.

ADR-0004 makes the SDK own its client-side bindings, "derived from the
Toolbox's published contracts, preferably generated, never edited by hand once
generation exists" (#213). The registry
(``libs/sdk/src/acessilia_sdk/toolbox/capabilities.py``) has two parts:

- the SDK's own choices, written by hand in ``_selected(...)`` calls: which
  capability ids clients may call, at which exact contract version, through
  which transport, with which provider key and error label;
- the contract data of each selected version, generated here into the block
  between ``# BEGIN GENERATED BINDINGS`` and ``# END GENERATED BINDINGS``:
  its output schema and whether it is idempotent.

The input is ``tests/fixtures/toolbox-contract.json``, a copy of the contract
the Toolbox publishes (``contract/toolbox-contract.json``), refreshed only by
``scripts/capture_toolbox_contract.py --ref <ref>``. This script never reads
the Toolbox's manifests or imports its package (ADR-0002, P3), and it is a
development tool: nothing in the SDK imports it.

Rules for the generated data:

- a selected ``(id, version)`` that the contract does not publish is an error;
- ``idempotent`` must be a boolean in the contract, or it is an error;
- ``output_schema`` is the contract's ``output.schema`` without its
  ``artifact/`` prefix for ``:execute`` capabilities, and ``None`` for REST
  ones, as the hand-written registry had it. Typed result models for REST
  outputs are a later step of #213.

It also writes the SDK's result models from published schemas
(``MODELS``): one module per schema, a frozen dataclass with standard-library
code only, read from ``tests/fixtures/toolbox-schemas/`` (captured from the same
ref as the contract by ``scripts/capture_toolbox_contract.py``). A model's
``from_dict`` validates required properties, types, patterns, ``minLength``
and ``minimum``, and ignores unknown properties, so a later schema version that
only adds fields keeps being read (#185). Schema constructs it does not handle
are refused rather than half-generated.

Usage:
    python scripts/generate_sdk_bindings.py           # rewrite the block and models
    python scripts/generate_sdk_bindings.py --check   # exit 1 if one is stale
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "libs" / "sdk" / "src" / "acessilia_sdk" / "toolbox" / "capabilities.py"
CONTRACT_PATH = REPO_ROOT / "tests" / "fixtures" / "toolbox-contract.json"
SCHEMAS_DIR = REPO_ROOT / "tests" / "fixtures" / "toolbox-schemas"
SDK_TOOLBOX = REPO_ROOT / "libs" / "sdk" / "src" / "acessilia_sdk" / "toolbox"

#: Published schema file -> (class name, generated module).
MODELS: dict[str, tuple[str, Path]] = {
    "reference@1.json": ("ArtifactReference", SDK_TOOLBOX / "reference.py"),
}

_JSON_TYPES = {
    "string": ("str", "isinstance(value, str)"),
    "integer": ("int", "isinstance(value, int) and not isinstance(value, bool)"),
    "number": ("float", "isinstance(value, (int, float)) and not isinstance(value, bool)"),
    "boolean": ("bool", "isinstance(value, bool)"),
    "null": ("None", "value is None"),
}
_KEYWORDS = {"description", "type", "pattern", "minLength", "minimum"}
#: Keywords allowed at a schema's root. Anything else, such as allOf, oneOf,
#: not or if/then/else, is a constraint the generated reader would not
#: enforce, so it is refused instead of silently dropped. additionalProperties
#: is allowed: the reader ignores unknown properties on purpose (#185).
_ROOT_KEYWORDS = {
    "$schema", "$id", "title", "description", "type", "properties", "required",
    "additionalProperties",
}

BEGIN = "# BEGIN GENERATED BINDINGS\n"
END = "# END GENERATED BINDINGS\n"


class BindingError(ValueError):
    """The selection and the contract cannot produce the registry's data."""


def selection(source: str) -> list[tuple[str, int, str]]:
    """``(id, version, transport)`` of every ``_selected(...)`` call, in order.

    Read from the source with ``ast``, not by importing it: the module builds
    its capabilities from the very block this script writes.
    """
    selected: list[tuple[str, int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_selected"
        ):
            continue
        try:
            capability_id = ast.literal_eval(node.args[0])
            version = ast.literal_eval(node.args[1])
            keywords = {k.arg: ast.literal_eval(k.value) for k in node.keywords}
        except (IndexError, ValueError) as exc:
            raise BindingError(
                f"line {node.lineno}: _selected() arguments must be literals"
            ) from exc
        selected.append((capability_id, version, keywords.get("transport", "execute")))
    if not selected:
        raise BindingError("no _selected(...) call found in the registry")
    return selected


def bindings(
    selected: list[tuple[str, int, str]], contract: dict
) -> dict[tuple[str, int], tuple[str | None, bool]]:
    """The generated data for each selected capability version."""
    published = {
        (entry["id"], entry.get("version", 1)): entry
        for entry in contract.get("capabilities") or []
        if isinstance(entry, dict) and entry.get("id")
    }
    result: dict[tuple[str, int], tuple[str | None, bool]] = {}
    for capability_id, version, transport in selected:
        entry = published.get((capability_id, version))
        if entry is None:
            raise BindingError(
                f"{capability_id}@{version} is selected, but the contract does not publish it"
            )
        idempotent = (entry.get("execution") or {}).get("idempotent")
        if not isinstance(idempotent, bool):
            raise BindingError(
                f"the contract publishes execution.idempotent={idempotent!r} for "
                f"{capability_id}@{version}, which is not a boolean"
            )
        output_schema: str | None = None
        if transport == "execute":
            schema = (entry.get("output") or {}).get("schema")
            if not isinstance(schema, str) or not schema:
                raise BindingError(
                    f"the contract publishes no output.schema for {capability_id}@{version}"
                )
            output_schema = schema.removeprefix("artifact/")
        result[(capability_id, version)] = (output_schema, idempotent)
    return result


def render_block(data: dict[tuple[str, int], tuple[str | None, bool]]) -> str:
    lines = ["_BINDINGS: dict[tuple[str, int], tuple[str | None, bool]] = {\n"]
    for (capability_id, version), (output_schema, idempotent) in sorted(data.items()):
        lines.append(
            f"    ({capability_id!r}, {version}): ({output_schema!r}, {idempotent!r}),\n"
        )
    lines.append("}\n")
    return "".join(lines)


def regenerate(source: str, contract: dict) -> str:
    """``source`` with its generated block rewritten from ``contract``."""
    if source.count(BEGIN) != 1 or source.count(END) != 1:
        raise BindingError("the registry needs exactly one generated block")
    head, rest = source.split(BEGIN)
    _, tail = rest.split(END)
    block = render_block(bindings(selection(source), contract))
    return head + BEGIN + block + END + tail


def _escape_braces(text: str) -> str:
    """``text`` as a literal inside a generated f-string."""
    return text.replace("{", "{{").replace("}", "}}")


def _field(name: str, spec: dict, required: bool) -> tuple[str, str]:
    """The dataclass field line and the validation function for one property."""
    unknown = sorted(set(spec) - _KEYWORDS)
    if unknown:
        raise BindingError(f"property {name!r} uses unsupported keywords {unknown}")
    types = spec.get("type")
    types = [types] if isinstance(types, str) else list(types or [])
    if not types or any(kind not in _JSON_TYPES for kind in types):
        raise BindingError(f"property {name!r} has an unsupported type {spec.get('type')!r}")
    annotation = " | ".join(_JSON_TYPES[kind][0] for kind in types)
    if not required and "null" not in types:
        annotation += " | None"
    checks = " or ".join(
        f"({_JSON_TYPES[kind][1]})" if len(types) > 1 else _JSON_TYPES[kind][1]
        for kind in types
    )
    lines = [f"def _check_{name}(value: Any) -> {annotation}:"]
    if "integer" in types:
        # Draft-07 (6.1.1): a number with a zero fractional part is an integer,
        # whatever its notation (10.0, 1e3). Normalize it; booleans stay out.
        lines += [
            "    if isinstance(value, float) and value.is_integer():",
            "        value = int(value)",
        ]
    lines += [
        f"    if not ({checks}):",
        f'        raise ValueError(f"{name}: expected {" or ".join(types)}, got {{value!r}}")',
    ]
    if "pattern" in spec:
        lines += [
            f"    if isinstance(value, str) and re.fullmatch({spec['pattern']!r}, value) is None:",
            f'        raise ValueError(f"{name}: {{value!r}} does not match {_escape_braces(spec["pattern"])}")',
        ]
    if "minLength" in spec:
        lines += [
            f"    if isinstance(value, str) and len(value) < {spec['minLength']}:",
            f'        raise ValueError(f"{name}: shorter than {spec["minLength"]}")',
        ]
    if "minimum" in spec:
        lines += [
            "    if isinstance(value, (int, float)) and not isinstance(value, bool)"
            f" and value < {spec['minimum']}:",
            f'        raise ValueError(f"{name}: below {spec["minimum"]}")',
        ]
    lines.append("    return value")
    default = "" if required else " = None"
    return f"    {name}: {annotation}{default}", "\n".join(lines)


def render_model(schema: dict, class_name: str, schema_file: str) -> str:
    """A standard-library module with a frozen dataclass for a flat object schema."""
    if schema.get("type") != "object" or not isinstance(schema.get("properties"), dict):
        raise BindingError(f"{schema_file}: only flat object schemas are supported")
    unsupported = sorted(set(schema) - _ROOT_KEYWORDS)
    if unsupported:
        raise BindingError(f"{schema_file}: unsupported root keywords {unsupported}")
    properties: dict[str, dict] = schema["properties"]
    required = list(schema.get("required") or [])
    missing = sorted(set(required) - set(properties))
    if missing:
        raise BindingError(f"{schema_file}: required properties not declared: {missing}")
    # Required fields first: a dataclass field without default cannot follow one with.
    ordered = [n for n in properties if n in required] + [
        n for n in properties if n not in required
    ]
    fields, checks = [], []
    for name in ordered:
        if not name.isidentifier():
            raise BindingError(f"{schema_file}: property {name!r} is not an identifier")
        line, check = _field(name, properties[name], name in required)
        fields.append(line)
        checks.append(check)
    description = textwrap.fill(schema.get("description", "").strip(), width=79)
    reads = "\n".join(
        f"            {name!r}: _check_{name}(data[{name!r}])," for name in required
    )
    optional = "\n".join(
        f"        if {name!r} in data:\n"
        f"            values[{name!r}] = _check_{name}(data[{name!r}])"
        for name in ordered
        if name not in required
    )
    missing_check = (
        "        missing = [name for name in REQUIRED if name not in data]\n"
        "        if missing:\n"
        f'            raise ValueError(f"{class_name}: missing required properties {{missing}}")\n'
    )
    body = [
        f'"""{schema.get("title", class_name)} ({schema["$id"]}).',
        "",
        "Generated by scripts/generate_sdk_bindings.py from the Toolbox's published",
        f"schema (tests/fixtures/toolbox-schemas/{schema_file}); do not edit by hand.",
        "",
        description,
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "import re",
        "from dataclasses import asdict, dataclass",
        "from typing import Any",
        "",
        f"SCHEMA_ID = {schema['$id']!r}",
        f"REQUIRED: tuple[str, ...] = {tuple(required)!r}",
        "",
        "",
        "\n\n\n".join(checks),
        "",
        "",
        "@dataclass(frozen=True)",
        f"class {class_name}:",
        f'    """{schema.get("title", class_name)}; build it with :meth:`from_dict`."""',
        "",
        *fields,
        "",
        "    @classmethod",
        f"    def from_dict(cls, data: Any) -> {class_name}:",
        '        """Validate ``data`` against the schema and build the model.',
        "",
        "        Unknown properties are ignored: a later schema version only adds",
        "        fields. A missing required property, a wrong type or a value the",
        "        schema refuses raises ``ValueError``.",
        '        """',
        "        if not isinstance(data, dict):",
        f'            raise ValueError(f"{class_name}: expected an object, got {{data!r}}")',
        missing_check.rstrip("\n"),
        "        values: dict[str, Any] = {",
        reads,
        "        }",
        *([optional] if optional else []),
        "        return cls(**values)",
        "",
        "    def to_dict(self) -> dict[str, Any]:",
        '        """The JSON object, with every field."""',
        "        return asdict(self)",
        "",
        "",
        f'__all__ = ["REQUIRED", "SCHEMA_ID", "{class_name}"]',
        "",
    ]
    return "\n".join(body)


def models() -> dict[Path, str]:
    """Every generated model module and its content."""
    generated: dict[Path, str] = {}
    for schema_file, (class_name, target) in MODELS.items():
        schema = json.loads((SCHEMAS_DIR / schema_file).read_text(encoding="utf-8"))
        generated[target] = render_model(schema, class_name, schema_file)
    return generated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if the block is stale")
    parser.add_argument("--contract", type=Path, default=CONTRACT_PATH)
    args = parser.parse_args(argv)

    source = REGISTRY_PATH.read_text(encoding="utf-8")
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    try:
        outputs = {REGISTRY_PATH: regenerate(source, contract), **models()}
    except BindingError as exc:
        print(f"cannot generate the SDK bindings: {exc}", file=sys.stderr)
        return 1

    if args.check:
        stale = [
            path
            for path, text in outputs.items()
            if not path.is_file() or path.read_text(encoding="utf-8") != text
        ]
        for path in stale:
            print(
                f"{path.relative_to(REPO_ROOT)} is stale: "
                "run python scripts/generate_sdk_bindings.py",
                file=sys.stderr,
            )
        if stale:
            return 1
        print("SDK bindings are up to date")
        return 0
    for path, text in outputs.items():
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
