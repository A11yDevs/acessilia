"""Run one differential case through the whole pipeline (#849).

The run is the backend's (``backend/service.py``): the PDDL orchestrator's
``execute`` with a structured output, the paragraph merge, then
``build_canonical_document``. Every Toolbox and model call goes to
:class:`~tests.differential.fake_toolbox.FakeToolbox`. The runner uses only
what core 0.3.11 already had, so ``scripts/record_differential_references.py``
runs it unchanged on an older tree to record its references.

``python -m tests.differential.runner <case.json>... --out <dir>`` writes each
case's normalized canonical document to ``<dir>/<case>.json``.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import os
import re
import shutil
import tempfile
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CASES = HERE / "cases"
REFERENCES = HERE / "references"
SOURCE_PDF = HERE / "source.pdf"

#: The harness a reference is recorded with, copied into the older tree; the
#: comparison (``compare.py``) is not part of it, so changing it does not
#: call for recording again.
HARNESS_FILES = ("__init__.py", "fake_toolbox.py", "runner.py")

#: The packages the fake needs that an older lock may lack, at the version
#: the references were recorded with (``uv run --with``).
PINNED = {"pillow": "13.0.0", "jsonschema": "4.26.0"}

#: The run's settings: every call to the fake, no cache, no retry, the
#: availability gate off (the fake publishes no catalogue).
ENVIRONMENT = {
    "TOOLBOX_BASE_URL": "http://toolbox.differential.test",
    "TOOLBOX_BASE_URLS": "",
    "AI_CLIENT": "toolbox",
    "PIPELINE_ENGINE": "pddl",
    "TOOLBOX_USE_REMOTE_CACHE": "false",
    "TOOLBOX_USE_ARTIFACT_STORE": "true",
    "TOOLBOX_AVAILABILITY_GATE": "off",
    "TOOLBOX_RETRIES": "0",
    "TOOLBOX_RETRY_BACKOFF_SECONDS": "0",
    "VISION_REGION_CACHE_ENABLED": "false",
    "VISION_RETRY_PASS_DELAY_SECONDS": "0",
    "FUSION_MODE": "single",
}

#: Where the output changes from run to run (the source's temporary path),
#: or identifies or prices the planning state rather than the document (the
#: plan, execution and manifest ids, the expected cost: they change with
#: every migration by design). JSON pointers; nothing else is dropped, so a
#: field of the same name elsewhere is still compared. The document's ``id``
#: hashes the metadata, those ids included, and is dropped too.
VOLATILE_POINTERS = frozenset({
    "/id",
    "/source/path",
    "/metadata/pddl_plan_id",
    "/metadata/pddl_execution_id",
    "/metadata/pddl_manifest_id",
    "/metadata/pddl_expected_total_cost",
})

#: The files the backend's settings read their environment from.
SETTINGS_SOURCES = ("backend/config/settings.py", "backend/config/core_config.py")


def load_case(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_case(case_path: Path) -> dict[str, Any]:
    """The normalized canonical document of ``case_path``, and what the fake saw.

    The run is hermetic (:func:`hermetic_environment`): the settings get
    their defaults plus ``ENVIRONMENT``, whatever the shell or ``.env`` says,
    so a reference recorded in a bare worktree and a run in a developer's
    tree see the same configuration.
    """
    # Imported before the environment is cleaned: the settings module loads
    # ``.env`` into the process environment once, when it is imported.
    import backend.config.settings  # noqa: F401
    from tests.differential.fake_toolbox import FakeToolbox, installed

    case = load_case(case_path)
    with hermetic_environment(case.get("environment", {})) as workdir:
        fake = FakeToolbox(case)
        source = workdir / f"{case_path.parent.name}.pdf"
        shutil.copy(SOURCE_PDF, source)
        with installed(fake):
            canonical, cacheable = asyncio.run(_run(source, case.get("mode", "normal")))
    return {
        "canonical": normalize(canonical),
        # Diagnostic only: an older core may call more or less (M4b stopped
        # reading the text layer of a document with no prose to mark).
        "calls": dict(sorted(Counter(fake.calls).items())),
        "unhandled": sorted(set(fake.unhandled)),
        "refused": sorted(set(fake.refused)),
        # How many times each LaTeX was converted: diagnostic, not compared.
        "converted": dict(sorted(Counter(fake.converted).items())),
        # Whether the backend would cache the result: a degraded one must not
        # be cached as a success (#882). Recorded, checked on this tree only.
        "cacheable": cacheable,
    }


@contextlib.contextmanager
def hermetic_environment(extra: dict[str, str]) -> Iterator[Path]:
    """Run with only the settings' defaults, ``ENVIRONMENT`` and ``extra``,
    in ``PINNED_LOCALE``.

    Every variable the backend's settings can read (each quoted upper-case
    name in ``SETTINGS_SOURCES``) is removed first, ``.env`` included, which
    ``load_dotenv`` copied into the process environment. ``DATA_DIR`` and
    ``TEMP_DIR`` point into a temporary directory, which the block gets. The
    whole environment is restored on the way out, whatever happens.
    """
    saved = dict(os.environ)
    workdir = Path(tempfile.mkdtemp(prefix="differential-"))
    locale = _pinned_locale()
    try:
        for name in _settings_variables():
            os.environ.pop(name, None)
        os.environ.update(ENVIRONMENT)
        os.environ.update({"DATA_DIR": str(workdir / "data"), "TEMP_DIR": str(workdir / "temp")})
        os.environ.update(extra)
        yield workdir
    finally:
        _restore_locale(locale)
        os.environ.clear()
        os.environ.update(saved)
        shutil.rmtree(workdir, ignore_errors=True)


#: The messages a run writes in its output (a warning, a fallback alt text)
#: follow the process locale, which an earlier test or ``LANG`` may have set.
PINNED_LOCALE = "en_US"


def _pinned_locale() -> tuple[Any, Any]:
    """Pin the server and the task locale to ``PINNED_LOCALE``; what to
    restore. Both exist since core 0.3.11."""
    from acessilia_core import i18n

    previous = i18n._SERVER_LOCALE
    i18n.configure_server_locale(PINNED_LOCALE)
    return previous, i18n.set_request_locale(PINNED_LOCALE)


def _restore_locale(pinned: tuple[Any, Any]) -> None:
    from acessilia_core import i18n

    previous, token = pinned
    i18n.reset_request_locale(token)
    i18n._SERVER_LOCALE = previous


def _settings_variables() -> set[str]:
    root = HERE.parents[1]
    names: set[str] = set()
    for relative in SETTINGS_SOURCES:
        path = root / relative
        if path.is_file():
            names.update(re.findall(r"""["']([A-Z][A-Z0-9_]{2,})["']""", path.read_text(encoding="utf-8")))
    return names


async def _run(source: Path, mode: str) -> tuple[dict[str, Any], bool]:
    # Imported here: the settings read the environment when they are built.
    from acessilia_core.pipeline.canonical_builder import build_canonical_document
    from acessilia_core.pipeline.orchestrator import PddlAccessibilityOrchestrator
    from acessilia_core.ports import RunPorts
    from backend.config.core_config import core_config_from_settings
    from backend.config.settings import Settings
    from backend.services.model_calls import get_model_calls
    from docstruct.profiles import verbosity_for_mode
    from docstruct.text.paragraphs import merge_broken_paragraphs

    settings = Settings()
    config = core_config_from_settings(settings)
    orchestrator = _orchestrator(PddlAccessibilityOrchestrator, settings)
    result = await orchestrator.execute(
        source, source.parent, None, mode=mode, structured_output=True,
        config=config, model_calls=get_model_calls(), ports=RunPorts.none(),
    )
    if not isinstance(result, dict):
        raise RuntimeError(f"the run returned {type(result).__name__}, not a structured payload")
    processed = {**result, "text": merge_broken_paragraphs(result["text"])}
    metadata = result.get("canonical_metadata")
    warnings = result.get("technical_warnings")
    canonical = build_canonical_document(
        processed,
        toolbox=config.toolbox,
        title=source.stem,
        language="pt-BR",
        verbosity=verbosity_for_mode(mode),
        source_name=source.name,
        source_path=str(source),
        audience=["reader"],
        metadata=metadata if isinstance(metadata, dict) else None,
        technical_warnings=[str(item) for item in warnings] if isinstance(warnings, list) else None,
    )
    return canonical, bool(result.get("cacheable", True))


def _orchestrator(cls: Any, settings: Any) -> Any:
    """The orchestrator ``backend/service.py`` builds, without Fast Downward:
    each argument only when this version's constructor takes it.

    The replan budgets keep the constructor's defaults, the version's own:
    the settings read them when the module is imported, before
    :func:`hermetic_environment` can clean what a shell or ``.env`` set."""
    import inspect

    wanted = {
        "planner_backend": "internal",
        "preferred_plan": settings.pddl_preferred_plan,
        "execute_dry_run": False,
        "enable_ocr": False,
        "extractor_backend": "toolbox",
    }
    accepted = inspect.signature(cls).parameters
    return cls(**{
        name: value for name, value in wanted.items()
        if name in accepted and value is not None
    })


def normalize(value: Any, pointer: str = "") -> Any:
    """``value`` without ``VOLATILE_POINTERS``, its keys sorted."""
    if isinstance(value, dict):
        return {
            key: normalize(item, f"{pointer}/{escape(key)}")
            for key, item in sorted(value.items())
            if f"{pointer}/{escape(key)}" not in VOLATILE_POINTERS
        }
    if isinstance(value, list):
        return [normalize(item, f"{pointer}/{index}") for index, item in enumerate(value)]
    return value


def escape(key: str) -> str:
    """A JSON pointer segment (RFC 6901)."""
    return str(key).replace("~", "~0").replace("/", "~1")


def identity() -> dict[str, str]:
    """What a reference depends on besides the core: SHA-256 digests of the
    harness the run copies (``HARNESS_FILES``), of every case, and of the
    source PDF, plus the versions of the packages the fake adds
    (``PINNED``). ``scripts/record_differential_references.py`` stores it in
    ``SOURCE.json``, and the test refuses a reference whose identity differs."""

    def digest(paths: list[Path]) -> str:
        hasher = hashlib.sha256()
        for path in sorted(paths):
            hasher.update(path.relative_to(HERE).as_posix().encode() + b"\0")
            hasher.update(path.read_bytes() + b"\0")
        return hasher.hexdigest()

    return {
        "harness_sha256": digest([HERE / name for name in HARNESS_FILES]),
        "cases_sha256": digest(list(CASES.glob("*/case.json"))),
        "source_pdf_sha256": hashlib.sha256(SOURCE_PDF.read_bytes()).hexdigest(),
        **{f"{name}_version": version for name, version in PINNED.items()},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cases", nargs="*", type=Path, help="case.json files (default: every case)")
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    arguments.out.mkdir(parents=True, exist_ok=True)
    for case_path in arguments.cases or sorted(CASES.glob("*/case.json")):
        outcome = run_case(case_path)
        target = arguments.out / f"{case_path.parent.name}.json"
        target.write_text(json.dumps(outcome, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"{case_path.parent.name}: {len(outcome['unhandled'])} unhandled call(s) -> {target}")


if __name__ == "__main__":
    main()
