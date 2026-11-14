"""
What this suite verifies: backend/core/pipeline/validators.audit_canonical_document separates findings
into BLOCKER (base-structural failures plus missing sections) and WARNING (accessibility issues
such as images without alt text and tables lacking an explicit table_ast header). Locale is pinned
to en_US for deterministic canonical-English assertions.
"""

from __future__ import annotations

import pytest

import backend.core.i18n as i8n
from backend.core.pipeline.validators import audit_canonical_document


@pytest.fixture(autouse=True)
def _pin_en_us(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the en_US runtime locale for every test in this module.

    The audit findings resolve through backend.core.i18n.t, so assertions need a deterministic locale;
    en_US returns the canonical English msgids.
    """
    monkeypatch.setenv("LOCALE", "en_US")
    i8n._catalog_for.cache_clear()


def _sample_valid_document() -> dict:
    """Build a minimal valid canonical document used as the base fixture for most audit tests.

    Returns:
        dict: Canonical-document mapping with a single section holding an H1 heading and one paragraph.
    """
    return {
        "schema_version": "1.0.0",
        "id": "doc-1",
        "title": "Documento Valido",
        "language": "pt-BR",
        "sections": [
            {
                "id": "sec-1",
                "title": "Titulo Principal",
                "blocks": [
                    {
                        "id": "blk-h1",
                        "type": "heading",
                        "level": 1,
                        "text": "Titulo Principal",
                    },
                    {
                        "id": "blk-p1",
                        "type": "paragraph",
                        "text": "Texto do documento.",
                    },
                ],
                "children": [],
            }
        ],
    }


def test_audit_valid_document_no_errors():
    """A well-formed document should produce an empty BLOCKER and WARNING report."""
    doc = _sample_valid_document()
    report = audit_canonical_document(doc)

    assert report["BLOCKER"] == []
    assert report["WARNING"] == []


def test_audit_detects_missing_sections():
    """A document whose sections list is empty must be blocked for having no sections."""
    doc = _sample_valid_document()
    doc["sections"] = []

    report = audit_canonical_document(doc)

    assert any("Document has no sections" in err for err in report["BLOCKER"])


def test_audit_detects_blockers_from_base_validation():
    """A duplicated block id from base validation must surface as a BLOCKER finding."""
    doc = _sample_valid_document()
    # Duplicate the id to trigger an error in base validation.
    doc["sections"][0]["blocks"].append(
        {
            "id": "blk-p1",  # Duplicated id.
            "type": "paragraph",
            "text": "Outro texto.",
        }
    )

    report = audit_canonical_document(doc)

    assert any("Duplicate internal id: blk-p1" in err for err in report["BLOCKER"])


def test_audit_detects_warning_missing_alt_text():
    """An image block with no alt text in its metadata must produce a WARNING finding."""
    doc = _sample_valid_document()
    doc["sections"][0]["blocks"].append(
        {
            "id": "img-1",
            "type": "image",
            "src": "path/to/img.png",
            "metadata": {},  # No alt text.
        }
    )

    report = audit_canonical_document(doc)

    assert any("Image img-1 has no alt-text" in err for err in report["WARNING"])


def test_audit_nested_sections_accessibility():
    """Accessibility warnings must also be raised for image blocks in nested child sections."""
    doc = _sample_valid_document()
    doc["sections"][0]["children"] = [
        {
            "id": "sec-sub",
            "blocks": [
                {
                    "id": "img-sub",
                    "type": "image",
                    "metadata": {"alt": ""},  # An empty alt must also raise a warning.
                }
            ],
        }
    ]

    report = audit_canonical_document(doc)

    assert any("Image img-sub has no alt-text" in err for err in report["WARNING"])


def test_audit_accepts_explicit_row_header_cells() -> None:
    doc = _sample_valid_document()
    doc["sections"][0]["blocks"].append(
        {
            "id": "table-row-headers",
            "type": "table",
            "table_ast": {
                "body": [
                    {
                        "cells": [
                            {"text": "Janeiro", "header": True, "scope": "row"},
                            {"text": "10"},
                        ]
                    },
                    {
                        "cells": [
                            {"text": "Fevereiro", "header": True, "scope": "row"},
                            {"text": "12"},
                        ]
                    },
                ]
            },
        }
    )

    report = audit_canonical_document(doc)

    assert report["WARNING"] == []


def test_audit_warns_when_only_one_body_row_has_a_partial_header() -> None:
    doc = _sample_valid_document()
    doc["sections"][0]["blocks"].append(
        {
            "id": "table-partial-row-header",
            "type": "table",
            "table_ast": {
                "body": [
                    {"cells": [{"text": "Mês"}, {"text": "Valor"}]},
                    {
                        "cells": [
                            {
                                "text": "Janeiro",
                                "header": True,
                                "scope": "row",
                            },
                            {"text": "10"},
                        ]
                    },
                    {"cells": [{"text": "Fevereiro"}, {"text": "12"}]},
                ]
            },
        }
    )

    report = audit_canonical_document(doc)

    assert any(
        "table-partial-row-header" in warning for warning in report["WARNING"]
    )


# ── Empty table cells (hotfix #116 on main) ──────────────────────────────


def test_audit_table_with_empty_cells_allowed():
    """A schedule-style table_ast with blank cells is valid, not a blocker."""
    doc = _sample_valid_document()
    doc["sections"][0]["blocks"].append(
        {
            "id": "blk-tbl-1",
            "type": "table",
            "table_ast": {
                "header": [
                    {
                        "cells": [
                            {"text": "Task", "header": True},
                            {"text": "Week 1", "header": True},
                            {"text": "Week 2", "header": True},
                        ]
                    }
                ],
                "body": [
                    {"cells": [{"text": "Planning"}, {"text": "X"}, {"text": ""}]},
                    {"cells": [{"text": "Execution"}, {"text": ""}, {"text": "X"}]},
                ],
            },
        }
    )

    report = audit_canonical_document(doc)

    assert report["BLOCKER"] == []


def test_audit_table_legacy_rows_with_empty_cells_allowed():
    """Legacy ``rows`` tables may hold blank cells too."""
    doc = _sample_valid_document()
    doc["sections"][0]["blocks"].append(
        {
            "id": "blk-tbl-legacy",
            "type": "table",
            "rows": [
                ["Step", "Week 1", "Week 2"],
                ["Survey", "OK", ""],
                ["Analysis", "", "OK"],
            ],
        }
    )

    report = audit_canonical_document(doc)

    assert report["BLOCKER"] == []


def test_audit_table_detects_invalid_text_type():
    """A non-string cell text is still a blocker."""
    doc = _sample_valid_document()
    doc["sections"][0]["blocks"].append(
        {
            "id": "blk-tbl-invalid",
            "type": "table",
            "table_ast": {"body": [{"cells": [{"text": 12345}]}]},
        }
    )

    report = audit_canonical_document(doc)

    assert any(
        "table_ast cell without text in blk-tbl-invalid" in err for err in report["BLOCKER"]
    )
