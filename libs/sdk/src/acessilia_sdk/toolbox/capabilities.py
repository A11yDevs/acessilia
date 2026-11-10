"""Capabilities of the Acessilia Toolbox that SDK clients are allowed to call.

This module is the single place where the Toolbox contracts consumed through the
SDK are declared. Everything else is derived from it:

- ``execute_capability`` refuses a capability that is not listed here, so a
  capability id cannot reach the wire by accident;
- the core's ``Settings`` take the default provider of each
  ``TOOLBOX_*_PROVIDER`` variable from ``PROVIDER_DEFAULTS``;
- ``scripts/check_capability_contract.py`` (in the core) compares this registry
  with the Toolbox catalogue.

It is pure data on purpose: it must stay importable on its own, without the
HTTP client or anything else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Transport = Literal["execute", "rest"]


@dataclass(frozen=True)
class ToolboxCapability:
    #: Capability id published by the Toolbox (``capabilities/<id>.yaml``).
    id: str
    #: Manifest ``version`` the core was written against. Compatibility is exact.
    contract_version: int
    #: Human label used in error messages ("<label> falhou na Toolbox").
    label: str
    #: ``execute`` capabilities go through ``POST /v1/capabilities/{id}:execute``;
    #: ``rest`` ones are reached through dedicated routes (datasets, artifacts).
    transport: Transport = "execute"
    #: Configuration key holding the provider id (the core's ``Settings``
    #: attribute; its env var is the upper-case name). ``None`` when the Toolbox
    #: resolves the provider on its own.
    provider_key: str | None = None
    #: Output schema reference from the manifest (``schemas/<ref>.json``), or
    #: ``None`` while the Toolbox does not publish the capability.
    output_schema: str | None = None
    #: The manifest's ``execution.idempotent`` at ``contract_version``:
    #: repeating the same operation has no effect beyond the first execution.
    #: Required, with no default, so the retry policy of ADR-0006 (applied
    #: by the client in #406) can never treat a capability as idempotent by
    #: omission. ``scripts/check_capability_contract.py`` compares it with the
    #: published contract.
    idempotent: bool = field(kw_only=True)


#: Default provider for each provider key. Several
#: capabilities may share one attribute (e.g. ``pdf.split`` and ``pdf.render``).
PROVIDER_DEFAULTS: dict[str, str] = {
    "toolbox_provider": "docling",
    "toolbox_layout_provider": "docling-layout",
    "toolbox_pdf_provider": "pymupdf-pdf",
    "toolbox_math_recognize_provider": "pp-formulanet",
    "toolbox_math_provider": "math-speech",
    "toolbox_ocr_provider": "docling-ocr",
    "toolbox_page_ocr_provider": "qwen3-vl-8b",
    "toolbox_adjudicate_provider": "qwen3-vl-8b",
    "toolbox_table_provider": "qwen3-vl-8b",
    "toolbox_orientation_provider": "rapidocr-orient",
    "toolbox_media_inspect_provider": "pure-media-inspect",
    "toolbox_pdf_ua_provider": "pandoc-pdf-ua",
    "toolbox_pdf_validate_provider": "verapdf",
    "toolbox_docx_provider": "pandoc-docx",
}

#: Default provider for each provider key of a Toolbox route that is not a
#: capability: the VLM chat gateway (:mod:`acessilia_sdk.toolbox.vlm`). The
#: core's contract check verifies these ids like ``PROVIDER_DEFAULTS``.
ROUTE_PROVIDER_DEFAULTS: dict[str, str] = {
    "toolbox_vlm_provider": "qwen3-vl-8b",
}


# Generated: do not edit by hand.
# What the Toolbox's published contract says about each selected capability
# version: (output schema, idempotent). Written by
# scripts/generate_sdk_bindings.py from tests/fixtures/toolbox-contract.json
# (ADR-0004, #213); a test fails while it is out of date.
# BEGIN GENERATED BINDINGS
_BINDINGS: dict[tuple[str, int], tuple[str | None, bool]] = {
    ('artifact.retrieve', 1): (None, True),
    ('artifact.store', 1): (None, True),
    ('dataset.describe', 1): (None, True),
    ('dataset.get_artifact', 1): (None, True),
    ('dataset.get_item', 1): (None, True),
    ('dataset.list', 1): (None, True),
    ('dataset.list_items', 1): (None, True),
    ('dataset.list_splits', 1): (None, True),
    ('dataset.sample', 1): (None, False),
    ('dataset.sync', 1): (None, True),
    ('document.adjudicate.page', 1): ('page-judgement@1', True),
    ('document.adjudicate.region', 1): ('region-transcription@1', True),
    ('document.export.docx', 1): ('docx-export@1', True),
    ('document.export.pdf_ua', 1): ('pdf-export@1', True),
    ('document.layout.analyze', 1): ('layout-analysis@1', True),
    ('document.ocr', 1): ('ocr-result@1', True),
    ('document.ocr.page', 1): ('page-transcription@1', True),
    ('document.structure.extract', 1): ('structured-document@1', True),
    ('document.text.spans', 1): ('text-spans@1', True),
    ('image.page.orient', 1): ('page-orientation@1', True),
    ('math.convert', 1): ('mathml@1', True),
    ('math.recognize', 1): ('latex@1', True),
    ('math.verbalize', 1): ('verbalized@1', True),
    ('media.inspect', 1): ('media-inspection@1', True),
    ('pdf.render', 2): ('image@2', True),
    ('pdf.split', 1): ('page-collection@1', True),
    ('pdf.validate.pdf_ua', 1): ('pdf-validation-report@1', True),
    ('table.recognize', 1): ('table-candidates@1', True),
}
# END GENERATED BINDINGS


def _selected(
    capability_id: str,
    contract_version: int,
    label: str,
    *,
    transport: Transport = "execute",
    provider_key: str | None = None,
) -> ToolboxCapability:
    """A capability the SDK allows, with its contract data from ``_BINDINGS``.

    The arguments are the SDK's own choices, written by hand: which ids it may
    call, at which exact version, through which transport, with which provider
    key and error label. ``output_schema`` and ``idempotent`` come from the
    published contract, never from here.
    """
    output_schema, idempotent = _BINDINGS[(capability_id, contract_version)]
    return ToolboxCapability(
        capability_id,
        contract_version,
        label,
        transport=transport,
        provider_key=provider_key,
        output_schema=output_schema,
        idempotent=idempotent,
    )


#: The capabilities SDK clients may call (the allowlist). Adding one here and
#: running scripts/generate_sdk_bindings.py is all the registry needs.
_CAPABILITIES: tuple[ToolboxCapability, ...] = (
    _selected("document.structure.extract", 1, "Extração", provider_key="toolbox_provider"),
    _selected(
        "document.layout.analyze", 1, "Análise de layout", provider_key="toolbox_layout_provider"
    ),
    _selected("pdf.split", 1, "Divisão de PDF", provider_key="toolbox_pdf_provider"),
    # Version 2: clip, size bound, raster inputs, PNG by reference.
    _selected("pdf.render", 2, "Renderização de PDF", provider_key="toolbox_pdf_provider"),
    # The text layer with fonts and baselines, read for inline math (#265).
    _selected("document.text.spans", 1, "Text spans", provider_key="toolbox_pdf_provider"),
    _selected(
        "math.recognize", 1, "Reconhecimento de fórmula",
        provider_key="toolbox_math_recognize_provider",
    ),
    _selected("math.convert", 1, "Conversão de fórmula", provider_key="toolbox_math_provider"),
    _selected(
        "math.verbalize", 1, "Verbalização de fórmula", provider_key="toolbox_math_provider"
    ),
    _selected("document.ocr", 1, "OCR", provider_key="toolbox_ocr_provider"),
    _selected(
        "image.page.orient", 1, "Detecção de orientação",
        provider_key="toolbox_orientation_provider",
    ),
    _selected(
        "media.inspect", 1, "Inspeção de mídia", provider_key="toolbox_media_inspect_provider"
    ),
    # The PDF comes back as a stored artifact; the result carries its id.
    _selected(
        "document.export.pdf_ua", 1, "Exportação PDF/UA", provider_key="toolbox_pdf_ua_provider"
    ),
    # veraPDF; a non-compliant PDF is a successful result listing failed rules.
    _selected(
        "pdf.validate.pdf_ua", 1, "PDF/UA validation",
        provider_key="toolbox_pdf_validate_provider",
    ),
    # The DOCX also comes back as a stored artifact.
    _selected("document.export.docx", 1, "Exportação DOCX", provider_key="toolbox_docx_provider"),
    # Vision-language capabilities (Dr.DocBench, PR #125), served by the
    # Toolbox's OpenAI-compatible VLM provider.
    _selected("document.ocr.page", 1, "OCR de página", provider_key="toolbox_page_ocr_provider"),
    _selected(
        "document.adjudicate.page", 1, "Adjudicação", provider_key="toolbox_adjudicate_provider"
    ),
    _selected(
        "document.adjudicate.region", 1, "Adjudicação", provider_key="toolbox_adjudicate_provider"
    ),
    _selected(
        "table.recognize", 1, "Reconhecimento de tabela", provider_key="toolbox_table_provider"
    ),
    # Reached through dedicated REST routes, not ":execute".
    _selected("dataset.list", 1, "Dataset", transport="rest"),
    _selected("dataset.describe", 1, "Dataset", transport="rest"),
    _selected("dataset.list_splits", 1, "Dataset", transport="rest"),
    _selected("dataset.list_items", 1, "Dataset", transport="rest"),
    _selected("dataset.get_item", 1, "Dataset", transport="rest"),
    _selected("dataset.get_artifact", 1, "Dataset", transport="rest"),
    _selected("dataset.sample", 1, "Dataset", transport="rest"),
    _selected("dataset.sync", 1, "Dataset", transport="rest"),
    _selected("artifact.store", 1, "Armazenamento de artefato", transport="rest"),
    _selected("artifact.retrieve", 1, "Recuperação de artefato", transport="rest"),
)

TOOLBOX_CAPABILITIES: dict[str, ToolboxCapability] = {
    capability.id: capability for capability in _CAPABILITIES
}

if len(TOOLBOX_CAPABILITIES) != len(_CAPABILITIES):
    raise RuntimeError("duplicate capability id in TOOLBOX_CAPABILITIES")
for _capability in _CAPABILITIES:
    if (
        _capability.provider_key is not None
        and _capability.provider_key not in PROVIDER_DEFAULTS
    ):
        raise RuntimeError(
            f"{_capability.id} names provider key "
            f"{_capability.provider_key!r} with no entry in PROVIDER_DEFAULTS"
        )


def provider_default(key: str) -> str:
    """Default provider id for a provider key."""
    if key in ROUTE_PROVIDER_DEFAULTS:
        return ROUTE_PROVIDER_DEFAULTS[key]
    return PROVIDER_DEFAULTS[key]


__all__ = [
    "PROVIDER_DEFAULTS",
    "ROUTE_PROVIDER_DEFAULTS",
    "TOOLBOX_CAPABILITIES",
    "ToolboxCapability",
    "provider_default",
]
