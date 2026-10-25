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
    assert output.warnings == [
        "formula_latex dropped because kind is 'description': NaCl"
    ]
    # The orchestrator revalidates the dumped output; that must be a no-op.
    assert VisionOutput.model_validate(output.model_dump()) == output


@pytest.mark.parametrize("description", ["", "   "])
def test_a_description_with_only_a_formula_becomes_a_formula(description: str) -> None:
    # A whitespace-only description counts as absent because AgentOutput strips
    # strings; this pins that, since it decides which branch applies.
    output = validate_structured_content(
        _vision_json(kind="description", description=description, formula_latex="E=mc^2"),
        VisionOutput,
    )

    assert (output.kind, output.formula_latex) == ("formula", "E=mc^2")
    assert output.warnings == [
        "kind changed from 'description' to 'formula': only formula_latex was provided"
    ]
    assert VisionOutput.model_validate(output.model_dump()) == output


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
    monkeypatch.setattr(vision_module, "get_agno_model", lambda **_kwargs: object())
    monkeypatch.setattr(vision_module.asyncio, "to_thread", run_inline)

    result = await vision_module.VisionAgent().describe_region(
        b"image", "embedded_image"
    )

    assert captured["output_schema"] is VisionOutput
    assert isinstance(result, VisionOutput)
    assert result.description == "Um círculo azul."


#: What qwen3-vl-8b returned for an image on page 25 of 006.pdf: a formula padded
#: with "\\text{ }" until max_tokens cut the JSON string off.
TRUNCATED_FORMULA = '{\n  "kind": "formula",\n  "formula_latex": "x = ' + "\\\\text{ }" * 200


def _scripted_vision_agent(monkeypatch, answers: list[object]):
    from backend.agents import vision_agent as vision_module

    calls: list[dict] = []

    class FakeAgent:
        def __init__(self, **_kwargs):
            pass

        def run(self, **kwargs):
            calls.append(kwargs)
            answer = answers[len(calls) - 1]
            if isinstance(answer, Exception):
                raise answer
            return type("Response", (), {"content": answer})()

    async def run_inline(function, *args):
        return function(*args)

    monkeypatch.setattr(vision_module, "Agent", FakeAgent)
    monkeypatch.setattr(vision_module, "get_agno_model", lambda **_kwargs: object())
    monkeypatch.setattr(vision_module.asyncio, "to_thread", run_inline)
    return vision_module, calls


VALID_FORMULA = {
    "kind": "formula",
    "formula_latex": "x = y",
    "language": "pt-BR",
    "confidence": 0.8,
    "mentioned_elements": [],
    "warnings": [],
}


@pytest.mark.asyncio
async def test_vision_agent_retries_a_truncated_answer(monkeypatch) -> None:
    from backend.tools.logger import logger

    vision_module, calls = _scripted_vision_agent(
        monkeypatch, [TRUNCATED_FORMULA, VALID_FORMULA]
    )
    infos: list[str] = []
    sink = logger.add(infos.append, level="INFO", format="{message}")
    try:
        result = await vision_module.VisionAgent().describe_region(
            b"image", "embedded_image", page_num=25
        )
    finally:
        logger.remove(sink)

    assert isinstance(result, VisionOutput)
    assert result.formula_latex == "x = y"
    assert len(calls) == 2
    assert vision_module.RETRY_INSTRUCTION not in calls[0]["input"]
    assert calls[1]["input"].endswith(vision_module.RETRY_INSTRUCTION)
    # Every try sends the image again: that is what a retry costs.
    assert all([image.content for image in call["images"]] == [b"image"] for call in calls)
    # A recovered region is logged, so the retry rate can be measured.
    assert any("2/2" in message and "embedded_image" in message for message in infos)


@pytest.mark.asyncio
async def test_vision_agent_gives_up_after_its_attempts(monkeypatch) -> None:
    from backend.agents.vision_agent import REGION_ATTEMPTS
    from backend.tools.logger import logger

    vision_module, calls = _scripted_vision_agent(
        monkeypatch, [TRUNCATED_FORMULA] * REGION_ATTEMPTS
    )
    critical: list[str] = []
    warnings: list[str] = []
    sinks = [
        logger.add(critical.append, level="CRITICAL", format="{message}"),
        logger.add(
            warnings.append,
            level="WARNING",
            format="{message}",
            filter=lambda record: record["level"].name == "WARNING",
        ),
    ]
    try:
        result = await vision_module.VisionAgent().describe_region(
            b"image", "embedded_image", page_num=25
        )
    finally:
        for sink in sinks:
            logger.remove(sink)

    assert result is None
    assert len(calls) == REGION_ATTEMPTS
    assert len(critical) == 1
    assert len(warnings) == REGION_ATTEMPTS - 1
    # The retry warning names the cause, without the rejected answer itself.
    for message in warnings:
        assert "Invalid JSON" in message and "line 3" in message
        assert "\\text{ }" not in message
        assert len(message) < 500


@pytest.mark.asyncio
async def test_vision_agent_does_not_retry_a_provider_failure(monkeypatch) -> None:
    vision_module, calls = _scripted_vision_agent(
        monkeypatch, [TimeoutError("read timed out"), VALID_FORMULA]
    )

    result = await vision_module.VisionAgent().describe_region(
        b"image", "embedded_image", page_num=25
    )

    assert result is None
    assert len(calls) == 1


#: 006.pdf, page 23 (a periodic table): the description was whole and
#: mentioned_elements listed element names until max_tokens cut the JSON off.
TRUNCATED_IN_A_LATER_FIELD = (
    '{\n  "kind": "description",\n'
    '  "description": "The image shows the Periodic Table of the Elements on a '
    'blue background, arranged in groups and periods.",\n'
    '  "language": "en",\n  "confidence": 0.9,\n  "mentioned_elements": [\n'
    + "".join(f'    "Ununennium {index}",\n' for index in range(300))
    + '    "Ununen'
)

#: The description itself loops ("Ununennium" over and over) and is cut mid-word.
TRUNCATED_IN_THE_DESCRIPTION = (
    '{\n  "kind": "description",\n'
    '  "description": "The Periodic Table of the Elements on a blue background. '
    'The elements are: '
    + "Ununennium, " * 300
    + 'Unun'
)


@pytest.mark.asyncio
async def test_a_description_cut_off_in_a_later_field_is_salvaged(monkeypatch) -> None:
    from backend.agents.vision_agent import REGION_ATTEMPTS, SALVAGE_WARNING

    vision_module, calls = _scripted_vision_agent(
        monkeypatch, [TRUNCATED_IN_A_LATER_FIELD] * REGION_ATTEMPTS
    )

    result = await vision_module.VisionAgent().describe_region(
        b"image", "embedded_image", page_num=23
    )

    assert isinstance(result, VisionOutput)
    assert result.kind == "description"
    assert result.description == (
        "The image shows the Periodic Table of the Elements on a blue background, "
        "arranged in groups and periods."
    )
    assert result.language == "en"
    # Recovered, not what the model meant to send: the evidence says so.
    assert result.confidence == 0.0
    assert result.warnings == [SALVAGE_WARNING]
    assert len(calls) == REGION_ATTEMPTS


@pytest.mark.asyncio
async def test_a_looping_description_is_salvaged_without_the_loop(monkeypatch) -> None:
    from backend.agents.vision_agent import REGION_ATTEMPTS

    vision_module, _ = _scripted_vision_agent(
        monkeypatch, [TRUNCATED_IN_THE_DESCRIPTION] * REGION_ATTEMPTS
    )

    result = await vision_module.VisionAgent().describe_region(
        b"image", "embedded_image", page_num=23
    )

    assert isinstance(result, VisionOutput)
    # The repetition collapses and the cut sentence is dropped.
    assert result.description == "The Periodic Table of the Elements on a blue background."
    assert result.language == "und"


def test_a_description_over_the_region_budget_is_truncated_and_warns() -> None:
    from backend.agents.vision_agent import (
        DESCRIPTION_CHARS_PER_TOKEN,
        _truncate_description,
    )
    from backend.config.settings import settings
    from backend.i18n import t
    from backend.log_messages import MSG_VISION_TRUNCATION_NOTICE

    limit_chars = settings.vision_region_max_tokens * DESCRIPTION_CHARS_PER_TOKEN
    output = VisionOutput(
        kind="description",
        description="a" * (limit_chars + 100),
        language="en",
        confidence=0.9,
    )

    truncated, was_truncated = _truncate_description(
        output, page_num=18, region_type="embedded_image",
        limit_tokens=settings.vision_region_max_tokens,
    )

    assert was_truncated
    assert len(truncated.description) == limit_chars
    assert truncated.description.endswith("\n\n" + t(MSG_VISION_TRUNCATION_NOTICE))
    assert truncated.warnings == [
        "description truncated to the "
        f"{settings.vision_region_max_tokens}-token budget ({limit_chars} characters kept)"
    ]


def test_a_description_within_the_region_budget_is_kept_whole() -> None:
    from backend.agents.vision_agent import _truncate_description
    from backend.config.settings import settings

    output = VisionOutput(
        kind="description", description="Short description.", language="en", confidence=0.9
    )

    kept, was_truncated = _truncate_description(
        output, page_num=18, region_type="embedded_image",
        limit_tokens=settings.vision_region_max_tokens,
    )

    assert not was_truncated
    assert kept.description == "Short description."
    assert kept.warnings == []


@pytest.mark.asyncio
async def test_a_region_on_the_general_budget_is_never_truncated(monkeypatch) -> None:
    from backend.config.settings import settings

    description = "a" * (settings.vision_region_max_tokens * 100)
    vision_module, _ = _scripted_vision_agent(
        monkeypatch,
        [{"kind": "description", "description": description, "language": "en", "confidence": 0.9}],
    )

    result = await vision_module.VisionAgent().describe_region(
        b"image", "embedded_image", full_budget=True
    )

    # Transcription content: a cut there would lose document text.
    assert isinstance(result, VisionOutput)
    assert result.description == description
    assert result.warnings == []


@pytest.mark.asyncio
async def test_a_rate_limited_region_waits_and_is_retried(monkeypatch) -> None:
    from backend.agents.vision_agent import REGION_ATTEMPTS, _RATE_LIMIT_RETRIES

    class RateLimited(Exception):
        status_code = 429

    vision_module, calls = _scripted_vision_agent(
        monkeypatch, [RateLimited("HTTP 429")] * _RATE_LIMIT_RETRIES + [VALID_FORMULA]
    )
    monkeypatch.setattr(vision_module, "_RATE_LIMIT_RETRY_SECONDS", 0)

    result = await vision_module.VisionAgent().describe_region(
        b"image", "embedded_image", page_num=7
    )

    assert isinstance(result, VisionOutput)
    assert result.formula_latex == "x = y"
    # The rate-limit retries are a budget of their own: they did not consume
    # any of the answer tries, and the answer came on the first real try.
    assert len(calls) == _RATE_LIMIT_RETRIES + 1


@pytest.mark.asyncio
async def test_a_hung_model_call_is_abandoned_at_the_deadline(monkeypatch) -> None:
    """The HTTP timeout is per read; a call that never answers must still end."""
    import time

    from backend.agents import vision_agent as vision_module
    from backend.config.settings import settings

    class HangingAgent:
        def __init__(self, **_kwargs):
            pass

        def run(self, **_kwargs):
            time.sleep(1)
            raise AssertionError("the caller should already have given up")

    monkeypatch.setattr(vision_module, "Agent", HangingAgent)
    monkeypatch.setattr(vision_module, "get_agno_model", lambda **_kwargs: object())
    monkeypatch.setattr(settings, "model_call_timeout_seconds", 0)
    monkeypatch.setattr(vision_module, "CALL_DEADLINE_GRACE_SECONDS", 0.05)
    monkeypatch.setattr(settings, "vision_region_cache_enabled", False)

    started = time.monotonic()
    result = await vision_module.VisionAgent().describe_region(
        b"image", "full_page_image", page_num=14
    )

    assert result is None
    assert time.monotonic() - started < 2


@pytest.mark.asyncio
async def test_a_rate_limit_budget_exhausted_degrades_the_region(monkeypatch) -> None:
    from backend.agents.vision_agent import _RATE_LIMIT_RETRIES

    class RateLimited(Exception):
        status_code = 429

    vision_module, calls = _scripted_vision_agent(
        monkeypatch, [RateLimited("HTTP 429")] * (_RATE_LIMIT_RETRIES + 1)
    )
    monkeypatch.setattr(vision_module, "_RATE_LIMIT_RETRY_SECONDS", 0)

    result = await vision_module.VisionAgent().describe_region(
        b"image", "embedded_image", page_num=7
    )

    assert result is None
    assert len(calls) == _RATE_LIMIT_RETRIES + 1


@pytest.mark.asyncio
async def test_an_incomplete_run_rejected_as_a_rate_limit_is_retried(monkeypatch) -> None:
    vision_module, calls = _scripted_vision_agent(
        monkeypatch,
        [
            type("Incomplete", (), {"status": "cancelled", "content": "429 Too Many Requests"})(),
            VALID_FORMULA,
        ],
    )
    monkeypatch.setattr(vision_module, "_RATE_LIMIT_RETRY_SECONDS", 0)

    result = await vision_module.VisionAgent().describe_region(
        b"image", "embedded_image", page_num=7
    )

    assert isinstance(result, VisionOutput)
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_completed_content_mentioning_429_is_not_mistaken_for_a_rate_limit(
    monkeypatch,
) -> None:
    vision_module, calls = _scripted_vision_agent(
        monkeypatch,
        [
            {
                "kind": "description",
                "description": "A rodovia 429 tem uma placa de rate limit na entrada.",
                "language": "pt-BR",
                "confidence": 0.9,
                "mentioned_elements": [],
                "warnings": [],
            }
        ],
    )

    result = await vision_module.VisionAgent().describe_region(
        b"image", "embedded_image", page_num=7
    )

    # The 429 text lives in the model's answer, not in a provider failure: the
    # answer validates on the first try, with no backoff and no extra call.
    assert isinstance(result, VisionOutput)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_an_identical_region_reuses_the_cached_description(monkeypatch, tmp_path) -> None:
    from backend.config.settings import settings
    from backend.services import cache as cache_module

    vision_module, calls = _scripted_vision_agent(monkeypatch, [VALID_FORMULA])
    monkeypatch.setattr(settings, "vision_region_cache_enabled", True)
    monkeypatch.setattr(cache_module, "CACHE_DIR", tmp_path / "cache")

    first = await vision_module.VisionAgent().describe_region(b"image", "embedded_image")
    second = await vision_module.VisionAgent().describe_region(b"image", "embedded_image")

    assert isinstance(first, VisionOutput)
    assert second.model_dump(mode="json") == first.model_dump(mode="json")
    # The second identical call never reached the model.
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_a_truncated_description_is_not_cached(monkeypatch, tmp_path) -> None:
    from backend.config.settings import settings
    from backend.services import cache as cache_module

    long_answer = {
        "kind": "description",
        "description": "a" * (settings.vision_region_max_tokens * 100),
        "language": "en",
        "confidence": 0.9,
        "mentioned_elements": [],
        "warnings": [],
    }
    vision_module, calls = _scripted_vision_agent(monkeypatch, [long_answer, long_answer])
    monkeypatch.setattr(settings, "vision_region_cache_enabled", True)
    monkeypatch.setattr(cache_module, "CACHE_DIR", tmp_path / "cache")

    first = await vision_module.VisionAgent().describe_region(b"image", "embedded_image")
    second = await vision_module.VisionAgent().describe_region(b"image", "embedded_image")

    # A truncated answer is degraded: a rerun asks the model again instead of
    # being served the same cut text for the TTL.
    assert len(calls) == 2
    assert first is not None and second is not None
    assert first.description == second.description


@pytest.mark.asyncio
async def test_a_salvaged_description_is_not_cached(monkeypatch, tmp_path) -> None:
    from backend.agents.vision_agent import REGION_ATTEMPTS
    from backend.config.settings import settings
    from backend.services import cache as cache_module

    vision_module, calls = _scripted_vision_agent(
        monkeypatch, [TRUNCATED_IN_A_LATER_FIELD] * (2 * REGION_ATTEMPTS)
    )
    monkeypatch.setattr(settings, "vision_region_cache_enabled", True)
    monkeypatch.setattr(cache_module, "CACHE_DIR", tmp_path / "cache")

    first = await vision_module.VisionAgent().describe_region(b"image", "embedded_image")
    second = await vision_module.VisionAgent().describe_region(b"image", "embedded_image")

    assert isinstance(first, VisionOutput) and isinstance(second, VisionOutput)
    assert first.warnings and second.warnings
    # Both calls reached the model: the salvaged prefix is never stored.
    assert len(calls) == 2 * REGION_ATTEMPTS


def test_the_region_cache_key_varies_with_what_the_answer_depends_on(monkeypatch) -> None:
    from backend.agents.vision_agent import _region_cache_extra
    from backend.config.settings import settings
    from backend.i18n import reset_request_locale, set_request_locale

    monkeypatch.setattr(settings, "ai_client", "openrouter")
    monkeypatch.setattr(settings, "openrouter_model", "test/model")

    token = set_request_locale("en_US")
    base = _region_cache_extra("a prompt", "medio", 2000)
    reset_request_locale(token)

    assert _region_cache_extra("another prompt", "medio", 2000) != base
    assert _region_cache_extra("a prompt", "detalhado", 2000) != base
    assert _region_cache_extra("a prompt", "medio", 1500) != base
    # The same model name under another client is a different ask.
    monkeypatch.setattr(settings, "ai_client", "ollama")
    monkeypatch.setattr(settings, "ollama_model", "test/model")
    assert _region_cache_extra("a prompt", "medio", 2000) != base
    # The stored notice text is localized, so the locale is part of the key.
    token = set_request_locale("pt_BR")
    localized = _region_cache_extra("a prompt", "medio", 2000)
    reset_request_locale(token)
    assert localized != base


BLANK_PAGE = {"kind": "blank", "language": "und", "confidence": 0.9}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "call, answer, budget",
    [
        # A picture description gets the region budget.
        (lambda agent: agent.describe_region(b"image", "embedded_image"), VALID_FORMULA, 1234),
        # A whole page and a region inspected for review-structure may need
        # transcribing: they keep the general budget.
        (lambda agent: agent.describe_region(b"image", "full_page_image"), VALID_FORMULA, None),
        (
            lambda agent: agent.describe_region(b"image", "embedded_image", full_budget=True),
            VALID_FORMULA,
            None,
        ),
        (lambda agent: agent.inspect_page(b"image", page_num=1, total_pages=1), BLANK_PAGE, None),
    ],
    ids=["picture", "full-page", "region-inspection", "page-inspection"],
)
async def test_the_token_budget_of_each_vision_call(monkeypatch, call, answer, budget) -> None:
    from backend.config.settings import settings

    vision_module, _ = _scripted_vision_agent(monkeypatch, [answer])
    budgets: list = []
    monkeypatch.setattr(
        vision_module,
        "get_agno_model",
        lambda **kwargs: budgets.append(kwargs.get("max_tokens")),
    )
    monkeypatch.setattr(settings, "vision_region_max_tokens", 1234)

    await call(vision_module.VisionAgent())

    assert budgets == [budget]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "answer",
    [
        # Complete, but with an unquoted label inside the description.
        '{"kind": "description", "description": "A bar chart of monthly revenue '
        'for the whole year, labelled "Revenue" on its axis.", "language": "en", '
        '"confidence": 0.9}',
        # Complete, but with an invalid escape.
        '{"kind": "description", "description": "A bar chart of monthly revenue '
        'for the whole year \\q with its axis.", "language": "en", "confidence": 0.9}',
    ],
    ids=["inner-quote", "invalid-escape"],
)
async def test_an_answer_malformed_before_its_end_is_not_salvaged(monkeypatch, answer) -> None:
    """Only a cut answer is salvaged; a malformed one would be kept as a fragment."""
    from backend.agents.vision_agent import REGION_ATTEMPTS

    vision_module, _ = _scripted_vision_agent(monkeypatch, [answer] * REGION_ATTEMPTS)

    result = await vision_module.VisionAgent().describe_region(b"image", "embedded_image")

    assert result is None


@pytest.mark.asyncio
async def test_inspect_page_retries_a_truncated_answer(monkeypatch) -> None:
    from backend.agents.output_schemas import PageInspectionOutput

    truncated = '{\n  "kind": "content",\n  "description": "' + "a " * 200
    blank = {"kind": "blank", "language": "und", "confidence": 0.9}
    vision_module, calls = _scripted_vision_agent(monkeypatch, [truncated, blank])

    output = await vision_module.VisionAgent().inspect_page(b"image", page_num=2, total_pages=3)

    assert isinstance(output, PageInspectionOutput) and output.kind == "blank"
    assert len(calls) == 2
    assert calls[1]["input"].endswith(vision_module.RETRY_INSTRUCTION)


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
    monkeypatch.setattr(data_module.settings, "data_agent_timeout_seconds", 3600)

    result = await data_module.DataAgent().process_region(b"image", "table")

    assert result is not None and result.kind == "table"
    # Table transcription keeps the long ceiling: a local Ollama may run long
    # with the 8192-token budget.
    assert captured["model_kwargs"] == {
        "max_tokens": 8192,
        "timeout_seconds": 3600,
    }
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
