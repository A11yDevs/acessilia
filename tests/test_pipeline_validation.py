"""
What this suite verifies: backend/pipeline/validators structural checks (document shape, block
id/heading rules, table and table_ast payloads, export-profile verbosity, final-text scan rules)
report localized findings, and the verbosity-manager helpers pick the expected block filters and
verbosity defaults. Locale is pinned to en_US for deterministic canonical-English assertions.
"""

from __future__ import annotations

import pytest

import backend.i18n as i8n
from backend.pipeline.validators import validate_canonical_document
from backend.pipeline.validators import validate_export_profile
from backend.pipeline.validators import validate_output_text
from backend.pipeline.verbosity_manager import filter_blocks_for_profile
from backend.pipeline.verbosity_manager import normalize_profile
from backend.pipeline.verbosity_manager import verbosity_for_mode


@pytest.fixture(autouse=True)
def _pin_en_us(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the en_US runtime locale for every test in this module.

    The validators resolve every finding through backend.i18n.t, so assertions on the
    localized text need a deterministic locale; en_US returns the canonical English msgids.
    """
    monkeypatch.setenv("LOCALE", "en_US")
    i8n._catalog_for.cache_clear()


def _sample_document() -> dict:
    """Build a minimal two-paragraf canonical document used as the base fixture for most tests.

    Returns:
        dict: Canonical-document mapping with one section holding a basic and a technical paragraph block.
    """
    return {
        "schema_version": "1.0.0",
        "id": "doc-1",
        "title": "Documento",
        "language": "pt-BR",
        "sections": [
            {
                "id": "sec-1",
                "title": "Titulo",
                "level": 1,
                "blocks": [
                    {
                        "id": "blk-1",
                        "type": "paragraph",
                        "text": "Texto simples.",
                        "verbosity": "basic",
                    },
                    {
                        "id": "blk-2",
                        "type": "paragraph",
                        "text": "Texto tecnico.",
                        "verbosity": "technical",
                    },
                ],
                "children": [],
            }
        ],
    }


def test_validate_canonical_document_detects_duplicate_ids_and_heading_skip():
    """A repeated block id must be reported as a duplicate, and H1 -> H3 heading jumps as a level skip."""
    document = _sample_document()
    document["sections"].append(
        {
            "id": "sec-2",
            "title": "Subtitulo",
            "level": 3,
            "blocks": [
                {
                    "id": "blk-1",
                    "type": "heading",
                    "level": 3,
                    "text": "Subtitulo",
                }
            ],
            "children": [],
        }
    )

    errors = validate_canonical_document(document)

    assert any("Duplicate internal id: blk-1" in error for error in errors)
    assert any("skips levels" in error for error in errors)


def test_validate_canonical_document_rejects_empty_table_rows():
    """A table block whose rows list is empty must be flagged as an empty table."""
    document = _sample_document()
    document["sections"][0]["blocks"].append(
        {
            "id": "blk-table",
            "type": "table",
            "rows": [],
        }
    )

    errors = validate_canonical_document(document)

    assert any("Empty table in blk-table" in error for error in errors)


def test_validate_canonical_document_accepts_table_ast_only():
    """A well-formed table_ast (non-empty body rows with cells) produces no findings for that block."""
    document = _sample_document()
    document["sections"][0]["blocks"].append(
        {
            "id": "blk-table-ast",
            "type": "table",
            "table_ast": {
                "body": [
                    {
                        "cells": [
                            {"text": "Coluna A"},
                            {"text": "Coluna B"},
                        ]
                    },
                    {
                        "cells": [
                            {"text": "Valor 1"},
                            {"text": "Valor 2"},
                        ]
                    },
                ]
            },
        }
    )

    errors = validate_canonical_document(document)

    assert not any("blk-table-ast" in error for error in errors)


def test_validate_canonical_document_detects_table_row_inconsistency():
    """Table rows whose column count differs from the first row must be flagged as inconsistent columns."""
    document = _sample_document()
    document["sections"][0]["blocks"].append(
        {
            "id": "blk-table-bad",
            "type": "table",
            "rows": [
                ["A", "B"],
                ["C"],
            ],
        }
    )

    errors = validate_canonical_document(document)

    assert any("inconsistent columns" in error for error in errors)


def test_validate_export_profile_detects_profile_mismatch():
    """A technical block inside a txt-profile document is not allowed by the txt verbosity set."""
    document = _sample_document()

    errors = validate_export_profile("txt", document)

    assert any("not allowed in profile" in error for error in errors)


def test_validate_output_text_flags_leaks_and_markdown():
    """Final-text scan should flag markdown artifacts plus a prompt leak (pdf profile) and TXT-only metadata."""
    errors_pdf = validate_output_text(
        "Texto com **marcacao** e system prompt embutido.",
        "pdf",
    )
    errors_txt = validate_output_text(
        "[INICIO DA AUDIODESCRICAO] metadados tecnicos",
        "txt",
    )

    assert any("Improper markdown in the final output" in error for error in errors_pdf)
    assert any("prompt leak" in error.lower() for error in errors_pdf)
    assert any("Technical metadata" in error for error in errors_txt)


def test_verbosity_helpers_choose_expected_defaults():
    """Unknown profile names and unknown mode names fall back to the documented safe defaults."""
    assert normalize_profile("desconhecido")["verbosity"] == ["basic"]
    assert verbosity_for_mode("inexistente") == "detailed"


def test_filter_blocks_for_profile_hides_technical_blocks_in_txt():
    """The txt profile keeps only basic-verbosity blocks, while html keeps both basic and technical blocks."""
    blocks = _sample_document()["sections"][0]["blocks"]

    filtered_txt = filter_blocks_for_profile(blocks, "txt")
    filtered_html = filter_blocks_for_profile(blocks, "html")

    assert [block["id"] for block in filtered_txt] == ["blk-1"]
    assert [block["id"] for block in filtered_html] == ["blk-1", "blk-2"]


def test_validate_canonical_document_allows_short_multiline_code_block():
    """A code block with only a signature and a closing brace must not be reported as losing indentation."""
    document = _sample_document()
    document["sections"][0]["blocks"].append(
        {
            "id": "blk-code-short",
            "type": "code",
            "text": "public interface ContaTributavel extends Conta, Tributavel {\n}",
        }
    )

    errors = validate_canonical_document(document)

    assert not any("blk-code-short" in error for error in errors)


def test_validate_canonical_document_flags_flattened_multiline_code_without_indent():
    """A flattened multi-line code block with no indented interior lines must be flagged as inconsistent indentation."""
    document = _sample_document()
    document["sections"][0]["blocks"].append(
        {
            "id": "blk-code-flat",
            "type": "code",
            "text": "public class A {\nprivate String nome;\nprivate String cpf;\n}",
        }
    )

    errors = validate_canonical_document(document)

    assert any("blk-code-flat" in error for error in errors)
