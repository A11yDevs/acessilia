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

from docstruct.policy import FusionPolicy

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

# The accents are escaped so this English test stays out of the Portuguese scan.
SECTION_HEADINGS = ("Public API", "API p\u00fablica")
LEGACY_LABELS = ("Legacy compatibility exports", "Exports legados de compatibilidade")
LEGACY_MODULES = ("docstruct.types", "docstruct")
MODULE_CELL = re.compile(r"^`(?P<module>docstruct(?:\.[a-z0-9_]+)+)`$")
MODULE_REFERENCE = re.compile(r"`(?P<module>docstruct(?:\.[a-z0-9_]+)*)`")
SYMBOL = re.compile(r"`(?P<name>[A-Za-z_][A-Za-z0-9_.]*)`")
# A symbol list is the leading comma-separated run of backticked names at the
# start of a cell or of a `;`-separated group. Prose around it is descriptive.
LEADING_SYMBOLS = re.compile(r"^(?:`[A-Za-z_][A-Za-z0-9_.]*`(?:\s*,\s*)?)+")
HEADER_CELLS = {"Module", "M\u00f3dulo"}
# A restyle that hides the table must fail loudly; lower this only when the
# table deliberately loses modules.
MINIMUM_MODULE_ROWS = 50


def _public_api_rows(text: str) -> list[tuple[str, str]]:
    """The two cells of each row in the Public API section, in document order."""
    rows: list[tuple[str, str]] = []
    in_section = False
    for line in text.splitlines():
        heading = re.match(r"^##\s+(?P<title>.+?)\s*$", line)
        if heading:
            in_section = heading.group("title") in SECTION_HEADINGS
            continue
        if not in_section or not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 2:
            raise AssertionError(f"Public API row does not have two columns: {line}")
        first = cells[0]
        if first in HEADER_CELLS or set(first) <= {"-", ":"}:
            continue
        rows.append((first, cells[1]))
    return rows


def _symbol_names(cell: str) -> list[str]:
    """The leading backticked names of every `;`-separated group in a cell."""
    names: list[str] = []
    for group in cell.split(";"):
        leading = LEADING_SYMBOLS.match(group.strip())
        if leading is None:
            continue
        for name in SYMBOL.findall(leading.group(0)):
            if name not in names:
                names.append(name)
    return names


def _documented_rows(text: str) -> dict[str, list[str]]:
    """The module rows of the Public API table, with their highlighted names."""
    rows: dict[str, list[str]] = {}
    for first, cell in _public_api_rows(text):
        label = MODULE_CELL.match(first)
        if label is None:
            continue
        module = label.group("module")
        if module in rows:
            raise AssertionError(f"duplicated Public API row for {module}")
        rows[module] = _symbol_names(cell)
    return rows


def _legacy_row(text: str) -> tuple[tuple[str, ...], list[str]] | None:
    """The legacy compatibility row: the modules it names and its symbols."""
    for first, cell in _public_api_rows(text):
        if any(label in first for label in LEGACY_LABELS):
            return tuple(MODULE_REFERENCE.findall(first)), _symbol_names(cell)
    return None


def _is_public_attribute(value: object) -> bool:
    """Whether a module attribute is an export, not imported plumbing."""
    if isinstance(value, types.ModuleType):
        return False
    origin = getattr(value, "__module__", None)
    if origin in {"typing", "__future__"}:
        return False
    if isinstance(value, (type, types.FunctionType, types.BuiltinFunctionType)):
        return origin is None or origin == "builtins" or origin.startswith("docstruct.")
    # Constants and typing aliases (for example `SchemaValidator`) stay public.
    return True


def _exports(module_name: str) -> set[str]:
    """The names a module exports: its ``__all__``, or its public attributes.

    Several small modules predate ``__all__``; for them, the public namespace
    excluding modules and imported plumbing is the export list.
    """
    module = importlib.import_module(module_name)
    declared = getattr(module, "__all__", None)
    if declared is not None:
        return set(declared)
    return {
        name
        for name, value in vars(module).items()
        if not name.startswith("_") and _is_public_attribute(value)
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


def _name_failures(label: str, names: list[str], exported: set[str]) -> list[str]:
    """Why the listed names do not belong to the module(s), if they do not."""
    failures: list[str] = []
    for name in names:
        if "." in name:
            if not name.startswith("docstruct."):
                failures.append(
                    f"{label}: {name} must be written with its full docstruct.* path"
                )
            elif not _module_reference_exists(name):
                failures.append(f"{label}: {name} does not resolve")
        elif name not in exported:
            failures.append(f"{label}: {name} is not exported")
    return failures


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


class TestTableParser:
    def test_the_scan_is_limited_to_the_public_api_section(self):
        text = (
            "## Public API\n\n"
            "| Module | Symbols |\n|---|---|\n"
            "| `docstruct.fusion.flood` | `flood_guard` |\n\n"
            "## Other\n\n"
            "| `docstruct.fusion.verse` | `verse_blocks` |\n"
        )
        assert _documented_rows(text) == {"docstruct.fusion.flood": ["flood_guard"]}

    def test_a_name_before_prose_is_still_a_symbol(self):
        text = (
            "## Public API\n\n"
            "| Module | Symbols |\n|---|---|\n"
            "| `docstruct.fusion.flood` | `flood_guard_v9` is the newer guard |\n"
        )
        assert _documented_rows(text) == {"docstruct.fusion.flood": ["flood_guard_v9"]}

    def test_a_relative_cross_reference_is_reported(self):
        failures = _name_failures("docstruct.text", ["paragraphs.PAGE_HEADING"], set())
        assert failures == [
            "docstruct.text: paragraphs.PAGE_HEADING must be written with its "
            "full docstruct.* path"
        ]

    def test_a_row_with_three_columns_is_rejected(self):
        text = (
            "## Public API\n\n"
            "| Module | Symbols | Extra |\n|---|---|---|\n"
            "| `docstruct.fusion.flood` | `flood_guard` | x |\n"
        )
        with pytest.raises(AssertionError, match="two columns"):
            _public_api_rows(text)

    def test_the_legacy_row_is_parsed(self):
        text = (
            "## Public API\n\n"
            "| Module | Symbols |\n|---|---|\n"
            "| Legacy compatibility exports in `docstruct.types` and `docstruct` "
            "| `CanonicalDocument`, `CanonicalSection` — deprecated |\n"
        )
        assert _legacy_row(text) == (
            ("docstruct.types", "docstruct"),
            ["CanonicalDocument", "CanonicalSection"],
        )

    def test_the_fallback_does_not_count_imported_plumbing_as_exports(self):
        exported = _exports("docstruct.types")
        assert {"Any", "dataclass", "field", "annotations"}.isdisjoint(exported)
        assert {"BBox", "CanonicalBlock"} <= exported


class TestModuleTableMatchesExports:
    @pytest.mark.parametrize("path", (EN, PT), ids=("en", "pt-br"))
    def test_the_table_rows_are_unique_and_non_empty(self, path):
        text = path.read_text(encoding="utf-8")
        rows = _documented_rows(text)
        assert rows, f"{path.name}: no Public API module rows parsed"
        assert len(rows) >= MINIMUM_MODULE_ROWS, (
            f"{path.name}: only {len(rows)} module rows parsed; "
            "a restyle may have hidden the table"
        )
        assert set(DOCUMENTED_MODULES) <= set(rows), (
            f"{path.name}: the row parser lost documented modules: "
            f"{sorted(set(DOCUMENTED_MODULES) - set(rows))}"
        )
        empty = sorted(module for module, names in rows.items() if not names)
        assert not empty, f"{path.name}: rows without symbols: {empty}"
        legacy = _legacy_row(text)
        assert legacy is not None, f"{path.name}: legacy compatibility row not found"
        assert legacy[1], f"{path.name}: legacy compatibility row without symbols"

    @pytest.mark.parametrize("path", (EN, PT), ids=("en", "pt-br"))
    def test_every_listed_name_is_exported(self, path):
        text = path.read_text(encoding="utf-8")
        failures: list[str] = []
        validated = 0
        for module_name, names in _documented_rows(text).items():
            validated += len(names)
            try:
                exported = _exports(module_name)
            except ImportError as error:
                failures.append(f"{module_name}: cannot import ({error})")
                continue
            failures.extend(_name_failures(module_name, names, exported))
        # Fully-qualified references in the row's prose must resolve too.
        for _, cell in _public_api_rows(text):
            for reference in SYMBOL.findall(cell):
                if reference.startswith("docstruct.") and not _module_reference_exists(
                    reference
                ):
                    failures.append(
                        f"row references {reference}, which does not resolve"
                    )
        assert validated, f"{path.name}: no symbol names validated"
        assert not failures, (
            f"{path.name} lists names its modules do not export:\n"
            + "\n".join(failures)
        )

    @pytest.mark.parametrize("path", (EN, PT), ids=("en", "pt-br"))
    def test_the_legacy_row_is_checked(self, path):
        text = path.read_text(encoding="utf-8")
        legacy = _legacy_row(text)
        assert legacy is not None, f"{path.name}: legacy compatibility row not found"
        modules, names = legacy
        assert set(modules) == set(LEGACY_MODULES), (
            f"{path.name}: legacy row names {modules}, expected {LEGACY_MODULES}"
        )
        exported: set[str] = set()
        failures: list[str] = []
        for module_name in modules:
            try:
                exported |= _exports(module_name)
            except ImportError as error:
                failures.append(f"{module_name}: cannot import ({error})")
        failures.extend(_name_failures("legacy row", names, exported))
        assert names, f"{path.name}: legacy compatibility row without symbols"
        assert not failures, (
            f"{path.name} has a stale legacy compatibility row:\n" + "\n".join(failures)
        )

    def test_both_languages_list_the_same_names(self, en, pt):
        assert _documented_rows(en) == _documented_rows(pt)
        assert _legacy_row(en) == _legacy_row(pt)


class TestPresetsAreListed:
    @pytest.mark.parametrize("preset", PRESETS)
    def test_english_lists_the_preset(self, en, preset):
        assert preset in en, f"README.md não menciona {preset}"

    @pytest.mark.parametrize("preset", PRESETS)
    def test_mirror_lists_the_preset(self, pt, preset):
        assert preset in pt, f"README.pt-br.md não menciona {preset}"

    @pytest.mark.parametrize("preset", PRESETS)
    def test_every_preset_exists_on_the_policy(self, preset):
        assert hasattr(FusionPolicy, preset), f"FusionPolicy has no {preset} preset"


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
