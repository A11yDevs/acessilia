"""The installed package works on its own (ADR-0016, step 6).

CI installs ``acessilia-core`` from its lock, outside the checkout, and runs
this file from a temporary folder: the package's data must travel in the
wheel. Importing the modules alone would not load these resources, so the
test plans and executes a fixture manifest (dry run) and loads the PDDL
domain, a prompt and both translation catalogs.
"""

from __future__ import annotations

from datetime import UTC, datetime

import acessilia_core
from acessilia_core.agents.prompt_tools import (
    MODE_MAP,
    PROMPTS_DIR,
    REGION_PROMPT_MAP,
    load_system_prompt,
)
from acessilia_core.execution.executor import ExecutorAgent
from acessilia_core.i18n import get_translations
from acessilia_core.manifest.models import (
    ExtractorRun,
    ManifestElement,
    ManifestSummary,
    Obligation,
    PageDescriptor,
    ProcessingManifest,
    SourceDocument,
)
from acessilia_core.planning.domain_bundle import DomainBundle
from acessilia_core.planning.planner_agent import PlannerAgent

NOW = datetime(2026, 11, 18, tzinfo=UTC)


def _manifest() -> ProcessingManifest:
    """One picture with one obligation, satisfiable by human review only."""
    picture = ManifestElement(
        id="e-1",
        type="picture",
        raw_label="picture",
        reading_order=1,
        hierarchy_level=1,
        text=None,
        page_number=1,
        metadata={},
    )
    obligation = Obligation(
        id="o-1",
        kind="describe-image",
        target_ids=["e-1"],
        admissible_methods=["human-review"],
        method_costs={"human-review": 5},
        rationale="smoke",
    )
    obligation.selected = True
    return ProcessingManifest(
        manifest_id="manifest-smoke",
        created_at=NOW,
        source=SourceDocument(
            document_id="doc-smoke",
            filename="smoke.pdf",
            path="/nonexistent/smoke.pdf",
            media_type="application/pdf",
            byte_size=1,
            sha256="a" * 64,
        ),
        extractor=ExtractorRun(
            version="2.0.0",
            started_at=NOW,
            completed_at=NOW,
            duration_ms=1,
            configuration={},
        ),
        title="Smoke",
        language="en-US",
        pages=[PageDescriptor(page_number=1, element_ids=["e-1"])],
        elements=[picture],
        obligations=[obligation],
        summary=ManifestSummary(
            page_count=1,
            element_count=1,
            observation_count=0,
            obligation_count=1,
            element_types={},
        ),
    )


def test_the_pddl_domain_loads() -> None:
    bundle = DomainBundle.load()

    assert bundle.name == "acessilia-obligations"
    assert bundle.version == "2.3"
    assert bundle.description_path.is_file()


def test_every_prompt_ships_with_the_package() -> None:
    """The loader falls back to a short built-in text when a file is
    missing, so loading one is no proof: each file the loaders name must be
    in the package, and the loaded text must be the file's."""
    names = set(MODE_MAP.values()) | {name for name in REGION_PROMPT_MAP.values() if name}
    missing = sorted(name for name in names if not (PROMPTS_DIR / name).is_file())

    assert not missing, f"prompts missing from the package: {missing}"
    assert load_system_prompt("medio") == (PROMPTS_DIR / "medio.md").read_text(encoding="utf-8")


def test_both_catalogs_load() -> None:
    message = "Processing your document…"

    assert get_translations("pt_BR").gettext(message) == "Processando seu documento…"
    assert get_translations("en_US").gettext(message) == message


def test_a_fixture_manifest_is_planned_and_executed() -> None:
    manifest = _manifest()

    _, plan = PlannerAgent().plan(manifest, selected_roots=["o-1"])
    _, report = ExecutorAgent().execute(plan, manifest, dry_run=True)

    assert plan.steps
    assert report.status == "dry-run-completed"
    assert {step.status for step in report.steps} == {"simulated"}


def test_the_package_is_the_installed_one() -> None:
    """Run from the installed wheel, the resources above come from it."""
    assert acessilia_core.__file__ is not None
    assert DomainBundle.load().domain_path.is_relative_to(
        __import__("pathlib").Path(acessilia_core.__file__).parent
    )
