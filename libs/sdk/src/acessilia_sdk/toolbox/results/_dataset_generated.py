"""Generated from selected dataset REST schemas; scripts/generate_sdk_bindings.py; do not edit by hand."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from acessilia_sdk.toolbox.results._model import ResultModel, decode


@dataclass(frozen=True)
class DatasetArtifactRef(ResultModel):
    path: str
    media_type: str | None = None
    size: int | None = None
    sha256: str | None = None
    mirrored: bool | None = None
    artifact_id: str | None = None


@dataclass(frozen=True)
class DatasetInfo(ResultModel):
    id: str
    name: str
    source: str
    source_type: str
    description: str | None = None
    default_revision: str | None = None
    revisions: list[str] | None = None
    splits: list[str] | None = None
    item_count: int | None = None
    license: str | None = None
    citation: str | None = None


@dataclass(frozen=True)
class SplitInfo(ResultModel):
    id: str
    item_count: int
    has_ground_truth: bool
    name: str | None = None
    description: str | None = None
    artifact_types: list[str] | None = None


@dataclass(frozen=True)
class ItemSummary(ResultModel):
    id: str
    artifact_count: int
    has_annotations: bool
    dataset: str | None = None
    split: str | None = None
    revision: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class DatasetItem(ResultModel):
    id: str
    dataset: str | None = None
    split: str | None = None
    revision: str | None = None
    artifacts: list[DatasetArtifactRef] | None = None
    annotations: list[DatasetArtifactRef] | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class DatasetSyncEntry(ResultModel):
    status: str
    item: str | None = None
    split: str | None = None
    artifact: str | None = None
    reason: str | None = None


_MODELS = {'DatasetArtifactRef': DatasetArtifactRef, 'DatasetInfo': DatasetInfo, 'SplitInfo': SplitInfo, 'ItemSummary': ItemSummary, 'DatasetItem': DatasetItem, 'DatasetSyncEntry': DatasetSyncEntry}

DatasetArtifactRef._rule = {'type': ['object'], 'properties': {'path': {'type': ['string'], 'minLength': 1}, 'media_type': {'type': ['string']}, 'size': {'type': ['integer'], 'minimum': 0}, 'sha256': {'type': ['string', 'null']}, 'mirrored': {'type': ['boolean']}, 'artifact_id': {'type': ['string', 'null']}}, 'required': ['path'], 'model': 'DatasetArtifactRef'}
DatasetArtifactRef._models = _MODELS
DatasetInfo._rule = {'type': ['object'], 'properties': {'id': {'type': ['string'], 'minLength': 1}, 'name': {'type': ['string'], 'minLength': 1}, 'description': {'type': ['string']}, 'source': {'type': ['string'], 'minLength': 1}, 'source_type': {'type': ['string'], 'enum': ['github', 'huggingface']}, 'default_revision': {'type': ['string']}, 'revisions': {'type': ['array'], 'items': {'type': ['string']}}, 'splits': {'type': ['array'], 'items': {'type': ['string']}}, 'item_count': {'type': ['integer', 'null'], 'minimum': 0}, 'license': {'type': ['string', 'null']}, 'citation': {'type': ['string', 'null']}}, 'required': ['id', 'name', 'source', 'source_type'], 'model': 'DatasetInfo'}
DatasetInfo._models = _MODELS
SplitInfo._rule = {'type': ['object'], 'properties': {'id': {'type': ['string'], 'minLength': 1}, 'name': {'type': ['string']}, 'description': {'type': ['string']}, 'item_count': {'type': ['integer'], 'minimum': 0}, 'has_ground_truth': {'type': ['boolean']}, 'artifact_types': {'type': ['array'], 'items': {'type': ['string']}}}, 'required': ['id', 'item_count', 'has_ground_truth'], 'model': 'SplitInfo'}
SplitInfo._models = _MODELS
ItemSummary._rule = {'type': ['object'], 'properties': {'id': {'type': ['string'], 'minLength': 1}, 'dataset': {'type': ['string']}, 'split': {'type': ['string']}, 'revision': {'type': ['string']}, 'artifact_count': {'type': ['integer'], 'minimum': 0}, 'has_annotations': {'type': ['boolean']}, 'metadata': {'type': ['object'], 'properties': {}}}, 'required': ['id', 'artifact_count', 'has_annotations'], 'model': 'ItemSummary'}
ItemSummary._models = _MODELS
DatasetItem._rule = {'type': ['object'], 'properties': {'id': {'type': ['string'], 'minLength': 1}, 'dataset': {'type': ['string']}, 'split': {'type': ['string']}, 'revision': {'type': ['string']}, 'artifacts': {'type': ['array'], 'items': {'type': ['object'], 'properties': {'path': {'type': ['string'], 'minLength': 1}, 'media_type': {'type': ['string']}, 'size': {'type': ['integer'], 'minimum': 0}, 'sha256': {'type': ['string', 'null']}, 'mirrored': {'type': ['boolean']}, 'artifact_id': {'type': ['string', 'null']}}, 'required': ['path'], 'model': 'DatasetArtifactRef'}}, 'annotations': {'type': ['array'], 'items': {'type': ['object'], 'properties': {'path': {'type': ['string'], 'minLength': 1}, 'media_type': {'type': ['string']}, 'size': {'type': ['integer'], 'minimum': 0}, 'sha256': {'type': ['string', 'null']}, 'mirrored': {'type': ['boolean']}, 'artifact_id': {'type': ['string', 'null']}}, 'required': ['path'], 'model': 'DatasetArtifactRef'}}, 'metadata': {'type': ['object'], 'properties': {}}}, 'required': ['id'], 'model': 'DatasetItem'}
DatasetItem._models = _MODELS
DatasetSyncEntry._rule = {'type': ['object'], 'properties': {'status': {'type': ['string'], 'enum': ['mirrored', 'skipped']}, 'item': {'type': ['string']}, 'split': {'type': ['string']}, 'artifact': {'type': ['string']}, 'reason': {'type': ['string']}}, 'required': ['status'], 'status_required': {'mirrored': ['item', 'split', 'artifact'], 'skipped': ['reason']}, 'model': 'DatasetSyncEntry'}
DatasetSyncEntry._models = _MODELS


def _read(data: Any, rule: dict, name: str) -> Any:
    return decode(data, rule, _MODELS, name)


_READ_DATASET_LIST_RULE = {'type': ['array'], 'items': {'type': ['object'], 'properties': {'id': {'type': ['string'], 'minLength': 1}, 'name': {'type': ['string'], 'minLength': 1}, 'description': {'type': ['string']}, 'source': {'type': ['string'], 'minLength': 1}, 'source_type': {'type': ['string'], 'enum': ['github', 'huggingface']}, 'default_revision': {'type': ['string']}, 'revisions': {'type': ['array'], 'items': {'type': ['string']}}, 'splits': {'type': ['array'], 'items': {'type': ['string']}}, 'item_count': {'type': ['integer', 'null'], 'minimum': 0}, 'license': {'type': ['string', 'null']}, 'citation': {'type': ['string', 'null']}}, 'required': ['id', 'name', 'source', 'source_type'], 'model': 'DatasetInfo'}}

def read_dataset_list(data: Any) -> list[DatasetInfo]:
    return _read(data, _READ_DATASET_LIST_RULE, 'read_dataset_list')

_READ_DATASET_SPLITS_RULE = {'type': ['array'], 'items': {'type': ['object'], 'properties': {'id': {'type': ['string'], 'minLength': 1}, 'name': {'type': ['string']}, 'description': {'type': ['string']}, 'item_count': {'type': ['integer'], 'minimum': 0}, 'has_ground_truth': {'type': ['boolean']}, 'artifact_types': {'type': ['array'], 'items': {'type': ['string']}}}, 'required': ['id', 'item_count', 'has_ground_truth'], 'model': 'SplitInfo'}}

def read_dataset_splits(data: Any) -> list[SplitInfo]:
    return _read(data, _READ_DATASET_SPLITS_RULE, 'read_dataset_splits')

_READ_ITEM_SUMMARIES_RULE = {'type': ['array'], 'items': {'type': ['object'], 'properties': {'id': {'type': ['string'], 'minLength': 1}, 'dataset': {'type': ['string']}, 'split': {'type': ['string']}, 'revision': {'type': ['string']}, 'artifact_count': {'type': ['integer'], 'minimum': 0}, 'has_annotations': {'type': ['boolean']}, 'metadata': {'type': ['object'], 'properties': {}}}, 'required': ['id', 'artifact_count', 'has_annotations'], 'model': 'ItemSummary'}}

def read_item_summaries(data: Any) -> list[ItemSummary]:
    return _read(data, _READ_ITEM_SUMMARIES_RULE, 'read_item_summaries')

_READ_DATASET_SAMPLE_RULE = {'type': ['array'], 'items': {'type': ['object'], 'properties': {'id': {'type': ['string'], 'minLength': 1}, 'dataset': {'type': ['string']}, 'split': {'type': ['string']}, 'revision': {'type': ['string']}, 'artifacts': {'type': ['array'], 'items': {'type': ['object'], 'properties': {'path': {'type': ['string'], 'minLength': 1}, 'media_type': {'type': ['string']}, 'size': {'type': ['integer'], 'minimum': 0}, 'sha256': {'type': ['string', 'null']}, 'mirrored': {'type': ['boolean']}, 'artifact_id': {'type': ['string', 'null']}}, 'required': ['path'], 'model': 'DatasetArtifactRef'}}, 'annotations': {'type': ['array'], 'items': {'type': ['object'], 'properties': {'path': {'type': ['string'], 'minLength': 1}, 'media_type': {'type': ['string']}, 'size': {'type': ['integer'], 'minimum': 0}, 'sha256': {'type': ['string', 'null']}, 'mirrored': {'type': ['boolean']}, 'artifact_id': {'type': ['string', 'null']}}, 'required': ['path'], 'model': 'DatasetArtifactRef'}}, 'metadata': {'type': ['object'], 'properties': {}}}, 'required': ['id'], 'model': 'DatasetItem'}}

def read_dataset_sample(data: Any) -> list[DatasetItem]:
    return _read(data, _READ_DATASET_SAMPLE_RULE, 'read_dataset_sample')

_READ_SYNC_REPORT_RULE = {'type': ['array'], 'items': {'type': ['object'], 'properties': {'status': {'type': ['string'], 'enum': ['mirrored', 'skipped']}, 'item': {'type': ['string']}, 'split': {'type': ['string']}, 'artifact': {'type': ['string']}, 'reason': {'type': ['string']}}, 'required': ['status'], 'status_required': {'mirrored': ['item', 'split', 'artifact'], 'skipped': ['reason']}, 'model': 'DatasetSyncEntry'}}

def read_sync_report(data: Any) -> list[DatasetSyncEntry]:
    return _read(data, _READ_SYNC_REPORT_RULE, 'read_sync_report')


__all__ = ['DatasetArtifactRef', 'DatasetInfo', 'SplitInfo', 'ItemSummary', 'DatasetItem', 'DatasetSyncEntry', 'read_dataset_list', 'read_dataset_splits', 'read_item_summaries', 'read_dataset_sample', 'read_sync_report']
