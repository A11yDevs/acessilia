"""The document's formula LaTeX as a planned method (#640, M3, #846).

Until 0.3.14 the orchestrator read the formulas' LaTeX before planning.
``formula-recognizer`` runs the same step as the method of the document's
``recognize-formulas`` obligation, so the plan chooses, orders and accounts it
(``docs/architecture/workflow-actions.md``): ``_enrich_formula_latex``
separates the equation labels of the obligation's formulas, then reads the
LaTeX of the ones without it, ``math.recognize`` first and the vision model as
the fallback, with its concurrency. The formulas' ``verbalize-formula`` and
``normalize-formula`` depend on it, so they work on the recognized LaTeX.

A formula the descriptions find while the plan runs (a picture the vision
model reads as a formula) gets the step on the replan, through the
reconciliation, as it did before planning until 0.3.14 (#846).

The model call of the fallback is the core's ``VisionAgent``, so the method
is ``transitional`` in ``LOCAL_METHODS`` until that call becomes a Toolbox
capability (#804, #735). Its Toolbox calls (``math.recognize``, and
``pdf.render`` for the crop) degrade per formula, so they are not
requirements that could rule it out (#848).

The breaker, the region cache and the progress reporter are the run's
(``RunPorts``), the ones the steps before planning use. The mode is the one
the run recorded in the manifest (``region_inspection_mode``).

**The step can change obligations.** A formula the vision fallback reads as
a picture becomes one: its formula obligations are replaced by a
``describe-image``, which the executor skips and the replan plans (M0).

**What the result means.** ``success`` and ``validated`` say that the step
ran for every formula of the obligation, not that each one now has LaTeX: a
formula left without keeps its text and its reason
(``formula_recognition_failure``), and its own obligations validate it. The
message reports what happened to each formula. The method fails when the
step raises, and when none of its targets is in the manifest any more
(``MSG_MATH_NO_FORMULA``).

**Inside the step the strategy stays fixed:** ``math.recognize`` first, the
vision model as the fallback, each reading gated by the text layer. The plan
chooses, orders and accounts the step, not that strategy.

**One probe per obligation.** ``math.recognize``'s outage is paid once per
call of the method; a second obligation, for formulas found while the plan
ran, probes again (``_MathRecognizer``).
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from acessilia_core.config import CoreConfig
from acessilia_core.execution.models import MethodResult
from acessilia_core.i18n import n, t
from acessilia_core.i18n.stage_messages import STAGE_ENRICHING_FORMULAS
from acessilia_core.manifest.models import ManifestElement, ProcessingManifest
from acessilia_core.pipeline.enrichment.common import run_breaker
from acessilia_core.pipeline.enrichment.formulas import _enrich_formula_latex
from acessilia_core.pipeline.handlers.common import run_status, step_checkpoint
from acessilia_core.pipeline.handlers.messages import (
    MSG_FORMULAS_RECOGNIZED,
    MSG_MATH_NO_FORMULA,
)
from acessilia_core.ports import RunPorts, region_cache_for
from acessilia_sdk.runtime import run_sync


async def _recognize_formulas(
    manifest: ProcessingManifest,
    source: Path,
    config: CoreConfig,
    ports: RunPorts,
    targets: frozenset[str],
    obligation_id: str,
) -> None:
    """Recognize the obligation's ``targets``: a second obligation
    (``obligation-recognize-formulas-2``, #832) never reads again a formula
    an earlier one owns."""
    status = run_status(ports)
    if status is not None:
        await status(t(STAGE_ENRICHING_FORMULAS))
    await _enrich_formula_latex(
        manifest,
        source,
        mode=str(manifest.extractor.configuration.get("region_inspection_mode", "medio")),
        document=config.document,
        vision=config.vision,
        toolbox=config.toolbox,
        models=config.models,
        region_cache=region_cache_for(ports, config.vision),
        status_callback=status,
        breaker=run_breaker(ports, config.vision),
        targets=targets,
        # Each finished object is saved into the execution checkpoint (#836).
        on_progress=step_checkpoint(ports, manifest, obligation_id),
    )


def _snapshot(element: ManifestElement) -> tuple[Any, Any]:
    return element.metadata.get("formula_recognition"), element.metadata.get("equation_number")


def _outcome(element: ManifestElement, before: tuple[Any, Any]) -> str:
    """What the step left on a formula it worked on: ``picture`` (the
    fallback read it as one), the recognition method of a new reading,
    ``text-layer`` (no reading agreed with the text layer, so it kept it),
    the failure reason, ``not_formula`` (another step's element now, not
    tried) or ``unchanged`` (nothing to read: its label, at most, moved)."""
    if element.type == "picture":
        return "picture"
    if element.type != "formula":
        return "not_formula"
    recognition = element.metadata.get("formula_recognition")
    if recognition != before[0] and isinstance(recognition, dict):
        return str(recognition.get("method"))
    failure = element.metadata.get("formula_recognition_failure")
    return str(failure) if failure else "unchanged"


def _handle_formula_recognizer_method(
    manifest: ProcessingManifest, obligation_id: str, *, config: CoreConfig, ports: RunPorts
) -> MethodResult:
    """Recognize the document's formulas; satisfied once the step ran for all of them."""
    obligation = next((item for item in manifest.obligations if item.id == obligation_id), None)
    targets = frozenset(obligation.target_ids) if obligation is not None else frozenset()
    formulas = [element for element in manifest.elements if element.id in targets]
    if not formulas:
        return MethodResult(success=False, validated=False, message=t(MSG_MATH_NO_FORMULA))
    before = {element.id: _snapshot(element) for element in formulas}
    run_sync(_recognize_formulas(manifest, Path(manifest.source.path), config, ports, targets, obligation_id))
    outcomes = Counter(_outcome(element, before[element.id]) for element in formulas)
    numbered = sum(
        element.metadata.get("equation_number") is not None and before[element.id][1] is None
        for element in formulas
    )
    pictures = outcomes.pop("picture", 0)
    outcomes.pop("unchanged", None)
    recognized = {method: outcomes.pop(method) for method in ("math.recognize", "vision") if method in outcomes}
    return MethodResult(
        success=True,
        validated=True,
        message=n(*MSG_FORMULAS_RECOGNIZED, len(formulas)).format(
            count=len(formulas),
            recognized=sum(recognized.values()),
            methods=", ".join(f"{method}: {count}" for method, count in recognized.items()) or "-",
            numbered=numbered,
            pictures=pictures,
            left=", ".join(f"{reason}: {count}" for reason, count in sorted(outcomes.items())) or "-",
        ),
    )


__all__ = ["_handle_formula_recognizer_method"]
