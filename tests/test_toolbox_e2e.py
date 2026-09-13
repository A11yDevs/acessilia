"""Testes de integração E2E contra uma instância real da Acessilia Toolbox.

Requires:
- TOOLBOX_BASE_URL environment variable pointing to a running Toolbox
- A PDF fixture at tests/fixtures/tutorials/
- A PNG image fixture or the ability to create one on the fly

Mark all tests with @pytest.mark.e2e so they can be skipped in CI
when the Toolbox is not available.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend.tools.toolbox_layout_client import ToolboxLayoutClient
from backend.tools.toolbox_math_client import ToolboxMathClient
from backend.tools.toolbox_ocr_client import ToolboxOcrClient
from backend.tools.toolbox_pdf_client import ToolboxPdfClient

TOOLBOX_BASE_URL = os.getenv("TOOLBOX_BASE_URL", "").strip()
FIXTURES_DIR = Path(__file__).parent / "fixtures"

if not TOOLBOX_BASE_URL:
    pytest.skip("TOOLBOX_BASE_URL not set — skipping E2E tests", allow_module_level=True)


def _get_pdf() -> Path:
    pdfs = sorted(FIXTURES_DIR.rglob("*.pdf"))
    if not pdfs:
        pytest.skip("No PDF fixtures found under tests/fixtures/")
    # Pick the smallest PDF under 500 KB
    for pdf in pdfs:
        size = pdf.stat().st_size
        if size < 500_000:
            return pdf
    return pdfs[0]


def _create_test_image() -> bytes:
    """Create a small PNG image with a formula-like drawing for testing."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        pytest.skip("Pillow not available — cannot create test image")

    img = Image.new("RGB", (400, 100), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((10, 30), "E = mc^2", fill="black")
    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# LayoutClient
# ---------------------------------------------------------------------------


class TestLayoutClientE2E:
    @pytest.fixture
    def client(self) -> ToolboxLayoutClient:
        return ToolboxLayoutClient(base_url=TOOLBOX_BASE_URL, timeout_seconds=120)

    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_health(self, client: ToolboxLayoutClient) -> None:
        result = await client.health()
        assert result is not None

    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_analyze_pdf_direct_upload(self, client: ToolboxLayoutClient) -> None:
        pdf = _get_pdf()
        result = await client.analyze(file_path=pdf)
        assert result["status"] == "succeeded"
        assert result["capability"] == "document.layout.analyze"
        doc = result.get("document", {})
        assert doc.get("page_count", 0) >= 1
        assert doc.get("region_count", 0) >= 0
        assert doc.get("pages") is not None

    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_analyze_pages_returns_regions(self, client: ToolboxLayoutClient) -> None:
        pdf = _get_pdf()
        pages = await client.analyze_pages(file_path=pdf)
        assert len(pages) >= 1
        first = pages[0]
        assert "page_number" in first
        assert "regions" in first
        # At least one region should have a type
        types = {r.get("type") for r in first["regions"]}
        assert len(types) >= 1

    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_analyze_page_specific(self, client: ToolboxLayoutClient) -> None:
        pdf = _get_pdf()
        page = await client.analyze_page(1, file_path=pdf)
        assert page is not None
        assert page["page_number"] == 1


# ---------------------------------------------------------------------------
# PdfClient
# ---------------------------------------------------------------------------


class TestPdfClientE2E:
    @pytest.fixture
    def client(self) -> ToolboxPdfClient:
        return ToolboxPdfClient(base_url=TOOLBOX_BASE_URL, timeout_seconds=120)

    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_split_pdf(self, client: ToolboxPdfClient) -> None:
        pdf = _get_pdf()
        result = await client.split(file_path=pdf)
        assert result["status"] == "succeeded"
        assert result["capability"] == "pdf.split"
        doc = result.get("document", {})
        assert doc.get("page_count", 0) >= 1
        assert len(doc.get("pages", [])) == doc["page_count"]
        for page in doc["pages"]:
            assert "page_number" in page
            assert page["page_number"] >= 1

    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_render_page(self, client: ToolboxPdfClient) -> None:
        pdf = _get_pdf()
        result = await client.render(file_path=pdf, page_number=1, dpi=150)
        assert result["status"] == "succeeded"
        doc = result.get("document", {})
        assert doc.get("page_number") == 1
        assert doc.get("width", 0) > 0
        assert doc.get("height", 0) > 0
        assert doc.get("image_bytes_base64") is not None
        assert doc.get("size_bytes", 0) > 0

    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_render_with_custom_dpi(self, client: ToolboxPdfClient) -> None:
        pdf = _get_pdf()
        result = await client.render(file_path=pdf, page_number=1, dpi=300)
        doc = result.get("document", {})
        assert doc.get("size_bytes", 0) > 0


# ---------------------------------------------------------------------------
# MathClient
# ---------------------------------------------------------------------------


class TestMathClientE2E:
    @pytest.fixture
    def client(self) -> ToolboxMathClient:
        return ToolboxMathClient(base_url=TOOLBOX_BASE_URL, timeout_seconds=300)

    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_convert_latex_to_mathml(self, client: ToolboxMathClient) -> None:
        result = await client.convert("E = mc^2", direction="latex-to-mathml")
        assert result["status"] == "succeeded"
        doc = result.get("document", {})
        assert doc.get("direction") == "latex-to-mathml"
        assert doc.get("latex") == "E = mc^2"
        assert "<math " in doc.get("mathml", "")

    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_verbalize_latex(self, client: ToolboxMathClient) -> None:
        result = await client.verbalize("E = mc^2", language="pt-BR")
        assert result["status"] == "succeeded"
        doc = result.get("document", {})
        assert doc.get("language") == "pt-BR"
        assert len(doc.get("verbalized", "")) > 0


# ---------------------------------------------------------------------------
# OcrClient
# ---------------------------------------------------------------------------


class TestOcrClientE2E:
    @pytest.fixture
    def client(self) -> ToolboxOcrClient:
        return ToolboxOcrClient(base_url=TOOLBOX_BASE_URL, timeout_seconds=300)

    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_ocr_pdf(self, client: ToolboxOcrClient) -> None:
        pdf = _get_pdf()
        result = await client.ocr(file_path=pdf, language="pt-BR", force_ocr=True)
        assert result["status"] == "succeeded"
        doc = result.get("document", {})
        assert doc.get("item_count", 0) >= 0
        assert doc.get("language") == "pt-BR"
        if doc["item_count"] > 0:
            assert len(doc.get("full_text", "")) > 0


# ---------------------------------------------------------------------------
# Multi-step workflow (integration scenario)
# ---------------------------------------------------------------------------


class TestWorkflowE2E:
    """End-to-end workflow: split → render → ocr → layout."""

    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_pdf_split_then_render_first_page(
        self,
    ) -> None:
        pdf_client = ToolboxPdfClient(base_url=TOOLBOX_BASE_URL, timeout_seconds=120)
        layout_client = ToolboxLayoutClient(base_url=TOOLBOX_BASE_URL, timeout_seconds=120)

        pdf = _get_pdf()

        # Split
        split_result = await pdf_client.split(file_path=pdf)
        page_count = split_result["document"]["page_count"]
        assert page_count >= 1

        # Render first page
        render_result = await pdf_client.render(
            file_path=pdf, page_number=1, dpi=150
        )
        assert render_result["document"]["page_number"] == 1

        # Analyze layout
        layout_result = await layout_client.analyze(file_path=pdf)
        assert layout_result["document"]["page_count"] == page_count

    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_math_convert_then_verbalize(self) -> None:
        math_client = ToolboxMathClient(
            base_url=TOOLBOX_BASE_URL, timeout_seconds=120
        )

        # Convert LaTeX to MathML
        convert_result = await math_client.convert(
            r"\frac{-b \pm \sqrt{b^2 - 4ac}}{2a}",
            direction="latex-to-mathml",
        )
        assert "<mfrac>" in convert_result["document"]["mathml"]

        # Verbalize the same LaTeX
        verbalize_result = await math_client.verbalize(
            r"\frac{-b \pm \sqrt{b^2 - 4ac}}{2a}",
            language="pt-BR",
        )
        verbalized = verbalize_result["document"]["verbalized"]
        assert len(verbalized) > 0