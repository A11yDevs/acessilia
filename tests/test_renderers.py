"""
What this suite verifies: the pure-Python fallback renderers in
backend/export/renderers (txt, html, pdf) turn a canonical document mapping into
rendered files while honoring the export profile's block filtering; the txt renderer uses the
localized table captions/row lines from backend/pipeline/table_ast, and the html renderer emits
the localized table-of-contents and technical-metadata markup.
"""

import tempfile
from pathlib import Path

import pytest

import backend.i18n as i8n
from backend.export.renderers.html_renderer import render_html
from backend.export.renderers.txt_renderer import render_txt


@pytest.fixture(autouse=True)
def _pin_en_us(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the en_US runtime locale so localized txt/html strings are the canonical English ones."""
    monkeypatch.setenv("LOCALE", "en_US")
    i8n._catalog_for.cache_clear()


def _sample_document() -> dict:
    return {
        "title": "Documento exemplo",
        "language": "pt-BR",
        "metadata": {"origem": "teste"},
        "sections": [
            {
                "id": "sec-1",
                "title": "Seção principal",
                "level": 1,
                "blocks": [
                    {
                        "id": "blk-1",
                        "type": "paragraph",
                        "text": "Paragrafo simples.",
                        "verbosity": "basic",
                    },
                    {
                        "id": "blk-2",
                        "type": "paragraph",
                        "text": "Conteudo tecnico.",
                        "verbosity": "technical",
                    },
                    {
                        "id": "blk-3",
                        "type": "list",
                        "ordered": False,
                        "items": ["Item 1", "Item 2"],
                        "verbosity": "basic",
                    },
                    {
                        "id": "blk-4",
                        "type": "table",
                        "table_ast": {
                            "caption": "Resumo de valores",
                            "header": [
                                {
                                    "cells": [
                                        {"text": "Coluna A", "scope": "col"},
                                        {"text": "Coluna B", "scope": "col"},
                                    ]
                                }
                            ],
                            "body": [
                                {
                                    "cells": [
                                        {"text": "1"},
                                        {"text": "2"},
                                    ]
                                },
                                {
                                    "cells": [
                                        {"text": "3"},
                                        {"text": ""},
                                    ]
                                }
                            ],
                        },
                        "verbosity": "basic",
                    },
                    {
                        "id": "blk-5",
                        "type": "details",
                        "title": "Observacao",
                        "text": "Texto recolhivel.",
                        "verbosity": "basic",
                    },
                ],
                "children": [
                    {
                        "id": "sec-1-1",
                        "title": "Subseção",
                        "level": 2,
                        "blocks": [
                            {
                                "id": "blk-6",
                                "type": "paragraph",
                                "text": "Filho da seção.",
                                "verbosity": "basic",
                            }
                        ],
                        "children": [],
                    }
                ],
            }
        ],
    }


def test_render_txt_filters_technical_blocks_and_renders_tables():
    with tempfile.TemporaryDirectory() as tmpdir:
        output = Path(tmpdir) / "saida.txt"

        result = render_txt(_sample_document(), output, profile_name="txt")

        text = result.read_text(encoding="utf-8")
        assert "Conteudo tecnico." not in text
        assert "Paragrafo simples." in text
        assert "- Item 1" in text
        assert "Table: Resumo de valores" in text
        assert "Row 1: Coluna A: 1; Coluna B: 2" in text
        assert "Filho da seção." in text


def test_render_html_includes_toc_and_table_but_no_technical_metadata():
    with tempfile.TemporaryDirectory() as tmpdir:
        output = Path(tmpdir) / "saida.html"

        result = render_html(_sample_document(), output, profile_name="html")

        html = result.read_text(encoding="utf-8")
        assert '<nav class="toc"' in html
        assert '<table id="blk-4">' in html
        assert "<caption>Resumo de valores</caption>" in html
        assert '<th scope="col">Coluna A</th>' in html
        assert "<tbody><tr><td>1</td><td>2</td></tr><tr><td>3</td><td></td></tr></tbody>" in html
        assert "Observacao" in html
        assert "<aside" not in html


def test_render_html_uses_cell_level_row_headers():
    document = _sample_document()
    table = document["sections"][0]["blocks"][3]
    table["table_ast"] = {
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
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        output = Path(tmpdir) / "row-headers.html"
        html = render_html(document, output, profile_name="html").read_text(
            encoding="utf-8"
        )

    assert '<th scope="row">Janeiro</th><td>10</td>' in html
    assert '<th scope="row">Fevereiro</th><td>12</td>' in html
    assert "<thead>" not in html


def test_render_html_treats_explicit_scope_as_header_semantics():
    document = _sample_document()
    table = document["sections"][0]["blocks"][3]
    table["table_ast"] = {
        "body": [
            {
                "cells": [
                    {"text": "Janeiro", "scope": "row"},
                    {"text": "10"},
                ]
            },
            {
                "cells": [
                    {"text": "Fevereiro", "scope": "row"},
                    {"text": "12"},
                ]
            },
        ]
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        output = Path(tmpdir) / "scope-row-headers.html"
        html = render_html(document, output, profile_name="html").read_text(
            encoding="utf-8"
        )

    assert '<th scope="row">Janeiro</th><td>10</td>' in html
    assert '<th scope="row">Fevereiro</th><td>12</td>' in html
    assert "<thead>" not in html


