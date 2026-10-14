"""Testes do oráculo por bloco (``docstruct.fusion.oracle``).

Espelham a semântica de ``block_oracle.py`` do Dr.DocBench (PR #125).
"""
import difflib

from docstruct.fusion.oracle import (
    best_score,
    gt_text_blocks,
    kind_of,
    oracle_page,
    page_scores,
    summarize,
)


class TestKindOf:
    def test_tabela(self):
        assert kind_of("<table><tr></tr></table>") == "table"

    def test_formula(self):
        assert kind_of("$$ x $$") == "formula"

    def test_formula_colchete(self):
        assert kind_of("\\[ x \\]") == "formula"

    def test_texto(self):
        assert kind_of("plain text") == "text"


class TestBestScore:
    def test_bloco_identico(self):
        sm = difflib.SequenceMatcher()
        sm.set_seq1("hello world")
        assert best_score("hello world", ["hello world"], sm) == 1.0

    def test_melhor_entre_varios(self):
        sm = difflib.SequenceMatcher()
        sm.set_seq1("hello world")
        assert best_score("hello world", ["zzz", "hello world"], sm) == 1.0

    def test_sem_blocos(self):
        sm = difflib.SequenceMatcher()
        sm.set_seq1("hello")
        assert best_score("hello", [], sm) == 0.0

    def test_sem_similaridade(self):
        sm = difflib.SequenceMatcher()
        sm.set_seq1("abc")
        assert best_score("abc", ["xyz"], sm) == 0.0


class TestPageScores:
    def test_score_medio_por_provider(self):
        sm = difflib.SequenceMatcher()
        out = page_scores(["hello world"], {"a": ["hello world"], "b": ["zzz"]}, sm)
        assert out["a"] == 1.0
        assert out["b"] == 0.0

    def test_sem_blocos_de_gt(self):
        sm = difflib.SequenceMatcher()
        out = page_scores([], {"a": ["x"]}, sm)
        assert out["a"] != out["a"]  # nan


class TestGtTextBlocks:
    def test_filtra_tabelas_e_formulas(self):
        blocks = ["plain text that is long enough here", "<table>x</table>", "$$ y $$"]
        assert gt_text_blocks(blocks) == ["plain text that is long enough here"]

    def test_filtra_blocos_curtos(self):
        assert gt_text_blocks(["short"]) == []

    def test_normaliza(self):
        assert gt_text_blocks(["**Hello** world this is long enough"]) == ["hello world this is long enough"]


class TestOraclePage:
    def test_oracle_escolhe_o_melhor_provider(self):
        sm = difflib.SequenceMatcher()
        gt = ["hello world this is long enough"]
        pred = {"docling": ["hello world this is long enough"], "mineru": ["zzz"], "differ": ["zzz"]}
        out = oracle_page(gt, pred, sm)
        assert out["oracle"] == 1.0
        assert out["headroom"] == 1.0

    def test_differ_no_oraculo_nao_tem_folga(self):
        sm = difflib.SequenceMatcher()
        gt = ["hello world this is long enough"]
        pred = {"docling": ["hello world this is long enough"], "mineru": ["zzz"],
                "differ": ["hello world this is long enough"]}
        out = oracle_page(gt, pred, sm)
        assert out["headroom"] == 0.0

    def test_sem_blocos_de_gt(self):
        sm = difflib.SequenceMatcher()
        out = oracle_page([], {"docling": [], "mineru": [], "differ": []}, sm)
        assert out["oracle"] != out["oracle"]  # nan


class TestSummarize:
    def _row(self, headroom: float) -> dict:
        return {"docling": 0.5, "mineru": 0.6, "differ": 0.7, "oracle": 0.8, "headroom": headroom}

    def test_medias(self):
        out = summarize([self._row(0.1), self._row(0.3)])
        assert out["n"] == 2
        assert out["oracle"] == 0.8
        assert out["headroom"] == 0.2

    def test_contagem_de_paginas_com_folga(self):
        out = summarize([self._row(0.1), self._row(0.01)])
        assert out["pages_with_headroom"] == 1
        assert out["pages_with_headroom_pct"] == 50.0

    def test_contagem_de_paginas_no_oraculo(self):
        out = summarize([self._row(0.001), self._row(0.1)])
        assert out["pages_at_oracle"] == 1

    def test_lista_vazia(self):
        assert summarize([]) == {"n": 0}
