"""Each Toolbox helper builds its client from the run's ``ToolboxConfig`` (ADR-0016, step 3).

The run's config is a distinct object here, unlike one built from the
settings, and the client factory is replaced by a recorder that stops the
call. A helper that rebuilt the config from the settings, or dropped it,
would hand the factory another object and fail its test.
"""

from __future__ import annotations

import asyncio
import struct
import zlib
from pathlib import Path

import pytest
from core_config_support import fusion_config, paths_config, toolbox_config
from pddl_support import build_element

from acessilia_core.toolbox import toolbox_client

FIXTURE_PDF = Path(__file__).parent / "fixtures" / "tutorials" / "java-oo-3pgs.pdf"


def test_the_adapter_exposes_only_its_config_and_factory() -> None:
    assert set(toolbox_client.__all__) == {
        "TIMEOUT_KEYS",
        "endpoints_from",
        "make_toolbox_client",
        "toolbox_client_config",
        "toolbox_endpoints",
        "toolbox_vlm_endpoint",
    }
    assert not hasattr(toolbox_client, "ToolboxError")
    assert not hasattr(toolbox_client, "ToolboxCapabilityClient")
    assert not hasattr(toolbox_client, "PROVIDER_DEFAULTS")
    assert not hasattr(toolbox_client, "execute_capability")


#: Modules that bind the factory at import; the others look it up in
#: ``toolbox_client`` when they call it.
BOUND_FACTORY_MODULES = (
    "acessilia_core.manifest.toolbox_extractor",
    "acessilia_core.pipeline.fusion",
    "acessilia_core.toolbox.toolbox_math_tools",
    "acessilia_core.toolbox.vision_payload",
)


class Built(Exception):
    """Raised by the recording factory once it has seen the config."""


@pytest.fixture
def run_toolbox():
    """The run's config: its own object, with values the settings do not have."""
    return toolbox_config(
        retries=7, media_inspect_enabled=True, pdf_validate_enabled=True, use_artifact_store=False
    )


@pytest.fixture
def received(monkeypatch):
    import importlib

    seen: list = []

    def factory(client_cls, toolbox, **_overrides):
        seen.append(toolbox)
        raise Built(client_cls.__name__)

    monkeypatch.setattr(toolbox_client, "make_toolbox_client", factory)
    for name in BOUND_FACTORY_MODULES:
        monkeypatch.setattr(importlib.import_module(name), "make_toolbox_client", factory)
    return seen


def _chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def _png(width: int = 200, height: int = 100) -> bytes:
    """A valid RGB PNG built with the standard library.

    The recording factory stops the helpers before any real processing; the
    image only needs enough pixels for the downscale helper to reach it.
    """
    raw = b"".join(b"\x00" + b"\x00\x00\x00" * width for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(raw))
        + _chunk(b"IEND", b"")
    )


def _call(run_toolbox, tmp_path):
    """One call per helper, each given ``run_toolbox``."""
    from acessilia_core.export.pandoc_exporter import toolbox_export_docx
    from acessilia_core.manifest.toolbox_extractor import ToolboxManifestExtractor
    from acessilia_core.pipeline import fusion, judge
    from acessilia_core.pipeline.enrichment.common import _extract_picture_bytes
    from acessilia_core.pipeline.toolbox import _toolbox_render
    from acessilia_core.toolbox import (
        media_inspect,
        pdf_ua_audit,
        text_spans,
        toolbox_math_tools,
        vision_payload,
    )

    png = _png()
    picture = build_element("pic-1", "picture")
    picture.page_number = 1
    return {
        "render": lambda: _toolbox_render(FIXTURE_PDF, 1, dpi=72, toolbox=run_toolbox),
        "picture crop": lambda: _extract_picture_bytes(
            FIXTURE_PDF, picture, 1, toolbox=run_toolbox
        ),
        "judge": lambda: judge._judge_page(png, "a", "b", toolbox=run_toolbox),
        "math.recognize": lambda: toolbox_math_tools.toolbox_recognize_formula(
            png, toolbox=run_toolbox
        ),
        "math.convert": lambda: toolbox_math_tools.toolbox_convert_latex("x", toolbox=run_toolbox),
        "math.verbalize": lambda: toolbox_math_tools.toolbox_verbalize_latex(
            "x", toolbox=run_toolbox
        ),
        "downscale": lambda: asyncio.run(
            vision_payload.downscale_image(png, 0.5, toolbox=run_toolbox)
        ),
        "media.inspect": lambda: asyncio.run(
            media_inspect.inspect_source_media(FIXTURE_PDF, toolbox=run_toolbox)
        ),
        "pdf.validate": lambda: asyncio.run(
            pdf_ua_audit.audit_pdf_ua(FIXTURE_PDF, toolbox=run_toolbox)
        ),
        "text spans": lambda: asyncio.run(
            text_spans.fetch_text_spans(FIXTURE_PDF, [1], toolbox=run_toolbox)
        ),
        "export": lambda: toolbox_export_docx(
            {"blocks": []}, tmp_path / "out.docx", toolbox=run_toolbox
        ),
        "fusion": lambda: asyncio.run(
            fusion.extract_fused(FIXTURE_PDF, secondary_provider="mineru", toolbox=run_toolbox)
        ),
        "extraction": lambda: ToolboxManifestExtractor().extract(
            FIXTURE_PDF, fusion=fusion_config(), toolbox=run_toolbox,
            paths=paths_config(), operations=None
        ),
    }


HELPERS = [
    "render", "picture crop", "judge", "math.recognize", "math.convert", "math.verbalize",
    "downscale", "media.inspect", "pdf.validate", "text spans", "export", "fusion", "extraction",
]


@pytest.mark.parametrize("helper", HELPERS)
def test_the_helper_builds_its_client_from_the_run_config(
    received, run_toolbox, tmp_path, helper
) -> None:
    # The recorder stops the call. Most helpers let it through; some wrap it
    # (a task group) or log it and go on (the picture crop): only an error
    # that is not the recorder's fails the test.
    try:
        _call(run_toolbox, tmp_path)[helper]()
    except Exception as error:
        if not _built_inside(error):
            raise

    assert received, f"{helper} built no client"
    assert all(toolbox is run_toolbox for toolbox in received)


def _built_inside(error: BaseException) -> bool:
    cause = error
    while cause is not None:
        if isinstance(cause, Built):
            return True
        if isinstance(cause, BaseExceptionGroup):
            return any(_built_inside(inner) for inner in cause.exceptions)
        cause = cause.__cause__ or cause.__context__
    return False
