"""Tests that the docstruct README and its Portuguese mirror stay in sync.

Constitution rule 8: English is authoritative and every `*.pt-br.md` mirror must
be updated in the same change. The library README drifted once (the mirror kept
the old "conservative defaults" text after the production defaults landed), so
this is now a guard.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LIB = REPO_ROOT / "libs" / "docstruct"
EN = LIB / "README.md"
PT = LIB / "README.pt-br.md"

# Módulos que o README precisa listar nas duas línguas.
DOCUMENTED_MODULES = (
    "docstruct.fusion.verse",
    "docstruct.fusion.line_numbers",
    "docstruct.fusion.flood",
    "docstruct.fusion.tailjoin",
    "docstruct.fusion.repetition",
    "docstruct.fusion.page_select",
    "docstruct.fusion.judge",
    "docstruct.fusion.adjudication",
    "docstruct.fusion.oracle",
    "docstruct.fusion.hf_end",
    "docstruct.fusion.table_specialist",
    "docstruct.text",
    "docstruct.imaging.policy",
    "docstruct.evaluation.holdout",
)

PRESETS = (
    "drbench_v12",
    "drbench_v13",
    "drbench_v14",
    "drbench_v15",
    "drbench_best_method",
)


@pytest.fixture(scope="module")
def en() -> str:
    return EN.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def pt() -> str:
    return PT.read_text(encoding="utf-8")


class TestReadmePairExists:
    def test_both_languages_exist(self):
        assert EN.is_file()
        assert PT.is_file()

    def test_language_links_are_bidirectional(self, en, pt):
        assert "README.pt-br.md" in en
        assert "README.md" in pt


class TestSectionsMatch:
    def test_same_number_of_sections(self, en, pt):
        en_sections = re.findall(r"^#{2,3} (.+)$", en, re.M)
        pt_sections = re.findall(r"^#{2,3} (.+)$", pt, re.M)
        assert len(en_sections) == len(pt_sections), (
            f"seções divergentes: {len(en_sections)} EN vs {len(pt_sections)} pt-BR"
        )

    def test_mirror_has_the_production_defaults_section(self, pt):
        assert "Defaults de produção" in pt

    def test_mirror_has_the_presets_section(self, pt):
        assert "Presets do Dr.DocBench" in pt


class TestModulesAreListed:
    @pytest.mark.parametrize("module", DOCUMENTED_MODULES)
    def test_english_lists_the_module(self, en, module):
        assert module in en, f"README.md não menciona {module}"

    @pytest.mark.parametrize("module", DOCUMENTED_MODULES)
    def test_mirror_lists_the_module(self, pt, module):
        assert module in pt, f"README.pt-br.md não menciona {module}"


class TestPresetsAreListed:
    @pytest.mark.parametrize("preset", PRESETS)
    def test_english_lists_the_preset(self, en, preset):
        assert preset in en, f"README.md não menciona {preset}"

    @pytest.mark.parametrize("preset", PRESETS)
    def test_mirror_lists_the_preset(self, pt, preset):
        assert preset in pt, f"README.pt-br.md não menciona {preset}"


class TestDefaultsAreDocumented:
    def test_english_states_the_production_rule(self, en):
        assert "production" in en.lower()
        assert "consumes a model" in en

    def test_mirror_states_the_production_rule(self, pt):
        assert "produção" in pt.lower()
        assert "consome modelo" in pt

    def test_both_state_the_method_caveat(self, en, pt):
        for text in (en, pt):
            assert "70.37" in text
            assert "87.33" in text

    def test_mirror_does_not_claim_conservative_defaults(self, pt):
        # O texto antigo dizia "defaults conservadores"; isso não é mais verdade.
        assert "defaults conservadores" not in pt
