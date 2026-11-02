"""Testes do protocolo do adjudicador (``docstruct.fusion.adjudication``).

Espelham a semântica de ``adjudicate_v0.py``, ``adjudicate_v1.py``,
``vlm_adjudicate.py`` e ``filter_adjudications.py`` do Dr.DocBench (PR #125).
"""
from collections import Counter

import pytest

from docstruct.fusion.adjudication import (
    clean_transcription,
    decide,
    decide_v0,
    decide_v1,
    filter_decision,
    is_struct,
    norm_text,
    nrm,
    useful_text,
)


class TestUsefulText:
    def test_remove_header_e_imagens(self):
        assert useful_text("# Dr.DocBench page\n![img](a.png)\nhello") == "hello"

    def test_remove_tags_e_marcacao(self):
        assert useful_text("<p>**hi**</p>") == "hi"

    def test_colapsa_espacos(self):
        assert useful_text("a   b") == "a b"


class TestNormText:
    def test_baixa_caixa_e_remove_marcacao(self):
        assert norm_text("**Hello**") == "hello"


class TestNrm:
    def test_remove_marcacao(self):
        assert nrm("# Title > body") == "title body"

    def test_none_vira_vazio(self):
        assert nrm(None) == ""


class TestIsStruct:
    def test_tabela(self):
        assert is_struct("<table><tr></tr></table>") is True

    def test_formula(self):
        assert is_struct("$$ x $$") is True

    def test_imagem(self):
        assert is_struct("![a](b.png)") is True

    def test_texto_comum(self):
        assert is_struct("plain text") is False

    def test_none(self):
        assert is_struct(None) is False


class TestDecideV0:
    def test_mineru_com_tabela(self):
        assert decide_v0("text", "<table></table>") == ("mineru", "mineru_has_table")

    def test_mineru_com_formula(self):
        assert decide_v0("text", "$$ x $$") == ("mineru", "mineru_has_formula")

    def test_mineru_com_formula_inline(self):
        assert decide_v0("text", "Formula $x+1$") == ("mineru", "mineru_has_formula")

    def test_docling_quase_vazio(self):
        assert decide_v0("", "a" * 100) == ("mineru", "docling_near_empty")

    def test_mineru_quase_vazio(self):
        assert decide_v0("a" * 100, "") == ("docling", "mineru_near_empty")

    def test_default_docling(self):
        assert decide_v0("a" * 100, "b" * 100) == ("docling", "default_docling_text")


class TestDecideV1:
    TABLE = "<table><tr><td>" + "lots of table content here " * 5 + "</td></tr></table>"

    def test_quase_vazio_tem_prioridade(self):
        assert decide_v1("", self.TABLE) == ("mineru", "docling_near_empty")

    def test_so_docling_tem_tabela(self):
        assert decide_v1(self.TABLE, "b" * 200) == ("docling", "only_docling_table")

    def test_so_mineru_tem_tabela(self):
        assert decide_v1("a" * 200, self.TABLE) == ("mineru", "only_mineru_table")

    def test_ambos_tem_tabela_usa_preferencia(self):
        assert decide_v1(self.TABLE, self.TABLE) == ("mineru", "both_table->mineru")

    def test_so_mineru_tem_formula(self):
        assert decide_v1("a" * 200, "$$ " + "x" * 200 + " $$") == ("mineru", "only_mineru_formula")

    def test_so_mineru_tem_formula_inline(self):
        doc = "Docling has enough body text to avoid the near-empty rule. " * 2
        min_ = "MinerU has enough body text to avoid the near-empty rule $x+1$. " * 2
        assert decide_v1(doc, min_) == ("mineru", "only_mineru_formula")

    def test_ambos_tem_formula_usa_preferencia(self):
        f = "$$ " + "x" * 200 + " $$"
        assert decide_v1(f, f) == ("mineru", "both_formula->mineru")

    def test_default_usa_text_pref(self):
        assert decide_v1("a" * 100, "b" * 100) == ("docling", "default_docling")

    def test_preferencias_customizadas(self):
        assert decide_v1("a" * 100, "b" * 100, text_pref="mineru") == ("mineru", "default_mineru")


class TestCleanTranscription:
    def test_remove_cerca_de_codigo(self):
        assert clean_transcription("```\nhello\n```") == "hello"

    def test_empty_vira_vazio(self):
        assert clean_transcription("<EMPTY>") == ""

    def test_texto_normal(self):
        assert clean_transcription("  hello  ") == "hello"


class TestDecide:
    def _pair(self, a: str, b: str) -> dict:
        return {"i": 0, "j": 0, "md_d": a, "md_m": b}

    def _uni(self, a: str) -> dict:
        return {"i": 0, "j": -1, "md_d": a, "md_m": ""}

    def test_par_com_transcricao_igual_ao_a(self):
        stats = Counter()
        out = decide(self._pair("hello world", "other text"), "hello world", stats)
        assert out == {"action": "select_a"}
        assert stats["pair-select"] == 1

    def test_par_com_transcricao_igual_ao_b(self):
        stats = Counter()
        out = decide(self._pair("other text", "hello world"), "hello world", stats)
        assert out == {"action": "select_b"}

    def test_par_com_transcricao_plausivel_diferente(self):
        stats = Counter()
        out = decide(self._pair("hello world", "other text"), "hello there", stats)
        assert out["action"] == "replace"
        assert stats["pair-replace"] == 1

    def test_par_com_transcricao_implausivel(self):
        stats = Counter()
        out = decide(self._pair("hello world", "other text"), "x" * 500, stats)
        assert out is None
        assert stats["pair-implausible"] == 1

    def test_par_com_transcricao_vazia(self):
        stats = Counter()
        assert decide(self._pair("hello", "world"), "", stats) is None
        assert stats["pair-empty"] == 1

    def test_unilateral_vazia_e_descartada(self):
        stats = Counter()
        assert decide(self._uni("hello world"), "", stats) == {"action": "drop"}
        assert stats["uni-drop-empty"] == 1

    def test_unilateral_igual_ao_candidato_e_mantida(self):
        stats = Counter()
        assert decide(self._uni("hello world"), "hello world", stats) is None
        assert stats["uni-keep"] == 1

    def test_unilateral_nao_suportada_e_descartada(self):
        stats = Counter()
        out = decide(self._uni("a" * 100), "zzz", stats)
        assert out == {"action": "drop"}
        assert stats["uni-drop-unsupported"] == 1

    def test_unilateral_plausivel_e_substituida(self):
        stats = Counter()
        out = decide(self._uni("hello world"), "hello there", stats)
        assert out["action"] == "replace"
        assert stats["uni-replace"] == 1


class TestFilterDecision:
    def _rec(self, a: str, b: str) -> dict:
        return {"md_d": a, "md_m": b}

    def test_replace_sobre_bloco_estrutural_e_barrado(self):
        x = {"action": "replace", "text": "plain"}
        assert filter_decision(x, self._rec("<table></table>", "text"), "notab") is False

    def test_replace_sobre_texto_passa_em_notab(self):
        x = {"action": "replace", "text": "plain"}
        assert filter_decision(x, self._rec("text a", "text b"), "notab") is True

    def test_tight_limita_o_tamanho_relativo(self):
        x = {"action": "replace", "text": "x" * 500}
        assert filter_decision(x, self._rec("short", "short"), "tight") is False

    def test_tight_aceita_tamanho_proximo(self):
        x = {"action": "replace", "text": "hello there"}
        assert filter_decision(x, self._rec("hello world", "hello world"), "tight") is True

    def test_sel_nunca_injeta_texto(self):
        x = {"action": "replace", "text": "hello there"}
        assert filter_decision(x, self._rec("hello world", "hello world"), "sel") is False

    def test_select_entre_estruturas_diferentes_e_barrado(self):
        x = {"action": "select_a"}
        assert filter_decision(x, self._rec("<table></table>", "text"), "notab") is False

    def test_select_entre_estruturas_iguais_passa(self):
        x = {"action": "select_a"}
        assert filter_decision(x, self._rec("<table></table>", "<table></table>"), "notab") is True

    def test_drop_sempre_passa(self):
        x = {"action": "drop"}
        assert filter_decision(x, self._rec("<table></table>", "text"), "notab") is True

    def test_filtro_invalido(self):
        with pytest.raises(ValueError):
            filter_decision({"action": "drop"}, self._rec("a", "b"), "nope")
