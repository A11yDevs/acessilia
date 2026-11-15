"""The PDDL pipeline's orchestrator: the sequence of ``execute``.

``PddlAccessibilityOrchestrator.execute`` inspects the source and checks the
page limit, extracts the manifest through the Toolbox, runs the enrichment
stages, plans with the PDDL planner and executes the plan with the method
registry, planning again while the execution report asks for it (up to
``max_replans``); ``_plan_progress`` reports each step to the job, and
``_log_availability`` the Toolbox's availability decision. The stages, the
handlers and the page judge live in the modules of ``backend/core/pipeline``.
Moved verbatim from ``backend/agents/pddl_orchestrator.py``, the last move of
#402's phase 3, step 6; the module itself is gone.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine, Iterable
from pathlib import Path
from typing import Any


from backend.services.blocking import run_blocking
from backend.services import job_checkpoint
from backend.services.operation_context import current_task_id
from backend.core.agents.provider_breaker import ProviderBreaker
from backend.core.config import CoreConfig, DocumentConfig, FusionConfig, ToolboxConfig
from backend.core.agents.informational_structural import InformationalStructuralAgent
from backend.core.execution.executor import (
    ExecutionResume,
    ExecutorAgent,
    StepProgress,
)
from backend.core.execution.models import ExecutionReport, ExecutionStepResult
from backend.core.manifest.models import (
    ProcessingManifest,
)
from backend.core.manifest.toolbox_extractor import ToolboxManifestExtractor
from backend.core.planning.domain_bundle import DomainBundle
from backend.core.planning.models import NominalPlan, PlanningComparison, PlanStep
from backend.core.planning import toolbox_gate
from backend.core.planning.planner_agent import PlannerAgent
from backend.core.i18n import t
from backend.core.i18n.log_messages import (
    LOG_PDDL_PREFERRED_PLAN_MISSING,
)
from backend.core.i18n.stage_messages import (
    STAGE_ANALYZING_STRUCTURAL,
    STAGE_STRUCTURAL_EXTRACTION_FAILED,
    STAGE_ENRICHING_IMAGE_DESCRIPTIONS,
    STAGE_ENRICHING_TABLES_OCR,
    STAGE_GENERATING_PDDL_PLAN,
    STAGE_VALIDATING_PLAN_DRY_RUN,
    STAGE_EXECUTING_PLAN,
    STAGE_EXECUTING_PLAN_STEP,
)
from backend.core.logger import logger
from backend.core.toolbox.toolbox_client import ToolboxError, refuse_toolbox_unlike_the_clients
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
from backend.core.pipeline.enrichment.formulas import (
    _classify_formula_regions,
    _enrich_formula_latex,
)
from backend.core.pipeline.handlers.registry import bind_config, build_method_registry


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
        max_replans (int): How many times a run plans again when the executor reports `replan-required`; negative values count as 0; defaults to 2.
        config (CoreConfig | None): The run's configuration (ADR-0016, step 3).
            When None, the bridge builds one from ``settings`` at the start of
            each run; defaults to None.
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
        config: CoreConfig | None = None,
    ) -> None:
        self.config = config
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

    def _run_config(self) -> CoreConfig:
        """The configuration of one run: the one given, or one built from ``settings`` now.

        The bridge of ADR-0016's step 3: until every stage takes its group,
        a caller that passes no config gets the settings of the run's start.
        The last step-3 pull request makes the config required.
        """
        from backend.config.core_config import core_config_from_settings

        if self.config is not None:
            refuse_toolbox_unlike_the_clients(self.config.toolbox)
            return self.config
        return core_config_from_settings()

    def _run_executor(self, config: CoreConfig) -> ExecutorAgent:
        """The executor of one run: its handlers that take ``config`` get the run's.

        Built from ``self.executor``'s registry, so a handler registered on it
        (a test's, for example) runs as well; that registry is left unchanged.
        """
        return ExecutorAgent(
            bind_config(self.executor.registry, config), domain=self.executor.domain
        )

    @staticmethod
    def _build_executor() -> ExecutorAgent:
        return ExecutorAgent(build_method_registry(), domain=DomainBundle.load())

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

        config = self._run_config()
        executor = self._run_executor(config)
        source_path = file_path.resolve()
        # Inside a job this id names the checkpoints; a benchmark or the CLI
        # calls the orchestrator without one and keeps the old behaviour.
        task_id = current_task_id()

        media_state = _load_checkpoint(task_id, job_checkpoint.PHASE_MEDIA)
        if media_state is not None:
            media_inspection = media_state.get("inspection")
            media_configuration = dict(media_state.get("configuration") or {})
        else:
            # media.inspect runs first: a slide deck is extracted and structured
            # slide by slide, which has to be decided before extraction.
            media_inspection, media_configuration = await _inspect_media(source_path)
            await _save_checkpoint(
                task_id,
                job_checkpoint.PHASE_MEDIA,
                {"inspection": media_inspection, "configuration": media_configuration},
            )
        _check_page_limit_before_extraction(media_inspection, config.document)
        presentation = _is_presentation(media_inspection)

        manifest_state = _load_checkpoint(task_id, job_checkpoint.PHASE_MANIFEST)
        resumed_manifest = manifest_state is not None
        if manifest_state is not None:
            manifest = ProcessingManifest.model_validate(manifest_state["manifest"])
        else:
            if status_callback:
                await status_callback(t(STAGE_ANALYZING_STRUCTURAL))
            manifest = await self._extract_structure(
                source_path, presentation, config.document, config.fusion
            )
        _check_page_limit(manifest, config.document)
        manifest.extractor.configuration["region_inspection_mode"] = effective_mode
        manifest.extractor.configuration.update(media_configuration)
        if not resumed_manifest:
            # Saved after the page limit and the media configuration: an
            # oversized document must not leave a checkpoint to resume from.
            await _save_checkpoint(
                task_id,
                job_checkpoint.PHASE_MANIFEST,
                {"manifest": _manifest_payload(manifest)},
            )

        enriched_state = _load_checkpoint(task_id, job_checkpoint.PHASE_ENRICHED)
        if enriched_state is not None:
            manifest = ProcessingManifest.model_validate(enriched_state["manifest"])
            # An enrichment checkpoint is complete for the mode it ran in; the
            # configuration is re-applied so a changed default is still visible.
            manifest.extractor.configuration["region_inspection_mode"] = effective_mode
            manifest.extractor.configuration.update(media_configuration)
        else:
            await self._enrich_before_planning(
                manifest, file_path, source_path, effective_mode, media_inspection, status_callback,
                config,
            )
            await _save_checkpoint(
                task_id,
                job_checkpoint.PHASE_ENRICHED,
                {"manifest": _manifest_payload(manifest)},
            )

        plan_state = _load_checkpoint(task_id, job_checkpoint.PHASE_PLAN)
        if plan_state is not None:
            plan = NominalPlan.model_validate(plan_state["plan"])
            comparison = (
                PlanningComparison.model_validate(plan_state["comparison"])
                if plan_state.get("comparison")
                else None
            )
            planning_manifest = ProcessingManifest.model_validate(plan_state["manifest"])
            availability = _availability_from(
                plan_state.get("availability") or {}, config.toolbox
            )
            gated = list(plan_state.get("gated") or [])
            replans = int(plan_state.get("replans") or 0)
        else:
            if status_callback:
                await status_callback(t(STAGE_GENERATING_PDDL_PLAN))
            # One catalogue snapshot per document, so the first plan and every
            # replan see the same Toolbox.
            availability = await toolbox_gate.decide(manifest, config)
            _log_availability(availability)
            gated = availability.unavailable_methods
            plan, comparison = await run_blocking(
                self._build_plan, manifest, extra_unavailable=gated
            )
            planning_manifest = manifest
            replans = 0
            await _save_plan(
                task_id, plan, comparison, planning_manifest, availability, gated, replans
            )

        execution_state = _load_checkpoint(task_id, job_checkpoint.PHASE_EXECUTION)
        if execution_state is not None and execution_state.get("plan_id") != plan.plan_id:
            # The plan checkpoint was replaced after this execution checkpoint
            # was written (a replan that crashed before it started). The old
            # progress does not apply to the new plan.
            execution_state = None
        if status_callback and execution_state is None:
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
        manifest, execution_report = await self._run_plan(
            plan,
            planning_manifest,
            execution_state,
            task_id,
            status_callback,
            loop,
            executor=executor,
        )
        manifest, execution_report, plan, comparison = await self._replan_until_done(
            manifest,
            execution_report,
            plan,
            comparison,
            gated,
            status_callback,
            loop,
            task_id=task_id,
            planning_manifest=planning_manifest,
            availability=availability,
            replans=replans,
            executor=executor,
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

    async def _run_plan(
        self,
        plan: NominalPlan,
        planning_manifest: ProcessingManifest,
        execution_state: dict[str, Any] | None,
        task_id: str | None,
        status_callback: Callable[[str], Coroutine[Any, Any, None]] | None,
        loop: asyncio.AbstractEventLoop,
        *,
        executor: ExecutorAgent,
    ) -> tuple[ProcessingManifest, ExecutionReport]:
        """Execute ``plan`` with the run's ``executor``, continuing from ``execution_state`` when it exists."""
        resume = None
        if execution_state is not None:
            resume = ExecutionResume(
                manifest=ProcessingManifest.model_validate(execution_state["manifest"]),
                results=[
                    ExecutionStepResult.model_validate(item)
                    for item in execution_state.get("results") or []
                ],
                replan_required=bool(execution_state.get("replan_required")),
            )
        on_step = (
            _execution_saver(task_id, plan)
            if task_id is not None and not self.execute_dry_run
            else None
        )
        return await run_blocking(
            executor.execute,
            plan,
            planning_manifest,
            dry_run=self.execute_dry_run,
            progress=_plan_progress(planning_manifest, status_callback, loop),
            resume=resume,
            on_step=on_step,
        )

    async def _extract_structure(
        self,
        source_path: Path,
        presentation: bool,
        document: DocumentConfig,
        fusion: FusionConfig,
    ) -> ProcessingManifest:
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
                document=document,
                fusion=fusion,
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
        config: CoreConfig,
    ) -> None:
        """Describe pictures, recognize formulas and inline math, read tables.

        The steps run in this order and share one provider breaker; the inline
        math of prose and of tables share one text-span reader. ``source_path``
        is ``file_path`` resolved.

        The manifest is checkpointed after each step (#407). Each step records
        per-object progress in the manifest and skips an object it already
        finished, so a restart repeats at most the step that was running.
        """
        if status_callback:
            await status_callback(t(STAGE_ENRICHING_IMAGE_DESCRIPTIONS))
        # Pictures, formulas and tables reach the vision provider from the
        # same pipeline, so one that went down does not get called again for
        # every remaining object.
        breaker = ProviderBreaker(config.vision.breaker_threshold)
        progress = _EnrichmentCheckpoint(current_task_id(), manifest).save
        await _classify_formula_regions(
            manifest, source_path, mode=effective_mode, vision=config.vision,
            breaker=breaker, on_progress=progress,
        )
        await self._checkpoint_enrichment(manifest)
        await _enrich_picture_descriptions(
            manifest,
            source_path,
            mode=effective_mode,
            vision=config.vision,
            media_inspection=media_inspection,
            status_callback=status_callback,
            breaker=breaker,
            on_progress=progress,
        )
        await self._checkpoint_enrichment(manifest)
        text_spans = _TextSpanReader(manifest, source_path)
        await _mark_inline_math(manifest, source_path, config.document, text_spans)
        await self._checkpoint_enrichment(manifest)
        await _enrich_formula_latex(
            manifest,
            source_path,
            mode=effective_mode,
            document=config.document,
            vision=config.vision,
            status_callback=status_callback,
            breaker=breaker,
            on_progress=progress,
        )
        await self._checkpoint_enrichment(manifest)

        if status_callback:
            await status_callback(t(STAGE_ENRICHING_TABLES_OCR))
        await _enrich_table_structures(
            manifest,
            file_path.resolve(),
            vision=config.vision,
            status_callback=status_callback,
            breaker=breaker,
            on_progress=progress,
        )
        await self._checkpoint_enrichment(manifest)
        # After the table enrichment, which can replace a table's cells.
        await _mark_table_inline_math(manifest, source_path, config.document, text_spans)
        await self._checkpoint_enrichment(manifest)

    async def _checkpoint_enrichment(self, manifest: ProcessingManifest) -> None:
        """Keep the manifest checkpoint current between enrichment steps (#407)."""
        task_id = current_task_id()
        if task_id is None:
            return
        await _save_checkpoint(
            task_id,
            job_checkpoint.PHASE_MANIFEST,
            {"manifest": _manifest_payload(manifest)},
        )

    async def _replan_until_done(
        self,
        manifest: ProcessingManifest,
        execution_report: ExecutionReport,
        plan: Any,
        comparison: Any,
        gated: Any,
        status_callback: Callable[[str], Coroutine[Any, Any, None]] | None,
        loop: asyncio.AbstractEventLoop,
        *,
        task_id: str | None,
        planning_manifest: ProcessingManifest,
        availability: Any,
        replans: int,
        executor: ExecutorAgent,
    ) -> tuple[ProcessingManifest, ExecutionReport, Any, Any]:
        """Plan and execute again while the report asks for it, up to ``max_replans``.

        Returns the last manifest, report, plan and comparison. The replan count
        and the plan it produced come from the checkpoint, so a restart after a
        replan neither repeats one nor exceeds the budget.
        """
        # A `replan-required` report means the executor recorded `(tried ?o ?m)`
        # for a method that failed and left the obligation pending. Without this
        # loop the status was terminal in production: the pipeline returned a plan
        # it already knew was wrong, and `complete-job` never ran, so no document
        # was produced.
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
            # The new plan applies to the manifest the execution just produced.
            planning_manifest = manifest
            plan, comparison = await run_blocking(
                self._build_plan,
                planning_manifest,
                extra_unavailable=gated,
                selected_roots=roots,
            )
            await _save_plan(
                task_id, plan, comparison, planning_manifest, availability, gated, replans
            )
            # The previous execution checkpoint belongs to the previous plan.
            _remove_checkpoint(task_id, job_checkpoint.PHASE_EXECUTION)
            manifest, execution_report = await self._run_plan(
                plan,
                planning_manifest,
                None,
                task_id,
                status_callback,
                loop,
                executor=executor,
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


class _EnrichmentCheckpoint:
    """Coalesced manifest checkpoints during one enrichment stage (#407).

    Each completed object calls :meth:`save`. One write runs at a time and a
    burst of completions during a write produces one more write with the latest
    manifest, so every object becomes durable without one full checkpoint per
    object. The manifest snapshot is taken synchronously before the write is
    handed to a thread, so concurrent folds never race with serialization.
    """

    def __init__(self, task_id: str | None, manifest: ProcessingManifest) -> None:
        self._task_id = task_id
        self._manifest = manifest
        self._lock = asyncio.Lock()
        self._pending = 0

    async def save(self) -> None:
        if self._task_id is None:
            return
        self._pending += 1
        if self._lock.locked():
            # The running writer sees the increment and writes again.
            return
        async with self._lock:
            while self._pending:
                self._pending = 0
                await _save_checkpoint(
                    self._task_id,
                    job_checkpoint.PHASE_MANIFEST,
                    {"manifest": _manifest_payload(self._manifest)},
                )


def _manifest_payload(manifest: ProcessingManifest) -> dict[str, Any]:
    return manifest.model_dump(mode="json", by_alias=True)


def _load_checkpoint(task_id: str | None, phase: str) -> dict[str, Any] | None:
    if task_id is None:
        return None
    return job_checkpoint.load(task_id, phase)


async def _save_checkpoint(
    task_id: str | None, phase: str, payload: dict[str, Any]
) -> None:
    """Persist one phase off the event loop; a failed write never fails the job."""
    if task_id is None:
        return
    try:
        await run_blocking(job_checkpoint.save, task_id, phase, payload)
    except Exception as exc:  # noqa: BLE001 - a checkpoint must not fail the job
        logger.warning("Job {}: {} checkpoint not written: {}", task_id, phase, exc)


def _remove_checkpoint(task_id: str | None, phase: str) -> None:
    if task_id is not None:
        job_checkpoint.remove(task_id, phase)


async def _save_plan(
    task_id: str | None,
    plan: NominalPlan,
    comparison: PlanningComparison | None,
    manifest: ProcessingManifest,
    availability: toolbox_gate.AvailabilityDecision,
    gated: Iterable[str],
    replans: int,
) -> None:
    await _save_checkpoint(
        task_id,
        job_checkpoint.PHASE_PLAN,
        {
            "plan": plan.model_dump(mode="json", by_alias=True),
            "comparison": (
                comparison.model_dump(mode="json", by_alias=True)
                if comparison is not None
                else None
            ),
            "manifest": _manifest_payload(manifest),
            "availability": availability.to_metadata(),
            "gated": sorted(gated),
            "replans": replans,
        },
    )


def _availability_from(
    metadata: dict[str, Any], toolbox: ToolboxConfig
) -> toolbox_gate.AvailabilityDecision:
    """Rebuild the gate decision the plan was built under, for the payload.

    A checkpoint without the mode gets the run's (``toolbox``).
    """
    blocked = metadata.get("blocked_methods") or {}
    return toolbox_gate.AvailabilityDecision(
        mode=str(metadata.get("mode") or toolbox_gate.gate_mode(toolbox)),
        catalog_revision=metadata.get("catalog_revision"),
        blocked={
            str(method): [str(reason) for reason in reasons]
            for method, reasons in blocked.items()
        },
        catalog_error=metadata.get("catalog_error"),
    )


def _execution_saver(task_id: str, plan: NominalPlan):
    """A callback the executor calls after each step, writing the checkpoint."""

    def save(snapshot: dict[str, Any]) -> None:
        if snapshot.get("plan_id") != plan.plan_id:
            # A snapshot from another plan must never overwrite this one.
            return
        try:
            job_checkpoint.save(task_id, job_checkpoint.PHASE_EXECUTION, snapshot)
        except Exception as exc:  # noqa: BLE001 - a checkpoint must not fail a step
            logger.warning(
                "Job {}: execution checkpoint not written: {}", task_id, exc
            )

    return save


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
