"""REST readers follow precise published array schemas and shared record sources."""

import copy
import importlib.util
import json
from pathlib import Path

import jsonschema
import pytest
from acessilia_sdk.toolbox.results import datasets
from acessilia_sdk.toolbox.errors import ToolboxContractViolation

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "tests/fixtures/toolbox-schemas"
EXAMPLES = json.loads(
    (ROOT / "libs/sdk/tests/fixtures/dataset-results.json").read_text()
)
RECORDS = dict(
    zip(
        EXAMPLES,
        [
            "dataset-info@1",
            "dataset-split@1",
            "dataset-item-summary@1",
            "dataset-artifact@1",
            "dataset-item@1",
            "dataset-sync-entry@1",
        ],
    )
)
COLLECTIONS = [
    ("dataset-list@1", "read_dataset_list", "DatasetInfo"),
    ("dataset-splits@1", "read_dataset_splits", "SplitInfo"),
    ("dataset-item-summary-list@1", "read_item_summaries", "ItemSummary"),
    ("dataset-sample@1", "read_dataset_sample", "DatasetItem"),
    ("dataset-sync-report@1", "read_sync_report", "DatasetSyncEntry"),
]


def validator(source):
    schema = json.loads((SCHEMAS / f"{source}.json").read_text())
    return jsonschema.Draft7Validator(schema)


def accepted(reader, data):
    try:
        reader(data)
    except (ValueError, ToolboxContractViolation):
        return False
    return True


@pytest.mark.parametrize("name", RECORDS)
def test_each_record_matches_its_source_schema(name):
    model = getattr(datasets, name)
    check = validator(RECORDS[name])
    good = EXAMPLES[name]
    assert check.is_valid(good)
    assert model.from_dict(good).to_dict() == good
    for key in check.schema["required"]:
        changed = {k: v for k, v in good.items() if k != key}
        assert accepted(model.from_dict, changed) is check.is_valid(changed) is False
    for invalid in (None, [], True, "record"):
        assert accepted(model.from_dict, invalid) is check.is_valid(invalid) is False


@pytest.mark.parametrize("source,reader,model", COLLECTIONS)
def test_precise_array_roots_including_empty_and_invalid(source, reader, model):
    check = validator(source)
    read = getattr(datasets, reader)
    for data in ([], [EXAMPLES[model]], {}, None, False, [None], [{}]):
        assert accepted(read, data) is check.is_valid(data)
    assert read([]) == []
    assert isinstance(read([EXAMPLES[model]])[0], getattr(datasets, model))


@pytest.mark.parametrize(
    "name,field,values",
    [
        ("DatasetInfo", "item_count", [None, 0, 1.0, -1, True, "0"]),
        ("DatasetInfo", "license", [None, "MIT", False]),
        ("DatasetInfo", "source_type", ["github", "huggingface", "other"]),
        ("SplitInfo", "item_count", [0, 1.0, -1, True, "0"]),
        ("ItemSummary", "has_annotations", [True, False, None, 0, "false"]),
        ("DatasetArtifactRef", "size", [0, 1.0, -1, True, "0", None]),
        ("DatasetArtifactRef", "artifact_id", [None, "sha256:abc", False]),
        ("DatasetArtifactRef", "path", ["", "nested/file.pdf", None]),
        (
            "DatasetItem",
            "artifacts",
            [[{"path": "a"}], [{}], [{"path": "a", "size": True}], None],
        ),
        ("DatasetItem", "metadata", [{}, {"extension": [1, None, {}]}, None]),
    ],
)
def test_bounds_nullability_and_nested_values(name, field, values):
    check = validator(RECORDS[name])
    read = getattr(datasets, name).from_dict
    for value in values:
        data = {**EXAMPLES[name], field: value}
        assert accepted(read, data) is check.is_valid(data), (name, field, value)


@pytest.mark.parametrize(
    "data",
    [
        [],
        [{"status": "skipped", "reason": "mirroring disabled"}],
        [{"status": "skipped", "reason": "missing item", "item": "i", "split": "s"}],
        [
            {
                "status": "skipped",
                "reason": "missing artifact",
                "item": "i",
                "artifact": "a",
            }
        ],
        [EXAMPLES["DatasetSyncEntry"]],
        [{"status": "mirrored"}],
        [{"status": "skipped"}],
        [{"status": "unknown", "reason": "x"}],
        [{"status": False}],
        [{"status": []}],
        {"synced": 1},
        [{"status": "mirrored", "item": "i", "split": "s", "artifact": None}],
    ],
)
def test_sync_discriminator_agrees_with_whole_published_array(data):
    assert accepted(datasets.read_sync_report, data) is validator(
        "dataset-sync-report@1"
    ).is_valid(data)


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"scripts/{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_embedded_record_drift_is_rejected(tmp_path):
    generator = load_tool("generate_sdk_bindings")
    for path in SCHEMAS.glob("dataset-*.json"):
        (tmp_path / path.name).write_bytes(path.read_bytes())
    path = tmp_path / "dataset-list@1.json"
    schema = json.loads(path.read_text())
    schema["definitions"]["DatasetInfo"]["properties"]["name"]["minLength"] = 10
    path.write_text(json.dumps(schema))
    contract = json.loads((ROOT / "tests/fixtures/toolbox-contract.json").read_text())
    with pytest.raises(ValueError, match="embedded DatasetInfo disagrees"):
        load_tool("sdk_dataset_binding").render_datasets(
            generator.result_compiler, tmp_path, contract
        )


def test_route_schema_drift_does_not_fall_back_to_capability_union():
    generator = load_tool("generate_sdk_bindings")
    contract = json.loads((ROOT / "tests/fixtures/toolbox-contract.json").read_text())
    next(
        r for r in contract["dataset_routes"] if r["capability"] == "dataset.list_items"
    )["output_schema"] = "artifact/dataset-item-list@1"
    with pytest.raises(ValueError, match="dataset route binding changed"):
        load_tool("sdk_dataset_binding").render_datasets(
            generator.result_compiler, SCHEMAS, contract
        )


def test_extra_sync_branch_constraint_is_not_silently_ignored():
    generator = load_tool("generate_sdk_bindings")
    compiler = generator.result_compiler()
    schema = json.loads((SCHEMAS / "dataset-sync-entry@1.json").read_text())
    schema["anyOf"][0]["properties"]["item"] = {"minLength": 1}
    with pytest.raises(ValueError, match="unsupported sync status constraints"):
        compiler.compile(schema, "DatasetSyncEntry", status_discriminator=True)


def test_optional_sync_discriminator_is_not_compiled_as_required():
    generator = load_tool("generate_sdk_bindings")
    schema = json.loads((SCHEMAS / "dataset-sync-entry@1.json").read_text())
    schema["required"] = []
    with pytest.raises(ValueError, match="required object discriminator"):
        generator.result_compiler().compile(
            schema, "DatasetSyncEntry", status_discriminator=True
        )
