"""Differential checks against the complete captured public schemas."""

import copy
import importlib.util
import json
from pathlib import Path

import jsonschema
import pytest
from acessilia_sdk.toolbox import results
from acessilia_sdk.toolbox.errors import ToolboxContractViolation

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = json.loads(
    (ROOT / "libs/sdk/tests/fixtures/execute-results.json").read_text()
)
SOURCES = dict(
    zip(
        EXAMPLES,
        [
            "latex@1",
            "mathml@1",
            "verbalized@1",
            "page-judgement@1",
            "region-transcription@1",
            "pdf-validation-report@1",
            "media-inspection@1",
            "image@2",
            "text-spans@1",
        ],
    )
)


def accepted(model, value):
    try:
        results.read_result(value, model)
    except ToolboxContractViolation:
        return False
    return True


@pytest.mark.parametrize("name", EXAMPLES)
def test_published_examples_and_required_fields(name):
    schema = json.loads(
        (ROOT / f"tests/fixtures/toolbox-schemas/{SOURCES[name]}.json").read_text()
    )
    validator = jsonschema.validators.validator_for(schema)(schema)
    model = getattr(results, name)
    good = EXAMPLES[name]
    assert validator.is_valid(good)
    assert model.from_dict(good).to_dict() == good
    for key in schema["required"]:
        missing = {k: v for k, v in good.items() if k != key}
        assert accepted(model, missing) is validator.is_valid(missing) is False
    for bad in (None, [], True, 1, "object"):
        assert accepted(model, bad) is validator.is_valid(bad) is False


@pytest.mark.parametrize(
    "name,path,values",
    [
        (
            "LatexResult",
            ["bbox"],
            [[0, 1, 2], [0, 1, 2, 3, 4], [0, True, 2, 3], [0, 1, 2, 3]],
        ),
        ("LatexResult", ["confidence"], [-0.1, 0, 1, 1.1, True, "0.5", None]),
        ("PageJudgement", ["pB"], [0, 1, -1, 2, True, "0.8", None]),
        (
            "MediaInspection",
            ["dimensions"],
            [
                None,
                {},
                {"width": 1, "height": 2, "aspect_ratio": 0},
                {"width": 1.0, "height": 2, "aspect_ratio": 0.5},
            ],
        ),
        ("MediaInspection", ["page_count"], [0, 1.0, 1.5, True, False, None]),
        ("MediaInspection", ["page_count_source"], ["pillow", "other", None]),
        ("RenderedPageMetadata", ["clip", "left"], [None, False, "0", 0.0]),
        ("RenderedPageMetadata", ["media_type"], ["image/jpeg", "image/png", None]),
        ("RenderedPageMetadata", ["scale"], [0, -1, 0.1, True]),
        ("TextSpansResult", ["pages", 0, "rotation"], [90, 180, 45, True]),
        (
            "TextSpansResult",
            ["pages", 0, "lines", 0, "spans", 0, "origin"],
            [[0], [0, 1], [0, 1, 2], [False, 1]],
        ),
        (
            "PdfValidationReport",
            ["validator"],
            [
                {},
                {"name": "veraPDF", "version": 1},
                {"name": "veraPDF", "version": "1"},
            ],
        ),
        (
            "PdfValidationReport",
            ["failures", 0, "checks", 0, "message"],
            ["", None, False],
        ),
    ],
)
def test_nested_constraints_agree_with_published_schema(name, path, values):
    schema = json.loads(
        (ROOT / f"tests/fixtures/toolbox-schemas/{SOURCES[name]}.json").read_text()
    )
    validator = jsonschema.validators.validator_for(schema)(schema)
    for value in values:
        document = copy.deepcopy(EXAMPLES[name])
        target = document
        for part in path[:-1]:
            target = target[part]
        target[path[-1]] = value
        assert accepted(getattr(results, name), document) is validator.is_valid(
            document
        ), (path, value)


def compiler():
    spec = importlib.util.spec_from_file_location(
        "compiler", ROOT / "scripts/sdk_result_compiler.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "change",
    [
        {"oneOf": [{"type": "string"}]},
        {"allOf": []},
        {"not": {}},
        {"if": {}, "then": {}},
        {"format": "date-time"},
        {"uniqueItems": True},
        {"unevaluatedProperties": False},
        {"$ref": "https://example.com/schema"},
        {"$ref": "#/definitions/missing"},
        {
            "$ref": "#/definitions/loop",
            "definitions": {"loop": {"$ref": "#/definitions/loop"}},
        },
    ],
)
def test_unsupported_constraints_and_bad_references_fail_explicitly(change):
    module = compiler()
    with pytest.raises(module.SchemaError):
        module.Compiler().compile({"type": "object", **change}, "Test")


def test_published_layout_union_is_not_flattened():
    module = compiler()
    schema = json.loads(
        (ROOT / "tests/fixtures/toolbox-schemas/layout-analysis@1.json").read_text()
    )
    with pytest.raises(module.SchemaError, match="anyOf"):
        module.Compiler().compile(schema, "Layout")
