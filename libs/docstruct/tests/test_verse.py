"""Testes do chunking de verso/registro (``docstruct.fusion.verse``).

Espelham a semântica fixada por ``tests/test_drbench_verse.py`` sobre o script
do Dr.DocBench, agora sobre a API tipada da biblioteca.
"""
from collections import Counter

from docstruct.fusion.types import DiffBlock
from docstruct.fusion.verse import (
    chunk_verse,
    record_like,
    split_box_rows,
    verse_blocks,
    verse_lines,
)
from docstruct.text.normalize import norm


def mk(text, box=None, kind="text", md=None, **kw):
    return DiffBlock(md=md or text, kind=kind, box=box, text=text, type=kw.pop("type", kind), **kw)


class TestNorm:
    def test_remove_tags_e_marcacao(self):
        assert norm("<p>Hello</p> **World**") == "hello world"

    def test_colapsa_espacos_e_baixa_caixa(self):
        assert norm("  A   B  ") == "a b"

    def test_pontuacao_de_conteudo_e_preservada(self):
        assert norm("1.5 + 2") == "1.5 + 2"


class TestRecordLike:
    def test_linhas_terminando_em_numero_sao_registros(self):
        assert record_like(["Chapter one 1", "Chapter two 2", "Chapter three 3"]) is True

    def test_dot_leaders_sao_registros(self):
        assert record_like(["Introduction .......", "Methods ..........", "Results ........."]) is True

    def test_verso_terminando_em_palavras_nao_e_registro(self):
        lines = ["Shall I compare thee to a summer's day", "Thou art more lovely and more temperate"]
        assert record_like(lines) is False

    def test_entrada_vazia_nao_e_registro(self):
        assert record_like([]) is False
        assert record_like(["", "   "]) is False

    def test_limiar_e_respeitado(self):
        assert record_like(["a 1", "b 2", "c", "d"]) is False
        assert record_like(["a 1", "b 2", "c", "d"], min_frac=0.5) is True


class TestVerseLines:
    def test_bloco_multilinha_curto_e_verso(self):
        md = "line one\nline two\nline three"
        assert verse_lines(md) == ["line one", "line two", "line three"]

    def test_linha_unica_nao_e_verso(self):
        assert verse_lines("just one line") is None

    def test_poucas_linhas_nao_e_verso(self):
        assert verse_lines("one\ntwo") is None

    def test_estruturas_de_markdown_sao_excluidas(self):
        for prefix in ("#", "<", "|", "$$", "!["):
            assert verse_lines(f"{prefix} a\nb\nc") is None

    def test_linhas_longas_nao_sao_verso(self):
        assert verse_lines(f"{'x' * 130}\nb\nc") is None

    def test_portao_de_mediana(self):
        assert verse_lines("\n".join(["y" * 80] * 3)) is None


class TestChunkVerse:
    def test_linha_em_branco_quebra_estrofes(self):
        assert chunk_verse(["a", "b", "", "c", "d"], max_chars=1000) == ["a\nb", "c\nd"]

    def test_rotulo_de_falante_inicia_novo_pedaco(self):
        chunks = chunk_verse(["HAMLET:", "to be", "or not to be", "KING:", "what ho"], max_chars=1000)
        assert chunks == ["HAMLET:\nto be\nor not to be", "KING:\nwhat ho"]

    def test_rotulo_inline_nao_quebra(self):
        assert chunk_verse(["HAMLET: to be", "or not to be"], max_chars=1000) == ["HAMLET: to be\nor not to be"]

    def test_max_chars_forca_quebra(self):
        assert len(chunk_verse(["aaaa", "bbbb", "cccc"], max_chars=5)) == 3

    def test_fim_de_frase_descarrega_apos_limiar_suave(self):
        chunks = chunk_verse(["first sentence.", "second sentence."], max_chars=10, soft=0.5)
        assert chunks == ["first sentence.", "second sentence."]

    def test_entrada_vazia_nao_gera_pedacos(self):
        assert chunk_verse([], max_chars=100) == []


class TestSplitBoxRows:
    def test_box_none_devolve_none_por_parte(self):
        assert split_box_rows(None, [1, 2]) == [None, None]

    def test_box_e_dividido_proporcionalmente(self):
        boxes = split_box_rows((0.0, 0.0, 1.0, 1.0), [1, 3])
        assert boxes[0] == (0.0, 0.0, 1.0, 0.25)
        assert boxes[1] == (0.0, 0.25, 1.0, 1.0)

    def test_partes_zero_nao_dividem_por_zero(self):
        assert len(split_box_rows((0.0, 0.0, 1.0, 1.0), [0, 0])) == 2


class TestVerseBlocks:
    def test_registros_sao_divididos(self):
        md = "\n".join(f"Entry {i} {i}" for i in range(1, 8))
        stats = Counter()
        out = verse_blocks([mk(md)], stats, "docling", max_chars=20)
        assert len(out) > 1
        assert stats["verse-docling-split"] == 1
        assert all(b.verse for b in out)

    def test_verso_real_fica_inteiro_no_modo_records(self):
        md = "Shall I compare thee\nTo a summer's day\nThou art more lovely"
        stats = Counter()
        out = verse_blocks([mk(md)], stats, "docling", max_chars=20, kind="records")
        assert len(out) == 1
        assert stats["verse-docling-whole"] == 1

    def test_modo_all_divide_verso_real(self):
        md = "Shall I compare thee\nTo a summer's day\nThou art more lovely"
        stats = Counter()
        out = verse_blocks([mk(md)], stats, "docling", max_chars=20, kind="all")
        assert len(out) > 1

    def test_blocos_nao_textuais_ficam_intactos(self):
        block = mk("a\nb\nc", kind="table")
        stats = Counter()
        assert verse_blocks([block], stats, "docling", max_chars=10) == [block]

    def test_pedaco_unico_e_mantido(self):
        stats = Counter()
        out = verse_blocks([mk("a\nb\nc")], stats, "docling", max_chars=1000)
        assert len(out) == 1
        assert stats["verse-docling-whole"] == 1

    def test_pedaco_unico_no_modo_all_e_mantido(self):
        stats = Counter()
        out = verse_blocks([mk("a\nb\nc")], stats, "docling", max_chars=1000, kind="all")
        assert len(out) == 1
        assert stats["verse-docling-kept"] == 1

    def test_boxes_dos_pedacos_derivam_do_original(self):
        md = "\n".join(f"Entry {i} {i}" for i in range(1, 8))
        stats = Counter()
        out = verse_blocks([mk(md, box=(0.0, 0.0, 1.0, 1.0))], stats, "docling", max_chars=20)
        assert all(b.box is not None for b in out)
        assert out[0].box[1] == 0.0
        assert out[-1].box[3] == 1.0

    def test_metadados_do_bloco_original_sao_preservados(self):
        md = "\n".join(f"Entry {i} {i}" for i in range(1, 8))
        stats = Counter()
        out = verse_blocks([mk(md, type="paragraph", role="header")], stats, "docling", max_chars=20)
        assert all(b.type == "paragraph" and b.role == "header" for b in out)

    def test_texto_dos_pedacos_e_normalizado(self):
        md = "\n".join(f"Entry {i} {i}" for i in range(1, 8))
        stats = Counter()
        out = verse_blocks([mk(md)], stats, "docling", max_chars=20)
        assert all(b.text == norm(b.md) for b in out)
