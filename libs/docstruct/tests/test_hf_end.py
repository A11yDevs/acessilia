"""Testes da convenção de cabeçalho/rodapé no fim (``docstruct.fusion.hf_end``).

Espelham a semântica de ``hfmove.py`` e do ``--hf-end`` de ``dots_page_ocr.py``
do Dr.DocBench (PR #125).
"""
import pytest

from docstruct.fusion.hf_end import (
    hf_categories_texts,
    hf_norm,
    hf_texts,
    move_body_hf_to_tail,
    move_hf_to_end,
)


class TestHfNorm:
    def test_remove_pontuacao_e_baixa_caixa(self):
        assert hf_norm("Page 42!") == "page42"

    def test_none_vira_vazio(self):
        assert hf_norm(None) == ""


class TestMoveHfToEnd:
    def test_header_e_footer_vao_para_o_fim(self):
        els = [
            {"category": "Page-header", "text": "H"},
            {"category": "Text", "text": "body"},
            {"category": "Page-footer", "text": "F"},
        ]
        out = move_hf_to_end(els)
        assert [e["text"] for e in out] == ["body", "H", "F"]

    def test_ordem_relativa_e_preservada(self):
        els = [
            {"category": "Page-header", "text": "H1"},
            {"category": "Page-header", "text": "H2"},
            {"category": "Text", "text": "body"},
        ]
        assert [e["text"] for e in move_hf_to_end(els)] == ["body", "H1", "H2"]

    def test_sem_hf_nao_muda(self):
        els = [{"category": "Text", "text": "a"}, {"category": "Text", "text": "b"}]
        assert move_hf_to_end(els) == els

    def test_entrada_nao_e_modificada(self):
        els = [{"category": "Page-header", "text": "H"}, {"category": "Text", "text": "b"}]
        move_hf_to_end(els)
        assert els[0]["text"] == "H"


class TestHfTexts:
    def test_extrai_textos_de_header_footer_e_numero(self):
        blocks = [
            {"type": "header", "text": "Running Head"},
            {"type": "page_number", "text": "42"},
            {"type": "text", "text": "body"},
        ]
        assert hf_texts(blocks) == {"runninghead", "42"}

    def test_ignora_textos_vazios(self):
        assert hf_texts([{"type": "header", "text": ""}]) == set()


class TestHfCategoriesTexts:
    def test_extrai_de_page_header_e_footer(self):
        els = [
            {"category": "Page-header", "text": "H"},
            {"category": "Page-footer", "text": "F"},
            {"category": "Text", "text": "body"},
        ]
        assert hf_categories_texts(els) == {"h", "f"}


class TestMoveBodyHfToTail:
    def test_bloco_do_corpo_e_movido_para_a_cauda(self):
        blocks = ["Running Head", "body text", "other body"]
        out = move_body_hf_to_tail(blocks, {"runninghead"}, {"runninghead"})
        assert out == ["body text", "other body", "Running Head"]

    def test_need_both_exige_os_dois_layouts(self):
        blocks = ["Running Head", "body text"]
        assert move_body_hf_to_tail(blocks, {"runninghead"}, set(), need="both") == blocks
        assert move_body_hf_to_tail(blocks, {"runninghead"}, set(), need="one") == ["body text", "Running Head"]

    def test_cauda_existente_e_preservada(self):
        blocks = ["Running Head", "body text", "Running Head"]
        out = move_body_hf_to_tail(blocks, {"runninghead"}, {"runninghead"})
        assert out == ["body text", "Running Head", "Running Head"]

    def test_bloco_longo_nao_e_movido(self):
        long_hf = "Running Head " + "x" * 100
        blocks = [long_hf, "body text"]
        assert move_body_hf_to_tail(blocks, {hf_norm(long_hf)}, {hf_norm(long_hf)}) == blocks

    def test_marcacao_de_heading_e_ignorada(self):
        blocks = ["# Running Head", "body text"]
        out = move_body_hf_to_tail(blocks, {"runninghead"}, {"runninghead"})
        assert out == ["body text", "# Running Head"]

    def test_pagina_so_de_hf_nao_e_alterada(self):
        blocks = ["Running Head", "42"]
        assert move_body_hf_to_tail(blocks, {"runninghead", "42"}, {"runninghead", "42"}) == blocks

    def test_need_invalido(self):
        with pytest.raises(ValueError):
            move_body_hf_to_tail(["a"], set(), set(), need="nope")

    def test_entrada_nao_e_modificada(self):
        blocks = ["Running Head", "body text"]
        move_body_hf_to_tail(blocks, {"runninghead"}, {"runninghead"})
        assert blocks == ["Running Head", "body text"]
