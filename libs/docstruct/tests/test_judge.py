"""Testes da regra do juiz pareado (``docstruct.fusion.judge``).

Espelham a decisão de ``vlm_page_judge.py`` e o LOOP #45 do Dr.DocBench (PR #125).
"""
import math

import pytest

from docstruct.fusion.judge import (
    debias,
    decide_pair,
    p2_from_logprobs,
    should_judge,
)


class TestDebias:
    def test_ordens_concordantes(self):
        # P(B) = 0.9 na ordem (A,B) e P(A) = 0.1 na ordem (B,A) -> B vence nas duas
        assert debias(0.9, 0.1) == pytest.approx(0.9)

    def test_vies_de_posicao_e_cancelado(self):
        # o modelo sempre prefere a primeira: P(B)=0.9 em (A,B), P(A)=0.9 em (B,A)
        assert debias(0.9, 0.9) == pytest.approx(0.5)

    def test_empate(self):
        assert debias(0.5, 0.5) == pytest.approx(0.5)

    def test_b_perde_nas_duas(self):
        assert debias(0.1, 0.9) == pytest.approx(0.1)


class TestP2FromLogprobs:
    def test_normaliza_entre_um_e_dois(self):
        lp = {"1": math.log(0.25), "2": math.log(0.75)}
        assert p2_from_logprobs(lp) == pytest.approx(0.75)

    def test_espacos_sao_ignorados(self):
        lp = {" 1": math.log(0.5), " 2": math.log(0.5)}
        assert p2_from_logprobs(lp) == pytest.approx(0.5)

    def test_sem_tokens_relevantes(self):
        assert p2_from_logprobs({"x": math.log(0.9)}) == 0.5

    def test_apenas_um_token(self):
        assert p2_from_logprobs({"2": math.log(0.9)}) == pytest.approx(1.0)


class TestDecidePair:
    def test_nova_vence_acima_do_limiar(self):
        assert decide_pair(0.6, 0.0) is True

    def test_nenhum_juiz_convence_mantem_a_antiga(self):
        assert decide_pair(0.4, 0.1) is False

    def test_juiz_antigo_convence_quando_o_novo_nao(self):
        # LOOP #45: "new>0.5, else old>0.2"
        assert decide_pair(0.4, 0.3) is True

    def test_limiares_customizados(self):
        assert decide_pair(0.3, 0.0, new_thr=0.2) is True
        assert decide_pair(0.6, 0.0, new_thr=0.9, old_thr=0.9) is False

    def test_limiar_e_estrito(self):
        assert decide_pair(0.5, 0.2) is False


class TestShouldJudge:
    def test_paginas_divergentes(self):
        assert should_judge("alpha beta gamma", "completely different text") is True

    def test_paginas_iguais_nao_valem_julgar(self):
        assert should_judge("same text here", "same text here") is False

    def test_a_vazio(self):
        assert should_judge("", "some text") is False

    def test_b_vazio(self):
        assert should_judge("some text", "") is False

    def test_max_ratio_customizado(self):
        assert should_judge("alpha beta", "alpha gamma", max_ratio=0.99) is True
        assert should_judge("alpha beta", "alpha gamma", max_ratio=0.1) is False
