"""Testes de policy.py."""
import dataclasses

import pytest

from docstruct.policy import FusionPolicy


class TestDefaults:
    def test_defaults_conservadores(self):
        p = FusionPolicy()
        assert p.text_pick == "auto"
        assert p.merge_paragraphs is True
        assert p.fuse_lines is False
        assert p.orientation_reinfer is True

    def test_frozen(self):
        p = FusionPolicy()
        with pytest.raises(dataclasses.FrozenInstanceError):
            p.align_tau = 0.9

    def test_validacao_lambda(self):
        with pytest.raises(ValueError):
            FusionPolicy(align_lambda=1.5)

    def test_validacao_tau(self):
        with pytest.raises(ValueError):
            FusionPolicy(align_tau=0.0)

    def test_fuse_lines_exige_merge_paragraphs(self):
        with pytest.raises(ValueError, match="no-op"):
            FusionPolicy(fuse_lines=True, merge_paragraphs=False)


class TestPresets:
    def test_v12_e_calibrado(self):
        p = FusionPolicy.drbench_v12()
        assert p.fuse_lines is True
        assert p.pic_need_text is False
        assert p.formula_text is False
        # Paridade com o script de referência (tree_differ_v2 v12-rh3-pc4):
        assert p.pic_min_blocks == 4
        assert p.pic_rule == "quality"
        assert p.pick_guard == 1.5
        assert p.fuse_h_ratio == 0.6
        assert p.fuse_max_len == 300

    def test_v13_ativa_formulas(self):
        p = FusionPolicy.drbench_v13()
        assert p.pic_need_text is True
        assert p.formula_text is True

    def test_presets_diferem_do_default(self):
        default = FusionPolicy().to_dict()
        assert FusionPolicy.drbench_v12().to_dict() != default


class TestSerializacao:
    def test_roundtrip(self):
        p = FusionPolicy(align_tau=0.7)
        assert FusionPolicy.from_dict(p.to_dict()) == p

    def test_from_dict_ignora_desconhecidas(self):
        p = FusionPolicy.from_dict({"align_tau": 0.7, "chave_futura": 1})
        assert p.align_tau == 0.7
        assert not hasattr(p, "chave_futura")


class TestDrbenchV14V15:
    def test_v14_ativa_os_pos_processamentos_deterministicos(self):
        p = FusionPolicy.drbench_v14()
        assert p.line_numbers is True
        assert p.table_eq is True
        assert p.verse_chunk == 300
        assert p.verse_kind == "records"

    def test_v14_herda_v13(self):
        v13, v14 = FusionPolicy.drbench_v13(), FusionPolicy.drbench_v14()
        assert v14.pic_need_text == v13.pic_need_text
        assert v14.formula_text == v13.formula_text
        assert v14.fuse_max_len == v13.fuse_max_len

    def test_v15_ativa_o_hibrido_de_pagina_e_tj3(self):
        p = FusionPolicy.drbench_v15()
        assert p.page_judge is True
        assert p.tailjoin == "end"
        assert p.tailjoin_max_len == 50
        assert p.tailjoin_k == 3
        assert p.tailjoin_bot == "hdr"
        assert p.rep_guard is True
        assert p.hf_end is True
        assert p.upscale is True
        assert p.orientation is True

    def test_v15_herda_v14(self):
        v14, v15 = FusionPolicy.drbench_v14(), FusionPolicy.drbench_v15()
        assert v15.line_numbers == v14.line_numbers
        assert v15.verse_chunk == v14.verse_chunk

    def test_defaults_nao_ativam_nada_novo(self):
        p = FusionPolicy()
        assert p.verse_chunk == 0
        assert p.line_numbers is False
        assert p.table_eq is False
        assert p.norm_text is False
        assert p.hf_end is False
        assert p.tailjoin == "off"
        assert p.rep_guard is False
        assert p.page_judge is False
        assert p.upscale is False
        assert p.orientation is False

    def test_roundtrip_to_from_dict(self):
        p = FusionPolicy.drbench_v15()
        assert FusionPolicy.from_dict(p.to_dict()) == p

    def test_validacao_de_verse_kind(self):
        with pytest.raises(ValueError):
            FusionPolicy(verse_kind="nope")

    def test_validacao_de_tailjoin(self):
        with pytest.raises(ValueError):
            FusionPolicy(tailjoin="nope")

    def test_validacao_de_tailjoin_bot(self):
        with pytest.raises(ValueError):
            FusionPolicy(tailjoin_bot="nope")

    def test_validacao_de_verse_chunk_negativo(self):
        with pytest.raises(ValueError):
            FusionPolicy(verse_chunk=-1)


class TestDrbenchBestMethod:
    def test_reproduz_a_composicao_do_melhor_metodo(self):
        p = FusionPolicy.drbench_best_method()
        # v13-pnt: alinhamento, escolha de texto e guarda
        assert p.align_lambda == 0.5
        assert p.align_tau == 0.6
        assert p.text_pick == "auto"
        assert p.pick_guard == 1.5
        assert p.fuse_max_len == 300
        # determinísticos da PR #125
        assert p.line_numbers is True
        assert p.table_eq is True
        assert p.verse_chunk == 300
        assert p.norm_text is True
        assert p.hf_end is True
        assert p.rep_guard is True
        assert p.blank_pages is True
        # híbrido de página + tj3
        assert p.page_judge is True
        assert p.page_judge_new_thr == 0.5
        assert p.page_judge_old_thr == 0.2
        assert p.tailjoin == "end"
        assert p.tailjoin_max_len == 50
        assert p.tailjoin_k == 3
        assert p.tailjoin_bot == "hdr"
        # imagem
        assert p.upscale is True
        assert p.orientation is True

    def test_herda_v15(self):
        v15, best = FusionPolicy.drbench_v15(), FusionPolicy.drbench_best_method()
        assert best.verse_chunk == v15.verse_chunk
        assert best.page_judge == v15.page_judge
        assert best.tailjoin == v15.tailjoin

    def test_nao_e_o_default(self):
        assert FusionPolicy() != FusionPolicy.drbench_best_method()
        assert FusionPolicy().page_judge is False
        assert FusionPolicy().tailjoin == "off"

    def test_roundtrip_to_from_dict(self):
        p = FusionPolicy.drbench_best_method()
        assert FusionPolicy.from_dict(p.to_dict()) == p
