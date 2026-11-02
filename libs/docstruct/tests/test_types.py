"""Testes de types.py — contratos."""
from docstruct.types import (
    BlockPairing,
    CanonicalBlock,
    CanonicalDocument,
    CanonicalSection,
    OrientationResult,
    Region,
)


class TestCanonicalBlock:
    def test_sem_bbox_e_permitido(self):
        b = CanonicalBlock(id="1", type="paragraph", text="olá")
        assert b.bbox is None
        assert b.page_index is None

    def test_com_bbox(self):
        b = CanonicalBlock(id="1", type="heading", text="T", bbox=(0, 0, 10, 10), page_index=3)
        assert b.bbox == (0, 0, 10, 10)


class TestCanonicalDocument:
    def test_blocks_em_ordem_de_leitura(self):
        doc = CanonicalDocument(
            title="T",
            sections=[
                CanonicalSection(id="s1", level=1, title="A", blocks=[
                    CanonicalBlock(id="1", type="paragraph", text="a"),
                ]),
                CanonicalSection(id="s2", level=1, title="B", blocks=[
                    CanonicalBlock(id="2", type="paragraph", text="b"),
                    CanonicalBlock(id="3", type="paragraph", text="c"),
                ]),
            ],
        )
        assert [b.id for b in doc.blocks()] == ["1", "2", "3"]


class TestBlockPairing:
    def test_is_match(self):
        a = CanonicalBlock(id="1", type="p", text="x")
        b = CanonicalBlock(id="2", type="p", text="x")
        assert BlockPairing(a=a, b=b).is_match
        assert not BlockPairing(a=a, b=None).is_match
        assert not BlockPairing(a=None, b=b).is_match


class TestOrientationResult:
    def test_needs_correction(self):
        assert not OrientationResult(0, 0, 0.99).needs_correction
        assert OrientationResult(0, 270, 0.99).needs_correction


class TestRegion:
    def test_campo_obrigatorios(self):
        r = Region(bbox=(0, 0, 1, 1), type="text", text="t", image_bytes=None, confidence=1.0, page_num=0)
        assert r.metadata == {}
