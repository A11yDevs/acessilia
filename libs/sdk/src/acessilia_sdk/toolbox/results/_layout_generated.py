"""Generated from layout-analysis@1.json; scripts/generate_sdk_bindings.py; do not edit by hand."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from acessilia_sdk.toolbox.results._model import ResultModel


@dataclass(frozen=True)
class LayoutPagesPagesItemRegionsItem(ResultModel):
    type: str
    label: str
    bbox: list[float]
    confidence: float | None
    text: str | None
    page_number: int


@dataclass(frozen=True)
class LayoutPagesPagesItem(ResultModel):
    page_number: int
    width: float
    height: float
    regions: list[LayoutPagesPagesItemRegionsItem]


@dataclass(frozen=True)
class LayoutPages(ResultModel):
    pages: list[LayoutPagesPagesItem]
    page_count: int
    region_count: int


@dataclass(frozen=True)
class MineruLayoutConfigurationLayoutRegionsItem(ResultModel):
    type: str
    source_label: str
    raw_label: str
    page: int
    bbox: dict[str, Any]
    text_preview: str | None


@dataclass(frozen=True)
class MineruLayoutConfiguration(ResultModel):
    layout_regions: list[MineruLayoutConfigurationLayoutRegionsItem]
    region_count: int
    backend: str


_MODELS = {'LayoutPagesPagesItemRegionsItem': LayoutPagesPagesItemRegionsItem, 'LayoutPagesPagesItem': LayoutPagesPagesItem, 'LayoutPages': LayoutPages, 'MineruLayoutConfigurationLayoutRegionsItem': MineruLayoutConfigurationLayoutRegionsItem, 'MineruLayoutConfiguration': MineruLayoutConfiguration}

LayoutPagesPagesItemRegionsItem._rule = {'type': ['object'], 'properties': {'type': {'type': ['string'], 'enum': ['text_clean', 'text_scanned', 'embedded_image', 'table', 'formula', 'code_block', 'list_block', 'callout_box', 'unknown', 'ignore']}, 'label': {'type': ['string']}, 'bbox': {'type': ['array'], 'items': {'type': ['number']}, 'minItems': 4, 'maxItems': 4}, 'confidence': {'type': ['number', 'null'], 'minimum': 0, 'maximum': 1}, 'text': {'type': ['string', 'null']}, 'page_number': {'type': ['integer'], 'minimum': 1}}, 'required': ['type', 'label', 'bbox', 'confidence', 'text', 'page_number'], 'model': 'LayoutPagesPagesItemRegionsItem'}
LayoutPagesPagesItemRegionsItem._models = _MODELS
LayoutPagesPagesItem._rule = {'type': ['object'], 'properties': {'page_number': {'type': ['integer'], 'minimum': 1}, 'width': {'type': ['number'], 'minimum': 0}, 'height': {'type': ['number'], 'minimum': 0}, 'regions': {'type': ['array'], 'items': {'type': ['object'], 'properties': {'type': {'type': ['string'], 'enum': ['text_clean', 'text_scanned', 'embedded_image', 'table', 'formula', 'code_block', 'list_block', 'callout_box', 'unknown', 'ignore']}, 'label': {'type': ['string']}, 'bbox': {'type': ['array'], 'items': {'type': ['number']}, 'minItems': 4, 'maxItems': 4}, 'confidence': {'type': ['number', 'null'], 'minimum': 0, 'maximum': 1}, 'text': {'type': ['string', 'null']}, 'page_number': {'type': ['integer'], 'minimum': 1}}, 'required': ['type', 'label', 'bbox', 'confidence', 'text', 'page_number'], 'model': 'LayoutPagesPagesItemRegionsItem'}}}, 'required': ['page_number', 'width', 'height', 'regions'], 'model': 'LayoutPagesPagesItem'}
LayoutPagesPagesItem._models = _MODELS
LayoutPages._rule = {'type': ['object'], 'properties': {'pages': {'type': ['array'], 'items': {'type': ['object'], 'properties': {'page_number': {'type': ['integer'], 'minimum': 1}, 'width': {'type': ['number'], 'minimum': 0}, 'height': {'type': ['number'], 'minimum': 0}, 'regions': {'type': ['array'], 'items': {'type': ['object'], 'properties': {'type': {'type': ['string'], 'enum': ['text_clean', 'text_scanned', 'embedded_image', 'table', 'formula', 'code_block', 'list_block', 'callout_box', 'unknown', 'ignore']}, 'label': {'type': ['string']}, 'bbox': {'type': ['array'], 'items': {'type': ['number']}, 'minItems': 4, 'maxItems': 4}, 'confidence': {'type': ['number', 'null'], 'minimum': 0, 'maximum': 1}, 'text': {'type': ['string', 'null']}, 'page_number': {'type': ['integer'], 'minimum': 1}}, 'required': ['type', 'label', 'bbox', 'confidence', 'text', 'page_number'], 'model': 'LayoutPagesPagesItemRegionsItem'}}}, 'required': ['page_number', 'width', 'height', 'regions'], 'model': 'LayoutPagesPagesItem'}}, 'page_count': {'type': ['integer'], 'minimum': 0}, 'region_count': {'type': ['integer'], 'minimum': 0}}, 'required': ['pages', 'page_count', 'region_count'], 'model': 'LayoutPages'}
LayoutPages._models = _MODELS
MineruLayoutConfigurationLayoutRegionsItem._rule = {'type': ['object'], 'properties': {'type': {'type': ['string'], 'enum': ['text', 'title', 'list_block', 'table', 'embedded_image', 'formula', 'ignore', 'unknown']}, 'source_label': {'type': ['string']}, 'raw_label': {'type': ['string']}, 'page': {'type': ['integer'], 'minimum': 0}, 'bbox': {'type': ['object'], 'properties': {'left': {'type': ['number']}, 'top': {'type': ['number']}, 'right': {'type': ['number']}, 'bottom': {'type': ['number']}}, 'required': ['left', 'top', 'right', 'bottom']}, 'text_preview': {'type': ['string', 'null'], 'maxLength': 120}}, 'required': ['type', 'source_label', 'raw_label', 'page', 'bbox', 'text_preview'], 'model': 'MineruLayoutConfigurationLayoutRegionsItem'}
MineruLayoutConfigurationLayoutRegionsItem._models = _MODELS
MineruLayoutConfiguration._rule = {'type': ['object'], 'properties': {'layout_regions': {'type': ['array'], 'items': {'type': ['object'], 'properties': {'type': {'type': ['string'], 'enum': ['text', 'title', 'list_block', 'table', 'embedded_image', 'formula', 'ignore', 'unknown']}, 'source_label': {'type': ['string']}, 'raw_label': {'type': ['string']}, 'page': {'type': ['integer'], 'minimum': 0}, 'bbox': {'type': ['object'], 'properties': {'left': {'type': ['number']}, 'top': {'type': ['number']}, 'right': {'type': ['number']}, 'bottom': {'type': ['number']}}, 'required': ['left', 'top', 'right', 'bottom']}, 'text_preview': {'type': ['string', 'null'], 'maxLength': 120}}, 'required': ['type', 'source_label', 'raw_label', 'page', 'bbox', 'text_preview'], 'model': 'MineruLayoutConfigurationLayoutRegionsItem'}}, 'region_count': {'type': ['integer'], 'minimum': 0}, 'backend': {'const': 'mineru-layout', 'type': ['string']}}, 'required': ['layout_regions', 'region_count', 'backend'], 'model': 'MineruLayoutConfiguration'}
MineruLayoutConfiguration._models = _MODELS

__all__ = ['LayoutPages', 'MineruLayoutConfiguration']

MANIFEST_RULE = {'additionalProperties': False, 'properties': {'$schema': {'type': ['string']}, 'schema_version': {'const': '1.1.0', 'type': ['string']}, 'manifest_id': {'minLength': 1, 'type': ['string']}, 'revision': {'minimum': 1, 'type': ['integer']}, 'status': {'enum': ['extracted', 'planned', 'processing', 'completed', 'failed'], 'type': ['string']}, 'created_at': {'type': ['string']}, 'source': {'additionalProperties': False, 'properties': {'document_id': {'minLength': 1, 'type': ['string']}, 'filename': {'minLength': 1, 'type': ['string']}, 'path': {'minLength': 1, 'type': ['string']}, 'media_type': {'minLength': 1, 'type': ['string']}, 'byte_size': {'minimum': 0, 'type': ['integer']}, 'sha256': {'pattern': '^[a-f0-9]{64}$', 'type': ['string']}}, 'required': ['document_id', 'filename', 'path', 'media_type', 'byte_size', 'sha256'], 'type': ['object']}, 'extractor': {'additionalProperties': False, 'properties': {'name': {'minLength': 1, 'type': ['string']}, 'version': {'minLength': 1, 'type': ['string']}, 'started_at': {'type': ['string']}, 'completed_at': {'type': ['string']}, 'duration_ms': {'minimum': 0, 'type': ['integer']}, 'configuration': {'additionalProperties': True, 'type': ['object'], 'properties': {}}}, 'required': ['version', 'started_at', 'completed_at', 'duration_ms'], 'type': ['object']}, 'title': {'minLength': 1, 'type': ['string']}, 'language': {'minLength': 2, 'type': ['string']}, 'pages': {'items': {'additionalProperties': False, 'properties': {'page_number': {'minimum': 1, 'type': ['integer']}, 'width': {'exclusiveMinimum': 0, 'type': ['number', 'null']}, 'height': {'exclusiveMinimum': 0, 'type': ['number', 'null']}, 'element_ids': {'items': {'type': ['string']}, 'type': ['array']}}, 'required': ['page_number'], 'type': ['object']}, 'type': ['array']}, 'elements': {'items': {'additionalProperties': False, 'properties': {'id': {'minLength': 1, 'type': ['string']}, 'type': {'enum': ['title', 'heading', 'paragraph', 'list_item', 'table', 'picture', 'formula', 'code', 'caption', 'footnote', 'page_header', 'page_footer', 'checkbox', 'key_value', 'form', 'group', 'unknown'], 'type': ['string']}, 'raw_label': {'minLength': 1, 'type': ['string']}, 'reading_order': {'minimum': 1, 'type': ['integer']}, 'hierarchy_level': {'minimum': 0, 'type': ['integer']}, 'text': {'type': ['string', 'null']}, 'source_ref': {'type': ['string', 'null']}, 'parent_ref': {'type': ['string', 'null']}, 'parent_id': {'type': ['string', 'null']}, 'page_number': {'minimum': 1, 'type': ['integer', 'null']}, 'confidence': {'maximum': 1, 'minimum': 0, 'type': ['number', 'null']}, 'provenance': {'items': {'additionalProperties': False, 'properties': {'page_number': {'minimum': 1, 'type': ['integer']}, 'bbox': {'additionalProperties': False, 'properties': {'left': {'type': ['number']}, 'top': {'type': ['number']}, 'right': {'type': ['number']}, 'bottom': {'type': ['number']}, 'coord_origin': {'enum': ['TOPLEFT', 'BOTTOMLEFT', 'UNKNOWN'], 'type': ['string']}}, 'required': ['left', 'top', 'right', 'bottom'], 'type': ['object', 'null']}, 'char_start': {'minimum': 0, 'type': ['integer', 'null']}, 'char_end': {'minimum': 0, 'type': ['integer', 'null']}}, 'required': ['page_number'], 'type': ['object']}, 'type': ['array']}, 'metadata': {'additionalProperties': True, 'type': ['object'], 'properties': {}}}, 'required': ['id', 'type', 'raw_label', 'reading_order', 'hierarchy_level'], 'type': ['object']}, 'type': ['array']}, 'observations': {'items': {'additionalProperties': False, 'properties': {'id': {'minLength': 1, 'type': ['string']}, 'kind': {'minLength': 1, 'type': ['string']}, 'severity': {'enum': ['info', 'warning', 'error'], 'type': ['string']}, 'message': {'minLength': 1, 'type': ['string']}, 'target_ids': {'items': {'type': ['string']}, 'type': ['array']}, 'evidence': {'additionalProperties': True, 'type': ['object'], 'properties': {}}}, 'required': ['id', 'kind', 'severity', 'message'], 'type': ['object']}, 'type': ['array']}, 'obligations': {'items': {'additionalProperties': False, 'properties': {'id': {'minLength': 1, 'type': ['string']}, 'kind': {'minLength': 1, 'type': ['string']}, 'status': {'enum': ['candidate', 'pending', 'in_progress', 'satisfied', 'failed'], 'type': ['string']}, 'selected': {'type': ['boolean']}, 'target_ids': {'items': {'type': ['string']}, 'minItems': 1, 'type': ['array']}, 'dependencies': {'items': {'type': ['string']}, 'type': ['array']}, 'admissible_methods': {'items': {'type': ['string']}, 'type': ['array']}, 'method_costs': {'additionalProperties': {'type': ['integer']}, 'type': ['object'], 'properties': {}}, 'attempts': {'items': {'additionalProperties': False, 'properties': {'method': {'minLength': 1, 'type': ['string']}, 'status': {'enum': ['succeeded', 'failed', 'rejected'], 'type': ['string']}, 'started_at': {'type': ['string']}, 'completed_at': {'type': ['string']}, 'message': {'type': ['string', 'null']}, 'artifact_ids': {'items': {'type': ['string']}, 'type': ['array']}}, 'required': ['method', 'status', 'started_at', 'completed_at'], 'type': ['object']}, 'type': ['array']}, 'rationale': {'minLength': 1, 'type': ['string']}}, 'required': ['id', 'kind', 'target_ids', 'rationale'], 'type': ['object']}, 'type': ['array']}, 'artifacts': {'items': {'additionalProperties': False, 'properties': {'id': {'minLength': 1, 'type': ['string']}, 'kind': {'minLength': 1, 'type': ['string']}, 'path': {'minLength': 1, 'type': ['string']}, 'media_type': {'minLength': 1, 'type': ['string']}, 'sha256': {'pattern': '^[a-f0-9]{64}$', 'type': ['string', 'null']}}, 'required': ['id', 'kind', 'path', 'media_type'], 'type': ['object']}, 'type': ['array']}, 'summary': {'additionalProperties': False, 'properties': {'page_count': {'minimum': 0, 'type': ['integer']}, 'element_count': {'minimum': 0, 'type': ['integer']}, 'observation_count': {'minimum': 0, 'type': ['integer']}, 'obligation_count': {'minimum': 0, 'type': ['integer']}, 'element_types': {'additionalProperties': {'type': ['integer']}, 'type': ['object'], 'properties': {}}}, 'required': ['page_count', 'element_count', 'observation_count', 'obligation_count'], 'type': ['object']}}, 'required': ['manifest_id', 'created_at', 'source', 'extractor', 'title', 'language', 'pages', 'elements', 'summary'], 'type': ['object']}
