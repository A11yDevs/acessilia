"""Testes da seleção/fusão de páginas (``docstruct.fusion.page_select``).

Espelham a semântica de ``page_fuse.py``, ``vlm_page_select.py`` e
``page_swap.py`` do Dr.DocBench (PR #125).
"""
import pytest

from docstruct.fusion.page_select import (
    blocks,
    fuse,
    page_agreement,
    page_norm,
    ratio,
    select_by_agreement,
    swap_low_agreement_pages,
    swap_norm,
)


class TestPageNorm:
    def test_remove_marcacao_e_baixa_caixa(self):
        assert page_norm("**Hello** _World_") == "hello world"

    def test_remove_tags_html(self):
        assert page_norm("<table><tr><td>x</td></tr></table>") == "x"

    def test_colapsa_espacos(self):
        assert page_norm("a   b\n\nc") == "a b c"

    def test_entrada_vazia(self):
        assert page_norm("") == ""


class TestSwapNorm:
    def test_remove_pontuacao_de_marcacao(self):
        assert swap_norm("# Title > body") == "title body"

    def test_colapsa_espacos(self):
        assert swap_norm("a   b") == "a b"


class TestBlocks:
    def test_divide_em_linhas_em_branco(self):
        assert blocks("one\n\ntwo\n\n\nthree") == ["one", "two", "three"]

    def test_ignora_pedacos_vazios(self):
        assert blocks("\n\n\n") == []

    def test_bloco_unico(self):
        assert blocks("only one") == ["only one"]


class TestRatio:
    def test_identico(self):
        assert ratio("abc", "abc") == 1.0

    def test_vazio_com_vazio(self):
        assert ratio("", "") == 1.0

    def test_vazio_com_nao_vazio(self):
        assert ratio("", "abc") == 0.0

    def test_sem_caracteres_em_comum(self):
        assert ratio("abc", "xyz") == 0.0

    def test_metade_em_comum(self):
        assert ratio("ab", "ac") == pytest.approx(0.5)


class TestPageAgreement:
    def test_paginas_iguais(self):
        assert page_agreement("hello world", "hello world") == 1.0

    def test_paginas_diferentes(self):
        assert page_agreement("hello world", "xyz") < 0.5


class TestFuse:
    def test_b_vazio_devolve_a_inalterado(self):
        a = "first\n\nsecond"
        assert fuse(a, "", "order", 0.5) == a

    def test_modo_order_mantem_a_contagem_de_blocos(self):
        out = fuse("alpha\n\nbeta", "alpha\n\nbeta", "order", 0.5)
        assert len(blocks(out)) == 2

    def test_modo_head_preserva_a_marcacao_de_heading(self):
        out = fuse("# Title\n\nbody text", "Title\n\nbody text", "head", 0.5)
        assert out.lstrip().startswith("#")

    def test_modo_swap_toma_o_texto_de_b(self):
        out = fuse("the quick brown fox", "the quick brown cat", "swap", 0.5)
        assert "cat" in out

    def test_modo_swap_mantem_a_abaixo_da_similaridade(self):
        out = fuse("completely different content here", "nothing alike at all", "swap", 0.99)
        assert "completely different" in out

    def test_modo_swap_nao_troca_tabelas_por_padrao(self):
        a = "<table><tr><td>alpha beta gamma</td></tr></table>"
        b = "<table><tr><td>alpha beta delta</td></tr></table>"
        assert "gamma" in fuse(a, b, "swap", 0.5)

    def test_modo_swap_troca_tabelas_quando_habilitado(self):
        a = "<table><tr><td>alpha beta gamma</td></tr></table>"
        b = "<table><tr><td>alpha beta delta</td></tr></table>"
        assert "delta" in fuse(a, b, "swap", 0.5, tables=True)

    def test_modo_invalido(self):
        with pytest.raises(ValueError):
            fuse("a", "b", "nope", 0.5)


class TestSelectByAgreement:
    def test_vlm_vazia_nao_troca(self):
        out, swapped = select_by_agreement("a", "", "d", "m", "stop")
        assert swapped is False
        assert out == "a"

    def test_geracao_incompleta_nao_troca(self):
        out, swapped = select_by_agreement("a", "vlm text", "d", "m", "length")
        assert swapped is False

    def test_alta_concordancia_nao_troca(self):
        out, swapped = select_by_agreement("a", "vlm text", "same text", "same text", "stop")
        assert swapped is False

    def test_baixa_concordancia_com_vlm_mais_longa_troca(self):
        out, swapped = select_by_agreement(
            "short", "a much longer vlm transcription here", "docling text", "zzz qqq", "stop"
        )
        assert swapped is True
        assert out != "short"

    def test_ab_permite_troca_sem_ser_mais_longa(self):
        out, swapped = select_by_agreement(
            "same text", "same text", "docling text", "zzz qqq", "stop", ab=0.9
        )
        assert swapped is True


class TestSwapLowAgreementPages:
    def test_sem_alternativa_nao_troca(self):
        out, swapped = swap_low_agreement_pages("base", None, "d", "m")
        assert swapped is False
        assert out == "base"

    def test_alta_concordancia_nao_troca(self):
        out, swapped = swap_low_agreement_pages("base", "alt", "same", "same")
        assert swapped is False

    def test_baixa_concordancia_troca(self):
        out, swapped = swap_low_agreement_pages("base text here", "alt text here", "aaa", "zzz")
        assert swapped is True
        assert out == "alt text here"

    def test_alternativa_curta_demais_nao_troca(self):
        out, swapped = swap_low_agreement_pages("a" * 100, "b", "aaa", "zzz")
        assert swapped is False
        assert out == "a" * 100
