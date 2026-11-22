"""E1.9 compatibility contracts: format roles are deliberately different sets."""

from dataclasses import replace

import pytest

from acessilia_core.export.catalog import (
    CATALOG,
    DOCX,
    DOWNLOAD_LABELS,
    DOWNLOAD_MEDIA_TYPES,
    DOWNLOAD_SUFFIXES,
    DRBENCH_MD,
    PDF,
    PDF_UA,
    TXT,
    downloadable_formats,
)
from acessilia_sdk.toolbox.capabilities import TOOLBOX_CAPABILITIES
from acessilia_sdk.toolbox.clients import ToolboxDocxClient, ToolboxPdfUaClient
from backend.api.export_plan import EXPORT_STEPS, PACKAGE_ORDER

# Literal baseline from develop at 7f02df52, not generated from the catalogue.
DOWNLOAD_BASELINE = (
    ("txt", "texto", "text/plain; charset=utf-8", "sample.txt"),
    ("docx", "word", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "sample.docx"),
    ("pdf", "pdf", "application/pdf", "sample.pdf"),
    ("pdf_ua", "pdf/ua", "application/pdf", "sample.pdf_ua.pdf"),
    ("html", "html", "text/html; charset=utf-8", "sample.html"),
    ("mp3", "audio", "audio/mpeg", "sample.mp3"),
    ("zip", "completo", "application/zip", "sample_acessivel.zip"),
)


def test_download_contract_keeps_wire_values_names_and_order():
    assert tuple(
        (item.spec.id, item.api_label, item.spec.media_type, item.output_filename("sample"))
        for item in downloadable_formats()
    ) == DOWNLOAD_BASELINE
    assert DOWNLOAD_LABELS == {row[0]: row[1] for row in DOWNLOAD_BASELINE}
    assert DOWNLOAD_MEDIA_TYPES == {row[0]: row[2] for row in DOWNLOAD_BASELINE}
    assert DOWNLOAD_SUFFIXES == {"pdf_ua": "pdf_ua.pdf", "zip": "_acessivel.zip"}
    assert PDF_UA.spec.extension == "pdf"


def test_catalogue_roles_preserve_legacy_downloads_and_internal_output():
    assert {key for key, item in CATALOG.items() if item.produced} == {
        "txt", "html", "docx", "pdf_ua", "mp3", "zip", "drbench_md",
    }
    assert {key for key, item in CATALOG.items() if item.packaged_in_zip} == {
        "txt", "html", "docx", "mp3", "pdf_ua",
    }
    assert {key for key, item in CATALOG.items() if item.canonical_export} == {
        "txt", "html", "docx", "pdf_ua",
    }
    assert PDF.legacy and PDF.downloadable and not PDF.produced
    assert PDF.spec.execution is None
    assert not DRBENCH_MD.downloadable and not DRBENCH_MD.packaged_in_zip
    assert DRBENCH_MD.status == "internal"


@pytest.mark.parametrize("status,default,explicit", [
    ("stable", True, True), ("experimental", False, True), ("internal", False, False),
])
def test_availability_requires_explicit_experimental_opt_in(status, default, explicit):
    item = replace(TXT, status=status)
    assert item.available() is default
    assert item.available(experimental=True) is explicit


@pytest.mark.parametrize("delivery,client", [(DOCX, ToolboxDocxClient), (PDF_UA, ToolboxPdfUaClient)])
def test_remote_bindings_reference_the_sdk_public_contract(delivery, client):
    capability = TOOLBOX_CAPABILITIES[client.capability]
    assert delivery.capability == capability.id
    assert delivery.spec.version == str(capability.contract_version)
    assert delivery.spec.media_type == client.media_type
    assert delivery.spec.execution == "remote"


def test_worker_plan_keeps_order_flags_required_exports_and_progress():
    assert [(step.format_id, step.optional, step.requires_flag, step.progress) for step in EXPORT_STEPS] == [
        ("txt", False, None, 0.85),
        ("drbench_md", True, None, 0.86),
        ("html", False, None, 0.90),
        ("docx", True, "toolbox_docx_enabled", 0.92),
        ("pdf_ua", True, "toolbox_pdf_ua_enabled", 0.93),
        ("mp3", True, None, 0.95),
        ("zip", False, None, None),
    ]
    assert all(step.stage_msgid for step in EXPORT_STEPS[:-1])
    assert EXPORT_STEPS[-1].stage_msgid is None
    assert PACKAGE_ORDER == ("txt", "html", "docx", "mp3", "pdf_ua")
    assert set(PACKAGE_ORDER) == {key for key, item in CATALOG.items() if item.packaged_in_zip}
