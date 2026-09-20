"""Backend fusion layer tests (Phase 4).

Toolbox is mocked — no test requires a running service.
"""
import pytest

from backend.pipeline.fusion import (
    _group_by_page,
    extract_fused,
)


def _payload(elements: list[dict]) -> dict:
    return {
        "status": "succeeded",
        "provider": "test",
        "document": {"elements": elements},
    }


def _el(text: str, order: int, page: int = 0, type_: str = "paragraph", **kw) -> dict:
    el = {"type": type_, "text": text, "reading_order": order, "page": page}
    el.update(kw)
    return el


class FakeToolbox:
    provider = "docling"

    def __init__(self):
        from backend.tools.toolbox_client import ToolboxClient
        self._client = ToolboxClient(provider="docling")


class TestGroupByPage:
    def test_groups_by_page(self):
        payload = _payload([
            _el("a", 0, page=0),
            _el("b", 1, page=1),
            _el("c", 2, page=0),
        ])
        groups = _group_by_page(payload)
        assert set(groups) == {0, 1}
        assert [b["text"] for b in groups[0]] == ["a", "c"]

    def test_empty_text_ignored(self):
        payload = _payload([_el("", 0), _el("x", 1)])
        assert list(_group_by_page(payload).values())[0][0]["text"] == "x"

    def test_bbox_preserved(self):
        payload = _payload([
            _el("a", 0, bbox=[1.0, 2.0, 3.0, 4.0], page_size=[100.0, 200.0])
        ])
        block = _group_by_page(payload)[0][0]
        assert block["bbox"] == [1.0, 2.0, 3.0, 4.0]
        assert block["page_index"] == 0


class TestExtractFused:
    @pytest.mark.asyncio
    async def test_primary_failure_fallback(self, monkeypatch):
        async def fake_extract(provider):
            if provider == "docling":
                return None
            return _payload([_el("só mineru", 0)])

        monkeypatch.setattr(
            "backend.pipeline.fusion.ToolboxClient",
            _FakeClientFactory(extract_fn=fake_extract),
        )
        result = await extract_fused("arquivo.pdf")
        # retorno é exatamente o payload do secundário (sem fusão)
        assert result["document"]["elements"][0]["text"] == "só mineru"

    @pytest.mark.asyncio
    async def test_both_fail(self, monkeypatch):
        async def fake_extract(provider):
            return None

        monkeypatch.setattr(
            "backend.pipeline.fusion.ToolboxClient",
            _FakeClientFactory(extract_fn=fake_extract),
        )
        from backend.tools.toolbox_client import ToolboxProviderUnavailable

        with pytest.raises(ToolboxProviderUnavailable):
            await extract_fused("arquivo.pdf")

    @pytest.mark.asyncio
    async def test_basic_fusion(self, monkeypatch):
        async def fake_extract(provider):
            if provider == "docling":
                return _payload([
                    _el("Parágrafo comum aos dois providers aqui", 0,
                        bbox=[10, 10, 90, 30], page_size=[100, 100]),
                    _el("Só no docling texto suficiente", 1,
                        bbox=[10, 80, 90, 95], page_size=[100, 100]),
                ])
            return _payload([
                _el("Parágrafo comum aos dois providers aqui", 0,
                    bbox=[10, 10, 90, 30], page_size=[100, 100]),
            ])

        monkeypatch.setattr(
            "backend.pipeline.fusion.ToolboxClient",
            _FakeClientFactory(extract_fn=fake_extract),
        )
        result = await extract_fused("arquivo.pdf")
        assert result["status"] == "succeeded"
        assert "docling+mineru" in result["provider"]
        texts = [e["text"] for e in result["document"]["elements"]]
        assert "Parágrafo comum aos dois providers aqui" in texts
        # docling-only aparece (min_len=0)
        assert "Só no docling texto suficiente" in texts
        assert result["fusion_stats"]

    @pytest.mark.asyncio
    async def test_mineru_skeleton_order(self, monkeypatch):
        """Reading order follows the secondary provider (MinerU)."""
        async def fake_extract(provider):
            if provider == "docling":
                return _payload([
                    _el("B", 0, bbox=[0, 40, 100, 60], page_size=[100, 100]),
                    _el("A", 1, bbox=[0, 0, 100, 30], page_size=[100, 100]),
                ])
            return _payload([
                _el("A", 0, bbox=[0, 0, 100, 30], page_size=[100, 100]),
                _el("B", 1, bbox=[0, 40, 100, 60], page_size=[100, 100]),
            ])

        monkeypatch.setattr(
            "backend.pipeline.fusion.ToolboxClient",
            _FakeClientFactory(extract_fn=fake_extract),
        )
        result = await extract_fused("arquivo.pdf")
        texts = [e["text"] for e in result["document"]["elements"]]
        assert texts.index("A") < texts.index("B")


class _FakeClientFactory:
    """Builds fake clients with an async extract_structure."""

    def __init__(self, extract_fn):
        self.extract_fn = extract_fn

    def __call__(self, provider: str = "docling", **kw):
        return _FakeClient(provider, self.extract_fn)


class _FakeClient:
    def __init__(self, provider, extract_fn):
        self.provider = provider
        self._extract_fn = extract_fn

    async def extract_structure(self, file_path, *, language="pt-BR", **kw):
        return await self._extract_fn(self.provider)
