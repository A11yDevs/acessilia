"""Tests for the documentation updated by the PR #125 work.

The docs must stay consistent with the code: the domain version they reference
has to exist, the modules they list have to be importable, and the English
source and the Portuguese mirror have to stay in sync (constitution rule 8).
"""
from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS = REPO_ROOT / "docs"

PAIRS = (
    ("docstruct_algorithms.md", "docstruct_algorithms.pt-br.md"),
    ("drbench.md", "drbench.pt-br.md"),
    ("pmv_agno_pddl.md", "pmv_agno_pddl.pt-br.md"),
    ("toolbox_integration.md", "toolbox_integration.pt-br.md"),
)

# Módulos que a documentação afirma existir.
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
    "docstruct.text.normalize",
    "docstruct.text.norm_fix",
    "docstruct.text.latex",
    "docstruct.imaging.policy",
    "docstruct.evaluation.holdout",
)


class TestDocPairsExist:
    @pytest.mark.parametrize(("en", "pt"), PAIRS)
    def test_both_languages_exist(self, en, pt):
        assert (DOCS / en).is_file(), f"{en} ausente"
        assert (DOCS / pt).is_file(), f"{pt} ausente"

    @pytest.mark.parametrize(("en", "pt"), PAIRS)
    def test_language_links_are_bidirectional(self, en, pt):
        assert pt in (DOCS / en).read_text(encoding="utf-8"), f"{en} não linka {pt}"
        assert en in (DOCS / pt).read_text(encoding="utf-8"), f"{pt} não linka {en}"


class TestDocumentedModulesExist:
    @pytest.mark.parametrize("module", DOCUMENTED_MODULES)
    def test_module_is_importable(self, module):
        importlib.import_module(module)

    def test_algorithms_doc_lists_every_module(self):
        text = (DOCS / "docstruct_algorithms.md").read_text(encoding="utf-8")
        for module in DOCUMENTED_MODULES:
            assert module in text, f"docstruct_algorithms.md não menciona {module}"

    def test_mirror_lists_every_module(self):
        text = (DOCS / "docstruct_algorithms.pt-br.md").read_text(encoding="utf-8")
        for module in DOCUMENTED_MODULES:
            assert module in text, f"espelho pt-BR não menciona {module}"


class TestDomainVersionIsConsistent:
    def test_referenced_domain_files_exist(self):
        domains = REPO_ROOT / "backend" / "core" / "planning" / "domains"
        assert (domains / "domain_v2.3.pddl").is_file()
        assert (domains / "domain_description_v2.3.md").is_file()

    @pytest.mark.parametrize(("en", "pt"), PAIRS)
    def test_no_stale_domain_version(self, en, pt):
        for name in (en, pt):
            text = (DOCS / name).read_text(encoding="utf-8")
            assert "domain_v2.2.pddl" not in text, f"{name} ainda referencia v2.2"
            assert "domain_description_v2.2.md" not in text, f"{name} ainda referencia v2.2"

    def test_pmv_doc_references_the_current_version(self):
        text = (DOCS / "pmv_agno_pddl.md").read_text(encoding="utf-8")
        assert "domain_v2.3.pddl" in text


class TestAgentsAreDocumented:
    AGENTS = (
        "AdjudicationAgent",
        "PageLevelAgent",
        "OrderAdjudicationAgent",
        "TableSpecialistAgent",
    )

    @pytest.mark.parametrize("agent", AGENTS)
    def test_agent_exists(self, agent):
        import backend.core.agents  # noqa: F401

        module = {
            "AdjudicationAgent": "backend.core.agents.adjudication_agent",
            "PageLevelAgent": "backend.core.agents.page_level_agent",
            "OrderAdjudicationAgent": "backend.core.agents.order_adjudication_agent",
            "TableSpecialistAgent": "backend.core.agents.table_specialist_agent",
        }[agent]
        assert hasattr(importlib.import_module(module), agent)

    def test_pmv_doc_lists_every_agent(self):
        text = (DOCS / "pmv_agno_pddl.md").read_text(encoding="utf-8")
        for agent in self.AGENTS:
            assert agent in text, f"pmv_agno_pddl.md não menciona {agent}"

    def test_mirror_lists_every_agent(self):
        text = (DOCS / "pmv_agno_pddl.pt-br.md").read_text(encoding="utf-8")
        for agent in self.AGENTS:
            assert agent in text, f"espelho pt-BR não menciona {agent}"


class TestDrbenchDocStatesTheStandard:
    def test_states_the_default_rule(self):
        text = (DOCS / "drbench.md").read_text(encoding="utf-8")
        assert "deterministic" in text.lower()
        assert "consumes a model" in text or "consome modelo" in text

    def test_states_the_method_caveat(self):
        text = (DOCS / "drbench.md").read_text(encoding="utf-8")
        assert "70.37" in text
        assert "87.33" in text

    def test_links_the_runbook(self):
        text = (DOCS / "drbench.md").read_text(encoding="utf-8")
        assert "RUNBOOK.md" in text
        assert (DOCS / "drbench" / "experiments" / "RUNBOOK.md").is_file()

    def test_mirror_links_the_runbook(self):
        text = (DOCS / "drbench.pt-br.md").read_text(encoding="utf-8")
        assert "RUNBOOK.pt-br.md" in text
        assert (DOCS / "drbench" / "experiments" / "RUNBOOK.pt-br.md").is_file()
