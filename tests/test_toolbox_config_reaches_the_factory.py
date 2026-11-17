"""Each Toolbox helper builds its client from the run's ``ToolboxConfig`` (ADR-0016, step 3).

The run's config is a distinct object here, unlike one built from the
settings, and the client factory is replaced by a recorder that stops the
call. A helper that rebuilt the config from the settings, or dropped it,
would hand the factory another object and fail its test.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import fitz
import pytest

from backend.core.toolbox import toolbox_client
from tests.core_config_support import fusion_config, paths_config, toolbox_config
from tests.pddl_support import build_element

FIXTURE_PDF = Path(__file__).parent / "fixtures" / "tutorials" / "java-oo-3pgs.pdf"

#: Modules that bind the factory at import; the others look it up in
#: ``toolbox_client`` when they call it.
BOUND_FACTORY_MODULES = (
    "backend.core.manifest.toolbox_extractor",
    "backend.core.pipeline.fusion",
    "backend.core.toolbox.toolbox_math_tools",
    "backend.core.toolbox.vision_payload",
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


def _png(tmp_path: Path) -> bytes:
    with fitz.open() as pdf:
        page = pdf.new_page(width=200, height=100)
        return page.get_pixmap().tobytes("png")


def _call(run_toolbox, tmp_path):
    """One call per helper, each given ``run_toolbox``."""
    from backend.core.export.pandoc_exporter import toolbox_export_docx
    from backend.core.manifest.toolbox_extractor import ToolboxManifestExtractor
    from backend.core.pipeline import fusion, judge
    from backend.core.pipeline.enrichment.common import _extract_picture_bytes
    from backend.core.pipeline.toolbox import _toolbox_render
    from backend.core.toolbox import (
        media_inspect,
        pdf_ua_audit,
        text_spans,
        toolbox_math_tools,
        vision_payload,
    )

    png = _png(tmp_path)
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
