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

from dataclasses import dataclass
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


#: Default provider for each provider key. Several
#: capabilities may share one attribute (e.g. ``pdf.split`` and ``pdf.render``).
PROVIDER_DEFAULTS: dict[str, str] = {
    "toolbox_provider": "docling",
    "toolbox_layout_provider": "docling-layout",
    "toolbox_pdf_provider": "pymupdf-pdf",
    "toolbox_math_recognize_provider": "docling-math",
    "toolbox_math_provider": "pure-math",
    "toolbox_ocr_provider": "docling-ocr",
    "toolbox_page_ocr_provider": "qwen3-vl-page",
    "toolbox_adjudicate_provider": "qwen3-vl-judge",
    "toolbox_orientation_provider": "rapidocr-orient",
    "toolbox_media_inspect_provider": "pure-media-inspect",
}


_CAPABILITIES: tuple[ToolboxCapability, ...] = (
    ToolboxCapability(
        "document.structure.extract", 1, "Extração",
        provider_key="toolbox_provider",
        output_schema="structured-document@1",
    ),
    ToolboxCapability(
        "document.layout.analyze", 1, "Análise de layout",
        provider_key="toolbox_layout_provider",
        output_schema="layout-analysis@1",
    ),
    ToolboxCapability(
        "pdf.split", 1, "Divisão de PDF",
        provider_key="toolbox_pdf_provider",
        output_schema="page-collection@1",
    ),
    ToolboxCapability(
        "pdf.render", 1, "Renderização de PDF",
        provider_key="toolbox_pdf_provider",
        output_schema="image@1",
    ),
    ToolboxCapability(
        "math.recognize", 1, "Reconhecimento de fórmula",
        provider_key="toolbox_math_recognize_provider",
        output_schema="latex@1",
    ),
    ToolboxCapability(
        "math.convert", 1, "Conversão de fórmula",
        provider_key="toolbox_math_provider",
        output_schema="mathml@1",
    ),
    ToolboxCapability(
        "math.verbalize", 1, "Verbalização de fórmula",
        provider_key="toolbox_math_provider",
        output_schema="verbalized@1",
    ),
    ToolboxCapability(
        "document.ocr", 1, "OCR",
        provider_key="toolbox_ocr_provider",
        output_schema="ocr-result@1",
    ),
    ToolboxCapability(
        "image.page.orient", 1, "Detecção de orientação",
        provider_key="toolbox_orientation_provider",
        output_schema="page-orientation@1",
    ),
    ToolboxCapability(
        "media.inspect", 1, "Inspeção de mídia",
        provider_key="toolbox_media_inspect_provider",
        output_schema="media-inspection@1",
    ),
    # Dr.DocBench (PR #125) contracts the Toolbox does not publish yet; tracked
    # as KNOWN_DRIFT in the core (tests/test_toolbox_contract_drift.py).
    ToolboxCapability(
        "document.ocr.page", 1, "OCR de página",
        provider_key="toolbox_page_ocr_provider",
    ),
    ToolboxCapability(
        "document.adjudicate.page", 1, "Adjudicação",
        provider_key="toolbox_adjudicate_provider",
    ),
    ToolboxCapability(
        "document.adjudicate.region", 1, "Adjudicação",
        provider_key="toolbox_adjudicate_provider",
    ),
    # Reached through dedicated REST routes, not ":execute".
    *(
        ToolboxCapability(capability_id, 1, "Dataset", transport="rest")
        for capability_id in (
            "dataset.list",
            "dataset.describe",
            "dataset.list_splits",
            "dataset.list_items",
            "dataset.get_item",
            "dataset.get_artifact",
            "dataset.sample",
            "dataset.sync",
        )
    ),
    ToolboxCapability("artifact.store", 1, "Armazenamento de artefato", transport="rest"),
    ToolboxCapability("artifact.retrieve", 1, "Recuperação de artefato", transport="rest"),
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
    return PROVIDER_DEFAULTS[key]


__all__ = [
    "PROVIDER_DEFAULTS",
    "TOOLBOX_CAPABILITIES",
    "ToolboxCapability",
    "provider_default",
]
