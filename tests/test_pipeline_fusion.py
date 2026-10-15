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

    def test_manifest_page_number_is_normalized_to_zero_based_index(self):
        payload = _payload([
            {"type": "paragraph", "text": "página 1", "page_number": 1}
        ])

        groups = _group_by_page(payload)

        assert set(groups) == {0}


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
    async def test_unexpected_provider_error_is_not_hidden(self, monkeypatch):
        async def fake_extract(provider):
            raise FileNotFoundError("arquivo ausente")

        monkeypatch.setattr(
            "backend.pipeline.fusion.ToolboxClient",
            _FakeClientFactory(extract_fn=fake_extract),
        )

        with pytest.raises(FileNotFoundError, match="arquivo ausente"):
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
        assert result["fusion_evidence"]["pages"][0]["page_number"] == 1
        assert result["fusion_evidence"]["pages"][0]["stats"]["provider_count"] == 2

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

    @pytest.mark.asyncio
    async def test_repetition_guard_changes_fused_output(self, monkeypatch):
        async def fake_extract(provider):
            return _payload([_el("observacao", 0)])

        def fake_merge_blocks(*args, **kwargs):
            return [" ".join(["observacao"] * 6)], {}

        monkeypatch.setattr(
            "backend.pipeline.fusion.ToolboxClient",
            _FakeClientFactory(extract_fn=fake_extract),
        )
        monkeypatch.setattr("backend.pipeline.fusion.merge_blocks", fake_merge_blocks)

        result = await extract_fused("arquivo.pdf")

        assert result["document"]["elements"][0]["text"].strip() == "observacao"
        assert (
            result["fusion_evidence"]["pages"][0]["stats"]["repetition_tokens_cut"]
            == 5
        )

    @pytest.mark.asyncio
    async def test_fusion_stats_are_page_local_and_not_double_counted(
        self, monkeypatch
    ):
        async def fake_extract(provider):
            if provider == "docling":
                return _payload([
                    _el("Mesmo texto", 0, page=0),
                    _el("Texto Docling", 1, page=1),
                ])
            return _payload([
                _el("Mesmo texto", 0, page=0),
                _el("Texto MinerU", 1, page=1),
            ])

        def fake_merge_blocks(docling, mineru, policy, *, stats, **kwargs):
            stats["pair-text-auto->mineru"] += 1
            return [docling[0].md], stats

        monkeypatch.setattr(
            "backend.pipeline.fusion.ToolboxClient",
            _FakeClientFactory(extract_fn=fake_extract),
        )
        monkeypatch.setattr("backend.pipeline.fusion.merge_blocks", fake_merge_blocks)

        result = await extract_fused("arquivo.pdf")
        pages = result["fusion_evidence"]["pages"]

        assert [page["page_number"] for page in pages] == [1, 2]
        assert pages[0]["stats"]["pair-text-auto->mineru"] == 1
        assert pages[1]["stats"]["pair-text-auto->mineru"] == 1
        assert pages[0]["stats"]["text_divergence"] is False
        assert pages[1]["stats"]["text_divergence"] is True
        assert result["fusion_stats"]["pair-text-auto->mineru"] == 2


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
