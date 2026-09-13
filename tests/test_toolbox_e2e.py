"""Testes de integração E2E contra uma instância real da Acessilia Toolbox.

Requires:
- TOOLBOX_BASE_URL environment variable pointing to a running Toolbox
- A PDF under 500KB found via recursive glob under tests/fixtures/

All tests are marked with @pytest.mark.e2e and excluded from CI
via -m "not e2e".
"""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest

from backend.tools.toolbox_layout_client import ToolboxLayoutClient
from backend.tools.toolbox_math_client import ToolboxMathClient
from backend.tools.toolbox_ocr_client import ToolboxOcrClient
from backend.tools.toolbox_pdf_client import ToolboxPdfClient

TOOLBOX_BASE_URL = os.getenv("TOOLBOX_BASE_URL", "").strip()
FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _get_pdf() -> Path:
    pdfs = sorted(FIXTURES_DIR.rglob("*.pdf"))
    if not pdfs:
        pytest.skip("No PDF fixtures found under tests/fixtures/")
    for pdf in pdfs:
        size = pdf.stat().st_size
        if size < 500_000:
            return pdf
    return min(pdfs, key=lambda p: p.stat().st_size)


def _make_formula_image() -> bytes:
    """Create a small PNG image with a formula-like drawing."""
    try:
        from PIL import Image, ImageDraw  # type: ignore[import-untyped]
    except ImportError:
        pytest.skip("Pillow not available — cannot create test image")
    img = Image.new("RGB", (400, 100), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((10, 30), "E = mc^2", fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Fixtures with cleanup
# ---------------------------------------------------------------------------


@pytest.fixture
async def layout_client() -> ToolboxLayoutClient:
    client = ToolboxLayoutClient(base_url=TOOLBOX_BASE_URL, timeout_seconds=120)
    yield client
    await client.close()


@pytest.fixture
async def pdf_client() -> ToolboxPdfClient:
    client = ToolboxPdfClient(base_url=TOOLBOX_BASE_URL, timeout_seconds=120)
    yield client
    await client.close()


@pytest.fixture
async def math_client() -> ToolboxMathClient:
    client = ToolboxMathClient(base_url=TOOLBOX_BASE_URL, timeout_seconds=300)
    yield client
    await client.close()


@pytest.fixture
async def ocr_client() -> ToolboxOcrClient:
    client = ToolboxOcrClient(base_url=TOOLBOX_BASE_URL, timeout_seconds=300)
    yield client
    await client.close()


# ---------------------------------------------------------------------------
# LayoutClient
# ---------------------------------------------------------------------------


class TestLayoutClientE2E:
    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_health(self, layout_client: ToolboxLayoutClient) -> None:
        result = await layout_client.health()
        assert result is not None

    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_analyze_pdf_direct_upload(
        self, layout_client: ToolboxLayoutClient
    ) -> None:
        pdf = _get_pdf()
        result = await layout_client.analyze(file_path=pdf)
        assert result["status"] == "succeeded"
        assert result["capability"] == "document.layout.analyze"
        doc = result.get("document", {})
        assert doc.get("page_count", 0) >= 1
        assert doc.get("page_count") == len(doc.get("pages", []))
        assert doc.get("region_count", 0) >= 0

    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_analyze_pages_returns_regions(
        self, layout_client: ToolboxLayoutClient
    ) -> None:
        pdf = _get_pdf()
        pages = await layout_client.analyze_pages(file_path=pdf)
        assert len(pages) >= 1
        first = pages[0]
        assert "page_number" in first
        assert "regions" in first
        types = {r.get("type") for r in first["regions"]}
        assert len(types) >= 1

    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_analyze_page_specific(
        self, layout_client: ToolboxLayoutClient
    ) -> None:
        pdf = _get_pdf()
        page = await layout_client.analyze_page(1, file_path=pdf)
        assert page is not None
        assert page["page_number"] == 1


# ---------------------------------------------------------------------------
# PdfClient
# ---------------------------------------------------------------------------


class TestPdfClientE2E:
    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_split_pdf(self, pdf_client: ToolboxPdfClient) -> None:
        pdf = _get_pdf()
        result = await pdf_client.split(file_path=pdf)
        assert result["status"] == "succeeded"
        assert result["capability"] == "pdf.split"
        doc = result.get("document", {})
        assert doc.get("page_count", 0) >= 1
        assert len(doc.get("pages", [])) == doc["page_count"]
        for page in doc["pages"]:
            assert page.get("page_number", 0) >= 1

    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_render_page(self, pdf_client: ToolboxPdfClient) -> None:
        pdf = _get_pdf()
        result = await pdf_client.render(file_path=pdf, page_number=1, dpi=150)
        assert result["status"] == "succeeded"
        doc = result.get("document", {})
        assert doc.get("page_number") == 1
        assert doc.get("width", 0) > 0
        assert doc.get("height", 0) > 0
        assert doc.get("image_bytes_base64") is not None
        assert doc.get("size_bytes", 0) > 0

    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_render_with_custom_dpi(
        self, pdf_client: ToolboxPdfClient
    ) -> None:
        pdf = _get_pdf()
        result = await pdf_client.render(file_path=pdf, page_number=1, dpi=300)
        doc = result.get("document", {})
        assert doc.get("size_bytes", 0) > 0


# ---------------------------------------------------------------------------
# MathClient
# ---------------------------------------------------------------------------


class TestMathClientE2E:
    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_convert_latex_to_mathml(
        self, math_client: ToolboxMathClient
    ) -> None:
        result = await math_client.convert("E = mc^2", direction="latex-to-mathml")
        assert result["status"] == "succeeded"
        doc = result.get("document", {})
        assert doc.get("direction") == "latex-to-mathml"
        assert doc.get("latex") == "E = mc^2"
        assert "<math " in doc.get("mathml", "")

    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_verbalize_latex(self, math_client: ToolboxMathClient) -> None:
        result = await math_client.verbalize("E = mc^2", language="pt-BR")
        assert result["status"] == "succeeded"
        doc = result.get("document", {})
        assert doc.get("language") == "pt-BR"
        assert len(doc.get("verbalized", "")) > 0

    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_recognize_formula(self, math_client: ToolboxMathClient) -> None:
        image = _make_formula_image()
        from pathlib import Path as _Path
        import tempfile

        tmp = _Path(tempfile.mkdtemp()) / "formula.png"
        tmp.write_bytes(image)
        try:
            result = await math_client.recognize(file_path=tmp)
            assert result["status"] == "succeeded"
            doc = result.get("document", {})
            assert doc.get("formula_count", 0) >= 0
            if doc["formula_count"] > 0:
                assert doc["formulas"][0].get("latex")
        finally:
            tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# OcrClient
# ---------------------------------------------------------------------------


class TestOcrClientE2E:
    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_ocr_pdf(self, ocr_client: ToolboxOcrClient) -> None:
        pdf = _get_pdf()
        result = await ocr_client.ocr(
            file_path=pdf, language="pt-BR", force_ocr=True
        )
        assert result["status"] == "succeeded"
        doc = result.get("document", {})
        assert doc.get("item_count", 0) >= 0
        assert doc.get("language") == "pt-BR"


# ---------------------------------------------------------------------------
# Multi-step workflow (integration scenario)
# ---------------------------------------------------------------------------


class TestWorkflowE2E:
    """End-to-end workflow: split -> render -> layout."""

    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_pdf_split_then_render_first_page(self) -> None:
        pdf_client = ToolboxPdfClient(
            base_url=TOOLBOX_BASE_URL, timeout_seconds=120
        )
        layout_client = ToolboxLayoutClient(
            base_url=TOOLBOX_BASE_URL, timeout_seconds=120
        )
        try:
            pdf = _get_pdf()

            split_result = await pdf_client.split(file_path=pdf)
            page_count = split_result["document"]["page_count"]
            assert page_count >= 1

            render_result = await pdf_client.render(
                file_path=pdf, page_number=1, dpi=150
            )
            assert render_result["document"]["page_number"] == 1

            layout_result = await layout_client.analyze(file_path=pdf)
            assert layout_result["document"]["page_count"] == page_count
        finally:
            await pdf_client.close()
            await layout_client.close()

    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_math_convert_then_verbalize(self) -> None:
        math_client = ToolboxMathClient(
            base_url=TOOLBOX_BASE_URL, timeout_seconds=120
        )
        try:
            convert_result = await math_client.convert(
                r"\frac{-b \pm \sqrt{b^2 - 4ac}}{2a}",
                direction="latex-to-mathml",
            )
            assert "<mfrac>" in convert_result["document"]["mathml"]

            verbalize_result = await math_client.verbalize(
                r"\frac{-b \pm \sqrt{b^2 - 4ac}}{2a}",
                language="pt-BR",
            )
            assert len(verbalize_result["document"]["verbalized"]) > 0
        finally:
            await math_client.close()