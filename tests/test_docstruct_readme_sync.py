"""Tests that the docstruct README and its Portuguese mirror stay in sync.

Constitution rule 8: English is authoritative and every `*.pt-br.md` mirror must
be updated in the same change. The library README drifted once (the mirror kept
the old "conservative defaults" text after the production defaults landed), so
this is now a guard.

The Public API table is also a claim about the code: each row must name only
what its module exports (#659). A full ``__all__`` dump made the large modules
unreadable, so the table stays a highlights list and the guard checks the other
direction: no listed name may outlive its export.
"""
from __future__ import annotations

import importlib
import re
import types
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

# A Public API row names one module and lists its highlighted names. The legacy
# compatibility row is not a module row and is deliberately left out.
MODULE_ROW = re.compile(
    r"^\|\s*`(?P<module>docstruct(?:\.[a-z0-9_]+)+)`\s*\|(?P<cell>.*)\|\s*$",
    re.MULTILINE,
)
SYMBOL = re.compile(r"`(?P<name>[A-Za-z_][A-Za-z0-9_.]*)`")
LEADING_SYMBOLS = re.compile(r"^(?:`[A-Za-z_][A-Za-z0-9_.]*`(?:\s*,\s*)?)+")


def _documented_rows(text: str) -> dict[str, list[str]]:
    """The module rows of the Public API table, with their highlighted names."""
    rows: dict[str, list[str]] = {}
    for match in MODULE_ROW.finditer(text):
        names: list[str] = []
        for group in match.group("cell").split(";"):
            group = group.strip()
            leading = LEADING_SYMBOLS.match(group)
            if leading is None:
                continue
            remainder = group[leading.end():].lstrip()
            # A name followed by a lowercase word, with no comma between them,
            # opens a sentence in the description; it is prose, not a symbol.
            if remainder[:1].islower() and not leading.group(0).rstrip().endswith(","):
                continue
            for name in SYMBOL.findall(leading.group(0)):
                if name not in names:
                    names.append(name)
        rows[match.group("module")] = names
    return rows


def _exports(module_name: str) -> set[str]:
    """The names a module exports: its ``__all__``, or its public attributes.

    Several small modules predate ``__all__``; treating their public namespace
    as the export list keeps the guard useful without changing their API.
    """
    module = importlib.import_module(module_name)
    declared = getattr(module, "__all__", None)
    if declared is not None:
        return set(declared)
    return {
        name
        for name, value in vars(module).items()
        if not name.startswith("_") and not isinstance(value, types.ModuleType)
    }


def _module_reference_exists(reference: str) -> bool:
    """Whether ``docstruct.a.b.NAME`` resolves to a module or an attribute."""
    parts = reference.split(".")
    for split_at in range(len(parts), 0, -1):
        try:
            target = importlib.import_module(".".join(parts[:split_at]))
        except ImportError:
            continue
        for attribute in parts[split_at:]:
            if not hasattr(target, attribute):
                return False
            target = getattr(target, attribute)
        return True
    return False


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


class TestModuleTableMatchesExports:
    @pytest.mark.parametrize("path", (EN, PT), ids=("en", "pt-br"))
    def test_the_table_rows_are_unique_and_non_empty(self, path):
        text = path.read_text(encoding="utf-8")
        modules = [match.group("module") for match in MODULE_ROW.finditer(text)]
        assert modules, f"{path.name}: no Public API module rows parsed"
        assert len(modules) == len(set(modules)), (
            f"{path.name}: duplicated module rows: {sorted(modules)}"
        )
        rows = _documented_rows(text)
        assert set(DOCUMENTED_MODULES) <= set(rows), (
            f"{path.name}: the row parser lost documented modules: "
            f"{sorted(set(DOCUMENTED_MODULES) - set(rows))}"
        )
        empty = sorted(module for module, names in rows.items() if not names)
        assert not empty, f"{path.name}: rows without symbols: {empty}"

    @pytest.mark.parametrize("path", (EN, PT), ids=("en", "pt-br"))
    def test_every_listed_name_is_exported(self, path):
        text = path.read_text(encoding="utf-8")
        failures: list[str] = []
        for module_name, names in _documented_rows(text).items():
            try:
                exported = _exports(module_name)
            except ImportError as error:
                failures.append(f"{module_name}: cannot import ({error})")
                continue
            for name in names:
                if "." not in name and name not in exported:
                    failures.append(f"{module_name}: {name} is not exported")
        # Cross-module names are written with their full path; they must resolve.
        for match in MODULE_ROW.finditer(text):
            module_name = match.group("module")
            for reference in SYMBOL.findall(match.group("cell")):
                if reference.startswith("docstruct.") and not _module_reference_exists(
                    reference
                ):
                    failures.append(f"{module_name}: {reference} does not resolve")
        assert not failures, (
            f"{path.name} lists names its modules do not export:\n"
            + "\n".join(failures)
        )

    def test_both_languages_list_the_same_names(self, en, pt):
        assert _documented_rows(en) == _documented_rows(pt)


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
