"""Capabilities of the Acessilia Toolbox that this core is allowed to call.

This module is the single place where the core declares which Toolbox contracts
it consumes. Everything else is derived from it:

- ``ToolboxCapabilityClient`` refuses to execute a capability that is not
  listed here, so a capability id cannot reach the wire by accident;
- ``settings.py`` takes the default provider of each ``TOOLBOX_*_PROVIDER``
  variable from ``PROVIDER_DEFAULTS``;
- ``scripts/check_capability_contract.py`` compares this registry with the
  Toolbox catalogue instead of scanning source files.

It is pure data on purpose: it must stay importable without loading settings,
HTTP clients or the rest of the backend.
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
    #: ``Settings`` attribute holding the provider id; its env var is the upper-
    #: case name. ``None`` when the Toolbox resolves the provider on its own.
    provider_setting: str | None = None
    #: Output schema reference from the manifest (``schemas/<ref>.json``), or
    #: ``None`` while the Toolbox does not publish the capability.
    output_schema: str | None = None


#: Default provider for each ``Settings`` provider attribute. Several
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
        provider_setting="toolbox_provider",
        output_schema="structured-document@1",
    ),
    ToolboxCapability(
        "document.layout.analyze", 1, "Análise de layout",
        provider_setting="toolbox_layout_provider",
        output_schema="layout-analysis@1",
    ),
    ToolboxCapability(
        "pdf.split", 1, "Divisão de PDF",
        provider_setting="toolbox_pdf_provider",
        output_schema="page-collection@1",
    ),
    ToolboxCapability(
        "pdf.render", 1, "Renderização de PDF",
        provider_setting="toolbox_pdf_provider",
        output_schema="image@1",
    ),
    ToolboxCapability(
        "math.recognize", 1, "Reconhecimento de fórmula",
        provider_setting="toolbox_math_recognize_provider",
        output_schema="latex@1",
    ),
    ToolboxCapability(
        "math.convert", 1, "Conversão de fórmula",
        provider_setting="toolbox_math_provider",
        output_schema="mathml@1",
    ),
    ToolboxCapability(
        "math.verbalize", 1, "Verbalização de fórmula",
        provider_setting="toolbox_math_provider",
        output_schema="verbalized@1",
    ),
    ToolboxCapability(
        "document.ocr", 1, "OCR",
        provider_setting="toolbox_ocr_provider",
        output_schema="ocr-result@1",
    ),
    ToolboxCapability(
        "image.page.orient", 1, "Detecção de orientação",
        provider_setting="toolbox_orientation_provider",
        output_schema="page-orientation@1",
    ),
    ToolboxCapability(
        "media.inspect", 1, "Inspeção de mídia",
        provider_setting="toolbox_media_inspect_provider",
        output_schema="media-inspection@1",
    ),
    # Dr.DocBench (PR #125) contracts the Toolbox does not publish yet; tracked
    # as KNOWN_DRIFT in tests/test_toolbox_contract_drift.py.
    ToolboxCapability(
        "document.ocr.page", 1, "OCR de página",
        provider_setting="toolbox_page_ocr_provider",
    ),
    ToolboxCapability(
        "document.adjudicate.page", 1, "Adjudicação",
        provider_setting="toolbox_adjudicate_provider",
    ),
    ToolboxCapability(
        "document.adjudicate.region", 1, "Adjudicação",
        provider_setting="toolbox_adjudicate_provider",
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
        _capability.provider_setting is not None
        and _capability.provider_setting not in PROVIDER_DEFAULTS
    ):
        raise RuntimeError(
            f"{_capability.id} names provider setting "
            f"{_capability.provider_setting!r} with no entry in PROVIDER_DEFAULTS"
        )


def provider_default(setting: str) -> str:
    """Default provider id for a ``Settings`` provider attribute."""
    return PROVIDER_DEFAULTS[setting]


__all__ = [
    "PROVIDER_DEFAULTS",
    "TOOLBOX_CAPABILITIES",
    "ToolboxCapability",
    "provider_default",
]
