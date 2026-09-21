"""Golden tests for the regions port (Phase 2, slice 3).

Also locks in the de-overfitting decision: no document-specific
callout titles in the lib — they are injected.
"""
from docstruct.regions.classify import (
    DOCLING_CLASSIFICATION,
    classify_region,
    formula_already_extracted,
    region_has_markers,
    region_needs_vision,
    region_prompt_key,
)
from docstruct.regions.grouping import (
    _estimate_main_text_band,
    _is_known_callout_title,
    _merge_bboxes,
    _normalize_text_key,
    _starts_with_list_marker,
)
from docstruct.types import Region


def _region(type_, text, bbox=(0, 0, 100, 50), **kw):
    metadata = kw.pop("metadata", {})
    return Region(
        bbox=bbox, type=type_, text=text, image_bytes=None,
        confidence=1.0, page_num=1, metadata=metadata,
        **kw,
    )


class TestNoOverfitting:
    def test_sem_constantes_de_documento(self):
        """The lib must NOT ship document-specific callout titles."""
        import docstruct.regions.grouping as g
        import inspect

        src = inspect.getsource(g)
        assert "precisamos mesmo de outra classe" not in src
        assert "super e sub classe" not in src
        assert not hasattr(g, "KNOWN_CALLOUT_TITLES")

    def test_default_sem_titulos(self):
        assert _is_known_callout_title("qualquer") is False

    def test_injecao_funciona(self):
        titles = frozenset({"super e sub classe"})
        assert _is_known_callout_title("Super e Sub Classe", titles) is True


class TestClassify:
    def test_docling_map(self):
        assert DOCLING_CLASSIFICATION["text"] == "text_clean"
        assert DOCLING_CLASSIFICATION["list"] == "list_block"

    def test_docling_region_tem_prioridade(self):
        r = _region("text", "x", metadata={"source": "docling"})
        assert classify_region(r) == "text_clean"

    def test_texto_limpo(self):
        r = _region("text", "a" * 40, metadata={"total_chars": 40, "text_density": 0.02})
        assert classify_region(r) == "text_clean"

    def test_texto_escaneado(self):
        r = _region("text", "abc", metadata={"total_chars": 6, "text_density": 0.006})
        assert classify_region(r) == "text_scanned"

    def test_imagem_com_bytes(self):
        r = _region("image", "", image_bytes=b"x") if False else Region(bbox=(0, 0, 100, 50), type="image", text="", image_bytes=b"x", confidence=1.0, page_num=1)
        assert classify_region(r) == "embedded_image"

    def test_imagem_pequena_ignorada(self):
        r = _region("image", "", bbox=(0, 0, 10, 10))
        assert classify_region(r) == "ignore"

    def test_formula_grande(self):
        r = _region("formula", "$$", bbox=(0, 0, 40, 40))
        assert classify_region(r) == "formula"

    def test_formula_pequena_ignorada(self):
        r = _region("formula", "$$", bbox=(0, 0, 10, 10))
        assert classify_region(r) == "ignore"

    def test_vision(self):
        assert region_needs_vision("text_scanned")
        assert region_needs_vision("embedded_image")
        assert not region_needs_vision("text_clean")

    def test_markers(self):
        assert region_has_markers("code_block")
        assert not region_has_markers("text_clean")

    def test_prompt_key(self):
        assert region_prompt_key("table") == "regiao_tabela"

    def test_formula_enriched(self):
        r = _region("formula", "$x$", metadata={"formula_enriched": True})
        assert formula_already_extracted(r)


class TestGrouping:
    def test_merge_bboxes(self):
        assert _merge_bboxes([(0, 0, 10, 10), (12, 2, 20, 9)]) == [(0.0, 0.0, 20.0, 10.0)]

    def test_starts_with_list_marker(self):
        assert _starts_with_list_marker("- item")
        assert _starts_with_list_marker("1. item")
        assert not _starts_with_list_marker("9.1 Seção")

    def test_normalize_text_key(self):
        assert _normalize_text_key("  A   B  ") == "a b"

    def test_main_text_band(self):
        regions = [
            _region("text", "t", bbox=(0, 0, 100, 20)),
            _region("text", "t", bbox=(0, 30, 100, 50)),
        ]
        y0, y1 = _estimate_main_text_band(regions)
        assert y0 <= 30 and y1 >= 30
