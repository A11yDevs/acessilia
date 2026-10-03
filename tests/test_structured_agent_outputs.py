"""Contracts and canonical integration for Vision/Data structured outputs."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.agents.output_schemas import (
    DataOutput,
    VisionOutput,
    validate_structured_content,
)
from backend.pipeline.canonical_builder import build_canonical_document


def test_vision_output_requires_description_for_description_kind() -> None:
    with pytest.raises(ValidationError):
        VisionOutput(
            kind="description",
            description="",
            language="pt-BR",
            confidence=0.8,
            mentioned_elements=[],
        )


def test_vision_description_normalizes_empty_optional_formula() -> None:
    output = VisionOutput(
        kind="description",
        description="A sunset over a city.",
        language="en",
        confidence=0.98,
        mentioned_elements=["sunset", "city"],
        formula_latex="  ",
    )

    assert output.formula_latex is None


def test_json_content_is_validated_into_the_requested_schema() -> None:
    result = validate_structured_content(
        """{
            "kind": "formula",
            "description": "",
            "language": "und",
            "confidence": 0.75,
            "mentioned_elements": ["equação"],
            "formula_latex": "E=mc^2",
            "warnings": []
        }""",
        VisionOutput,
    )

    assert isinstance(result, VisionOutput)
    assert result.formula_latex == "E=mc^2"


@pytest.mark.parametrize("opening_fence", ["```json", "```JSON", "```"])
def test_fenced_json_content_is_validated_into_the_requested_schema(
    opening_fence: str,
) -> None:
    result = validate_structured_content(
        f"""{opening_fence}
        {{
            "kind": "formula",
            "description": "",
            "language": "und",
            "confidence": 0.75,
            "mentioned_elements": ["equation"],
            "formula_latex": "E=mc^2",
            "warnings": []
        }}
        ```""",
        VisionOutput,
    )

    assert isinstance(result, VisionOutput)
    assert result.formula_latex == "E=mc^2"


def test_non_json_fence_is_not_silently_accepted() -> None:
    with pytest.raises(ValidationError):
        validate_structured_content(
            """```yaml
            kind: formula
            ```""",
            VisionOutput,
        )


def test_data_table_preserves_cells_spans_and_warnings_in_canonical_ast() -> None:
    output = DataOutput(
        kind="table",
        rows=[
            {
                "cells": [
                    {"text": "Produto", "header": True, "scope": "col"},
                    {"text": "Valor", "header": True, "scope": "col"},
                ]
            },
            {
                "cells": [
                    {"text": "Arroz", "rowspan": 2},
                    {"text": ""},
                ]
            },
        ],
        caption="Preços",
        notes=["Fonte: levantamento interno."],
        language="pt-BR",
        confidence=0.91,
        warnings=["Uma célula está ilegível."],
    )

    ast = output.table_ast()

    assert ast["header"][0]["cells"][0]["header"] is True
    assert ast["body"][0]["cells"][0]["rowspan"] == 2
    assert ast["body"][0]["cells"][1]["text"] == ""
    assert ast["footer"] == [
        {
            "cells": [
                {
                    "text": "Fonte: levantamento interno.",
                    "colspan": 2,
                }
            ]
        }
    ]
    assert ast["metadata"]["warnings"] == ["Uma célula está ilegível."]

    document = build_canonical_document(
        {"pages": [{"blocks": [{"type": "table", "table_ast": ast}]}]}
    )
    table = document["sections"][0]["blocks"][0]
    assert table["rows"][1] == ["Arroz", ""]
    assert table["table_ast"]["footer"][0]["cells"][0]["text"] == (
        "Fonte: levantamento interno."
    )


def test_data_formula_rejects_table_rows() -> None:
    with pytest.raises(ValidationError):
        DataOutput(
            kind="formula",
            rows=[{"cells": [{"text": "x"}]}],
            latex="x",
            language="und",
            confidence=1.0,
        )


def test_data_formula_rejects_table_notes() -> None:
    with pytest.raises(ValidationError):
        DataOutput(
            kind="formula",
            latex="x",
            notes=["Nota exclusiva de tabela"],
            language="und",
            confidence=1.0,
        )


def test_data_output_normalizes_blank_optional_latex_and_caption() -> None:
    output = DataOutput(
        kind="table",
        rows=[{"cells": [{"text": "Item"}]}],
        latex="  ",
        caption="\n ",
        language="en",
        confidence=0.9,
    )

    assert output.latex is None
    assert output.caption is None


def test_data_formula_rejects_blank_latex_after_normalization() -> None:
    with pytest.raises(ValidationError, match="latex is required"):
        DataOutput(
            kind="formula",
            latex="  ",
            language="und",
            confidence=1.0,
        )


def test_data_table_keeps_row_headers_in_body() -> None:
    output = DataOutput(
        kind="table",
        rows=[
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
        ],
        language="pt-BR",
        confidence=0.9,
    )

    ast = output.table_ast()

    assert "header" not in ast
    assert ast["body"][0]["cells"][0] == {
        "text": "Janeiro",
        "header": True,
        "scope": "row",
    }


def test_all_header_table_keeps_final_row_in_body() -> None:
    output = DataOutput(
        kind="table",
        rows=[
            {"cells": [{"text": "Group", "header": True, "scope": "colgroup"}]},
            {"cells": [{"text": "Value", "header": True, "scope": "col"}]},
        ],
        language="en",
        confidence=0.9,
    )

    ast = output.table_ast()

    assert ast["header"] == [
        {"cells": [{"text": "Group", "header": True, "scope": "colgroup"}]}
    ]
    assert ast["body"] == [
        {"cells": [{"text": "Value", "header": True, "scope": "col"}]}
    ]


@pytest.mark.asyncio
async def test_vision_agent_requests_and_returns_its_output_schema(monkeypatch) -> None:
    from backend.agents import vision_agent as vision_module

    captured: dict = {}

    class FakeAgent:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run(self, **_kwargs):
            content = {
                "kind": "description",
                "description": "Um círculo azul.",
                "language": "pt-BR",
                "confidence": 0.96,
                "mentioned_elements": ["círculo"],
                "warnings": [],
            }
            return type("Response", (), {"content": content})()

    async def run_inline(function, *args):
        return function(*args)

    monkeypatch.setattr(vision_module, "Agent", FakeAgent)
    monkeypatch.setattr(vision_module, "get_agno_model", lambda: object())
    monkeypatch.setattr(vision_module.asyncio, "to_thread", run_inline)

    result = await vision_module.VisionAgent().describe_region(
        b"image", "embedded_image"
    )

    assert captured["output_schema"] is VisionOutput
    assert isinstance(result, VisionOutput)
    assert result.description == "Um círculo azul."


@pytest.mark.asyncio
async def test_data_agent_rejects_output_for_the_wrong_region_kind(monkeypatch) -> None:
    from backend.agents import data_agent as data_module

    class FakeAgent:
        def __init__(self, **_kwargs):
            pass

        def run(self, **_kwargs):
            content = DataOutput(
                kind="formula",
                latex="x^2",
                language="und",
                confidence=0.9,
            )
            return type("Response", (), {"content": content})()

    async def run_inline(function, *args):
        return function(*args)

    monkeypatch.setattr(data_module, "Agent", FakeAgent)
    monkeypatch.setattr(data_module, "get_agno_model", lambda: object())
    monkeypatch.setattr(data_module, "load_region_prompt", lambda _key: "prompt")
    monkeypatch.setattr(data_module.asyncio, "to_thread", run_inline)

    result = await data_module.DataAgent().process_region(b"image", "table")

    assert result is None
