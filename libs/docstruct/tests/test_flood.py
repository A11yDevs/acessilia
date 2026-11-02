"""Testes do guarda de inundação de blocos (``docstruct.fusion.flood``).

Espelham a semântica de ``flood_guard`` do Tree Differ v2 (PR #125).
"""
from collections import Counter

from docstruct.fusion.flood import flood_guard
from docstruct.fusion.types import DiffBlock

LEXICON = frozenset({"caption", "figure", "table", "results", "chapter"})


def mk(text, box=None, kind="text", md=None, **kw):
    return DiffBlock(md=md or text, kind=kind, box=box, text=text, type=kw.pop("type", kind), **kw)


def many(n, text="x", kind="text"):
    return [mk(text, kind=kind) for _ in range(n)]


class TestFloodGuard:
    def test_nao_age_abaixo_do_minimo_de_blocos(self):
        a = many(10, "ab")
        stats = Counter()
        assert flood_guard(a, many(1), stats, ratio=2.0, lexicon=LEXICON) == a
        assert stats["flood-pages"] == 0

    def test_nao_age_quando_a_nao_inunda_b(self):
        a = many(40, "ab")
        stats = Counter()
        assert flood_guard(a, many(40), stats, ratio=2.0, lexicon=LEXICON) == a
        assert stats["flood-pages"] == 0

    def test_descarta_blocos_curtos_sem_palavra_do_lexico(self):
        a = many(40, "ab") + [mk("caption")]
        stats = Counter()
        out = flood_guard(a, many(5), stats, ratio=2.0, lexicon=LEXICON)
        assert len(out) == 1
        assert out[0].md == "caption"
        assert stats["flood-docling-dropped"] == 40
        assert stats["flood-pages"] == 1

    def test_blocos_longos_sao_preservados(self):
        a = many(40, "ab") + [mk("a" * 40)]
        stats = Counter()
        out = flood_guard(a, many(5), stats, ratio=2.0, lexicon=LEXICON)
        assert len(out) == 1

    def test_blocos_nao_textuais_sao_preservados(self):
        a = many(40, "ab") + [mk("ab", kind="table"), mk("ab", kind="heading")]
        stats = Counter()
        out = flood_guard(a, many(5), stats, ratio=2.0, lexicon=LEXICON)
        assert len(out) == 2

    def test_lexico_vazio_descarta_todos_os_curtos(self):
        a = many(40, "ab")
        stats = Counter()
        assert flood_guard(a, many(5), stats, ratio=2.0) == []
        assert stats["flood-docling-dropped"] == 40

    def test_ratio_e_respeitado(self):
        a = many(40, "ab")
        stats = Counter()
        # 40 < 3.0 * 20 -> não dispara
        assert len(flood_guard(a, many(20), stats, ratio=3.0, lexicon=LEXICON)) == 40
        # 40 >= 2.0 * 20 -> dispara
        assert flood_guard(a, many(20), stats, ratio=2.0, lexicon=LEXICON) == []

    def test_tag_entra_nas_stats(self):
        stats = Counter()
        flood_guard(many(40, "ab"), many(5), stats, ratio=2.0, lexicon=LEXICON, tag="mineru")
        assert stats["flood-mineru-dropped"] == 40

    def test_lista_vazia_nao_quebra(self):
        stats = Counter()
        assert flood_guard([], [], stats, ratio=2.0, lexicon=LEXICON) == []
