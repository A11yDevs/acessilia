"""Tests for the FusedStructurer wire-up (FUSION_MODE=dual)."""
import asyncio

import pytest

from backend.config.settings import settings
from backend.tools.structurer import FusedStructurer, get_structurer


def _fused_payload(texts: list[str]) -> dict:
    return {
        "status": "succeeded",
        "provider": "docling+mineru",
        "document": {
            "elements": [
                {"type": "paragraph", "text": t, "reading_order": i}
                for i, t in enumerate(texts)
            ]
        },
        "fusion_stats": {},
    }


class TestGetStructurer:
    def test_dual_mode_returns_fused(self, monkeypatch):
        monkeypatch.setattr(settings, "fusion_mode", "dual")
        s = get_structurer()
        assert isinstance(s, FusedStructurer)

    def test_single_mode_not_fused(self, monkeypatch):
        monkeypatch.setattr(settings, "fusion_mode", "single")
        monkeypatch.setattr(settings, "structurer", "pymupdf")
        s = get_structurer()
        assert not isinstance(s, FusedStructurer)


class TestFusedTextsForPage:
    def test_single_page_no_markers(self):
        s = FusedStructurer()
        result = _fused_payload(["primeiro", "segundo"])
        texts = s._fused_texts_for_page(result, 0)
        assert texts == ["primeiro", "segundo"]

    def test_multi_page_markers(self):
        s = FusedStructurer()
        payload = {
            "status": "succeeded",
            "document": {
                "elements": [
                    {"type": "paragraph", "text": "p0a", "reading_order": 0, "page": 0},
                    {"type": "paragraph", "text": "p1a", "reading_order": 1, "page": 1},
                    {"type": "paragraph", "text": "p0b", "reading_order": 2, "page": 0},
                ]
            },
        }
        texts = s._fused_texts_for_page(payload, 0)
        assert texts == ["p0a", "p0b"]

    def test_empty_elements(self):
        s = FusedStructurer()
        assert s._fused_texts_for_page(_fused_payload([]), 0) == []


class TestAttachFusedText:
    def _regions(self, n: int):
        from backend.tools.region_extractor import Region

        return [
            Region(
                bbox=(0, i * 10, 100, (i + 1) * 10),
                type="text",
                text=f"local {i}",
                image_bytes=None,
                confidence=1.0,
                page_num=1,
            )
            for i in range(n)
        ]

    def test_distribui_em_ordem(self):
        s = FusedStructurer()
        regions = s._attach_fused_text(self._regions(2), ["f0", "f1"], 1)
        assert [r.text for r in regions] == ["f0", "f1"]
        assert all(r.metadata.get("fused") for r in regions)

    def test_textos_excedentes_vao_para_ultima(self):
        s = FusedStructurer()
        regions = s._attach_fused_text(self._regions(2), ["f0", "f1", "f2"], 1)
        assert regions[1].text.count("f2") == 1

    def test_regioes_excedentes_mantem_texto_local(self):
        s = FusedStructurer()
        regions = s._attach_fused_text(self._regions(3), ["f0"], 1)
        assert regions[0].text == "f0"
        assert regions[1].text == "local 1"

    def test_sem_textos_retorna_regioes(self):
        s = FusedStructurer()
        regions = self._regions(2)
        result = s._attach_fused_text(regions, [], 1)
        assert result is regions


class TestExtractPageRegions:
    def _page(self):
        from unittest.mock import MagicMock

        page = MagicMock()
        page.number = 0
        page.parent.name = "doc.pdf"
        page.rect.width = 100
        page.rect.height = 200
        return page

    def test_fallback_local_quando_fusao_falha(self, monkeypatch):
        s = FusedStructurer()

        async def boom(file_path):
            raise RuntimeError("toolbox down")

        monkeypatch.setattr(s, "_fetch_fused", boom)
        local = self._page()

        # PyMuPDF local also needs mocking: replace _local
        class FakeLocal:
            def extract_page_regions(self, page):
                from backend.tools.region_extractor import Region

                return [
                    Region(
                        bbox=(0, 0, 100, 200),
                        type="text",
                        text="local",
                        image_bytes=None,
                        confidence=1.0,
                        page_num=1,
                    )
                ]

        s._local = FakeLocal()
        regions = s.extract_page_regions(local)
        assert len(regions) == 1
        assert regions[0].text == "local"
        assert "fused" not in regions[0].metadata

    def test_sucesso_aplica_texto_fundido(self, monkeypatch):
        s = FusedStructurer()

        async def ok(file_path):
            return _fused_payload(["fusao 0", "fusao 1"])

        monkeypatch.setattr(s, "_fetch_fused", ok)

        from backend.tools.region_extractor import Region

        class FakeLocal:
            def extract_page_regions(self, page):
                return [
                    Region(
                        bbox=(0, 0, 100, 100),
                        type="text",
                        text="local a",
                        image_bytes=None,
                        confidence=1.0,
                        page_num=1,
                    ),
                    Region(
                        bbox=(0, 100, 100, 200),
                        type="text",
                        text="local b",
                        image_bytes=None,
                        confidence=1.0,
                        page_num=1,
                    ),
                ]

        s._local = FakeLocal()
        regions = s.extract_page_regions(self._page())
        assert [r.text for r in regions] == ["fusao 0", "fusao 1"]
        assert all(r.metadata.get("fused") for r in regions)

    def test_cache_por_documento(self, monkeypatch):
        s = FusedStructurer()
        calls = []

        async def fake_extract(file_path, **kw):
            calls.append(str(file_path))
            return _fused_payload(["t"])

        monkeypatch.setattr("backend.pipeline.fusion.extract_fused", fake_extract)
        asyncio.run(s._fetch_fused("doc.pdf"))
        asyncio.run(s._fetch_fused("doc.pdf"))
        assert len(calls) == 1  # segunda chamada veio do cache
