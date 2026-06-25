from pipeline.validators import audit_canonical_document


def _sample_valid_document() -> dict:
    return {
        "schema_version": "1.0.0",
        "id": "doc-1",
        "title": "Documento Válido",
        "language": "pt-BR",
        "sections": [
            {
                "id": "sec-1",
                "title": "Título Principal",
                "blocks": [
                    {
                        "id": "blk-h1",
                        "type": "heading",
                        "level": 1,
                        "text": "Título Principal",
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
    doc = _sample_valid_document()
    report = audit_canonical_document(doc)

    assert report["BLOCKER"] == []
    assert report["WARNING"] == []


def test_audit_detects_missing_sections():
    doc = _sample_valid_document()
    doc["sections"] = []

    report = audit_canonical_document(doc)

    assert any("Documento sem seções" in err for err in report["BLOCKER"])


def test_audit_detects_blockers_from_base_validation():
    doc = _sample_valid_document()
    # Duplicar ID para gerar erro na validação base
    doc["sections"][0]["blocks"].append(
        {
            "id": "blk-p1",  # ID Duplicado
            "type": "paragraph",
            "text": "Outro texto.",
        }
    )

    report = audit_canonical_document(doc)

    assert any("ID interno duplicado" in err for err in report["BLOCKER"])


def test_audit_detects_warning_missing_alt_text():
    doc = _sample_valid_document()
    doc["sections"][0]["blocks"].append(
        {
            "id": "img-1",
            "type": "image",
            "src": "path/to/img.png",
            "metadata": {},  # Sem alt-text
        }
    )

    report = audit_canonical_document(doc)

    assert any("Imagem img-1 sem alt-text" in err for err in report["WARNING"])


def test_audit_nested_sections_accessibility():
    doc = _sample_valid_document()
    doc["sections"][0]["children"] = [
        {
            "id": "sec-sub",
            "blocks": [
                {
                    "id": "img-sub",
                    "type": "image",
                    "metadata": {"alt": ""},  # Vazio também deve disparar warning
                }
            ],
        }
    ]

    report = audit_canonical_document(doc)

    assert any("Imagem img-sub sem alt-text" in err for err in report["WARNING"])
