"""Check the adapter against the whole union, including its parent branches."""

import copy
import importlib.util
import json
from pathlib import Path

import jsonschema
import pytest
from acessilia_sdk.toolbox.errors import ToolboxContractViolation
from acessilia_sdk.toolbox.results.layout import read_layout

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads(
    (ROOT / "tests/fixtures/toolbox-schemas/layout-analysis@1.json").read_text()
)
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)


def example(variant):
    return json.loads(
        (ROOT / f"libs/sdk/tests/fixtures/{variant}-layout.json").read_text()
    )


def assert_agrees(document):
    valid = VALIDATOR.is_valid(document)
    try:
        read_layout(document)
    except ToolboxContractViolation:
        accepted = False
    else:
        accepted = True
    assert accepted is valid


@pytest.mark.parametrize("variant", ["docling", "mineru"])
def test_complete_required_fields_including_parent_constraints(variant):
    document = example(variant)
    assert VALIDATOR.is_valid(document)
    assert_agrees(document)
    root = SCHEMA["$defs"][
        "LayoutPages" if variant == "docling" else "ProcessingManifest"
    ]
    for key in root["required"]:
        changed = copy.deepcopy(document)
        del changed[key]
        assert_agrees(changed)
    if variant == "mineru":
        for key in SCHEMA["$defs"]["ExtractorRun"]["required"]:
            changed = copy.deepcopy(document)
            del changed["extractor"][key]
            assert_agrees(changed)
        for key in SCHEMA["$defs"]["MineruLayoutConfiguration"]["required"]:
            changed = copy.deepcopy(document)
            del changed["extractor"]["configuration"][key]
            assert_agrees(changed)


@pytest.mark.parametrize(
    "path,values",
    [
        (
            ["extractor", "configuration", "layout_regions", 0, "page"],
            [-1, 0, True, "0"],
        ),
        (
            ["extractor", "configuration", "layout_regions", 0, "text_preview"],
            [None, "x" * 120, "x" * 121, False],
        ),
        (
            ["extractor", "configuration", "layout_regions", 0, "bbox", "left"],
            [None, True, 0],
        ),
        (["extractor", "configuration", "backend"], ["mineru-layout", "other", None]),
        (["source", "sha256"], ["a" * 64, "wrong"]),
        (["pages", 0, "width"], [None, 0, 1, True]),
        (
            ["elements", 0, "provenance", 0, "bbox", "coord_origin"],
            ["TOPLEFT", "UNKNOWN", "other"],
        ),
    ],
)
def test_mineru_nested_constraints(path, values):
    for value in values:
        document = example("mineru")
        target = document
        for part in path[:-1]:
            target = target[part]
        target[path[-1]] = value
        assert_agrees(document)


@pytest.mark.parametrize(
    "field,values",
    [
        ("bbox", [[0, 1, 2], [0, 1, 2, 3], [0, True, 2, 3]]),
        ("confidence", [None, 0, 1, 1.1, True]),
        ("page_number", [0, 1, True]),
        ("type", ["table", "other"]),
    ],
)
def test_docling_nested_constraints(field, values):
    for value in values:
        document = example("docling")
        document["pages"][0]["regions"][0][field] = value
        assert_agrees(document)


def test_changed_parent_branch_cannot_be_silently_ignored(tmp_path):
    schema = copy.deepcopy(SCHEMA)
    schema["$defs"]["MineruLayoutResult"]["allOf"].append({"required": ["new_field"]})
    (tmp_path / "layout-analysis@1.json").write_text(json.dumps(schema))
    spec = importlib.util.spec_from_file_location(
        "layout_compiler", ROOT / "scripts/sdk_layout_binding.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(ValueError, match="containing constraints"):
        module.render_layout(None, tmp_path)
