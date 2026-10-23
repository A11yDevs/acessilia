"""Contracts and canonical integration for Vision/Data structured outputs."""

from __future__ import annotations

import json
from types import SimpleNamespace

from agno.run.base import RunStatus
import pytest
from pydantic import ValidationError

from backend.agents.output_schemas import (
    DataOutput,
    VisionOutput,
    validate_structured_content,
    validate_structured_run,
)
from backend.pipeline.canonical_builder import build_canonical_document


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (RunStatus.error, "model run failed"),
        (RunStatus.cancelled, "Agent run did not complete"),
        (RunStatus.paused, "Agent run did not complete"),
    ],
)
def test_unsuccessful_agent_run_cannot_publish_valid_looking_content(status, message):
    content = VisionOutput(
        kind="description", description="A blue circle.", language="en",
        confidence=0.9, mentioned_elements=["circle"],
    )
    response = SimpleNamespace(status=status, content=content)
    with pytest.raises(RuntimeError, match=message):
        validate_structured_run(response, VisionOutput)


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


def _vision_json(**fields) -> str:
    payload = {
        "language": "pt-BR",
        "confidence": 0.9,
        "mentioned_elements": [],
        "warnings": [],
        **fields,
    }
    return json.dumps(payload)


def test_a_description_that_also_carries_a_formula_keeps_the_description() -> None:
    """006.pdf, page 29: kind='description' with formula_latex='NaCl' failed the job."""
    output = validate_structured_content(
        _vision_json(
            kind="description",
            description="Cubic crystals of sodium chloride (NaCl).",
            formula_latex="NaCl",
        ),
        VisionOutput,
    )

    assert output.kind == "description"
    assert output.description.startswith("Cubic crystals of sodium chloride")
    assert output.formula_latex is None


def test_a_description_with_only_a_formula_becomes_a_formula() -> None:
    output = validate_structured_content(
        _vision_json(kind="description", formula_latex="E=mc^2"), VisionOutput
    )

    assert (output.kind, output.formula_latex) == ("formula", "E=mc^2")


def test_a_description_with_neither_text_nor_formula_is_still_rejected() -> None:
    with pytest.raises(ValidationError, match="description is required"):
        validate_structured_content(_vision_json(kind="description"), VisionOutput)


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
    monkeypatch.setattr(data_module, "get_agno_model", lambda **_kwargs: object())
    monkeypatch.setattr(data_module, "load_region_prompt", lambda _key: "prompt")
    monkeypatch.setattr(data_module.asyncio, "to_thread", run_inline)

    result = await data_module.DataAgent().process_region(b"image", "table")

    assert result is None


@pytest.mark.asyncio
async def test_data_agent_uses_larger_token_budget_for_tables(monkeypatch) -> None:
    from backend.agents import data_agent as data_module

    captured: dict[str, object] = {}

    class FakeAgent:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run(self, **_kwargs):
            content = DataOutput(
                kind="table",
                rows=[{"cells": [{"text": "Item"}, {"text": "Valor"}]}],
                language="pt-BR",
                confidence=0.9,
            )
            return type("Response", (), {"content": content})()

    async def run_inline(function, *args):
        return function(*args)

    monkeypatch.setattr(data_module, "Agent", FakeAgent)
    monkeypatch.setattr(
        data_module,
        "get_agno_model",
        lambda **kwargs: (captured.update(model_kwargs=kwargs) or object()),
    )
    monkeypatch.setattr(data_module, "load_region_prompt", lambda _key: "prompt")
    monkeypatch.setattr(data_module.asyncio, "to_thread", run_inline)
    monkeypatch.setattr(data_module.settings, "data_agent_max_tokens", 8192)

    result = await data_module.DataAgent().process_region(b"image", "table")

    assert result is not None and result.kind == "table"
    assert captured["model_kwargs"] == {"max_tokens": 8192}
    assert captured["output_schema"] is DataOutput


def test_run_content_raises_when_the_run_failed() -> None:
    """Agno reports provider errors as a run with status=error, not an exception."""
    from agno.run.base import RunStatus

    from backend.agents.run_helpers import AgentRunError, run_content

    failed = type("Run", (), {"status": RunStatus.error, "content": "Invalid API Key"})()
    with pytest.raises(AgentRunError, match="Invalid API Key"):
        run_content(failed)

    done = type("Run", (), {"status": RunStatus.completed, "content": {"a": 1}})()
    assert run_content(done) == {"a": 1}
    # Responses without a status (older fakes, plain objects) keep working.
    assert run_content(type("Run", (), {"content": "x"})()) == "x"
    # A plain string status is accepted too.
    with pytest.raises(AgentRunError, match="x"):
        run_content(type("Run", (), {"status": "error", "content": "x"})())
    # A failed run without content still says why it raised.
    with pytest.raises(AgentRunError, match="no error message"):
        run_content(type("Run", (), {"status": RunStatus.error, "content": None})())


@pytest.mark.asyncio
@pytest.mark.parametrize("agent_module", ["vision_agent", "data_agent"])
async def test_failed_run_is_logged_with_its_real_cause(monkeypatch, agent_module) -> None:
    """A rejected key must be logged as such, not as a JSON validation error."""
    import importlib

    from agno.run.base import RunStatus

    from backend.tools.logger import logger

    module = importlib.import_module(f"backend.agents.{agent_module}")

    class FakeAgent:
        def __init__(self, **_kwargs):
            pass

        def run(self, **_kwargs):
            return type("Run", (), {"status": RunStatus.error, "content": "Invalid API Key"})()

    async def run_inline(function, *args):
        return function(*args)

    monkeypatch.setattr(module, "Agent", FakeAgent)
    monkeypatch.setattr(module, "get_agno_model", lambda **_kwargs: object())
    monkeypatch.setattr(module.asyncio, "to_thread", run_inline)
    if agent_module == "data_agent":
        monkeypatch.setattr(module, "load_region_prompt", lambda _key: "prompt")

    messages: list[str] = []
    sink = logger.add(lambda message: messages.append(str(message)), level="CRITICAL")
    try:
        if agent_module == "vision_agent":
            result = await module.VisionAgent().describe_region(b"image", "embedded_image")
        else:
            result = await module.DataAgent().process_region(b"image", "table")
    finally:
        logger.remove(sink)

    assert result is None
    logged = "\n".join(messages)
    assert "model run failed: Invalid API Key" in logged
    assert "json_invalid" not in logged
