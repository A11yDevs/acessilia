"""Generated from published text-normalization@1 schemas; scripts/generate_sdk_bindings.py; do not edit by hand."""
from __future__ import annotations

from dataclasses import dataclass

from acessilia_sdk.toolbox.results._model import ResultModel


@dataclass(frozen=True)
class TextNormalizationRequestTargetsItem(ResultModel):
    id: str
    text: str | None


@dataclass(frozen=True)
class TextNormalizationRequest(ResultModel):
    targets: list[TextNormalizationRequestTargetsItem]


@dataclass(frozen=True)
class TextNormalizationResultResultsItem(ResultModel):
    id: str
    text: str | None
    input_fingerprint: str
    processed: bool
    changed: bool


@dataclass(frozen=True)
class TextNormalizationResult(ResultModel):
    results: list[TextNormalizationResultResultsItem]
    processed_count: int
    changed_count: int


_MODELS = {'TextNormalizationRequestTargetsItem': TextNormalizationRequestTargetsItem, 'TextNormalizationRequest': TextNormalizationRequest, 'TextNormalizationResultResultsItem': TextNormalizationResultResultsItem, 'TextNormalizationResult': TextNormalizationResult}

TextNormalizationRequestTargetsItem._rule = {'additionalProperties': False, 'properties': {'id': {'maxLength': 256, 'minLength': 1, 'type': ['string']}, 'text': {'maxLength': 1048576, 'type': ['string', 'null']}}, 'required': ['id', 'text'], 'type': ['object'], 'model': 'TextNormalizationRequestTargetsItem'}
TextNormalizationRequestTargetsItem._models = _MODELS
TextNormalizationRequest._rule = {'additionalProperties': False, 'properties': {'targets': {'items': {'additionalProperties': False, 'properties': {'id': {'maxLength': 256, 'minLength': 1, 'type': ['string']}, 'text': {'maxLength': 1048576, 'type': ['string', 'null']}}, 'required': ['id', 'text'], 'type': ['object'], 'model': 'TextNormalizationRequestTargetsItem'}, 'maxItems': 256, 'type': ['array']}}, 'required': ['targets'], 'type': ['object'], 'model': 'TextNormalizationRequest'}
TextNormalizationRequest._models = _MODELS
TextNormalizationResultResultsItem._rule = {'additionalProperties': False, 'properties': {'id': {'maxLength': 256, 'minLength': 1, 'type': ['string']}, 'text': {'maxLength': 1048576, 'type': ['string', 'null']}, 'input_fingerprint': {'pattern': '^sha256:[0-9a-f]{64}$', 'type': ['string']}, 'processed': {'type': ['boolean']}, 'changed': {'type': ['boolean']}}, 'required': ['id', 'text', 'input_fingerprint', 'processed', 'changed'], 'type': ['object'], 'model': 'TextNormalizationResultResultsItem'}
TextNormalizationResultResultsItem._models = _MODELS
TextNormalizationResult._rule = {'additionalProperties': False, 'properties': {'results': {'items': {'additionalProperties': False, 'properties': {'id': {'maxLength': 256, 'minLength': 1, 'type': ['string']}, 'text': {'maxLength': 1048576, 'type': ['string', 'null']}, 'input_fingerprint': {'pattern': '^sha256:[0-9a-f]{64}$', 'type': ['string']}, 'processed': {'type': ['boolean']}, 'changed': {'type': ['boolean']}}, 'required': ['id', 'text', 'input_fingerprint', 'processed', 'changed'], 'type': ['object'], 'model': 'TextNormalizationResultResultsItem'}, 'maxItems': 256, 'type': ['array']}, 'processed_count': {'maximum': 256, 'minimum': 0, 'type': ['integer']}, 'changed_count': {'maximum': 256, 'minimum': 0, 'type': ['integer']}}, 'required': ['results', 'processed_count', 'changed_count'], 'type': ['object'], 'model': 'TextNormalizationResult'}
TextNormalizationResult._models = _MODELS

__all__ = ['TextNormalizationRequest', 'TextNormalizationResult']
