"""Testes de geometry.py — golden do comportamento original do backend."""
from docstruct.geometry import (
    content_fingerprint,
    intersection_area,
    merge_bboxes,
    overlaps_clean,
    union,
)


class TestContentFingerprint:
    def test_whitespace_e_case_invariantes(self):
        assert content_fingerprint("Olá  Mundo") == content_fingerprint("olá mundo")
        assert content_fingerprint("a\n\tb") == content_fingerprint("a b")

    def test_diferentes_geram_diferentes(self):
        assert content_fingerprint("abc") != content_fingerprint("xyz")


class TestOverlapsClean:
    def test_overlap_total(self):
        assert overlaps_clean((0, 0, 10, 10), [(0, 0, 10, 10)], threshold=0.3)

    def test_overlap_abaixo_do_threshold(self):
        # interseção 10% da área
        assert not overlaps_clean((0, 0, 10, 10), [(9, 0, 19, 10)], threshold=0.3)

    def test_sem_intersecao(self):
        assert not overlaps_clean((0, 0, 10, 10), [(20, 20, 30, 30)])

    def test_varios_candidatos(self):
        assert overlaps_clean(
            (0, 0, 10, 10), [(20, 20, 30, 30), (0, 0, 10, 5)], threshold=0.3
        )


class TestMergeBboxes:
    def test_vazio(self):
        assert merge_bboxes([]) == []

    def test_faixa_unica(self):
        # bboxes na mesma banda vertical
        result = merge_bboxes([(0, 0, 10, 10), (12, 2, 20, 9)])
        assert result == [(0.0, 0.0, 20.0, 10.0)]

    def test_bandas_separadas(self):
        result = merge_bboxes([(0, 0, 10, 10), (0, 100, 10, 110)])
        assert len(result) == 2

    def test_gap_customizado(self):
        # gap de 15 não funde com vertical_gap=5, mas funde com 20
        boxes = [(0, 0, 10, 10), (0, 25, 10, 30)]
        assert len(merge_bboxes(boxes, vertical_gap=5)) == 2
        assert len(merge_bboxes(boxes, vertical_gap=20)) == 1

    def test_ordenacao_por_y_antes_da_fusao(self):
        # gap de 15px > vertical_gap padrão (5): bandas separadas
        result = merge_bboxes([(0, 25, 10, 30), (0, 0, 10, 10)])
        assert len(result) == 2
        # com gap suficiente, funde em uma faixa
        assert merge_bboxes([(0, 25, 10, 30), (0, 0, 10, 10)], vertical_gap=20) == [
            (0.0, 0.0, 10.0, 30.0)
        ]


class TestUnionIntersection:
    def test_union(self):
        assert union((0, 0, 10, 10), (5, 5, 20, 20)) == (0, 0, 20, 20)

    def test_intersection_area_sem_toque(self):
        assert intersection_area((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0

    def test_intersection_area_parcial(self):
        assert intersection_area((0, 0, 10, 10), (5, 5, 20, 20)) == 25.0
