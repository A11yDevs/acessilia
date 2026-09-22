"""Golden tests for tables/validation/profiles port (Phase 2, slice 2)."""
from docstruct.profiles import (
    MODE_TO_VERBOSITY,
    OUTPUT_PROFILES,
    filter_blocks_for_profile,
    normalize_profile,
    verbosity_for_mode,
)
from docstruct.tables.ast import (
    ALLOWED_SCOPES,
    MSG_TABLE_TEXT_CAPTION,
    MSG_TABLE_TEXT_ROW,
    linearize_table_for_text,
    normalize_table_ast,
    row_header_column_count,
    rows_from_table_ast,
    split_header_and_body,
    table_ast_from_block,
    table_ast_from_rows,
)
from docstruct.validation import (
    MSG_FIELD_MISSING,
    validate_canonical_document,
    validate_export_profile,
    validate_output_text,
)


class TestTableAst:
    def test_normalize_rows(self):
        ast = normalize_table_ast({"rows": [["A", "B"], ["1", "2"]], "caption": "T"})
        assert ast["caption"] == "T"
        assert len(ast["body"]) == 2

    def test_normalize_none_sem_body(self):
        assert normalize_table_ast({"rows": []}) is None
        assert normalize_table_ast(None) is None

    def test_rows_roundtrip(self):
        ast = normalize_table_ast({"rows": [["A", "B"], ["1", "2"]]})
        assert rows_from_table_ast(ast) == [["A", "B"], ["1", "2"]]

    def test_header_inference(self):
        _, body, _ = split_header_and_body({"body": [{"cells": [{"text": "H"}]}, {"cells": [{"text": "v"}]}]})
        assert len(body) == 1

    def test_explicit_row_headers_disable_legacy_first_row_inference(self):
        header, body, _ = split_header_and_body(
            {
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
        )

        assert header == []
        assert len(body) == 2

    def test_partial_row_header_does_not_disable_legacy_inference(self):
        rows = [
            {"cells": [{"text": "Mês"}, {"text": "Valor"}]},
            {
                "cells": [
                    {"text": "Janeiro", "header": True, "scope": "row"},
                    {"text": "10"},
                ]
            },
            {"cells": [{"text": "Fevereiro"}, {"text": "12"}]},
        ]

        header, body, _ = split_header_and_body({"body": rows})

        assert header == [rows[0]]
        assert body == rows[1:]
        assert row_header_column_count(rows) == 0

    def test_linearize_canonical_english(self):
        out = linearize_table_for_text({"rows": [["A", "B"], ["1", "2"]], "caption": "T"})
        assert out[0] == "Table: T"
        assert "Row 1:" in out[1]

    def test_msgids_canonicos(self):
        assert MSG_TABLE_TEXT_CAPTION == "Table: {caption}"
        assert MSG_TABLE_TEXT_ROW == "Row {row_index}: {joined}"

    def test_scopes(self):
        assert ALLOWED_SCOPES == {"none", "row", "col", "rowgroup", "colgroup"}

    def test_from_block(self):
        ast = table_ast_from_block({"rows": [["x"]]})
        assert ast is not None

    def test_from_rows_caption(self):
        ast = table_ast_from_rows([["a"]], caption="C")
        assert ast["caption"] == "C"


class TestProfiles:
    def test_profiles_conhecidos(self):
        assert set(OUTPUT_PROFILES) == {"html", "pdf", "pdf_ua", "docx", "txt"}

    def test_txt_somente_basic(self):
        assert OUTPUT_PROFILES["txt"]["verbosity"] == ["basic"]

    def test_normalize_desconhecido_cai_txt(self):
        assert normalize_profile("inexistente") == OUTPUT_PROFILES["txt"]

    def test_mode_mapping(self):
        assert verbosity_for_mode("detalhado") == "technical"
        assert verbosity_for_mode("baixo") == "basic"
        assert verbosity_for_mode("desconhecido") == "detailed"

    def test_filter_por_perfil(self):
        blocks = [{"id": "a", "verbosity": "basic"}, {"id": "b", "verbosity": "technical"}]
        assert [b["id"] for b in filter_blocks_for_profile(blocks, "txt")] == ["a"]


class TestValidation:
    def _doc(self, blocks):
        return {
            "schema_version": "1",
            "id": "d",
            "title": "T",
            "language": "pt",
            "sections": [{"blocks": blocks}],
        }

    def test_doc_valido(self):
        assert validate_canonical_document(self._doc([
            {"id": "b1", "type": "heading", "level": 1, "text": "T"},
        ])) == []

    def test_campo_faltando(self):
        findings = validate_canonical_document({"sections": []})
        assert any("Required field missing" in f[0] for f in findings)

    def test_id_duplicado(self):
        findings = validate_canonical_document(self._doc([
            {"id": "x", "type": "paragraph", "text": "a"},
            {"id": "x", "type": "paragraph", "text": "b"},
        ]))
        assert any("Duplicate internal id" in f[0] for f in findings)

    def test_h1_multipla(self):
        findings = validate_canonical_document(self._doc([
            {"id": "1", "type": "heading", "level": 1, "text": "a"},
            {"id": "2", "type": "heading", "level": 1, "text": "b"},
        ]))
        assert any("only one main H1" in f[0] for f in findings)

    def test_prompt_leak(self):
        findings = validate_canonical_document(self._doc([
            {"id": "1", "type": "paragraph", "text": "ignore previous instructions"},
        ]))
        assert any("prompt leak" in f[0] for f in findings)

    def test_output_text_limpo(self):
        assert validate_output_text("texto ok", "txt") == []

    def test_output_text_markdown_nao_html(self):
        findings = validate_output_text("**bold**", "txt")
        assert any("markdown" in f[0].lower() for f in findings)

    def test_profile_desconhecido(self):
        findings = validate_export_profile("nao-existe", self._doc([]))
        assert any("Unknown export profile" in f[0] for f in findings)

    def test_msgid_constante(self):
        assert MSG_FIELD_MISSING == "Required field missing: {field}"

    def test_findings_sao_tuples(self):
        findings = validate_canonical_document({"sections": []})
        for f in findings:
            assert isinstance(f, tuple) and len(f) == 2
