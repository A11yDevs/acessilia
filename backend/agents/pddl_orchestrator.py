from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine, Iterable
from pathlib import Path
from typing import Any


from backend.services.blocking import run_blocking
from backend.agents.provider_breaker import ProviderBreaker
from backend.core.agents.informational_structural import InformationalStructuralAgent
from backend.core.execution.executor import ExecutorAgent, MethodRegistry, StepProgress
from backend.core.execution.models import ExecutionReport, MethodResult
from backend.core.manifest.models import (
    ProcessingManifest,
)
from backend.core.manifest.toolbox_extractor import ToolboxManifestExtractor
from backend.core.planning.domain_bundle import DomainBundle
from backend.core.planning.models import NominalPlan, PlanningComparison, PlanStep
from backend.core.planning import toolbox_gate
from backend.core.planning.planner_agent import PlannerAgent
from backend.i18n import t
from backend.log_messages import (
    LOG_PDDL_PREFERRED_PLAN_MISSING,
)
from backend.stage_messages import (
    STAGE_ANALYZING_STRUCTURAL,
    STAGE_STRUCTURAL_EXTRACTION_FAILED,
    STAGE_ENRICHING_IMAGE_DESCRIPTIONS,
    STAGE_ENRICHING_TABLES_OCR,
    STAGE_GENERATING_PDDL_PLAN,
    STAGE_VALIDATING_PLAN_DRY_RUN,
    STAGE_EXECUTING_PLAN,
    STAGE_EXECUTING_PLAN_STEP,
)
from backend.tools.logger import logger
from backend.tools.toolbox_client import ToolboxError
from backend.core.pipeline.obligations import (
    _blocks_delivery,
    _pages_label,
    _replannable_obligation_ids,
    _unsatisfied_selected_obligations,
    _unsatisfied_summary,
)
from backend.core.pipeline.payload import (
    build_pddl_structured_payload,
)
from backend.core.pipeline.handlers.text import (
    _handle_chunk_verse_method,
    _handle_deterministic_heading_repair_method,
    _handle_extract_line_numbers_method,
    _handle_norm_fix_method,
    _handle_repetition_guard_method,
    _handle_tailjoin_method,
    _handle_unicode_repair_method,
)
from backend.core.pipeline.handlers.content import (
    _handle_pandoc_code_method,
    _handle_pandoc_table_method,
    _handle_vision_description_method,
)
from backend.core.pipeline.handlers.review import (
    _handle_human_review_method,
)
from backend.core.pipeline.handlers.fusion import (
    _handle_agreement_rule_method,
    _handle_dual_provider_fusion_method,
    _handle_single_provider_method,
    _handle_table_smart_fusion_method,
)
from backend.core.pipeline.handlers.order import (
    _handle_skeleton_order_method,
    _handle_xycut_order_method,
)
from backend.core.pipeline.handlers.inspection import (
    _handle_pymupdf_region_method,
    _handle_vision_page_inspection_method,
)
from backend.core.pipeline.enrichment.pictures import (
    _enrich_picture_descriptions,
)
from backend.core.pipeline.enrichment.tables import (
    _enrich_table_structures,
)
from backend.core.pipeline.enrichment.inline_math import (
    _TextSpanReader,
    _mark_inline_math,
    _mark_table_inline_math,
)
from backend.core.pipeline.preflight import (
    _check_page_limit,
    _check_page_limit_before_extraction,
    _inspect_media,
    _is_presentation,
)
from backend.core.pipeline.handlers.formula import (
    _handle_latex_normalizer_method,
    _handle_latex_verbalizer_method,
    _handle_mathml_method,
)
from backend.core.pipeline.enrichment.formulas import (
    _classify_formula_regions,
    _enrich_formula_latex,
)
from backend.core.pipeline.handlers.judge import (
    _handle_vlm_pairwise_judge_method,
)


DETERMINISTIC_METHOD_HANDLERS: dict[
    str, Callable[[ProcessingManifest, str], MethodResult]
] = {
    #: Method name -> handler for every method run directly: work done before
    #: planning, deterministic work, or one vision model call (pymupdf-region,
    #: vision-page-inspection). A method the manifest can require but that is
    #: absent here is reported to the planner as unavailable: no step only fails.
    "vision-description": _handle_vision_description_method,
    "pandoc-table": _handle_pandoc_table_method,
    "pandoc-code": _handle_pandoc_code_method,
    "pymupdf-region": _handle_pymupdf_region_method,
    "vision-page-inspection": _handle_vision_page_inspection_method,
    "latex-normalizer": _handle_latex_normalizer_method,
    "norm-fix": _handle_norm_fix_method,
    "unicode-repair": _handle_unicode_repair_method,
    "rep-guard": _handle_repetition_guard_method,
    "line-number-extractor": _handle_extract_line_numbers_method,
    "verse-chunker": _handle_chunk_verse_method,
    "tailjoin": _handle_tailjoin_method,
    "tailjoin-positioned": _handle_tailjoin_method,
    "xycut-order": _handle_xycut_order_method,
    "skeleton-order": _handle_skeleton_order_method,
    "table-smart-fusion": _handle_table_smart_fusion_method,
    "agreement-rule": _handle_agreement_rule_method,
    "deterministic-heading-repair": _handle_deterministic_heading_repair_method,
}


class StructuralExtractionError(RuntimeError):
    """The Toolbox could not extract the document structure (job-level failure)."""


class PddlAccessibilityOrchestrator:
    """Drives the PDDL pipeline: informational-extraction -> planner -> executor.

    Args:
        planner_backend (str): Which planner backend to prefer for nominal-plan generation; defaults to "internal".
        preferred_plan (str): Which plan source to prefer when multiple are available; defaults to "internal".
        execute_dry_run (bool): When True the produced plan is only validated in dry-run instead of executed for real; defaults to True.
        fast_downward (Path | None): Optional filesystem path to a fast-downward binary used when planner_backend is fast-downward; defaults to None.
        fast_downward_alias (str | None): Optional shell alias to invoke fast_downward through instead of the raw path; defaults to None.
        fast_downward_search (str): Fast-downward search heuristic string passed when the backend is active; defaults to "astar(blind())".
        enable_ocr (bool): Whether the docling extraction backend should run its OCR pass; defaults to True.
        extractor_backend (str): Which manifest-extraction backend to use.
            Supported values:
            - "toolbox" — ToolboxManifestExtractor (remote via Acessilia Toolbox)
            - "toolbox-layout" / "toolbox_layout" — mapped to "toolbox" (same REST API)
            Defaults to "toolbox".
    """

    def __init__(
        self,
        *,
        planner_backend: str = "internal",
        preferred_plan: str = "internal",
        execute_dry_run: bool = True,
        fast_downward: Path | None = None,
        fast_downward_alias: str | None = None,
        fast_downward_search: str = "astar(blind())",
        enable_ocr: bool = True,
        extractor_backend: str = "toolbox",
        max_replans: int = 2,
    ) -> None:
        self.planner_backend = planner_backend
        self.preferred_plan = preferred_plan
        self.execute_dry_run = execute_dry_run
        self.max_replans = max(0, max_replans)
        self.fast_downward = fast_downward
        self.fast_downward_alias = fast_downward_alias
        self.fast_downward_search = fast_downward_search
        self.extractor_backend = extractor_backend.strip().lower()

        if self.extractor_backend in ("toolbox", "toolbox-layout", "toolbox_layout"):
            logger.info(
                "PDDL extractor_backend={}: using ToolboxManifestExtractor",
                self.extractor_backend,
            )
            extractor = ToolboxManifestExtractor(enable_ocr=enable_ocr)
        else:
            raise ValueError(
                f"Local extractor '{self.extractor_backend}' is disabled. "
                f"Use extractor_backend='toolbox' for the PDDL+Toolbox pipeline."
            )

        self.information_structural = InformationalStructuralAgent(
            extractor
        )
        self.planner = PlannerAgent()
        self.executor = self._build_executor()

    @staticmethod
    def _build_executor() -> ExecutorAgent:
        registry = MethodRegistry()

        # Model-backed or cross-cutting methods already wired by the pipeline.
        registry.register("mathml", _handle_mathml_method)
        registry.register("latex-verbalizer", _handle_latex_verbalizer_method)
        registry.register(
            "dual-provider-fusion", _handle_dual_provider_fusion_method
        )
        registry.register("single-provider", _handle_single_provider_method)
        registry.register("vlm-pairwise-judge", _handle_vlm_pairwise_judge_method)
        for method, handler in DETERMINISTIC_METHOD_HANDLERS.items():
            registry.register(method, handler)

        # `human-review` has its own semantics: it is the terminal escalation the
        # pipeline performs when no automated method can satisfy an obligation.
        registry.register("human-review", _handle_human_review_method)

        return ExecutorAgent(registry, domain=DomainBundle.load())

    async def execute(
        self,
        file_path: Path,
        tmpdir: Path,
        status_callback: Callable[[str], Coroutine[Any, Any, None]] | None = None,
        mode: str | None = None,
        structured_output: bool = False,
        custom_prompt: str | None = None,
        thinking_mode: bool = False,
    ) -> str | dict[str, Any]:
        effective_mode = mode or "medio"

        if custom_prompt or thinking_mode:
            raise ValueError("Custom instructions and thinking mode are unavailable for this pipeline")

        source_path = file_path.resolve()
        # media.inspect runs first: a slide deck is extracted and structured
        # slide by slide, which has to be decided before extraction.
        media_inspection, media_configuration = await _inspect_media(source_path)
        _check_page_limit_before_extraction(media_inspection)
        presentation = _is_presentation(media_inspection)

        if status_callback:
            await status_callback(t(STAGE_ANALYZING_STRUCTURAL))
        manifest = await self._extract_structure(source_path, presentation)
        _check_page_limit(manifest)
        manifest.extractor.configuration["region_inspection_mode"] = effective_mode
        manifest.extractor.configuration.update(media_configuration)

        await self._enrich_before_planning(
            manifest, file_path, source_path, effective_mode, media_inspection, status_callback
        )

        if status_callback:
            await status_callback(t(STAGE_GENERATING_PDDL_PLAN))
        # One catalogue snapshot per document, so the first plan and every replan
        # see the same Toolbox.
        availability = await toolbox_gate.decide(manifest)
        _log_availability(availability)
        gated = availability.unavailable_methods
        plan, comparison = await run_blocking(
            self._build_plan, manifest, extra_unavailable=gated
        )

        execution_report: ExecutionReport | None = None
        if status_callback:
            await status_callback(
                t(STAGE_VALIDATING_PLAN_DRY_RUN)
                if self.execute_dry_run
                else t(STAGE_EXECUTING_PLAN)
            )
        # `execute_dry_run` selects the *mode* of execution; it used to also gate
        # whether the executor ran at all, so setting it to false produced a plan
        # that was never executed and a report of None. Real execution is now the
        # other branch instead of silence.
        loop = asyncio.get_running_loop()
        manifest, execution_report = await run_blocking(
            self.executor.execute,
            plan,
            manifest,
            dry_run=self.execute_dry_run,
            progress=_plan_progress(manifest, status_callback, loop),
        )
        manifest, execution_report, plan, comparison = await self._replan_until_done(
            manifest, execution_report, plan, comparison, gated, status_callback, loop
        )
        self._check_unsatisfied(manifest, execution_report)

        payload = build_pddl_structured_payload(
            file_path=file_path,
            manifest=manifest,
            plan=plan,
            planner_backend=self.planner_backend,
            execution_report=execution_report,
            comparison=comparison,
            toolbox_availability=availability.to_metadata(),
        )

        if structured_output:
            return payload
        return payload["text"]

    async def _extract_structure(self, source_path: Path, presentation: bool) -> ProcessingManifest:
        """The document's manifest from ``document.structure.extract``.

        A Toolbox failure becomes a ``StructuralExtractionError`` whose message
        names only the capability and the kind of failure.
        """
        try:
            return await run_blocking(
                self.information_structural.process,
                source_path,
                language="pt-BR",
                presentation=presentation,
            )
        except ToolboxError as exc:
            # The SDK already retried and failed over; there is no local
            # extractor to fall back on (docs/adr/0003), so the job fails here.
            # The message reaches the end user, so it names the capability and
            # the kind of failure only; the full cause, which carries internal
            # Toolbox endpoints, goes to the log and stays chained.
            logger.error("Structural extraction failed on the Toolbox: {}", exc)
            raise StructuralExtractionError(
                t(STAGE_STRUCTURAL_EXTRACTION_FAILED).format(
                    capability="document.structure.extract", error=type(exc).__name__
                )
            ) from exc

    async def _enrich_before_planning(
        self,
        manifest: ProcessingManifest,
        file_path: Path,
        source_path: Path,
        effective_mode: str,
        media_inspection: dict[str, Any] | None,
        status_callback: Callable[[str], Coroutine[Any, Any, None]] | None,
    ) -> None:
        """Describe pictures, recognize formulas and inline math, read tables.

        The steps run in this order and share one provider breaker; the inline
        math of prose and of tables share one text-span reader. ``source_path``
        is ``file_path`` resolved.
        """
        if status_callback:
            await status_callback(t(STAGE_ENRICHING_IMAGE_DESCRIPTIONS))
        # Pictures, formulas and tables reach the vision provider from the
        # same pipeline, so one that went down does not get called again for
        # every remaining object.
        from backend.config.settings import settings

        breaker = ProviderBreaker(settings.vision_breaker_threshold)
        await _classify_formula_regions(
            manifest, source_path, mode=effective_mode, breaker=breaker,
        )
        await _enrich_picture_descriptions(
            manifest,
            source_path,
            mode=effective_mode,
            media_inspection=media_inspection,
            status_callback=status_callback,
            breaker=breaker,
        )
        text_spans = _TextSpanReader(manifest, source_path)
        await _mark_inline_math(manifest, source_path, text_spans)
        await _enrich_formula_latex(
            manifest,
            source_path,
            mode=effective_mode,
            status_callback=status_callback,
            breaker=breaker,
        )

        if status_callback:
            await status_callback(t(STAGE_ENRICHING_TABLES_OCR))
        await _enrich_table_structures(
            manifest,
            file_path.resolve(),
            status_callback=status_callback,
            breaker=breaker,
        )
        # After the table enrichment, which can replace a table's cells.
        await _mark_table_inline_math(manifest, source_path, text_spans)

    async def _replan_until_done(
        self,
        manifest: ProcessingManifest,
        execution_report: ExecutionReport,
        plan: Any,
        comparison: Any,
        gated: Any,
        status_callback: Callable[[str], Coroutine[Any, Any, None]] | None,
        loop: asyncio.AbstractEventLoop,
    ) -> tuple[ProcessingManifest, ExecutionReport, Any, Any]:
        """Plan and execute again while the report asks for it, up to ``max_replans``.

        Returns the last manifest, report, plan and comparison.
        """
        # A `replan-required` report means the executor recorded `(tried ?o ?m)`
        # for a method that failed and left the obligation pending. Without this
        # loop the status was terminal in production: the pipeline returned a plan
        # it already knew was wrong, and `complete-job` never ran, so no document
        # was produced.
        replans = 0
        while (
            execution_report.replan_required
            and replans < self.max_replans
            and not self.execute_dry_run
        ):
            # Steps after a failure still run, so one execution can leave an
            # obligation exhausted (no method left) next to another that has an
            # alternative. The planner rejects exhausted obligations, so they are
            # left out of the replan; an exhausted critical one fails the job.
            exhausted = [
                obligation for obligation in manifest.obligations
                if obligation.status == "failed"
            ]
            if any(_blocks_delivery(obligation, manifest) for obligation in exhausted):
                break
            roots = _replannable_obligation_ids(manifest)
            if not roots:
                break
            replans += 1
            logger.info(
                "PDDL: replanning ({}/{}) after {}",
                replans,
                self.max_replans,
                execution_report.status,
            )
            plan, comparison = await run_blocking(
                self._build_plan,
                manifest,
                extra_unavailable=gated,
                selected_roots=roots,
            )
            manifest, execution_report = await run_blocking(
                self.executor.execute,
                plan,
                manifest,
                dry_run=False,
                progress=_plan_progress(manifest, status_callback, loop),
            )
        return manifest, execution_report, plan, comparison

    @staticmethod
    def _check_unsatisfied(manifest: ProcessingManifest, execution_report: ExecutionReport) -> None:
        """Fail the job when an obligation that blocks delivery is open.

        A run that did not complete fails when nothing is open (the failure is
        elsewhere) or a critical obligation is; with only refinements open, the
        document is delivered with a technical warning.
        """
        if execution_report.status not in {"completed", "dry-run-completed"}:
            unsatisfied = _unsatisfied_selected_obligations(manifest)
            critical = [
                obligation for obligation in unsatisfied
                if _blocks_delivery(obligation, manifest)
            ]
            if not unsatisfied or critical:
                # The ids name every target element and run to kilobytes on a
                # long document, so they go to the log; the job error, which
                # reaches the user by e-mail, says what is open and where.
                logger.warning(
                    "PDDL: unsatisfied obligations: {}",
                    ", ".join(obligation.id for obligation in unsatisfied),
                )
                raise RuntimeError(_unsatisfied_summary(manifest))
            # Only refinements are left open; the extracted content is still
            # complete, so the document is delivered with a technical warning.
            logger.warning(
                "PDDL: finishing with non-critical obligations open: {}",
                ", ".join(obligation.id for obligation in unsatisfied),
            )

    def _build_plan(
        self,
        manifest: ProcessingManifest,
        *,
        extra_unavailable: Iterable[str] = (),
        selected_roots: Iterable[str] | None = None,
    ) -> tuple[NominalPlan, PlanningComparison | None]:
        # Tell the compiler which methods the executor can actually run. Without
        # this the planner happily emits steps for methods that have no handler,
        # and the failure only surfaces at execution time -- after the model-backed
        # work has already been paid for. ``extra_unavailable`` adds the methods
        # the Toolbox availability gate rules out for this document.
        unavailable = sorted(
            set(self._unavailable_methods(manifest)) | set(extra_unavailable)
        )
        if self.planner_backend == "both":
            _, plans, comparison = self.planner.compare(
                manifest,
                selected_roots=selected_roots,
                unavailable_methods=unavailable,
                fast_downward=self.fast_downward,
                fast_downward_alias=self.fast_downward_alias,
                fast_downward_search=self.fast_downward_search,
                preferred_backend=self.preferred_plan,
            )
            if self.preferred_plan not in plans:
                raise RuntimeError(
                    t(LOG_PDDL_PREFERRED_PLAN_MISSING).format(
                        backend=self.preferred_plan
                    )
                )
            return plans[self.preferred_plan], comparison

        _, plan = self.planner.plan(
            manifest,
            selected_roots=selected_roots,
            unavailable_methods=unavailable,
            backend=self.planner_backend,
            fast_downward=self.fast_downward,
            fast_downward_alias=self.fast_downward_alias,
            fast_downward_search=self.fast_downward_search,
        )
        return plan, None

    def _unavailable_methods(self, manifest: ProcessingManifest) -> list[str]:
        """Methods this manifest can ask for that no registered handler implements.

        The set is restricted to the methods the manifest actually declares: the
        compiler rejects unknown names on purpose, so passing every method that
        exists anywhere would be reported as a typo instead of a capability gap.
        """
        registered = set(self.executor.registry.names())
        requested = {
            method
            for obligation in manifest.obligations
            for method in obligation.admissible_methods
        }
        return sorted(requested - registered)


def _plan_progress(
    manifest: ProcessingManifest,
    status_callback: Callable[[str], Coroutine[Any, Any, None]] | None,
    loop: asyncio.AbstractEventLoop,
) -> StepProgress | None:
    """Report each obligation step, with its pages, through ``status_callback``.

    The executor runs on a worker thread while the callback is a coroutine of
    the event loop, so the report is scheduled on ``loop`` and awaited from the
    thread: the step only starts once its stage is recorded, which is what lets
    a job killed mid-step still say which step and page it was on. A failing
    report, including a broken translation of the label, is logged and never
    fails the step.

    The user sees only the step and its pages; the obligation kind and method
    are internal names, so they go to the debug log.
    """
    if status_callback is None:
        return None
    page_by_element = {element.id: element.page_number for element in manifest.elements}
    pages_by_obligation = {
        obligation.id: [page_by_element.get(target) for target in obligation.target_ids]
        for obligation in manifest.obligations
    }

    def report(step: PlanStep, position: int, total: int) -> None:
        if step.action != "execute-obligation" or step.obligation_id is None:
            return
        pages = pages_by_obligation.get(step.obligation_id, [])
        logger.debug(
            "PDDL: step {}/{} {} via {}, pages {}",
            position,
            total,
            step.obligation_id,
            step.method,
            pages,
        )
        try:
            message = t(STAGE_EXECUTING_PLAN_STEP).format(
                current=position,
                total=total,
                pages=_pages_label(pages, len(manifest.pages)),
            )
            asyncio.run_coroutine_threadsafe(status_callback(message), loop).result(
                timeout=_PROGRESS_REPORT_TIMEOUT_SECONDS
            )
        except Exception as exc:  # noqa: BLE001 - progress must not fail the plan
            logger.warning("PDDL: progress of step {} not recorded: {}", position, exc)

    return report


#: Upper bound on how long a plan step waits for its progress to be recorded.
_PROGRESS_REPORT_TIMEOUT_SECONDS = 10.0


def _log_availability(availability: toolbox_gate.AvailabilityDecision) -> None:
    if not availability.blocked:
        return
    blocked = "; ".join(
        f"{method}: {', '.join(reasons)}"
        for method, reasons in availability.blocked.items()
    )
    if availability.enforced:
        logger.warning(
            "Toolbox gate (catalogue {}): methods out of the plan — {}",
            availability.catalog_revision or "unavailable",
            blocked,
        )
    else:
        logger.warning(
            "Toolbox gate observing (catalogue {}): would remove — {}",
            availability.catalog_revision or "unavailable",
            blocked,
        )
