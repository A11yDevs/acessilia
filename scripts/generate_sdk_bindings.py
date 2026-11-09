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

Usage:
    python scripts/generate_sdk_bindings.py           # rewrite the block
    python scripts/generate_sdk_bindings.py --check   # exit 1 if it is stale
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "libs" / "sdk" / "src" / "acessilia_sdk" / "toolbox" / "capabilities.py"
CONTRACT_PATH = REPO_ROOT / "tests" / "fixtures" / "toolbox-contract.json"

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if the block is stale")
    parser.add_argument("--contract", type=Path, default=CONTRACT_PATH)
    args = parser.parse_args(argv)

    source = REGISTRY_PATH.read_text(encoding="utf-8")
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    try:
        generated = regenerate(source, contract)
    except BindingError as exc:
        print(f"cannot generate the SDK bindings: {exc}", file=sys.stderr)
        return 1

    if args.check:
        if generated != source:
            print(
                f"{REGISTRY_PATH.relative_to(REPO_ROOT)} is stale: "
                "run python scripts/generate_sdk_bindings.py",
                file=sys.stderr,
            )
            return 1
        print("SDK bindings are up to date")
        return 0
    REGISTRY_PATH.write_text(generated, encoding="utf-8")
    print(f"wrote {REGISTRY_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
