"""Testes do guarda de repetição (``docstruct.fusion.repetition``).

Espelham a semântica de ``rep_guard.py`` do Dr.DocBench (PR #125).
"""
from docstruct.fusion.repetition import (
    collapse,
    guard_page,
    is_blank_page,
    max_run,
    strip_comment,
    token_norm,
)


class TestTokenNorm:
    def test_remove_tags_e_pontuacao(self):
        assert token_norm("<p>Hello, World!</p>") == "hello world"

    def test_colapsa_espacos(self):
        assert token_norm("  a   b  ") == "a b"


class TestMaxRun:
    def test_conta_repeticoes_consecutivas(self):
        assert max_run(["a", "b", "a", "b", "a", "b"], ("a", "b")) == 3

    def test_grama_ausente_devolve_zero(self):
        assert max_run(["x", "y"], ("a", "b")) == 0

    def test_ocorrencia_unica(self):
        assert max_run(["a", "b", "c"], ("a", "b")) == 1


class TestCollapse:
    def test_loop_e_cortado_ao_run_de_referencia(self):
        block = " ".join(["5"] * 20)
        out, cut = collapse(block, [["5", "5"]], reps=5, max_n=12)
        assert cut > 0
        assert out.split().count("5") < 20

    def test_repeticao_legitima_e_preservada(self):
        block = " ".join(["5"] * 6)
        out, cut = collapse(block, [["5"] * 6], reps=5, max_n=12)
        assert cut == 0
        assert out.split().count("5") == 6

    def test_repeticao_curta_abaixo_do_limiar_fica_intacta(self):
        block = " ".join(["5"] * 4)
        out, cut = collapse(block, [[]], reps=5, max_n=12)
        assert cut == 0
        assert out == block

    def test_texto_sem_repeticao_fica_intacto(self):
        block = "the quick brown fox jumps over the lazy dog"
        out, cut = collapse(block, [[]], reps=5, max_n=12)
        assert cut == 0
        assert out == block

    def test_espacamento_e_preservado(self):
        block = "alpha beta gamma"
        assert collapse(block, [[]], reps=5, max_n=12)[0] == block

    def test_bloco_vazio(self):
        assert collapse("", [[]], reps=5, max_n=12) == ("", 0)

    def test_loop_de_frase_e_cortado(self):
        sentence = "the fox jumped over the dog"
        block = " ".join([sentence] * 10)
        out, cut = collapse(block, [[]], reps=5, max_n=12)
        assert cut > 0
        assert out.count(sentence) < 10


class TestStripComment:
    def test_comentario_de_pagina_branca_e_removido(self):
        assert strip_comment("There is no visible text on this page.") == ""

    def test_transcricao_e_preservada(self):
        assert strip_comment("Hello world") == "Hello world"

    def test_comentario_entre_blocos(self):
        t = "Hello\n\n\n\n\nThere is no text here\n\n\n\n\nWorld"
        assert strip_comment(t) == "Hello\n\n\n\n\nWorld"


class TestIsBlankPage:
    def test_pagina_branca(self):
        assert is_blank_page("5 5 5", "", "There is no visible text.") is True

    def test_docling_com_texto_nao_e_branca(self):
        assert is_blank_page("5 5 5", "real text", "There is no visible text.") is False

    def test_vlm_com_transcricao_nao_e_branca(self):
        assert is_blank_page("5 5 5", "", "real transcription") is False

    def test_a_vazio_nao_e_branca(self):
        assert is_blank_page("", "", "There is no visible text.") is False


class TestGuardPage:
    def test_pagina_branca_e_esvaziada_com_blank(self):
        out, cut, blank = guard_page("5 5 5 5 5 5", "", "There is no visible text.", blank=True)
        assert out == "\n"
        assert blank is True

    def test_pagina_branca_sem_blank_nao_e_esvaziada(self):
        out, _, blank = guard_page("5 5 5 5 5 5", "", "There is no visible text.", blank=False)
        assert blank is False
        assert out != "\n"

    def test_loop_e_cortado(self):
        out, cut, _ = guard_page(" ".join(["5"] * 20), "", "")
        assert cut > 0
        assert out.split().count("5") < 20

    def test_tabelas_sao_preservadas(self):
        block = "<table>" + " ".join(["5"] * 20) + "</table>"
        out, cut, _ = guard_page(block, "", "")
        assert cut == 0
        assert out == block

    def test_formulas_sao_preservadas(self):
        block = "$$ " + " ".join(["5"] * 20) + " $$"
        out, cut, _ = guard_page(block, "", "")
        assert cut == 0
        assert out == block
