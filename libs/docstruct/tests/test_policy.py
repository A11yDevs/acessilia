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
