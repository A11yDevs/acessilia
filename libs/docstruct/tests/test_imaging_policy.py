"""Testes da decisão pura de imagem (``docstruct.imaging.policy``).

Espelham a política de ``orient_pages.py`` e o upscale do LOOP #34/#36/#38/#40
do Dr.DocBench (PR #125).
"""
from docstruct.imaging.policy import (
    LARGE_FACTOR,
    MEDIUM_FACTOR,
    SMALL_FACTOR,
    decide_orientation,
    is_rotation_candidate,
    pick_orientation,
    tall_frac,
    upscale_factor,
)


def box(w: float, h: float) -> list:
    """Caixa retangular de ``w`` x ``h`` no formato de cantos do RapidOCR."""
    return [[0.0, 0.0], [w, 0.0], [w, h], [0.0, h]]


class TestUpscaleFactor:
    def test_pagina_pequena_usa_2x(self):
        assert upscale_factor(500, 700) == SMALL_FACTOR

    def test_pagina_media_usa_1_5x(self):
        assert upscale_factor(900, 1100) == MEDIUM_FACTOR

    def test_pagina_grande_usa_1x(self):
        assert upscale_factor(2000, 3000) == LARGE_FACTOR

    def test_usa_o_lado_maior(self):
        # 700 x 900 -> lado maior 900 -> média
        assert upscale_factor(700, 900) == MEDIUM_FACTOR

    def test_limite_de_800(self):
        assert upscale_factor(799, 799) == SMALL_FACTOR
        assert upscale_factor(800, 800) == MEDIUM_FACTOR

    def test_limite_de_1200(self):
        assert upscale_factor(1199, 1199) == MEDIUM_FACTOR
        assert upscale_factor(1200, 1200) == LARGE_FACTOR


class TestTallFrac:
    def test_sem_caixas(self):
        assert tall_frac([]) == 0.0

    def test_caixas_altas(self):
        assert tall_frac([box(10, 20), box(10, 20)]) == 1.0

    def test_caixas_largas(self):
        assert tall_frac([box(20, 10), box(20, 10)]) == 0.0

    def test_metade(self):
        assert tall_frac([box(10, 20), box(20, 10)]) == 0.5

    def test_razao_customizada(self):
        assert tall_frac([box(10, 11)], ratio=1.0) == 1.0


class TestIsRotationCandidate:
    def test_poucas_caixas_nao_e_candidata(self):
        assert is_rotation_candidate([box(10, 20), box(10, 20)]) is False

    def test_maioria_alta_e_candidata(self):
        assert is_rotation_candidate([box(10, 20)] * 4) is True

    def test_maioria_larga_nao_e_candidata(self):
        assert is_rotation_candidate([box(20, 10)] * 4) is False

    def test_limiar_e_respeitado(self):
        boxes = [box(10, 20), box(10, 20), box(20, 10), box(20, 10)]
        assert is_rotation_candidate(boxes, tall_thr=0.6) is False
        assert is_rotation_candidate(boxes, tall_thr=0.5) is True


class TestPickOrientation:
    def test_maior_score_vence(self):
        assert pick_orientation({90: (10.0, 5), 270: (20.0, 5)}) == 270

    def test_empate_vai_para_o_menor_angulo(self):
        assert pick_orientation({270: (10.0, 5), 90: (10.0, 5)}) == 90

    def test_sem_candidatos(self):
        assert pick_orientation({}) == 0


class TestDecideOrientation:
    def test_pagina_normal_fica_em_zero(self):
        assert decide_orientation([box(20, 10)] * 4, {90: (10.0, 5), 270: (20.0, 5)}) == 0

    def test_pagina_rotacionada_escolhe_o_maior_score(self):
        assert decide_orientation([box(10, 20)] * 4, {90: (10.0, 5), 270: (20.0, 5)}) == 270

    def test_candidata_sem_scores_fica_em_zero(self):
        assert decide_orientation([box(10, 20)] * 4) == 0
