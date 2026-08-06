from backend.pipeline.structure_parser import parse_text_to_blocks


def test_parse_text_to_blocks_assigns_ids_and_sanitizes_text():
    blocks = parse_text_to_blocks(
        (
            "# Titulo **forte**\n\n"
            "Paragrafo com `codigo` e __marcacao__.\n\n"
            "- Item 1\n2. Item 2"
        )
    )

    assert [block["type"] for block in blocks] == [
        "heading",
        "paragraph",
        "list",
        "list",
    ]
    assert len({block["id"] for block in blocks}) == len(blocks)
    assert blocks[0]["text"] == "Titulo forte"
    assert blocks[1]["text"] == "Paragrafo com codigo e marcacao."
    assert blocks[2]["items"] == ["Item 1"]
    assert blocks[3]["ordered"] is True


def test_parse_text_to_blocks_keeps_code_fence_marker():
    blocks = parse_text_to_blocks("```python")

    assert blocks == [
        {
            "type": "code",
            "text": "```python",
            "id": blocks[0]["id"],
        }
    ]


def test_parse_text_to_blocks_parses_simple_table():
    blocks = parse_text_to_blocks("| Coluna A | Coluna B |\n| --- | --- |\n| 1 | 2 |")

    assert blocks[0]["type"] == "table"
    assert blocks[0]["rows"] == [
        ["Coluna A", "Coluna B"],
        ["1", "2"],
    ]


def test_parse_text_to_blocks_parses_plain_text_heading_styles():
    blocks = parse_text_to_blocks(
        "TITULO PRINCIPAL\n\nSeção: Introdução\n\nTexto final."
    )

    assert blocks[0]["type"] == "heading"
    assert blocks[0]["level"] == 1
    assert blocks[0]["text"] == "TITULO PRINCIPAL"
    assert blocks[1]["type"] == "heading"
    assert blocks[1]["level"] == 2
    assert blocks[1]["text"] == "Introdução"
    assert blocks[2]["type"] == "paragraph"


def test_parse_text_to_blocks_parses_plain_ordered_list_with_parenthesis():
    blocks = parse_text_to_blocks("1) Primeiro item\n(2) Segundo item")

    assert blocks[0]["type"] == "list"
    assert blocks[0]["ordered"] is True
    assert blocks[0]["items"] == ["Primeiro item"]
    assert blocks[1]["type"] == "list"
    assert blocks[1]["ordered"] is True
    assert blocks[1]["items"] == ["Segundo item"]


def test_parse_text_to_blocks_maps_callout_marker_to_note():
    text = (
        "Início de nota:\n"
        "Este conteúdo está em uma caixa interna.\n"
        "Fim de nota"
    )

    blocks = parse_text_to_blocks(text)

    assert blocks[0]["type"] == "note"
    assert blocks[0]["title"] == "Nota"
    assert "caixa interna" in blocks[0]["text"]
    assert blocks[0]["metadata"]["source"] == "legacy-marker"


def test_parse_text_to_blocks_maps_callout_marker_to_warning():
    text = (
        "Início de aviso:\n"
        "Use equipamento de segurança.\n"
        "Fim de aviso"
    )

    blocks = parse_text_to_blocks(text)

    assert blocks[0]["type"] == "warning"
    assert blocks[0]["title"] == "Aviso"
    assert "equipamento de segurança" in blocks[0]["text"]
