"""The selected dataset REST bindings and their precise published routes."""

import json
from pathlib import Path

RECORDS = {
    "dataset-artifact@1": "DatasetArtifactRef",
    "dataset-info@1": "DatasetInfo",
    "dataset-split@1": "SplitInfo",
    "dataset-item-summary@1": "ItemSummary",
    "dataset-item@1": "DatasetItem",
    "dataset-sync-entry@1": "DatasetSyncEntry",
}
COLLECTIONS = {
    "dataset-list@1": "read_dataset_list",
    "dataset-splits@1": "read_dataset_splits",
    "dataset-item-summary-list@1": "read_item_summaries",
    "dataset-sample@1": "read_dataset_sample",
    "dataset-sync-report@1": "read_sync_report",
}
# SDK-owned selection, not a catalogue-wide compiler. Exact route responses
# take precedence over the shared dataset-item-list execute family.
ROUTES = [
    ("GET", "/v1/datasets", "dataset.list", "dataset-list@1"),
    ("GET", "/v1/datasets/{dataset_id}", "dataset.describe", "dataset-info@1"),
    (
        "GET",
        "/v1/datasets/{dataset_id}/splits",
        "dataset.list_splits",
        "dataset-splits@1",
    ),
    (
        "GET",
        "/v1/datasets/{dataset_id}/splits/{split}/items",
        "dataset.list_items",
        "dataset-item-summary-list@1",
    ),
    (
        "GET",
        "/v1/datasets/{dataset_id}/splits/{split}/items/{item_id}",
        "dataset.get_item",
        "dataset-item@1",
    ),
    (
        "GET",
        "/v1/datasets/{dataset_id}/splits/{split}/items/{item_id}/artifacts/{path}",
        "dataset.get_artifact",
        "binary@1",
    ),
    (
        "GET",
        "/v1/datasets/{dataset_id}/splits/{split}/sample",
        "dataset.sample",
        "dataset-sample@1",
    ),
    ("POST", "/v1/datasets/{dataset_id}/sync", "dataset.sync", "dataset-sync-report@1"),
]


def render_datasets(factory, directory: Path, contract: dict) -> str:
    published = contract.get("dataset_routes", [])
    for method, path, capability, schema in ROUTES:
        matches = [
            r for r in published if r.get("method") == method and r.get("path") == path
        ]
        if len(matches) != 1 or matches[0] != dict(
            method=method,
            path=path,
            capability=capability,
            output_schema="artifact/" + schema,
            capability_version=1,
        ):
            raise ValueError(f"dataset route binding changed: {method} {path}")
    compiler = factory()
    aliases = {name: name for name in RECORDS.values()}
    for schema, name in {**RECORDS, **COLLECTIONS}.items():
        payload = json.loads((directory / f"{schema}.json").read_text())
        compiler.compile(
            payload,
            name,
            reference_models=aliases,
            status_discriminator=schema
            in ("dataset-sync-entry@1", "dataset-sync-report@1"),
        )
    # Capture-only execute union: cross-check embedded record sources without
    # generating a union reader for the dedicated REST endpoints.
    shared = json.loads((directory / "dataset-item-list@1.json").read_text())
    if shared.get("type") != "array" or shared.get("items") != {
        "anyOf": [
            {"$ref": "#/definitions/ItemSummary"},
            {"$ref": "#/definitions/DatasetItem"},
        ]
    }:
        raise ValueError(
            "the shared dataset execute family changed; review REST selection"
        )
    for definition in ("ItemSummary", "DatasetArtifactRef", "DatasetItem"):
        compiler._node({"$ref": f"#/definitions/{definition}"}, shared, definition, ())
    return compiler.render(
        "selected dataset REST schemas; scripts/generate_sdk_bindings.py"
    )
