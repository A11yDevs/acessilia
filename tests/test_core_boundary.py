"""The core's boundary, before its extraction to ``libs/core`` (ADR-0016, step 5).

Checked on ``backend/core`` with an AST scan that includes imports inside
functions:

- it imports nothing from ``backend`` outside ``backend/core``, and nothing
  from ``frontend``;
- its other imports are the standard library and the libraries the ADR
  allows, with edge-tts as the deviation ADR-0003 records;
- it reads no environment variable;
- and the SDK and docstruct do not import it.

The service passes what the core needs instead: the ``CoreConfig`` (step 3),
the process setup (``backend/config/process_setup.py``, steps 3 and 5) and the
``RunPorts`` (step 4).
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "backend" / "core"

#: Third-party libraries the core may import, by top-level module (ADR-0016,
#: "acessilia_core may import ...").
ALLOWED_LIBRARIES = {
    "acessilia_sdk": "the SDK",
    "docstruct": "docstruct",
    "agno": "Agno: the agents, and the executor's workflow",
    "pydantic": "the manifest, plan and output models",
    "loguru": "the logger",
    "babel": "the translation catalogs",
    "jsonschema": "the manifest schema",
    "rapidfuzz": "the fusion's text comparison",
}

#: Allowed only as a recorded deviation: it leaves when the audio export
#: becomes a Toolbox capability (ADR-0003, acessilia-toolbox#73).
DEVIATIONS = {
    "edge_tts": "https://github.com/A11yDevs/acessilia-toolbox/issues/73",
}

#: Ways to read the environment, by the attribute or name used. ``tempfile``
#: honours ``TMPDIR`` inside the standard library; that is not the core
#: reading its environment, so it is not listed.
ENVIRONMENT_READS = {
    ("os", "environ"), ("os", "environb"), ("os", "getenv"), ("os", "getenvb"),
    ("os", "putenv"), ("os", "unsetenv"), ("Path", "home"),
}
#: Read ``HOME`` or any variable, on whatever they are called
#: (``os.path.expanduser``, ``Path(...).expanduser()``).
ENVIRONMENT_METHODS = {"expanduser", "expandvars"}
ENVIRONMENT_NAMES = {"environ", "environb", "getenv", "getenvb", "expanduser", "expandvars"}


def _modules(root: Path) -> Iterator[tuple[str, ast.AST]]:
    for path in sorted(root.rglob("*.py")):
        yield path.relative_to(ROOT).as_posix(), ast.parse(path.read_text(encoding="utf-8"))


def _imports(tree: ast.AST) -> Iterator[tuple[int, str]]:
    """Every absolute import, inside functions included, as ``(line, module)``.

    A relative import stays inside its package, so it is not a boundary.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.lineno, node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name


def _core_imports() -> list[tuple[str, int, str]]:
    return [(rel, line, module) for rel, tree in _modules(CORE) for line, module in _imports(tree)]


def test_the_scan_sees_the_core() -> None:
    """A scan that found nothing would pass every check below."""
    found = _core_imports()

    assert len(list(_modules(CORE))) > 100
    assert any(module == "acessilia_sdk.toolbox" for _, _, module in found)


def test_the_core_imports_nothing_from_the_service_or_the_frontends() -> None:
    found = [
        f"{rel}:{line} {module}"
        for rel, line, module in _core_imports()
        if (module == "backend" or module.startswith("backend."))
        and not (module == "backend.core" or module.startswith("backend.core."))
        or module == "frontend" or module.startswith("frontend.")
    ]

    assert not found, "backend/core reaches outside itself:\n" + "\n".join(found)


def test_the_core_imports_only_the_allowed_libraries() -> None:
    stdlib = set(sys.stdlib_module_names)
    allowed = stdlib | set(ALLOWED_LIBRARIES) | set(DEVIATIONS) | {"backend"}
    found = sorted(
        f"{rel}:{line} {module}"
        for rel, line, module in _core_imports()
        if module.split(".")[0] not in allowed
    )

    assert not found, "backend/core imports a library ADR-0016 does not allow:\n" + "\n".join(found)


@pytest.mark.parametrize("library", sorted(set(ALLOWED_LIBRARIES) | set(DEVIATIONS)))
def test_every_allowed_library_is_still_used(library) -> None:
    """The allowlist only shrinks: a library the core stopped importing leaves it."""
    assert any(module.split(".")[0] == library for _, _, module in _core_imports()), (
        f"{library} is allowed but not imported; remove it from the allowlist"
    )


def test_the_deviation_stays_where_it_is_recorded() -> None:
    """edge-tts is the audio exporter's, and nobody else's."""
    users = {rel for rel, _, module in _core_imports() if module.split(".")[0] == "edge_tts"}

    assert users == {"backend/core/export/exporters/audio_exporter.py"}


def _aliases(tree: ast.AST) -> dict[str, str]:
    """The local names bound to ``os`` and ``Path`` (``import os as o``)."""
    aliases = {"os": "os", "Path": "Path"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "os":
                    aliases[alias.asname or "os"] = "os"
        elif isinstance(node, ast.ImportFrom) and node.module == "pathlib":
            for alias in node.names:
                if alias.name == "Path":
                    aliases[alias.asname or "Path"] = "Path"
    return aliases


def _environment_reads(tree: ast.AST) -> Iterator[tuple[int, str]]:
    aliases = _aliases(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in ENVIRONMENT_METHODS:
            yield node.lineno, f".{node.attr}"
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if (aliases.get(node.value.id), node.attr) in ENVIRONMENT_READS:
                yield node.lineno, f"{node.value.id}.{node.attr}"
        elif isinstance(node, ast.ImportFrom) and node.module in {"os", "os.path", "dotenv"}:
            names = {alias.name for alias in node.names}
            if node.module == "dotenv" or names & ENVIRONMENT_NAMES:
                yield node.lineno, f"from {node.module} import {', '.join(sorted(names))}"
        elif isinstance(node, ast.Import) and any(a.name == "dotenv" for a in node.names):
            yield node.lineno, "import dotenv"


def test_the_core_reads_no_environment_variable() -> None:
    """The service reads its environment and passes what the core needs."""
    found = [
        f"{rel}:{line} {read}"
        for rel, tree in _modules(CORE)
        for line, read in _environment_reads(tree)
    ]

    assert not found, "backend/core reads the environment:\n" + "\n".join(found)


@pytest.mark.parametrize(
    "source",
    [
        "import os\nos.environ.get('X')",
        "import os\nos.getenv('X')",
        "from os import environ",
        "from os import getenv as read",
        "import os.path\nos.path.expanduser('~')",
        "from pathlib import Path\nPath.home()",
        "from pathlib import Path\nPath('~').expanduser()",
        "from dotenv import load_dotenv",
        "import os as system\nsystem.environ['X']",
        "from pathlib import Path as P\nP.home()",
    ],
)
def test_the_environment_scan_sees_each_way_to_read_it(source) -> None:
    """The scan is only as good as what it recognizes."""
    reads = list(_environment_reads(ast.parse(source)))

    assert reads, source


@pytest.mark.parametrize("library", ["libs/sdk/src", "libs/docstruct/src"])
def test_the_libraries_do_not_import_the_core(library) -> None:
    found = [
        f"{rel}:{line} {module}"
        for rel, tree in _modules(ROOT / library)
        for line, module in _imports(tree)
        if module.split(".")[0] in {"backend", "frontend", "acessilia_core"}
    ]

    assert not found, f"{library} imports the core or the service:\n" + "\n".join(found)
