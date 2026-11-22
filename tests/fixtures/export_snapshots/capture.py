"""Review-only capture of the pure export APIs; never rewrite golden files in tests.

Use --output-dir with a new directory, importing docstruct from the recorded
baseline checkout. Compare that directory with expected/ before accepting any
snapshot change. The test suite imports this harness but never calls main().
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterator

from docstruct.export.html import HtmlLabels, document_to_html
from docstruct.export.markdown import document_to_markdown
from docstruct.export.pandoc_ast import build_pandoc_ast
from docstruct.export.txt import document_to_txt_lines

ROOT = Path(__file__).resolve().parent


def plan() -> dict[str, Any]:
    return json.loads((ROOT / "manifest.json").read_text("utf-8"))


def variants() -> Iterator[tuple[str, dict[str, Any]]]:
    for case, exports in plan()["cases"].items():
        for export in exports:
            yield case, export


def render(document: dict[str, Any], export: dict[str, Any]) -> Any:
    kind = export["kind"]
    if kind == "txt":
        return document_to_txt_lines(
            document, profile=export["profile"], formula_label="Equation: {text}",
        )
    if kind == "html":
        return document_to_html(document, profile=export["profile"], labels=HtmlLabels(
            default_title="Untitled document", table_of_contents="Contents",
            image_description="Image description", extra={"table_region": "Table {number}"},
        ))
    if kind == "markdown":
        return document_to_markdown(document)
    if kind == "pandoc":
        return build_pandoc_ast(document, target_format=export["target"])
    raise ValueError(f"unknown snapshot export: {kind}")


def filename(case: str, export: dict[str, Any]) -> Path:
    return Path(case) / export["snapshot"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output.is_relative_to(ROOT) or output.exists():
        parser.error("output must be a new directory outside the committed fixtures")
    outputs: dict[Path, bytes] = {}
    for case, export in variants():
        document = json.loads((ROOT / "inputs" / f"{case}.json").read_text("utf-8"))
        before = deepcopy(document)
        value = render(document, export)
        if document != before or json.dumps(document) != json.dumps(before):
            raise ValueError(f"{case}/{export['snapshot']}: renderer mutated its input")
        path = filename(case, export)
        if path in outputs:
            raise ValueError(f"duplicate snapshot path: {path}")
        if export["kind"] == "pandoc":
            content = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
        elif export["kind"] == "txt":
            content = "\n".join(value)
            outputs[path.with_suffix(".lines.json")] = (
                json.dumps(value, ensure_ascii=False, indent=2) + "\n"
            ).encode("utf-8")
        else:
            content = value
        outputs[path] = content.encode("utf-8")
    output.mkdir(parents=True)
    for path, content in outputs.items():
        destination = output / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    print(f"Captured {len(outputs)} files in {output}")


if __name__ == "__main__":
    main()
