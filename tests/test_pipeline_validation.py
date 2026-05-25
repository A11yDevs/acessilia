from pipeline.validators import validate_canonical_document
from pipeline.validators import validate_export_profile
from pipeline.validators import validate_output_text
from pipeline.verbosity_manager import filter_blocks_for_profile
from pipeline.verbosity_manager import normalize_profile
from pipeline.verbosity_manager import verbosity_for_mode


def _sample_document() -> dict:
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

    assert any("ID interno duplicado" in error for error in errors)
    assert any("salta niveis" in error for error in errors)


def test_validate_canonical_document_rejects_empty_table_rows():
    document = _sample_document()
    document["sections"][0]["blocks"].append(
        {
            "id": "blk-table",
            "type": "table",
            "rows": [],
        }
    )

    errors = validate_canonical_document(document)

    assert any("Tabela vazia" in error for error in errors)


def test_validate_export_profile_detects_profile_mismatch():
    document = _sample_document()

    errors = validate_export_profile("txt", document)

    assert any("nao permitido" in error for error in errors)


def test_validate_output_text_flags_leaks_and_markdown():
    errors_pdf = validate_output_text(
        "Texto com **marcacao** e system prompt embutido.",
        "pdf",
    )
    errors_txt = validate_output_text(
        "[INICIO DA AUDIODESCRICAO] metadados tecnicos",
        "txt",
    )

    assert any("Markdown indevido" in error for error in errors_pdf)
    assert any("vazamento de prompt" in error.lower() for error in errors_pdf)
    assert any("Metadados tecnicos" in error for error in errors_txt)


def test_verbosity_helpers_choose_expected_defaults():
    assert normalize_profile("desconhecido")["verbosity"] == ["basic"]
    assert verbosity_for_mode("inexistente") == "detailed"


def test_filter_blocks_for_profile_hides_technical_blocks_in_txt():
    blocks = _sample_document()["sections"][0]["blocks"]

    filtered_txt = filter_blocks_for_profile(blocks, "txt")
    filtered_html = filter_blocks_for_profile(blocks, "html")

    assert [block["id"] for block in filtered_txt] == ["blk-1"]
    assert [block["id"] for block in filtered_html] == ["blk-1", "blk-2"]
