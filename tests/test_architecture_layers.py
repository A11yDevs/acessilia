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
#: #758): contract modules may be imported anywhere; the others are pinned to
#: the files that import them today, and the pins can only shrink as each
#: algorithm, operation, policy or validation leaves the core's process.
DOCSTRUCT_ALLOWLIST = REPO_ROOT / "tests" / "fixtures" / "docstruct_import_allowlist.json"
DOCSTRUCT_CLASSES = {"contract", "algorithm", "validation", "policy", "operation"}
DOCSTRUCT_INVENTORY_DOCS = (
    REPO_ROOT / "docs" / "architecture" / "docstruct-import-inventory.md",
    REPO_ROOT / "docs" / "architecture" / "docstruct-import-inventory.pt-br.md",
)


def _docstruct_imports() -> dict[str, set[str]]:
    """Each imported ``docstruct`` module and the files that import it, in the core and backend/."""
    importers: dict[str, set[str]] = {}
    for directory in SERVER_DIRS:
        for path in directory.rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom) and node.module and not node.level:
                    modules = [node.module]
                elif isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                else:
                    continue
                for module in modules:
                    if module.split(".")[0] == "docstruct":
                        importers.setdefault(module, set()).add(
                            str(path.relative_to(REPO_ROOT))
                        )
    return importers


def _docstruct_allowlist() -> dict[str, dict]:
    return json.loads(DOCSTRUCT_ALLOWLIST.read_text(encoding="utf-8"))


def test_every_docstruct_import_is_classified_and_pinned() -> None:
    allowlist = _docstruct_allowlist()
    unclassified = sorted(set(_docstruct_imports()) - set(allowlist))
    unpinned = sorted(
        f"{path}: {module}"
        for module, paths in _docstruct_imports().items()
        if module in allowlist and allowlist[module]["class"] != "contract"
        for path in paths - set(allowlist[module]["files"])
    )
    assert not unclassified, (
        "docstruct modules missing from tests/fixtures/docstruct_import_allowlist.json; "
        f"classify them (ADR-0028) and add them to the inventory: {unclassified}"
    )
    assert not unpinned, (
        "new imports of docstruct computation in the core (call a Toolbox capability "
        f"instead, ADR-0028; the allowlist only shrinks): {unpinned}"
    )


def test_the_docstruct_allowlist_only_shrinks() -> None:
    imports = _docstruct_imports()
    allowlist = _docstruct_allowlist()
    stale = sorted(
        f"{module}: {path}"
        for module, entry in allowlist.items()
        for path in (entry.get("files") or ["(module)"])
        if module not in imports or (path != "(module)" and path not in imports[module])
    )
    assert not stale, (
        "remove these entries from tests/fixtures/docstruct_import_allowlist.json "
        f"and from the inventory, they are no longer imported: {stale}"
    )
    assert {entry["class"] for entry in allowlist.values()} <= DOCSTRUCT_CLASSES
    assert all(
        ("files" in entry) == (entry["class"] != "contract") for entry in allowlist.values()
    ), "pin every non-contract module to its files, and no contract module"


def test_the_docstruct_inventory_lists_the_allowlist() -> None:
    expected = set(_docstruct_allowlist())
    for document in DOCSTRUCT_INVENTORY_DOCS:
        listed = set(re.findall(r"^\| `(docstruct[\w.]*)` \|", document.read_text(encoding="utf-8"), re.M))
        assert listed == expected, (
            f"{document.relative_to(REPO_ROOT)}: missing {sorted(expected - listed)}, "
            f"extra {sorted(listed - expected)}"
        )


def test_the_scanned_directories_exist() -> None:
    """A directory that moved would make every scan above pass on nothing."""
    for directory in (*SERVER_DIRS, *APPLICATION_DIRS):
        assert directory.is_dir(), directory
        assert any(directory.rglob("*.py")), directory
