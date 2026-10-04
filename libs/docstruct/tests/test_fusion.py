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

    def test_heading_continuation_merge(self):
        """Headings sobre-segmentados com continuação sintática (conectivo ou minúscula) são unidos."""
        policy = FusionPolicy(merge_paragraphs=True)
        D = [
            mk("Signs and Symbols – Direction and", box=(0.1, 0.1, 0.9, 0.15), kind="heading", md="# Signs and Symbols – Direction and"),
            mk("Prediction", box=(0.1, 0.15, 0.9, 0.2), kind="heading", md="# Prediction"),
        ]
        M = [
            mk("Signs and Symbols – Direction and Prediction", box=(0.1, 0.1, 0.9, 0.2), kind="heading", md="# Signs and Symbols – Direction and Prediction"),
        ]
        out, stats = merge_blocks(D, M, policy)
        assert out == ["# Signs and Symbols – Direction and Prediction"]
        assert stats.get("merge-split-docling", 0) == 1

    def test_heading_no_continuation_preserves_separate(self):
        """Headings independentes em maiúscula dentro de um bloco único do parceiro não são fundidos."""
        policy = FusionPolicy(merge_paragraphs=True)
        D = [
            mk("ROOTS AND BULBS", box=(0.1, 0.1, 0.9, 0.14), kind="heading", md="# ROOTS AND BULBS"),
            mk("Carrots", box=(0.1, 0.15, 0.9, 0.2), kind="heading", md="# Carrots"),
        ]
        M = [
            mk("ROOTS AND BULBS Carrots", box=(0.1, 0.1, 0.9, 0.2), kind="heading", md="# ROOTS AND BULBS Carrots"),
        ]
        out, stats = merge_blocks(D, M, policy)
        assert stats.get("merge-split-docling", 0) == 0
        assert len(out) == 2
        assert "# Carrots" in out



def test_disabling_unilateral_dedup_preserves_a_represented_fragment():
    fragment = "saved my life and brought me back to camp"
    text = "This earlier event " + fragment + " before the next day."
    matched = mk(text, box=(0.0, 0.1, 0.9, 0.3))
    contained = mk(fragment, box=(0.1, 0.15, 0.8, 0.2))
    policy = FusionPolicy(pick_guard=1.5, merge_paragraphs=False, decor_tail=False,
                          junk_filter=False, suppress_regions=False)
    original, original_stats = merge_blocks([matched, contained], [matched], policy)
    ablation, ablation_stats = merge_blocks([matched, contained], [matched], policy, unilateral_dedup=False)
    assert original == [text]
    assert original_stats["dropped-docling-duplicate"] == 1
    assert fragment in ablation
    assert ablation_stats["dropped-docling-duplicate"] == 0


def test_repeated_text_in_distinct_regions_is_preserved():
    text = "Repeated safety notice for this section"
    first = mk(text, box=(0.0, 0.1, 0.4, 0.2))
    second = mk(text, box=(0.6, 0.7, 1.0, 0.8))
    policy = FusionPolicy(pick_guard=1.5, merge_paragraphs=False, decor_tail=False,
                          junk_filter=False, suppress_regions=False)
    out, stats = merge_blocks([first, second], [first], policy)
    assert out == [text, text]
    assert stats["dropped-docling-duplicate"] == 0


def test_missing_coordinates_cannot_prove_a_repeated_occurrence_is_redundant():
    text = "Repeated form instruction for this section"
    block = mk(text)
    policy = FusionPolicy(pick_guard=1.5, merge_paragraphs=False, decor_tail=False,
                          junk_filter=False, suppress_regions=False)
    out, stats = merge_blocks([block, block.copy()], [block], policy)
    assert out == [text, text]
    assert stats["dropped-docling-duplicate"] == 0


def test_content_in_discarded_mineru_alternative_is_not_deduplicated():
    parent = "The selected parent paragraph contains its own complete description of this section."
    child = "Additional independent detail that must survive."
    box = (0.0, 0.1, 0.9, 0.3)
    docling = [mk(parent, box=box), mk(child, box=(0.1, 0.15, 0.8, 0.2))]
    mineru = [mk(parent + " " + child, box=box)]
    policy = FusionPolicy(pick_guard=1.5, text_pick="docling", merge_paragraphs=False,
                          decor_tail=False, junk_filter=False, suppress_regions=False)
    out, stats = merge_blocks(docling, mineru, policy)
    assert parent in out
    assert child in out
    assert stats["dropped-docling-duplicate"] == 0


def test_high_iou_preserves_match_under_ocr_degradation():
    """BBoxes com alto IoU (>= 0.70) permanecem pareados mesmo se OCR de um dos lados estiver degradado (sim < 0.15)."""
    clean_text = "This is a clean psychological evaluation text block with plenty of words."
    degraded_text = "d e s n e n x x y y z z w w q q 1 2 3 4 5 6 7 8 9 0"
    box = (0.1, 0.1, 0.9, 0.3)
    d = mk(clean_text, box=box)
    m = mk(degraded_text, box=box)
    policy = FusionPolicy(pick_guard=1.5, merge_paragraphs=False, decor_tail=False,
                          junk_filter=False, suppress_regions=False)
    out, stats = merge_blocks([d], [m], policy)
    assert out == [clean_text]
    assert stats.get("unilateral-docling", 0) == 0
    assert stats.get("pair-text-auto->docling(quality)", 0) == 1


def test_interior_paragraph_numbers_not_treated_as_page_numbers():
    """Números isolados no miolo da página (0.12 <= cy <= 0.88) permanecem no corpo como texto e não vão para decor."""
    from docstruct.fusion.noise import decor_role
    # Número no miolo da página (cy = 0.50): não é page_number
    b_interior = mk("239", box=(0.1, 0.48, 0.2, 0.52), type="paragraph")
    assert decor_role(b_interior) is None

    # Número na margem superior (cy = 0.05): é page_number
    b_margin_top = mk("239", box=(0.1, 0.04, 0.2, 0.06), type="paragraph")
    assert decor_role(b_margin_top) == "page_number"

    # Número na margem inferior (cy = 0.95): é page_number
    b_margin_bottom = mk("239", box=(0.1, 0.94, 0.2, 0.96), type="paragraph")
    assert decor_role(b_margin_bottom) == "page_number"

    # Bloco explicitamente tipado como decor: é page_number mesmo no miolo
    b_explicit = mk("239", box=(0.1, 0.48, 0.2, 0.52), type="page_header")
    assert decor_role(b_explicit) == "page_number"


def test_mega_block_does_not_merge_separate_paragraphs():
    """Mega-bloco sub-segmentado do parceiro (área > 0.35 ou altura > 0.40) não deve fundir parágrafos separados."""
    policy = FusionPolicy(merge_paragraphs=True)
    # 5 parágrafos separados ocupando a página
    D = [
        mk(f"Paragraph {i} with distinct information and words.", box=(0.1, 0.1 * i, 0.9, 0.1 * i + 0.08))
        for i in range(1, 6)
    ]
    # Mega-bloco cobrindo quase a página toda (área > 0.5, altura > 0.6)
    M = [
        mk("Mega block text containing everything", box=(0.05, 0.05, 0.95, 0.75))
    ]
    out, stats = merge_blocks(D, M, policy)
    assert stats.get("merge-split-docling", 0) == 0
    # Todos os 5 parágrafos de D foram preservados sem serem esmagados em um único bloco
    for i in range(1, 6):
        assert any(f"Paragraph {i}" in x for x in out)


def test_structural_heading_not_treated_as_decor():
    """Títulos estruturais (kind='heading') nunca são classificados como decor/page_number."""
    from docstruct.fusion.noise import decor_role
    # Título '1' na margem superior: permanece heading do corpo
    b_title = mk("1", box=(0.1, 0.02, 0.2, 0.06), type="title", kind="heading", md="# 1")
    assert decor_role(b_title) is None


def test_chapter_title_not_split_into_page_number():
    """Cabeçalhos de capítulo/seção como 'Chapter 5' não são decompostos em page_number avulso."""
    from docstruct.fusion.noise import split_decor
    b_chap = mk("Chapter 5", box=(0.1, 0.92, 0.4, 0.96), type="page_footer", md="Chapter 5")
    stats = Counter()
    body, decor = split_decor([b_chap], stats, "docling")
    assert any(b.text == "Chapter 5" for b in decor)
    assert not any(b.text == "5" and b.role == "page_number" for b in decor)
    assert stats.get("decor-docling-split-number", 0) == 0


def test_decor_wins_preserves_body_headings():
    """decor_wins não deve deletar headings do corpo do documento."""
    policy = FusionPolicy(decor_tail=True)
    heading = mk("INTRODUCTION", box=(0.1, 0.05, 0.9, 0.1), kind="heading", md="# INTRODUCTION")
    p1 = mk("Body paragraph 1", box=(0.1, 0.15, 0.9, 0.3))
    # Docling extraiu erroneamente como page_header no mesmo local
    header = mk("INTRODUCTION", box=(0.1, 0.05, 0.9, 0.1), type="page_header", md="INTRODUCTION")
    out, stats = merge_blocks([header, p1], [heading, p1], policy, decor_wins=True)
    assert out[0] == "# INTRODUCTION"
    assert out[1] == "Body paragraph 1"
    # O heading não foi jogado para o final da página
    assert len(out) == 2


