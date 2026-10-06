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

    def test_toolbox_manifest_provenance_is_normalized(self):
        payload = {
            "document": {
                "pages": [{"page_number": 2, "width": 400, "height": 600}],
                "elements": [{
                    "type": "formula",
                    "text": "x^2",
                    "reading_order": 7,
                    "page_number": 2,
                    "provenance": [{
                        "page_number": 2,
                        "bbox": {
                            "left": 10, "top": 20, "right": 90, "bottom": 40,
                            "coord_origin": "TOPLEFT",
                        },
                    }],
                }],
            },
        }
        block = _group_by_page(payload)[1][0]
        assert block["bbox"] == [10.0, 20.0, 90.0, 40.0]
        assert block["page_index"] == 1
        assert block["metadata"]["page_size"] == [400, 600]


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

    @pytest.mark.asyncio
    async def test_specialist_adds_only_tables_and_formulas(self, monkeypatch):
        base_text = "Texto de Docling e MinerU preservado"

        async def fake_extract(provider):
            if provider in {"docling", "mineru"}:
                return _payload([_el(base_text, 0)])
            return _payload([
                _el("prosa do especialista não deve entrar", 0),
                _el(r"x^2 + y^2", 1, type_="formula"),
                _el("$\\sin x$", 2),
                _el("<table><tr><td>valor</td></tr></table>", 3, type_="table",
                    metadata={"table_ast": {"body": [{"cells": [{"text": "valor"}]}]}}),
            ])

        monkeypatch.setattr(
            "backend.pipeline.fusion.ToolboxClient",
            _FakeClientFactory(extract_fn=fake_extract),
        )
        result = await extract_fused("arquivo.png", structure_provider="teleocr")
        elements = result["document"]["elements"]
        assert elements[0]["text"] == base_text
        assert [(element["type"], element["text"]) for element in elements[1:]] == [
            ("formula", r"x^2 + y^2"),
            ("formula", r"\sin x"),
            ("table", "<table><tr><td>valor</td></tr></table>"),
        ]
        assert all(element["metadata"]["supplemental"] for element in elements[1:])
        assert result["provider"] == "docling+mineru+teleocr"
        assert result["fusion_stats"]["supplemental_structures"] == 3

        from scripts.drbench.markdown_converter import canonical_to_drbench_md
        from scripts.drbench.run_pipeline import provider_payload_to_canonical

        markdown = canonical_to_drbench_md(provider_payload_to_canonical(result))
        assert base_text in markdown
        assert "$$\nx^2 + y^2\n$$" in markdown
        assert "$$\n\\sin x\n$$" in markdown
        assert "<table>" in markdown and "valor" in markdown

    @pytest.mark.asyncio
    async def test_teleocr_pdf_is_rendered_once_per_page_with_provenance(
        self, monkeypatch, tmp_path
    ):
        import fitz

        source = tmp_path / "two-pages.pdf"
        pdf = fitz.open()
        pdf.new_page(width=400, height=600)
        pdf.new_page(width=400, height=600)
        pdf.save(source)
        pdf.close()
        calls = []

        class Client:
            def __init__(self, provider):
                self.provider = provider

            async def extract_structure(self, file_path, **kwargs):
                if self.provider != "teleocr":
                    return _payload([
                        _el("texto página 1", 0, page=0),
                        _el("texto página 2", 1, page=1),
                    ])
                calls.append(file_path)
                assert file_path.suffix == ".png"
                page_number = int(file_path.stem.rsplit("-", 1)[1])
                return {
                    "status": "succeeded",
                    "provenance": {
                        "provider_version": "1.2b",
                        "model_versions": {
                            "model_revision": "teleocr-test-revision",
                            "inference_configuration": "{\"batch_size\": 8}",
                        },
                    },
                    "document": {
                        "pages": [{"page_number": 1, "width": 1111, "height": 1667}],
                        "elements": [{
                            "type": "formula",
                            "text": f"x_{page_number}^2",
                            "reading_order": 1,
                            "page_number": 1,
                            "provenance": [{
                                "page_number": 1,
                                "bbox": {
                                    "left": 10, "top": 20, "right": 90, "bottom": 40,
                                    "coord_origin": "TOPLEFT",
                                },
                            }],
                        }],
                    },
                }

            async def close(self):
                pass

        monkeypatch.setattr(
            "backend.pipeline.fusion.ToolboxClient", lambda provider: Client(provider)
        )
        result = await extract_fused(source, structure_provider="teleocr")

        assert len(calls) == 2
        supplements = [e for e in result["document"]["elements"] if e["type"] == "formula"]
        assert [(e["page"], e["text"]) for e in supplements] == [
            (0, "x_1^2"), (1, "x_2^2")
        ]
        assert all(e["bbox"] == [10.0, 20.0, 90.0, 40.0] for e in supplements)
        assert all(e["metadata"]["page_size"] == [1111, 1667] for e in supplements)
        assert result["fusion_stats"]["specialist_provider_version"] == "1.2b"
        assert result["fusion_stats"]["specialist_model_versions"]["model_revision"] == (
            "teleocr-test-revision"
        )

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
