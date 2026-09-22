"""Testes do núcleo de fusão: Húngaro puro, conversão e merge_blocks."""
from collections import Counter

from docstruct.fusion._hungarian import linear_sum_assignment
from docstruct.fusion.convert import block_to_diff, normalize_bbox
from docstruct.fusion.differ import merge_blocks
from docstruct.fusion.noise import is_junk, quality
from docstruct.fusion.similarity import iou, sim
from docstruct.fusion.types import DiffBlock
from docstruct.policy import FusionPolicy


def mk(text, box=None, kind="text", md=None, **kw):
    return DiffBlock(md=md or text, kind=kind, box=box, text=text, type=kw.pop("type", kind), **kw)


class TestHungarian:
    def test_identidade(self):
        cost = [[0, 1], [1, 0]]
        assert sorted(linear_sum_assignment(cost)) == [(0, 0), (1, 1)]

    def test_swapped(self):
        cost = [[1, 0], [0, 1]]
        assert sorted(linear_sum_assignment(cost)) == [(0, 1), (1, 0)]

    def test_retangular(self):
        cost = [[1, 2, 3], [4, 5, 6]]
        pairs = linear_sum_assignment(cost)
        assert len(pairs) == 2
        cols = {j for _, j in pairs}
        assert cols == {0, 1} or cols == {2, 1} or len(cols) == 2

    def test_otimo_minimo(self):
        # ótimo: 0+1 = 1 (não 3+1=4 nem 0+... )
        cost = [[0, 3], [5, 1]]
        pairs = dict(linear_sum_assignment(cost))
        assert cost[0][pairs[0]] + cost[1][pairs[1]] == 1

    def test_3x3(self):
        cost = [[4, 1, 3], [2, 0, 5], [3, 2, 2]]
        pairs = dict(linear_sum_assignment(cost))
        total = sum(cost[i][j] for i, j in pairs.items())
        # ótimo: 1 (0,1) + 0 (1,1)? não — colunas distintas: {1,0,2} = 1+2+2=5 ou 4+0+2=6... verificado: 5
        assert total == 5


class TestSimilarity:
    def test_iou_idênticos(self):
        assert iou((0, 0, 1, 1), (0, 0, 1, 1)) == 1.0

    def test_iou_disjuntos(self):
        assert iou((0, 0, 1, 1), (2, 2, 3, 3)) == 0.0

    def test_iou_none(self):
        assert iou(None, (0, 0, 1, 1)) == 0.0

    def test_sim(self):
        assert sim("abc", "abc") == 1.0
        assert sim("", "abc") == 0.0


class TestQuality:
    def test_texto_bom(self):
        assert quality("the quick brown fox jumps") > 0.8

    def test_ocr_lixo(self):
        assert quality("!!! ### ??? %%%") < 0.34

    def test_is_junk_repetido(self):
        assert is_junk("aaaa aa")

    def test_is_junk_pagenum_nao(self):
        assert not is_junk("102")


class TestNormalizeBbox:
    def test_top_left(self):
        b = normalize_bbox((0.1, 0.2, 0.5, 0.6), (1.0, 1.0), "TOPLEFT")
        assert b == (0.1, 0.2, 0.5, 0.6)

    def test_bottom_left_flip(self):
        # bbox y=80..90 numa página de altura 100 → y=0.1..0.2 após flip
        b = normalize_bbox((10.0, 80.0, 50.0, 90.0), (100.0, 100.0), "BOTTOMLEFT")
        assert abs(b[1] - 0.10) < 1e-9 and abs(b[3] - 0.20) < 1e-9

    def test_sem_page_size(self):
        assert normalize_bbox((0.1, 0.2, 0.5, 0.6), None) is None


class TestConvert:
    def test_canonical_para_diff(self):
        from docstruct.types import CanonicalBlock

        cb = CanonicalBlock(
            id="1", type="heading", text="Introdução",
            bbox=(0.1, 0.1, 0.9, 0.2),
            metadata={"page_size": (100.0, 200.0), "markdown": "# Introdução"},
        )
        db = block_to_diff(cb)
        assert db.kind == "heading"
        assert db.box is not None and db.box[0] == 0.1
        assert db.md == "# Introdução"


class TestMergeBlocks:
    def test_paginas_vazias(self):
        policy = FusionPolicy()
        out, stats = merge_blocks([], [mk("x")], policy)
        assert out == ["x"]

    def test_match_exato(self):
        policy = FusionPolicy(align_tau=0.9)
        D = [mk("Texto igual aqui", box=(0.0, 0.0, 1.0, 0.3))]
        M = [mk("Texto igual aqui", box=(0.0, 0.0, 1.0, 0.3))]
        out, stats = merge_blocks(D, M, policy)
        assert out == ["Texto igual aqui"]
        assert stats["unilateral-docling"] == 0

    def test_esqueleto_mineru(self):
        policy = FusionPolicy(align_tau=0.6)  # tau default: texto distinto + IoU 0 não casa
        D = [mk("docling only block que existe so aqui", box=(0.0, 0.9, 1.0, 1.0))]
        M = [
            mk("primeiro bloco mineru do corpo", box=(0.0, 0.0, 1.0, 0.3)),
            mk("segundo bloco mineru do corpo", box=(0.0, 0.4, 1.0, 0.7)),
        ]
        out, stats = merge_blocks(D, M, policy, min_len=0)
        # docling-only é unilateral (não casou) e inserido junto ao mais próximo
        assert stats["unilateral-docling"] == 1
        assert len(out) == 3
        assert out[0].startswith("primeiro")
        assert out[2].startswith("docling only") or out[1].startswith("docling only")

    def test_tabela_vence(self):
        policy = FusionPolicy(align_tau=0.9)
        D = [mk("<table><tr><td>docling</td></tr></table>", kind="table", box=(0, 0, 1, 0.5))]
        M = [mk("texto simples tabela", kind="text", box=(0, 0, 1, 0.5))]
        out, _ = merge_blocks(D, M, policy)
        assert "<table>" in out[0]

    def test_formula_text_demote(self):
        policy = FusionPolicy(formula_text=True)
        D = [mk("$$CH_3$$", kind="formula", md="$$CH_3$$")]
        M = [mk("formula quimica", kind="text")]
        out, stats = merge_blocks(D, M, policy, min_len=0)
        assert any("CH" in o for o in out)
        assert stats.get("formula->text-docling", 0) == 1

    def test_junk_filter(self):
        policy = FusionPolicy(junk_filter=True)
        D = [mk("!!! ### ??? %%% ^^"), mk("texto real aqui ok")]
        M = [mk("texto real aqui ok")]
        out, _ = merge_blocks(D, M, policy)
        assert out == ["texto real aqui ok"]

    def test_decor_tail(self):
        policy = FusionPolicy(decor_tail=True)
        D = [mk("102", type="page_header"), mk("corpo do documento aqui")]
        M = [mk("corpo do documento aqui")]
        out, _ = merge_blocks(D, M, policy)
        assert out[-1] == "102"  # decor vai para o fim
        assert out[0] == "corpo do documento aqui"

    def test_stats_retornadas(self):
        policy = FusionPolicy(align_tau=0.9)
        D = [mk("a" * 50, box=(0, 0, 1, 0.5)), mk("b" * 50, box=(0, 0.5, 1, 1.0))]
        M = [mk("a" * 50, box=(0, 0, 1, 0.5)), mk("b" * 50, box=(0, 0.5, 1, 1.0))]
        out, stats = merge_blocks(D, M, policy)
        assert isinstance(stats, Counter)
        assert stats["unilateral-mineru"] == 0

    def test_suppress_in_picture_respeita_pic_min_blocks(self):
        """Regressão: pic_min_blocks/pic_rule da policy devem ser respeitados
        (paridade com o tree_differ_v2). Com pic_rule='quality' e poucos blocos
        legíveis, o texto dentro da figura sobrevive."""
        # 2 blocos legíveis dentro de uma figura (não é OCR de figura)
        D = [
            mk("New York", box=(0.2, 0.2, 0.4, 0.3)),
            mk("The world", box=(0.2, 0.35, 0.4, 0.45)),
        ]
        M = [mk("corpo", box=(0.0, 0.0, 1.0, 0.1))]
        m_pics = [(0.1, 0.1, 0.9, 0.9)]  # figura grande
        # pic_rule='quality' + pic_min_blocks=4: 2 < 4 → não suprime
        policy = FusionPolicy(suppress_regions=True, pic_rule="quality", pic_min_blocks=4, pic_need_text=False)
        out, stats = merge_blocks(D, M, policy, min_len=0, m_pics=m_pics)
        assert stats.get("suppress-in-picture", 0) == 0
        assert stats.get("keep-in-picture", 0) == 2
        assert len(out) == 3  # corpo + 2 rótulos

    def test_suppress_in_picture_quality_rule(self):
        """pic_rule='quality' suprime quando há muitos blocos de baixa qualidade."""
        D = [
            mk("a", box=(0.2, 0.2, 0.4, 0.3)),
            mk("b", box=(0.2, 0.35, 0.4, 0.45)),
            mk("c", box=(0.2, 0.5, 0.4, 0.6)),
            mk("d", box=(0.2, 0.65, 0.4, 0.75)),
            mk("e", box=(0.2, 0.8, 0.4, 0.9)),
        ]
        M = [mk("corpo", box=(0.0, 0.0, 1.0, 0.1))]
        m_pics = [(0.1, 0.1, 0.9, 0.9)]
        policy = FusionPolicy(suppress_regions=True, pic_rule="quality", pic_min_blocks=4, pic_need_text=False)
        out, stats = merge_blocks(D, M, policy, min_len=0, m_pics=m_pics)
        # 5 >= 4 e qualidade baixa (letras soltas) → suprime
        assert stats.get("suppress-in-picture", 0) == 5
        assert out == ["corpo"]
