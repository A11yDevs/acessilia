"""Testes da extração de números de linha marginais (``docstruct.fusion.line_numbers``).

Espelham a semântica fixada por ``tests/test_drbench_line_numbers.py`` sobre o
script do Dr.DocBench, agora sobre a API tipada da biblioteca.
"""
from collections import Counter

from docstruct.fusion.line_numbers import extract_line_numbers, line_number_chain
from docstruct.fusion.types import DiffBlock


def mk(text, box=None, kind="text", md=None, **kw):
    return DiffBlock(md=md or text, kind=kind, box=box, text=text, type=kw.pop("type", kind), **kw)


class TestLineNumberChain:
    def test_cadeia_de_passo_cinco(self):
        step, idx = line_number_chain([10, 15, 20, 25])
        assert step == 5
        assert idx == {0, 1, 2, 3}

    def test_cadeia_de_passo_quatro(self):
        step, idx = line_number_chain([4, 8, 12])
        assert step == 4
        assert idx == {0, 1, 2}

    def test_valores_nao_precisam_ser_adjacentes(self):
        step, idx = line_number_chain([10, 1999, 15, 20])
        assert step == 5
        assert idx == {0, 2, 3}

    def test_cadeia_menor_que_min_len_e_rejeitada(self):
        assert line_number_chain([10, 15])[1] == set()

    def test_sem_progressao_aritmetica(self):
        assert line_number_chain([1, 7, 33, 91])[1] == set()

    def test_cadeia_mais_longa_vence(self):
        step, idx = line_number_chain([2, 4, 6, 8, 100, 105, 110])
        assert step == 2
        assert len(idx) == 4

    def test_entrada_vazia(self):
        assert line_number_chain([]) == (0, set())


class TestExtractLineNumbers:
    def _md(self) -> str:
        return ("word " * 30) + " 10 more words 15 more words 20 more words 25"

    def test_numeros_inline_sao_extraidos(self):
        stats = Counter()
        out = extract_line_numbers([mk(self._md(), box=(0.0, 0.0, 1.0, 1.0))], stats, "docling")
        assert len(out) > 1
        assert stats["line-numbers-docling"] == 1
        assert stats["line-numbers-docling-count"] == 4

    def test_numeros_viram_blocos_separados_apos_o_texto(self):
        stats = Counter()
        out = extract_line_numbers([mk(self._md(), box=(0.0, 0.0, 1.0, 1.0))], stats, "docling")
        assert out[0].verse_nums is True
        assert [b.md for b in out[1:]] == ["10", "15", "20", "25"]
        assert all(b.type == "line_number" for b in out[1:])

    def test_bloco_curto_e_ignorado(self):
        stats = Counter()
        out = extract_line_numbers([mk("10 15 20 25")], stats, "docling")
        assert len(out) == 1
        assert stats["line-numbers-docling"] == 0

    def test_menos_de_tres_numeros_e_ignorado(self):
        stats = Counter()
        out = extract_line_numbers([mk(("word " * 30) + " 10 more 15")], stats, "docling")
        assert len(out) == 1

    def test_blocos_nao_textuais_ficam_intactos(self):
        block = mk(self._md(), kind="table")
        stats = Counter()
        assert extract_line_numbers([block], stats, "docling") == [block]

    def test_bloco_ja_processado_nao_e_reprocessado(self):
        block = mk(self._md(), verse_nums=True)
        stats = Counter()
        assert extract_line_numbers([block], stats, "docling") == [block]

    def test_bloco_que_ficaria_vazio_e_mantido_inteiro(self):
        md = " ".join(str(n) for n in range(10, 205, 5))
        stats = Counter()
        out = extract_line_numbers([mk(md)], stats, "docling")
        assert len(out) == 1
        assert stats["line-numbers-docling"] == 0

    def test_boxes_dos_numeros_derivam_do_bloco(self):
        stats = Counter()
        out = extract_line_numbers([mk(self._md(), box=(0.0, 0.0, 1.0, 1.0))], stats, "docling")
        for b in out[1:]:
            assert b.box is not None
            assert b.box[2] <= 1.0

    def test_bloco_sem_box_nao_quebra(self):
        stats = Counter()
        out = extract_line_numbers([mk(self._md())], stats, "docling")
        assert all(b.box is None for b in out[1:])

    def test_metadados_do_bloco_original_sao_preservados(self):
        stats = Counter()
        out = extract_line_numbers([mk(self._md(), type="paragraph", role="header")], stats, "docling")
        assert out[0].type == "paragraph"
        assert out[0].role == "header"
