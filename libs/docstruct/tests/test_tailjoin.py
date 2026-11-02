"""Testes da junção de cauda (``docstruct.fusion.tailjoin``).

Espelham a semântica de ``tailjoin.py`` / ``tailjoin3.py`` do Dr.DocBench
(PR #125), agora sobre a API pura da biblioteca.
"""
import pytest

from docstruct.fusion.tailjoin import (
    is_page_number,
    is_short_block,
    join_tail,
    page_number_position,
    tail_start,
    tailjoin3,
)
from docstruct.fusion.types import DiffBlock


def mk(text, box=None, kind="text", md=None, **kw):
    return DiffBlock(md=md or text, kind=kind, box=box, text=text, type=kw.pop("type", kind), **kw)


class TestIsPageNumber:
    def test_arabico(self):
        assert is_page_number("42") is True

    def test_romano(self):
        assert is_page_number("xiv") is True
        assert is_page_number("XIV") is True

    def test_texto_nao_e_numero(self):
        assert is_page_number("RUNNING HEAD") is False

    def test_numero_longo_demais(self):
        assert is_page_number("123456") is False

    def test_espacos_sao_ignorados(self):
        assert is_page_number("  42  ") is True


class TestIsShortBlock:
    def test_curto_de_linha_unica(self):
        assert is_short_block("RUNNING HEAD", 50) is True

    def test_multilinha_nao_e_curto(self):
        assert is_short_block("a\nb", 50) is False

    def test_longo_demais(self):
        assert is_short_block("x" * 60, 50) is False


class TestTailStart:
    def test_cauda_de_dois_blocos_curtos(self):
        assert tail_start(["body", "HEAD", "42"], 50, 3) == 1

    def test_k_limita_o_tamanho_da_cauda(self):
        assert tail_start(["body", "a", "b", "c"], 50, 2) == 2

    def test_para_no_primeiro_bloco(self):
        assert tail_start(["a", "b"], 50, 5) == 1

    def test_bloco_longo_interrompe(self):
        assert tail_start(["body", "x" * 60, "42"], 50, 3) == 2


class TestJoinTail:
    def test_modo_any_junta_dois_blocos(self):
        assert join_tail(["body", "HEAD", "42"], "any", 50, 3) == ["body", "HEAD 42"]

    def test_modo_num_exige_numero(self):
        assert join_tail(["body", "HEAD", "FOOT"], "num", 50, 3) == ["body", "HEAD", "FOOT"]
        assert join_tail(["body", "HEAD", "42"], "num", 50, 3) == ["body", "HEAD 42"]

    def test_modo_end_exige_numero_numa_ponta(self):
        assert join_tail(["body", "42", "HEAD"], "end", 50, 3) == ["body", "42 HEAD"]
        assert join_tail(["body", "HEAD", "42"], "end", 50, 3) == ["body", "HEAD 42"]
        assert join_tail(["body", "HEAD", "FOOT"], "end", 50, 3) == ["body", "HEAD", "FOOT"]

    def test_cauda_de_um_bloco_nao_junta(self):
        assert join_tail(["body", "42"], "any", 50, 3) == ["body", "42"]

    def test_pagina_so_de_cauda_nao_junta(self):
        assert join_tail(["HEAD", "42"], "any", 50, 3) == ["HEAD", "42"]

    def test_modo_invalido(self):
        with pytest.raises(ValueError):
            join_tail(["a", "b"], "nope", 50, 3)

    def test_entrada_nao_e_modificada(self):
        blocks = ["body", "HEAD", "42"]
        join_tail(blocks, "any", 50, 3)
        assert blocks == ["body", "HEAD", "42"]


class TestPageNumberPosition:
    def test_numero_no_topo(self):
        b = mk("42", box=(0.0, 0.0, 1.0, 0.1), role="page_number")
        assert page_number_position([b]) == "top"

    def test_numero_no_rodape(self):
        b = mk("42", box=(0.0, 0.9, 1.0, 1.0), role="page_number")
        assert page_number_position([b]) == "bot"

    def test_sem_numero_de_pagina(self):
        assert page_number_position([mk("body", box=(0.0, 0.0, 1.0, 1.0))]) is None

    def test_bloco_sem_box_e_ignorado(self):
        assert page_number_position([mk("42", role="page_number")]) is None

    def test_role_irrelevante_e_ignorado(self):
        assert page_number_position([mk("42", box=(0.0, 0.0, 1.0, 0.1))]) is None


class TestTailjoin3:
    def test_topo_junta_a_cauda(self):
        assert tailjoin3(["body", "HEAD", "42"], "top", 50, 3) == ["body", "HEAD 42"]

    def test_rodape_com_keep_deixa_intacto(self):
        assert tailjoin3(["body", "HEAD", "42"], "bot", 50, 3, bot="keep") == ["body", "HEAD", "42"]

    def test_rodape_com_hdr_move_o_numero_para_o_fim(self):
        assert tailjoin3(["body", "42", "HEAD"], "bot", 50, 3, bot="hdr") == ["body", "HEAD", "42"]

    def test_posicao_desconhecida_junta(self):
        assert tailjoin3(["body", "HEAD", "42"], None, 50, 3) == ["body", "HEAD 42"]

    def test_sem_numero_na_cauda_nao_junta(self):
        assert tailjoin3(["body", "HEAD", "FOOT"], "top", 50, 3) == ["body", "HEAD", "FOOT"]

    def test_bot_invalido(self):
        with pytest.raises(ValueError):
            tailjoin3(["body", "HEAD", "42"], "bot", 50, 3, bot="nope")
