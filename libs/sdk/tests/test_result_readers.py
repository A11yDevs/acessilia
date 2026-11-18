"""Additive typed accessors preserve raw APIs and their transport errors."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from acessilia_sdk.toolbox import results
from acessilia_sdk.toolbox.clients.math import ToolboxMathClient, recognized_formulas
from acessilia_sdk.toolbox.clients.adjudicate import (
    ToolboxAdjudicateClient,
    page_judgement_probability,
)
from acessilia_sdk.toolbox.clients.media_inspect import ToolboxMediaInspectClient
from acessilia_sdk.toolbox.clients.pdf_validate import ToolboxPdfValidateClient
from acessilia_sdk.toolbox.clients.pdf import ToolboxPdfClient, RenderedPage
from acessilia_sdk.toolbox.errors import ToolboxContractViolation, ToolboxTimeout

EXAMPLES = json.loads(
    (Path(__file__).parent / "fixtures/execute-results.json").read_text()
)


@pytest.mark.parametrize(
    "cls,method,model,args",
    [
        (
            ToolboxMathClient,
            "convert",
            "MathmlResult",
            {"latex": "x", "direction": "mathml-to-latex"},
        ),
        (ToolboxMathClient, "verbalize", "VerbalizedResult", {"latex": "x"}),
        (
            ToolboxAdjudicateClient,
            "judge_page",
            "PageJudgement",
            {"candidate_a": "a", "candidate_b": "b"},
        ),
        (
            ToolboxAdjudicateClient,
            "transcribe_region",
            "RegionTranscription",
            {"candidates": []},
        ),
        (ToolboxMediaInspectClient, "inspect", "MediaInspection", {}),
        (ToolboxPdfValidateClient, "validate", "PdfValidationReport", {}),
        (ToolboxPdfClient, "text_spans", "TextSpansResult", {"pages": [1]}),
    ],
)
@pytest.mark.asyncio
async def test_typed_client_accessor(cls, method, model, args):
    client = cls(base_url="http://toolbox")
    try:
        document = EXAMPLES[model]
        payload = (
            document
            if method in ("inspect", "validate", "text_spans")
            else {"document": document}
        )
        mock = AsyncMock(return_value=payload)
        setattr(client, method, mock)
        typed = await getattr(client, method + "_result")(**args)
        assert isinstance(typed, getattr(results, model))
        assert typed.to_dict() == document
        for key, value in args.items():
            assert mock.call_args.kwargs[key] == value
        mock.return_value = []
        with pytest.raises(ToolboxContractViolation):
            await getattr(client, method + "_result")(**args)
        mock.side_effect = ToolboxTimeout("slow")
        with pytest.raises(ToolboxTimeout):
            await getattr(client, method + "_result")(**args)

    finally:
        await client.close()


@pytest.mark.asyncio
async def test_recognition_keeps_single_and_legacy_list_shapes():
    client = ToolboxMathClient(base_url="http://toolbox")
    try:
        for document in (
            EXAMPLES["LatexResult"],
            {"formulas": [EXAMPLES["LatexResult"]]},
        ):
            client.recognize = AsyncMock(return_value={"document": document})
            assert (await client.recognize_result())[0].latex == "x^2"
            assert recognized_formulas(document)[0]["latex"] == "x^2"
        assert recognized_formulas({"formulas": [{"latex": None}]}) == []

    finally:
        await client.close()


def test_render_metadata_does_not_replace_verified_bytes():
    page = RenderedPage(b"PNG", (0, 0, 100, 200), EXAMPLES["RenderedPageMetadata"])
    assert page.metadata.page_width == 100
    assert page.image == b"PNG"


def test_missing_null_extensions_and_open_metadata_round_trip():
    missing = results.MediaInspection.from_dict(
        {
            k: v
            for k, v in EXAMPLES["MediaInspection"].items()
            if k != "declared_media_type"
        }
    )
    assert missing.declared_media_type is None
    assert "declared_media_type" not in missing.to_dict()
    explicit = results.MediaInspection.from_dict(
        {**missing.to_dict(), "declared_media_type": None, "future": {"a": [1, None]}}
    )
    assert explicit.to_dict()["declared_media_type"] is None
    assert explicit.to_dict()["future"] == {"a": [1, None]}
    assert explicit.to_dict()["metadata"] == EXAMPLES["MediaInspection"]["metadata"]
    assert page_judgement_probability({"pB": "0.8"}) == 0.8
    with pytest.raises(ToolboxContractViolation):
        results.read_result(
            {**EXAMPLES["PageJudgement"], "pB": "0.8"}, results.PageJudgement
        )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True])
def test_non_json_numbers_rejected(value):
    with pytest.raises(ValueError):
        results.LatexResult.from_dict({"latex": "x", "confidence": value})
