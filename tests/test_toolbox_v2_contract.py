"""Replay an actual Toolbox adapter output through Core and real exporters.

The fixture was generated from provider-shaped synthetic Docling data, not
from live inference. It preserves the cross-project normalization contract.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from docx import Document

from backend.agents.pddl_orchestrator import _manifest_pages_to_payload
from backend.core.manifest.builder import build_processing_manifest
from backend.export.exporters.docx_exporter import export_docx
from backend.export.exporters.txt_exporter import export_txt
from backend.pipeline.canonical_builder import build_canonical_document
from backend.pipeline.table_ast import rows_from_table_ast
from backend.pipeline.validators import validate_canonical_document


def test_toolbox_contract_retains_order_tables_and_math_through_exports(tmp_path):
    response = json.loads(
        (Path(__file__).parent / "fixtures/toolbox-v2-contract.json").read_text()
    )
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF-test")
    now = datetime.now(timezone.utc)
    extraction = SimpleNamespace(
        document=response,
        version="synthetic-v2",
        started_at=now,
        completed_at=now,
        duration_ms=0,
        configuration={},
    )
    manifest = build_processing_manifest(source, extraction, language="en-US")
    assert [element.type for element in manifest.elements] == [
        "paragraph",
        "table",
        "picture",
        "paragraph",
        "formula",
    ]
    pages = _manifest_pages_to_payload(manifest)
    canonical = build_canonical_document(
        {"pages": pages, "text": "synthetic"}, language="en-US"
    )
    assert validate_canonical_document(canonical) == []
    blocks = [block for section in canonical["sections"] for block in section["blocks"]]
    table = next(block for block in blocks if block["type"] == "table")
    assert rows_from_table_ast(table["table_ast"]) == [
        ["Name", "Age", "City"],
        ["Ana", "", "Recife"],
    ]
    formula = next(block for block in blocks if block["type"] == "math")
    assert formula["text"] == "x=1"
    text_path = export_txt(canonical, tmp_path / "sample.txt")
    text = text_path.read_text()
    assert (
        text.index("Before table") < text.index("Recife") < text.index("After picture")
    )
    docx_path = export_docx(canonical, tmp_path / "sample.docx")
    document = Document(docx_path)
    assert [cell.text for cell in document.tables[0].rows[1].cells] == [
        "Ana",
        "",
        "Recife",
    ]
