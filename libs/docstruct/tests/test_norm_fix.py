"""Testes das limpezas determinísticas de texto (``docstruct.text.norm_fix``).

Espelham a semântica de ``norm_fix`` do Tree Differ v2 (PR #125).
"""
from docstruct.text.norm_fix import LIGATURES, norm_fix


class TestNormFix:
    def test_ligaduras_sao_expandidas(self):
        assert norm_fix("ﬁnal ﬂow") == "final flow"

    def test_todas_as_ligaduras_conhecidas(self):
        for k, v in LIGATURES.items():
            assert norm_fix(f"a{k}b") == f"a{v}b"

    def test_hifen_suave_e_removido(self):
        assert norm_fix("co\u00adoperate") == "cooperate"

    def test_nbsp_vira_espaco(self):
        assert norm_fix("a\u00a0b") == "a b"

    def test_hifenizacao_de_fim_de_linha_e_juntada(self):
        assert norm_fix("inter-\nnational") == "international"

    def test_hifen_de_composto_no_meio_da_linha_e_preservado(self):
        assert norm_fix("well-known") == "well-known"

    def test_espacos_duplicados_sao_colapsados(self):
        assert norm_fix("a   b\t\tc") == "a b c"

    def test_tabelas_sao_preservadas(self):
        md = "<table><tr><td>a   b</td></tr></table>"
        assert norm_fix(md) == md

    def test_formulas_sao_preservadas(self):
        for md in ("$$ a  b $$", "\\[ a  b \\]", "| a | b |"):
            assert norm_fix(md) == md

    def test_prefixo_com_espaco_ainda_protege(self):
        md = "  $$ a  b $$"
        assert norm_fix(md) == md

    def test_texto_vazio(self):
        assert norm_fix("") == ""
