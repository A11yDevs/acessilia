"""Public readers for precise dataset REST responses (no execute envelope)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from acessilia_sdk.toolbox.errors import ToolboxContractViolation
from acessilia_sdk.toolbox.results import _dataset_generated as generated
from acessilia_sdk.toolbox.results._dataset_generated import (
    DatasetArtifactRef,
    DatasetInfo,
    DatasetItem,
    DatasetSyncEntry,
    ItemSummary,
    SplitInfo,
)

T = TypeVar("T")


def _read(data: Any, reader: Callable[[Any], T]) -> T:
    try:
        return reader(data)
    except ValueError as exc:
        raise ToolboxContractViolation(str(exc)) from exc


def read_dataset_list(data: Any) -> list[DatasetInfo]:
    return _read(data, generated.read_dataset_list)


def read_dataset_info(data: Any) -> DatasetInfo:
    return _read(data, DatasetInfo.from_dict)


def read_dataset_splits(data: Any) -> list[SplitInfo]:
    return _read(data, generated.read_dataset_splits)


def read_item_summaries(data: Any) -> list[ItemSummary]:
    return _read(data, generated.read_item_summaries)


def read_dataset_item(data: Any) -> DatasetItem:
    return _read(data, DatasetItem.from_dict)


def read_dataset_sample(data: Any) -> list[DatasetItem]:
    return _read(data, generated.read_dataset_sample)


def read_sync_report(data: Any) -> list[DatasetSyncEntry]:
    return _read(data, generated.read_sync_report)


__all__ = [
    "DatasetArtifactRef",
    "DatasetInfo",
    "SplitInfo",
    "ItemSummary",
    "DatasetItem",
    "DatasetSyncEntry",
    "read_dataset_list",
    "read_dataset_info",
    "read_dataset_splits",
    "read_item_summaries",
    "read_dataset_item",
    "read_dataset_sample",
    "read_sync_report",
]
