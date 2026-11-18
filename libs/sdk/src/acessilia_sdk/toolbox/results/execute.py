"""Generated from selected Toolbox schemas; scripts/generate_sdk_bindings.py; do not edit by hand."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from acessilia_sdk.toolbox.results._model import ResultModel


@dataclass(frozen=True)
class LatexResult(ResultModel):
    latex: str
    confidence: float | None = None
    page: int | None = None
    bbox: list[float] | None = None


@dataclass(frozen=True)
class MathmlResult(ResultModel):
    mathml: str
    latex: str | None = None
    direction: str | None = None


@dataclass(frozen=True)
class VerbalizedResult(ResultModel):
    verbalized: str
    latex: str | None = None
    language: str | None = None


@dataclass(frozen=True)
class PageJudgement(ResultModel):
    pB_ab: float
    pA_ba: float
    pB: float
    prompt: str
    model: str


@dataclass(frozen=True)
class RegionTranscription(ResultModel):
    text: str
    model: str


@dataclass(frozen=True)
class PdfValidationReportSummary(ResultModel):
    passed_rules: int
    failed_rules: int
    passed_checks: int
    failed_checks: int


@dataclass(frozen=True)
class PdfValidationReportFailuresItemChecksItem(ResultModel):
    context: str
    message: str


@dataclass(frozen=True)
class PdfValidationReportFailuresItem(ResultModel):
    specification: str
    clause: str
    test_number: int
    description: str
    object: str
    test: str
    tags: list[str]
    failed_checks: int
    checks: list[PdfValidationReportFailuresItemChecksItem]


@dataclass(frozen=True)
class PdfValidationReport(ResultModel):
    compliant: bool
    profile: str
    profile_name: str
    statement: str
    summary: PdfValidationReportSummary
    failures: list[PdfValidationReportFailuresItem]
    validator: dict[str, str]


@dataclass(frozen=True)
class MediaInspectionDimensions(ResultModel):
    width: int
    height: int
    aspect_ratio: float


@dataclass(frozen=True)
class MediaInspection(ResultModel):
    media_type: str
    file_size_bytes: int
    is_image: bool
    is_pdf: bool
    page_count: int
    artifact_nature: str
    requires_visual_inspection: bool
    declared_media_type: str | None = None
    page_count_source: str | None = None
    dimensions: MediaInspectionDimensions | None = None
    dimensions_source: str | None = None
    color_mode: str | None = None
    format: str | None = None
    document_genre: str | None = None
    genre_signals: list[str] | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class RenderedPageMetadataClip(ResultModel):
    left: float
    top: float
    right: float
    bottom: float


@dataclass(frozen=True)
class RenderedPageMetadata(ResultModel):
    artifact_id: str
    media_type: str
    size_bytes: int
    page_number: int
    page_count: int
    page_width: float
    page_height: float
    clip: RenderedPageMetadataClip
    scale: float
    dpi: float
    width_px: int
    height_px: int
    source_media_type: str
    source_filename: str


@dataclass(frozen=True)
class TextSpansResultPagesItemLinesItemSpansItem(ResultModel):
    text: str
    font: str
    size: float
    flags: int
    bbox: list[float]
    origin: list[float]


@dataclass(frozen=True)
class TextSpansResultPagesItemLinesItem(ResultModel):
    bbox: list[float]
    spans: list[TextSpansResultPagesItemLinesItemSpansItem]


@dataclass(frozen=True)
class TextSpansResultPagesItem(ResultModel):
    page_number: int
    width: float
    height: float
    rotation: int
    lines: list[TextSpansResultPagesItemLinesItem]


@dataclass(frozen=True)
class TextSpansResult(ResultModel):
    page_count: int
    coord_origin: str
    pages: list[TextSpansResultPagesItem]


_MODELS = {'LatexResult': LatexResult, 'MathmlResult': MathmlResult, 'VerbalizedResult': VerbalizedResult, 'PageJudgement': PageJudgement, 'RegionTranscription': RegionTranscription, 'PdfValidationReportSummary': PdfValidationReportSummary, 'PdfValidationReportFailuresItemChecksItem': PdfValidationReportFailuresItemChecksItem, 'PdfValidationReportFailuresItem': PdfValidationReportFailuresItem, 'PdfValidationReport': PdfValidationReport, 'MediaInspectionDimensions': MediaInspectionDimensions, 'MediaInspection': MediaInspection, 'RenderedPageMetadataClip': RenderedPageMetadataClip, 'RenderedPageMetadata': RenderedPageMetadata, 'TextSpansResultPagesItemLinesItemSpansItem': TextSpansResultPagesItemLinesItemSpansItem, 'TextSpansResultPagesItemLinesItem': TextSpansResultPagesItemLinesItem, 'TextSpansResultPagesItem': TextSpansResultPagesItem, 'TextSpansResult': TextSpansResult}

LatexResult._rule = {'type': ['object'], 'additionalProperties': False, 'required': ['latex'], 'properties': {'latex': {'type': ['string'], 'minLength': 1}, 'confidence': {'type': ['number'], 'minimum': 0, 'maximum': 1}, 'page': {'type': ['integer'], 'minimum': 1}, 'bbox': {'type': ['array'], 'items': {'type': ['number']}, 'minItems': 4, 'maxItems': 4}}, 'model': 'LatexResult'}
LatexResult._models = _MODELS
MathmlResult._rule = {'type': ['object'], 'additionalProperties': False, 'required': ['mathml'], 'properties': {'mathml': {'type': ['string'], 'minLength': 1}, 'latex': {'type': ['string']}, 'direction': {'type': ['string'], 'enum': ['latex-to-mathml', 'mathml-to-latex']}}, 'model': 'MathmlResult'}
MathmlResult._models = _MODELS
VerbalizedResult._rule = {'type': ['object'], 'additionalProperties': False, 'required': ['verbalized'], 'properties': {'verbalized': {'type': ['string']}, 'latex': {'type': ['string']}, 'language': {'type': ['string'], 'pattern': '^[a-z]{2}(-[A-Z]{2})?$'}}, 'model': 'VerbalizedResult'}
VerbalizedResult._models = _MODELS
PageJudgement._rule = {'type': ['object'], 'additionalProperties': False, 'required': ['pB_ab', 'pA_ba', 'pB', 'prompt', 'model'], 'properties': {'pB_ab': {'type': ['number'], 'minimum': 0, 'maximum': 1}, 'pA_ba': {'type': ['number'], 'minimum': 0, 'maximum': 1}, 'pB': {'type': ['number'], 'minimum': 0, 'maximum': 1}, 'prompt': {'type': ['string'], 'enum': ['base', 'para', 'err']}, 'model': {'type': ['string']}}, 'model': 'PageJudgement'}
PageJudgement._models = _MODELS
RegionTranscription._rule = {'type': ['object'], 'additionalProperties': False, 'required': ['text', 'model'], 'properties': {'text': {'type': ['string']}, 'model': {'type': ['string']}}, 'model': 'RegionTranscription'}
RegionTranscription._models = _MODELS
PdfValidationReportSummary._rule = {'type': ['object'], 'additionalProperties': False, 'required': ['passed_rules', 'failed_rules', 'passed_checks', 'failed_checks'], 'properties': {'passed_rules': {'type': ['integer'], 'minimum': 0}, 'failed_rules': {'type': ['integer'], 'minimum': 0}, 'passed_checks': {'type': ['integer'], 'minimum': 0}, 'failed_checks': {'type': ['integer'], 'minimum': 0}}, 'model': 'PdfValidationReportSummary'}
PdfValidationReportSummary._models = _MODELS
PdfValidationReportFailuresItemChecksItem._rule = {'type': ['object'], 'additionalProperties': False, 'required': ['context', 'message'], 'properties': {'context': {'type': ['string']}, 'message': {'type': ['string']}}, 'model': 'PdfValidationReportFailuresItemChecksItem'}
PdfValidationReportFailuresItemChecksItem._models = _MODELS
PdfValidationReportFailuresItem._rule = {'type': ['object'], 'additionalProperties': False, 'required': ['specification', 'clause', 'test_number', 'description', 'object', 'test', 'tags', 'failed_checks', 'checks'], 'properties': {'specification': {'type': ['string']}, 'clause': {'type': ['string']}, 'test_number': {'type': ['integer']}, 'description': {'type': ['string']}, 'object': {'type': ['string']}, 'test': {'type': ['string']}, 'tags': {'type': ['array'], 'items': {'type': ['string']}}, 'failed_checks': {'type': ['integer'], 'minimum': 0}, 'checks': {'type': ['array'], 'items': {'type': ['object'], 'additionalProperties': False, 'required': ['context', 'message'], 'properties': {'context': {'type': ['string']}, 'message': {'type': ['string']}}, 'model': 'PdfValidationReportFailuresItemChecksItem'}}}, 'model': 'PdfValidationReportFailuresItem'}
PdfValidationReportFailuresItem._models = _MODELS
PdfValidationReport._rule = {'type': ['object'], 'additionalProperties': False, 'required': ['compliant', 'profile', 'profile_name', 'statement', 'summary', 'failures', 'validator'], 'properties': {'compliant': {'type': ['boolean']}, 'profile': {'type': ['string'], 'enum': ['ua1', 'ua2']}, 'profile_name': {'type': ['string']}, 'statement': {'type': ['string']}, 'summary': {'type': ['object'], 'additionalProperties': False, 'required': ['passed_rules', 'failed_rules', 'passed_checks', 'failed_checks'], 'properties': {'passed_rules': {'type': ['integer'], 'minimum': 0}, 'failed_rules': {'type': ['integer'], 'minimum': 0}, 'passed_checks': {'type': ['integer'], 'minimum': 0}, 'failed_checks': {'type': ['integer'], 'minimum': 0}}, 'model': 'PdfValidationReportSummary'}, 'failures': {'type': ['array'], 'items': {'type': ['object'], 'additionalProperties': False, 'required': ['specification', 'clause', 'test_number', 'description', 'object', 'test', 'tags', 'failed_checks', 'checks'], 'properties': {'specification': {'type': ['string']}, 'clause': {'type': ['string']}, 'test_number': {'type': ['integer']}, 'description': {'type': ['string']}, 'object': {'type': ['string']}, 'test': {'type': ['string']}, 'tags': {'type': ['array'], 'items': {'type': ['string']}}, 'failed_checks': {'type': ['integer'], 'minimum': 0}, 'checks': {'type': ['array'], 'items': {'type': ['object'], 'additionalProperties': False, 'required': ['context', 'message'], 'properties': {'context': {'type': ['string']}, 'message': {'type': ['string']}}, 'model': 'PdfValidationReportFailuresItemChecksItem'}}}, 'model': 'PdfValidationReportFailuresItem'}}, 'validator': {'type': ['object'], 'required': ['name'], 'additionalProperties': {'type': ['string']}, 'properties': {}}}, 'model': 'PdfValidationReport'}
PdfValidationReport._models = _MODELS
MediaInspectionDimensions._rule = {'type': ['object', 'null'], 'additionalProperties': False, 'required': ['width', 'height', 'aspect_ratio'], 'properties': {'width': {'type': ['integer'], 'minimum': 1}, 'height': {'type': ['integer'], 'minimum': 1}, 'aspect_ratio': {'type': ['number'], 'exclusiveMinimum': 0}}, 'model': 'MediaInspectionDimensions'}
MediaInspectionDimensions._models = _MODELS
MediaInspection._rule = {'type': ['object'], 'additionalProperties': False, 'required': ['media_type', 'file_size_bytes', 'is_image', 'is_pdf', 'page_count', 'artifact_nature', 'requires_visual_inspection'], 'properties': {'media_type': {'type': ['string'], 'minLength': 1}, 'declared_media_type': {'type': ['string', 'null']}, 'file_size_bytes': {'type': ['integer'], 'minimum': 0}, 'is_image': {'type': ['boolean']}, 'is_pdf': {'type': ['boolean']}, 'page_count': {'type': ['integer'], 'minimum': 1}, 'page_count_source': {'type': ['string', 'null'], 'enum': ['pymupdf', 'content_stream_scan', 'pillow', None]}, 'dimensions': {'type': ['object', 'null'], 'additionalProperties': False, 'required': ['width', 'height', 'aspect_ratio'], 'properties': {'width': {'type': ['integer'], 'minimum': 1}, 'height': {'type': ['integer'], 'minimum': 1}, 'aspect_ratio': {'type': ['number'], 'exclusiveMinimum': 0}}, 'model': 'MediaInspectionDimensions'}, 'dimensions_source': {'type': ['string', 'null'], 'enum': ['pymupdf', 'pillow', None]}, 'color_mode': {'type': ['string', 'null']}, 'format': {'type': ['string', 'null']}, 'artifact_nature': {'type': ['string'], 'enum': ['standalone_image', 'scanned_page', 'paginated_document', 'unknown']}, 'document_genre': {'type': ['string', 'null'], 'enum': ['presentation', 'document', None]}, 'genre_signals': {'type': ['array'], 'items': {'type': ['string']}}, 'requires_visual_inspection': {'type': ['boolean']}, 'metadata': {'type': ['object'], 'additionalProperties': True, 'properties': {}}}, 'model': 'MediaInspection'}
MediaInspection._models = _MODELS
RenderedPageMetadataClip._rule = {'type': ['object'], 'additionalProperties': False, 'required': ['left', 'top', 'right', 'bottom'], 'properties': {'left': {'type': ['number']}, 'top': {'type': ['number']}, 'right': {'type': ['number']}, 'bottom': {'type': ['number']}}, 'model': 'RenderedPageMetadataClip'}
RenderedPageMetadataClip._models = _MODELS
RenderedPageMetadata._rule = {'type': ['object'], 'additionalProperties': False, 'required': ['artifact_id', 'media_type', 'size_bytes', 'page_number', 'page_count', 'page_width', 'page_height', 'clip', 'scale', 'dpi', 'width_px', 'height_px', 'source_media_type', 'source_filename'], 'properties': {'artifact_id': {'type': ['string'], 'pattern': '^(sha256:)?[0-9a-f]{64}$'}, 'media_type': {'type': ['string'], 'const': 'image/png'}, 'size_bytes': {'type': ['integer'], 'minimum': 1}, 'page_number': {'type': ['integer'], 'minimum': 1}, 'page_count': {'type': ['integer'], 'minimum': 1}, 'page_width': {'type': ['number'], 'exclusiveMinimum': 0}, 'page_height': {'type': ['number'], 'exclusiveMinimum': 0}, 'clip': {'type': ['object'], 'additionalProperties': False, 'required': ['left', 'top', 'right', 'bottom'], 'properties': {'left': {'type': ['number']}, 'top': {'type': ['number']}, 'right': {'type': ['number']}, 'bottom': {'type': ['number']}}, 'model': 'RenderedPageMetadataClip'}, 'scale': {'type': ['number'], 'exclusiveMinimum': 0}, 'dpi': {'type': ['number'], 'exclusiveMinimum': 0}, 'width_px': {'type': ['integer'], 'minimum': 1}, 'height_px': {'type': ['integer'], 'minimum': 1}, 'source_media_type': {'type': ['string']}, 'source_filename': {'type': ['string'], 'minLength': 1}}, 'model': 'RenderedPageMetadata'}
RenderedPageMetadata._models = _MODELS
TextSpansResultPagesItemLinesItemSpansItem._rule = {'type': ['object'], 'additionalProperties': False, 'required': ['text', 'font', 'size', 'flags', 'bbox', 'origin'], 'properties': {'text': {'type': ['string'], 'minLength': 1}, 'font': {'type': ['string']}, 'size': {'type': ['number'], 'minimum': 0}, 'flags': {'type': ['integer'], 'minimum': 0}, 'bbox': {'type': ['array'], 'items': {'type': ['number']}, 'minItems': 4, 'maxItems': 4}, 'origin': {'type': ['array'], 'items': {'type': ['number']}, 'minItems': 2, 'maxItems': 2}}, 'model': 'TextSpansResultPagesItemLinesItemSpansItem'}
TextSpansResultPagesItemLinesItemSpansItem._models = _MODELS
TextSpansResultPagesItemLinesItem._rule = {'type': ['object'], 'additionalProperties': False, 'required': ['bbox', 'spans'], 'properties': {'bbox': {'type': ['array'], 'items': {'type': ['number']}, 'minItems': 4, 'maxItems': 4}, 'spans': {'type': ['array'], 'minItems': 1, 'items': {'type': ['object'], 'additionalProperties': False, 'required': ['text', 'font', 'size', 'flags', 'bbox', 'origin'], 'properties': {'text': {'type': ['string'], 'minLength': 1}, 'font': {'type': ['string']}, 'size': {'type': ['number'], 'minimum': 0}, 'flags': {'type': ['integer'], 'minimum': 0}, 'bbox': {'type': ['array'], 'items': {'type': ['number']}, 'minItems': 4, 'maxItems': 4}, 'origin': {'type': ['array'], 'items': {'type': ['number']}, 'minItems': 2, 'maxItems': 2}}, 'model': 'TextSpansResultPagesItemLinesItemSpansItem'}}}, 'model': 'TextSpansResultPagesItemLinesItem'}
TextSpansResultPagesItemLinesItem._models = _MODELS
TextSpansResultPagesItem._rule = {'type': ['object'], 'additionalProperties': False, 'required': ['page_number', 'width', 'height', 'rotation', 'lines'], 'properties': {'page_number': {'type': ['integer'], 'minimum': 1}, 'width': {'type': ['number'], 'minimum': 0}, 'height': {'type': ['number'], 'minimum': 0}, 'rotation': {'type': ['integer'], 'enum': [0, 90, 180, 270]}, 'lines': {'type': ['array'], 'items': {'type': ['object'], 'additionalProperties': False, 'required': ['bbox', 'spans'], 'properties': {'bbox': {'type': ['array'], 'items': {'type': ['number']}, 'minItems': 4, 'maxItems': 4}, 'spans': {'type': ['array'], 'minItems': 1, 'items': {'type': ['object'], 'additionalProperties': False, 'required': ['text', 'font', 'size', 'flags', 'bbox', 'origin'], 'properties': {'text': {'type': ['string'], 'minLength': 1}, 'font': {'type': ['string']}, 'size': {'type': ['number'], 'minimum': 0}, 'flags': {'type': ['integer'], 'minimum': 0}, 'bbox': {'type': ['array'], 'items': {'type': ['number']}, 'minItems': 4, 'maxItems': 4}, 'origin': {'type': ['array'], 'items': {'type': ['number']}, 'minItems': 2, 'maxItems': 2}}, 'model': 'TextSpansResultPagesItemLinesItemSpansItem'}}}, 'model': 'TextSpansResultPagesItemLinesItem'}}}, 'model': 'TextSpansResultPagesItem'}
TextSpansResultPagesItem._models = _MODELS
TextSpansResult._rule = {'type': ['object'], 'additionalProperties': False, 'required': ['page_count', 'coord_origin', 'pages'], 'properties': {'page_count': {'type': ['integer'], 'minimum': 0}, 'coord_origin': {'type': ['string'], 'enum': ['TOPLEFT']}, 'pages': {'type': ['array'], 'items': {'type': ['object'], 'additionalProperties': False, 'required': ['page_number', 'width', 'height', 'rotation', 'lines'], 'properties': {'page_number': {'type': ['integer'], 'minimum': 1}, 'width': {'type': ['number'], 'minimum': 0}, 'height': {'type': ['number'], 'minimum': 0}, 'rotation': {'type': ['integer'], 'enum': [0, 90, 180, 270]}, 'lines': {'type': ['array'], 'items': {'type': ['object'], 'additionalProperties': False, 'required': ['bbox', 'spans'], 'properties': {'bbox': {'type': ['array'], 'items': {'type': ['number']}, 'minItems': 4, 'maxItems': 4}, 'spans': {'type': ['array'], 'minItems': 1, 'items': {'type': ['object'], 'additionalProperties': False, 'required': ['text', 'font', 'size', 'flags', 'bbox', 'origin'], 'properties': {'text': {'type': ['string'], 'minLength': 1}, 'font': {'type': ['string']}, 'size': {'type': ['number'], 'minimum': 0}, 'flags': {'type': ['integer'], 'minimum': 0}, 'bbox': {'type': ['array'], 'items': {'type': ['number']}, 'minItems': 4, 'maxItems': 4}, 'origin': {'type': ['array'], 'items': {'type': ['number']}, 'minItems': 2, 'maxItems': 2}}, 'model': 'TextSpansResultPagesItemLinesItemSpansItem'}}}, 'model': 'TextSpansResultPagesItemLinesItem'}}}, 'model': 'TextSpansResultPagesItem'}}}, 'model': 'TextSpansResult'}
TextSpansResult._models = _MODELS

__all__ = ['LatexResult', 'MathmlResult', 'VerbalizedResult', 'PageJudgement', 'RegionTranscription', 'PdfValidationReport', 'MediaInspection', 'RenderedPageMetadata', 'TextSpansResult']
