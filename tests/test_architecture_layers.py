"""Dependency direction between the Acessilia components (docs/adr/0002).

core → SDK, docstruct; SDK → docstruct and the Toolbox's published contract;
Toolbox → docstruct. The core reaches the Toolbox through the SDK and its
published HTTP contract only, so the backend must never import the Toolbox
package. Nor may it import the libraries that perform operations, which run
on the Toolbox too (docs/adr/0003). docstruct and the SDK guard their own side
in their ``tests/test_purity.py``.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
#: The core's package, out of backend/ since ADR-0016's step 6.
CORE_DIR = REPO_ROOT / "libs" / "core" / "src" / "acessilia_core"
#: The service and the core: both must reach the Toolbox through the SDK.
SERVER_DIRS = (BACKEND_DIR, CORE_DIR)
FORBIDDEN_IN_BACKEND = ("acessilia_toolbox",)


def _imported_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            roots.add(node.module.split(".")[0])
    return roots


def test_backend_does_not_import_the_toolbox_package() -> None:
    offenders = sorted(
        str(path.relative_to(REPO_ROOT))
        for directory in SERVER_DIRS
        for path in directory.rglob("*.py")
        if _imported_roots(path) & set(FORBIDDEN_IN_BACKEND)
    )
    assert not offenders, (
        "backend modules importing the Toolbox package "
        f"(use the HTTP contract instead): {offenders}"
    )




def test_the_core_imports_nothing_from_the_frontend() -> None:
    """The core owns its messages (ADR-0016, step 2); the frontend may import the core, not the reverse.

    Imports inside functions count: ``_imported_roots`` walks the whole module.
    """
    offenders = sorted(
        str(path.relative_to(REPO_ROOT))
        for path in CORE_DIR.rglob("*.py")
        if "frontend" in _imported_roots(path)
    )
    assert not offenders, f"libs/core/src/acessilia_core modules importing the frontend: {offenders}"

#: Libraries that run operations (rendering, OCR, conversion, extraction). They
#: belong to the Toolbox; the core reaches them through its capabilities
#: (docs/adr/0003). Tests may still use some of them to build fixtures.
#: There is no allowlist of exceptions (constitution, P4): one needs an ADR,
#: and once added it can only shrink.
OPERATIONAL_LIBRARIES = (
    "cv2",
    "docling",
    "docx",
    "fitz",
    "latex2mathml",
    "pymupdf",
    "PIL",
    "pypdf",
    "pypandoc",
    "rapidocr",
    "rapidocr_onnxruntime",
    "reportlab",
)
APPLICATION_DIRS = (BACKEND_DIR, CORE_DIR, REPO_ROOT / "frontend")


def test_the_application_imports_no_operational_library() -> None:
    offenders = sorted(
        f"{path.relative_to(REPO_ROOT)}: {', '.join(sorted(found))}"
        for directory in APPLICATION_DIRS
        for path in directory.rglob("*.py")
        if (found := _imported_roots(path) & set(OPERATIONAL_LIBRARIES))
    )
    assert not offenders, (
        "operational libraries imported by the application "
        f"(call the Toolbox capability instead, docs/adr/0003): {offenders}"
    )


#: Modules that may build an HTTP client themselves. The core reaches the
#: Toolbox through the SDK's clients (#402); these reach services that are not
#: the Toolbox. The list can only shrink.
HTTP_CLIENT_EXCEPTIONS = {
    # Health probes of Ollama and OpenRouter, which are not the Toolbox (#402).
    "backend/api/routes/health.py",
}


def test_the_backend_builds_no_http_client_for_the_toolbox() -> None:
    importers = {
        str(path.relative_to(REPO_ROOT))
        for directory in SERVER_DIRS
        for path in directory.rglob("*.py")
        if "httpx" in _imported_roots(path)
    }
    assert importers <= HTTP_CLIENT_EXCEPTIONS, (
        "backend modules importing httpx (reach the Toolbox through the SDK's "
        f"clients instead, #402): {sorted(importers - HTTP_CLIENT_EXCEPTIONS)}"
    )
    assert HTTP_CLIENT_EXCEPTIONS <= importers, (
        "remove exceptions that no longer import httpx: "
        f"{sorted(HTTP_CLIENT_EXCEPTIONS - importers)}"
    )


#: Every docstruct module the core and backend/ import, classified (ADR-0028,
#: #758). Contract modules may be imported anywhere. Every other module is
#: pinned to the files that import it today and to the names each file
#: imports or reads (``*`` for a dynamic use); the pins can only shrink as each
#: algorithm, operation, policy or validation leaves the core's process.
DOCSTRUCT_ALLOWLIST = REPO_ROOT / "tests" / "fixtures" / "docstruct_import_allowlist.json"
DOCSTRUCT_CLASSES = {"contract", "algorithm", "validation", "policy", "operation"}
#: The contract modules, the only unpinned class. A mixed module takes its
#: most operational class (see the inventory), so adding a module here is a
#: reviewed change to this test, not only to the fixture.
DOCSTRUCT_CONTRACT_MODULES = {"docstruct.manifest", "docstruct.export.formats"}
DOCSTRUCT_INVENTORY_DOCS = (
    REPO_ROOT / "docs" / "architecture" / "docstruct-import-inventory.md",
    REPO_ROOT / "docs" / "architecture" / "docstruct-import-inventory.pt-br.md",
)

#: ``{module: {file: {names}}}``
DocstructImports = dict[str, dict[str, set[str]]]


def _docstruct_names(tree: ast.AST) -> list[tuple[str, str]]:
    """``(module, name)`` for each docstruct name a module imports or uses.

    ``from docstruct.x import a`` gives ``a``. ``import docstruct.x as m`` gives
    each ``m.attr`` the module reads, and ``*`` when it uses ``m`` any other
    way (``getattr(m, name)``, passing ``m`` along): a transitional exception
    the inventory lists.
    """
    found: list[tuple[str, str]] = []
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.extend((node.module, alias.name) for alias in node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    aliases[alias.asname] = alias.name
                else:
                    found.append((alias.name, "*"))
    read = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id in aliases:
                found.append((aliases[node.value.id], node.attr))
                read.add(id(node.value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in aliases and id(node) not in read:
            found.append((aliases[node.id], "*"))
    return [(module, name) for module, name in found if module.split(".")[0] == "docstruct"]


def _docstruct_imports() -> DocstructImports:
    """Each docstruct module, the files that import it and the names they use, in the core and backend/."""
    imports: DocstructImports = {}
    for directory in SERVER_DIRS:
        for path in directory.rglob("*.py"):
            relative = str(path.relative_to(REPO_ROOT))
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for module, name in _docstruct_names(tree):
                imports.setdefault(module, {}).setdefault(relative, set()).add(name)
    return imports


def _docstruct_allowlist() -> dict[str, dict]:
    return json.loads(DOCSTRUCT_ALLOWLIST.read_text(encoding="utf-8"))


def _docstruct_violations(
    imports: DocstructImports, allowlist: dict[str, dict]
) -> tuple[list[str], list[str], list[str]]:
    """``(unclassified, unpinned, stale)`` for ``imports`` against ``allowlist``.

    Unpinned: a file, or a name, that a non-contract module's pin does not
    list. Stale: a module, file or name the allowlist lists and the code no
    longer imports.
    """
    unclassified = sorted(set(imports) - set(allowlist))
    unpinned: list[str] = []
    stale: list[str] = []
    for module, entry in sorted(allowlist.items()):
        importers = imports.get(module, {})
        if not importers:
            stale.append(module)
            continue
        if entry["class"] == "contract":
            continue
        pins = {path: set(names) for path, names in entry["files"].items()}
        for path, names in sorted(importers.items()):
            for name in sorted(names - pins.get(path, set())):
                unpinned.append(f"{path}: {module}.{name}")
        for path, names in sorted(pins.items()):
            for name in sorted(names - importers.get(path, set())):
                stale.append(f"{path}: {module}.{name}")
    return unclassified, unpinned, stale


def test_every_docstruct_import_is_classified_and_pinned() -> None:
    unclassified, unpinned, _ = _docstruct_violations(_docstruct_imports(), _docstruct_allowlist())
    assert not unclassified, (
        "docstruct modules missing from tests/fixtures/docstruct_import_allowlist.json; "
        f"classify them (ADR-0028) and add them to the inventory: {unclassified}"
    )
    assert not unpinned, (
        "new imports of docstruct computation in the core (call a Toolbox capability "
        f"instead, ADR-0028; the allowlist only shrinks): {unpinned}"
    )


def test_the_docstruct_allowlist_only_shrinks() -> None:
    _, _, stale = _docstruct_violations(_docstruct_imports(), _docstruct_allowlist())
    assert not stale, (
        "remove these entries from tests/fixtures/docstruct_import_allowlist.json "
        f"(and a module's row from the inventory), they are no longer imported: {stale}"
    )


def test_the_docstruct_classes_are_closed() -> None:
    allowlist = _docstruct_allowlist()
    assert {entry["class"] for entry in allowlist.values()} <= DOCSTRUCT_CLASSES
    contracts = {module for module, entry in allowlist.items() if entry["class"] == "contract"}
    assert contracts == DOCSTRUCT_CONTRACT_MODULES, (
        "the contract modules changed; a mixed module takes its most operational "
        "class (docs/architecture/docstruct-import-inventory.md)"
    )
    assert all(
        ("files" in entry) == (entry["class"] != "contract") for entry in allowlist.values()
    ), "pin every non-contract module to its files, and no contract module"


_PINNED = {
    "docstruct.fusion.judge": {"class": "algorithm", "files": {"a.py": ["should_judge"]}},
    "docstruct.manifest": {"class": "contract"},
}


def test_the_docstruct_guard_refuses_a_new_name_in_an_existing_import() -> None:
    imports = {"docstruct.fusion.judge": {"a.py": {"should_judge", "decide_pair"}},
               "docstruct.manifest": {"a.py": {"StructuredDocument"}}}
    assert _docstruct_violations(imports, _PINNED) == (
        [], ["a.py: docstruct.fusion.judge.decide_pair"], []
    )


def test_the_docstruct_guard_refuses_a_new_importer() -> None:
    imports = {"docstruct.fusion.judge": {"a.py": {"should_judge"}, "b.py": {"should_judge"}},
               "docstruct.manifest": {"b.py": {"StructuredDocument"}}}
    assert _docstruct_violations(imports, _PINNED) == (
        [], ["b.py: docstruct.fusion.judge.should_judge"], []
    )


def test_the_docstruct_guard_refuses_an_unclassified_module() -> None:
    imports = {"docstruct.fusion.judge": {"a.py": {"should_judge"}},
               "docstruct.manifest": {"a.py": {"StructuredDocument"}},
               "docstruct.new": {"a.py": {"thing"}}}
    assert _docstruct_violations(imports, _PINNED)[0] == ["docstruct.new"]


def test_the_docstruct_guard_reports_obsolete_pins() -> None:
    imports = {"docstruct.fusion.judge": {"b.py": {"should_judge"}}}
    unclassified, unpinned, stale = _docstruct_violations(imports, _PINNED)
    assert unclassified == []
    assert unpinned == ["b.py: docstruct.fusion.judge.should_judge"]
    assert stale == ["a.py: docstruct.fusion.judge.should_judge", "docstruct.manifest"]


def test_the_docstruct_scan_resolves_module_aliases() -> None:
    tree = ast.parse(
        "import docstruct.text.latex as latex\n"
        "import docstruct.tables.ast as tables\n"
        "import docstruct.geometry\n"
        "from docstruct.manifest import StructuredDocument\n"
        "latex.bare_latex(x)\n"
        "y = getattr(tables, name)\n"
    )
    assert sorted(_docstruct_names(tree)) == [
        ("docstruct.geometry", "*"),
        ("docstruct.manifest", "StructuredDocument"),
        ("docstruct.tables.ast", "*"),
        ("docstruct.text.latex", "bare_latex"),
    ]


def test_the_docstruct_inventory_lists_the_allowlist() -> None:
    expected = set(_docstruct_allowlist())
    for document in DOCSTRUCT_INVENTORY_DOCS:
        listed = set(re.findall(r"^\| `(docstruct[\w.]*)` \|", document.read_text(encoding="utf-8"), re.M))
        assert listed == expected, (
            f"{document.relative_to(REPO_ROOT)}: missing {sorted(expected - listed)}, "
            f"extra {sorted(listed - expected)}"
        )


#: Every module in acessilia_core.agents, classified (ADR-0029, #768) by role
#: and lifecycle. All agency is in the core: an agent is strategic (global
#: goals), managerial (a domain subplan, #774) or operational (a logically
#: atomic task), and no agent moves to the Toolbox, which stays passive. A
#: support module is operational (decomposed with the operational code) or
#: infrastructure (stays while the core makes model calls). The lifecycle
#: separates a permanent component (active) from one being decomposed into
#: non-agentic Toolbox capabilities (legacy) or retired (deprecated).
AGENT_CLASSIFICATION = REPO_ROOT / "tests" / "fixtures" / "core_agent_classification.json"
AGENT_CLASSES = {
    "agent": {"strategic", "managerial", "operational"},
    "support": {"operational", "infrastructure"},
}
AGENT_LIFECYCLES = {"active", "legacy", "deprecated"}
AGENT_CLASSIFICATION_DOCS = (
    REPO_ROOT / "docs" / "architecture" / "core-agent-classification.md",
    REPO_ROOT / "docs" / "architecture" / "core-agent-classification.pt-br.md",
)


def test_every_core_agent_module_is_classified() -> None:
    classification = json.loads(AGENT_CLASSIFICATION.read_text(encoding="utf-8"))
    modules = {path.stem for path in (CORE_DIR / "agents").glob("*.py")} - {"__init__"}
    assert set(classification) == modules, (
        "classify the new agent modules in tests/fixtures/core_agent_classification.json "
        f"(ADR-0029): missing {sorted(modules - set(classification))}, "
        f"stale {sorted(set(classification) - modules)}"
    )
    wrong = sorted(
        module for module, entry in classification.items()
        if entry["class"] not in AGENT_CLASSES.get(entry["kind"], set())
        or entry.get("lifecycle") not in AGENT_LIFECYCLES
    )
    assert not wrong, f"unknown kind, class or lifecycle: {wrong}"


def test_the_agent_classification_lists_the_fixture() -> None:
    expected = set(json.loads(AGENT_CLASSIFICATION.read_text(encoding="utf-8")))
    for document in AGENT_CLASSIFICATION_DOCS:
        listed = set(re.findall(r"^\| `agents/(\w+)` \|", document.read_text(encoding="utf-8"), re.M))
        assert listed == expected, (
            f"{document.relative_to(REPO_ROOT)}: missing {sorted(expected - listed)}, "
            f"extra {sorted(listed - expected)}"
        )


def test_the_scanned_directories_exist() -> None:
    """A directory that moved would make every scan above pass on nothing."""
    for directory in (*SERVER_DIRS, *APPLICATION_DIRS):
        assert directory.is_dir(), directory
        assert any(directory.rglob("*.py")), directory
