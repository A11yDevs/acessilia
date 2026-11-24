"""The PDDL pipeline's orchestrator: the sequence of ``execute``.

``PddlAccessibilityOrchestrator.execute`` inspects the source and checks the
page limit, extracts the manifest through the Toolbox, runs the enrichment
stages, plans with the PDDL planner and executes the plan with the method
registry, planning again while the execution report asks for it (up to
``max_replans`` after a failed step, ``max_discovery_replans`` after a run
that changed the obligations); ``pipeline/progress.py`` reports each step to
the job, and ``_log_availability`` the Toolbox's availability decision. The
stages, the handlers and the page judge live in the modules of
``libs/core/src/acessilia_core/pipeline``; the module was moved verbatim from
``backend/agents/pddl_orchestrator.py`` (#402, phase 3, step 6).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from acessilia_core.agents.informational_structural import InformationalStructuralAgent
from acessilia_core.agents.model_calls import ModelCallRunner, model_call_scope
from acessilia_core.blocking import run_blocking
from acessilia_core.config import (
    CoreConfig,
    DocumentConfig,
    FusionConfig,
    PathsConfig,
    ToolboxConfig,
)
from acessilia_core.execution.executor import ExecutionResume, ExecutorAgent
from acessilia_core.execution.models import ExecutionReport, ExecutionStepResult
from acessilia_core.i18n import t
from acessilia_core.i18n.stage_messages import (
    STAGE_ANALYZING_STRUCTURAL,
    STAGE_ENRICHING_FORMULAS,
    STAGE_EXECUTING_PLAN,
    STAGE_GENERATING_PDDL_PLAN,
    STAGE_STRUCTURAL_EXTRACTION_FAILED,
    STAGE_VALIDATING_PLAN_DRY_RUN,
)
from acessilia_core.logger import logger
from acessilia_core.manifest.models import ProcessingManifest, validate_obligation_graph
from acessilia_core.manifest.toolbox_extractor import ToolboxManifestExtractor
from acessilia_core.pipeline.checkpointing import (
    RunCheckpoints,
    manifest_payload,
    resumed_manifest,
)
from acessilia_core.pipeline.document_obligations import reconcile_document_steps
from acessilia_core.pipeline.enrichment.common import run_breaker
from acessilia_core.pipeline.enrichment.formulas import _classify_formula_regions
from acessilia_core.pipeline.enrichment.inline_math import (
    _mark_inline_math,
    _mark_inline_math_after_execution,
    run_text_spans,
)
from acessilia_core.pipeline.enrichment.pictures import _prepare_pictures
from acessilia_core.pipeline.handlers.registry import bind_run, build_method_registry
from acessilia_core.pipeline.obligations import (
    _blocks_delivery,
    _replannable_obligation_ids,
    _unsatisfied_selected_obligations,
    _unsatisfied_summary,
    planning_signature,
)
from acessilia_core.pipeline.payload import build_pddl_structured_payload
from acessilia_core.pipeline.preflight import (
    _check_page_limit,
    _check_page_limit_before_extraction,
    _inspect_media,
    _is_presentation,
)
from acessilia_core.pipeline.progress import _plan_progress, _thread_status
from acessilia_core.planning import toolbox_gate
from acessilia_core.planning.domain_bundle import DomainBundle
from acessilia_core.planning.engine import (
    CatalogueFacts,
    PddlPlanningEngine,
    PlanningEngine,
    PlanningProblem,
    _lazy_planner,
    require_engine,
)
from acessilia_core.planning.models import (
    DEFAULT_FAST_DOWNWARD_SEARCH,
    DEFAULT_PLANNER_BACKEND,
    NominalPlan,
    PlannerBackend,
    PlannerSelection,
    PlanningComparison,
)
from acessilia_core.planning.planner_agent import PlannerAgent
from acessilia_core.ports import (
    PHASE_ENRICHED,
    PHASE_EXECUTION,
    PHASE_MANIFEST,
    PHASE_MEDIA,
    PHASE_PLAN,
    RemoteOperations,
    RunPorts,
    region_cache_for,
)
from acessilia_sdk.toolbox import ToolboxError


class StructuralExtractionError(RuntimeError):
    """The Toolbox could not extract the document structure (job-level failure)."""


@dataclass(frozen=True)
class _RunContext:
    """What every phase of one ``execute`` call shares."""

    file_path: Path
    source_path: Path
    effective_mode: str
    status_callback: Callable[[str], Coroutine[Any, Any, None]] | None
    config: CoreConfig
    ports: RunPorts
    checkpoints: RunCheckpoints

    def __post_init__(self) -> None:
        # A composite method saves its progress mid-step through the run's
        # services, into this run's execution checkpoint (#836).
        if self.checkpoints.active:
            self.ports.services.step_checkpoint = self.checkpoints.step_progress


#: Replans after a run that changed the obligations without failing (#832); a
#: run of one document should need one or two.
DEFAULT_MAX_DISCOVERY_REPLANS = 3


@dataclass(frozen=True)
class _PlanningState:
    """The plan of a run and the planning inputs a replan reuses."""

    plan: NominalPlan
    comparison: PlanningComparison | None
    planning_manifest: ProcessingManifest
    availability: toolbox_gate.AvailabilityDecision
    gated: list[str]
    replans: int
    #: Replans after obligations changed, apart from ``replans`` (#832).
    discoveries: int = 0
    #: The planning signature the last discovery replan started from (#832).
    previous_signature: str | None = None


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
        max_replans (int): How many times a run plans again after a failed step, when the executor reports `replan-required`; negative values count as 0; defaults to 2.
        max_discovery_replans (int): How many times a run plans again after a run that changed the obligations without failing (found, removed or replaced, #832); a chain of discoveries longer than this ends the job with `replan-required`. Negative values count as 0; defaults to 3.
        planning_engine (PlanningEngine | None): The engine that produces the plans (#632, PR 3). Defaults to None: a `PddlPlanningEngine` built from `planner_backend`, `preferred_plan` and the Fast Downward options at each planning call. Can also be set later through the `planning_engine` property.
    """

    # Class defaults, so an instance built without ``__init__`` (the test
    # helpers do) has no planner yet and no injected engine.
    _planner: PlannerAgent | None = None
    _planning_engine: PlanningEngine | None = None
    max_discovery_replans: int = DEFAULT_MAX_DISCOVERY_REPLANS

    def __init__(
        self,
        *,
        planner_backend: str = DEFAULT_PLANNER_BACKEND,
        preferred_plan: str = DEFAULT_PLANNER_BACKEND,
        execute_dry_run: bool = True,
        fast_downward: Path | None = None,
        fast_downward_alias: str | None = None,
        fast_downward_search: str = DEFAULT_FAST_DOWNWARD_SEARCH,
        enable_ocr: bool = True,
        extractor_backend: str = "toolbox",
        max_replans: int = 2,
        planning_engine: PlanningEngine | None = None,
        max_discovery_replans: int = DEFAULT_MAX_DISCOVERY_REPLANS,
    ) -> None:
        self.planning_engine = planning_engine
        self.planner_backend = planner_backend
        self.preferred_plan = preferred_plan
        self.execute_dry_run = execute_dry_run
        self.max_replans = max(0, max_replans)
        self.max_discovery_replans = max(0, max_discovery_replans)
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
        self.executor = self._build_executor()

    @property
    def planner(self) -> PlannerAgent:
        """The default planner, built (loading the domain) on first use."""
        return _lazy_planner(self, PlannerAgent)

    @planner.setter
    def planner(self, planner: PlannerAgent | None) -> None:
        self._planner = planner

    @property
    def planning_engine(self) -> PlanningEngine:
        """The engine that plans this orchestrator's runs.

        The injected one, reused for every plan and replan; otherwise a new
        `PddlPlanningEngine` over ``self.planner`` per planning call, built
        from the current backend options so a change to them after
        construction still applies. An instance built without ``__init__``
        (the test helpers do) must set the backend options itself.
        """
        if self._planning_engine is not None:
            return self._planning_engine
        return PddlPlanningEngine(
            self.planner,
            backend=cast(PlannerSelection, self.planner_backend),
            preferred_plan=cast(PlannerBackend, self.preferred_plan),
            fast_downward=self.fast_downward,
            fast_downward_alias=self.fast_downward_alias,
            fast_downward_search=self.fast_downward_search,
        )

    @planning_engine.setter
    def planning_engine(self, engine: PlanningEngine | None) -> None:
        """Inject ``engine`` (checked now), or ``None`` for the default engine."""
        self._planning_engine = None if engine is None else require_engine(engine)

    def _run_executor(self, config: CoreConfig, ports: RunPorts) -> ExecutorAgent:
        """The executor of one run: its handlers get the run's ``config`` and ``ports``.

        Built from ``self.executor``'s registry, so a handler registered on it
        (a test's, for example) runs as well; that registry is left unchanged.
        """
        return ExecutorAgent(
            bind_run(self.executor.registry, config, ports), domain=self.executor.domain
        )

    def _checkpoint_options(self) -> dict[str, dict[str, Any]]:
        """The orchestrator's own options a checkpoint depends on (#549)."""
        planner = {
            "planner_backend": self.planner_backend, "preferred_plan": self.preferred_plan,
            "fast_downward": str(self.fast_downward or ""), "max_replans": self.max_replans,
            "fast_downward_alias": self.fast_downward_alias or "",
            "fast_downward_search": self.fast_downward_search,
            # A saved plan is bound to its domain (the executor refuses another),
            # so a new domain version plans again instead of failing (#640).
            "pddl_domain": f"{self.executor.domain.domain_sha256}:{self.executor.domain.description_sha256}",
        }
        # Only an injected engine adds its identity, so the default engine's
        # checkpoints keep the identity they had before the seam existed.
        if self._planning_engine is not None:
            planner["planning_engine"] = self._planning_engine.identity
        # Likewise the default bound keeps the checkpoints of 0.3.12.
        if self.max_discovery_replans != DEFAULT_MAX_DISCOVERY_REPLANS:
            planner["max_discovery_replans"] = self.max_discovery_replans
        return {"planning": planner, "execution": {**planner, "dry_run": self.execute_dry_run}}

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
        *,
        config: CoreConfig,
        model_calls: ModelCallRunner,
        ports: RunPorts,
    ) -> str | dict[str, Any]:
        """Run the pipeline on one document with the run's ``config``,
        ``model_calls`` and ``ports``.

        All are required (ADR-0016 steps 3 and 4, ADR-0021): nothing in a run
        falls back to the settings, the service's executor or its state, and
        one orchestrator serves runs with different configurations.
        """
        with model_call_scope(model_calls):
            return await self._execute(
                file_path,
                tmpdir,
                status_callback,
                mode,
                structured_output,
                custom_prompt,
                thinking_mode,
                config=config,
                ports=ports,
            )

    async def _execute(
        self,
        file_path: Path,
        tmpdir: Path,
        status_callback: Callable[[str], Coroutine[Any, Any, None]] | None,
        mode: str | None,
        structured_output: bool,
        custom_prompt: str | None,
        thinking_mode: bool,
        *,
        config: CoreConfig,
        ports: RunPorts,
    ) -> str | dict[str, Any]:
        if custom_prompt or thinking_mode:
            raise ValueError("Custom instructions and thinking mode are unavailable for this pipeline")

        executor = self._run_executor(config, ports)
        # Inside a job the service gives the run its checkpoints; a benchmark
        # or the CLI runs without one and keeps the old behaviour.
        ctx = _RunContext(
            file_path=file_path,
            source_path=file_path.resolve(),
            effective_mode=mode or "medio",
            status_callback=status_callback,
            config=config,
            ports=ports,
            checkpoints=RunCheckpoints(
                ports.checkpoints, config, options=self._checkpoint_options()
            ),
        )

        media_inspection, media_configuration = await self._load_or_inspect_media(ctx)
        _check_page_limit_before_extraction(media_inspection, config.document)
        manifest = await self._load_or_extract_manifest(
            ctx,
            presentation=_is_presentation(media_inspection),
            media_configuration=media_configuration,
        )
        manifest = await self._load_or_enrich_manifest(
            ctx, manifest, media_inspection, media_configuration
        )
        planning = await self._load_or_build_plan(ctx, manifest)

        execution_state = self._load_execution_state(ctx.checkpoints, planning.plan)
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
        # A method that reports its own progress, such as table-enrichment,
        # runs on the executor's worker thread (#640, M2).
        ports.services.progress = _thread_status(status_callback, loop)
        manifest, execution_report = await self._run_plan(
            planning.plan,
            planning.planning_manifest,
            execution_state,
            ctx.checkpoints,
            status_callback,
            loop,
            executor=executor,
        )
        manifest, execution_report, plan, comparison = await self._replan_until_done(
            manifest,
            execution_report,
            planning.plan,
            planning.comparison,
            planning.gated,
            status_callback,
            loop,
            checkpoints=ctx.checkpoints,
            planning_manifest=planning.planning_manifest,
            availability=planning.availability,
            replans=planning.replans,
            discoveries=planning.discoveries,
            previous_signature=planning.previous_signature,
            executor=executor,
        )
        self._check_unsatisfied(manifest, execution_report)
        # The canonical build converts the spans of the manifest it is given.
        await _mark_inline_math_after_execution(manifest, planning.planning_manifest, ctx.source_path, config.document, ctx.ports, config.toolbox)

        payload = build_pddl_structured_payload(
            file_path=file_path,
            manifest=manifest,
            plan=plan,
            planner_backend=self.planning_engine.identity,
            execution_report=execution_report,
            comparison=comparison,
            toolbox_availability=planning.availability.to_metadata(),
        )

        if structured_output:
            return payload
        return payload["text"]

    async def _load_or_inspect_media(
        self, ctx: _RunContext
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        """The media inspection and configuration, from the checkpoint or a new run.

        The inspection is also given to the run's services, for the
        ``picture-description`` method (#640, M1).
        """
        media_state = ctx.checkpoints.load(PHASE_MEDIA)
        if media_state is not None:
            ctx.ports.services.media_inspection = media_state.get("inspection")
            return media_state.get("inspection"), dict(media_state.get("configuration") or {})
        # media.inspect runs first: a slide deck is extracted and structured
        # slide by slide, which has to be decided before extraction.
        media_inspection, media_configuration = await _inspect_media(
            ctx.source_path, ctx.config.toolbox
        )
        await ctx.checkpoints.save(
            PHASE_MEDIA,
            lambda: {"inspection": media_inspection, "configuration": media_configuration},
        )
        ctx.ports.services.media_inspection = media_inspection
        return media_inspection, media_configuration

    async def _load_or_extract_manifest(
        self,
        ctx: _RunContext,
        *,
        presentation: bool,
        media_configuration: dict[str, Any],
    ) -> ProcessingManifest:
        """The extracted manifest, from the checkpoint or the Toolbox."""
        manifest_state = ctx.checkpoints.load(PHASE_MANIFEST)
        resumed_manifest = manifest_state is not None
        if manifest_state is not None:
            manifest = ProcessingManifest.model_validate(manifest_state["manifest"])
        else:
            if ctx.status_callback:
                await ctx.status_callback(t(STAGE_ANALYZING_STRUCTURAL))
            manifest = await self._extract_structure(
                ctx.source_path, presentation, ctx.config.document, ctx.config.fusion,
                ctx.config.toolbox, ctx.config.paths, ctx.ports.operations,
            )
        _check_page_limit(manifest, ctx.config.document)
        manifest.extractor.configuration["region_inspection_mode"] = ctx.effective_mode
        manifest.extractor.configuration.update(media_configuration)
        if not resumed_manifest:
            # Saved after the page limit and the media configuration: an
            # oversized document must not leave a checkpoint to resume from.
            await ctx.checkpoints.save_manifest(manifest, enriching=False)
        return manifest

    async def _load_or_enrich_manifest(
        self,
        ctx: _RunContext,
        manifest: ProcessingManifest,
        media_inspection: dict[str, Any] | None,
        media_configuration: dict[str, Any],
    ) -> ProcessingManifest:
        """The enriched manifest, from the checkpoint or the enrichment stages."""
        enriched_state = ctx.checkpoints.load(PHASE_ENRICHED)
        if enriched_state is not None:
            manifest = ProcessingManifest.model_validate(enriched_state["manifest"])
            # An enrichment checkpoint is complete for the mode it ran in; the
            # configuration is re-applied so a changed default is still visible.
            manifest.extractor.configuration["region_inspection_mode"] = ctx.effective_mode
            manifest.extractor.configuration.update(media_configuration)
            return manifest
        await self._enrich_before_planning(
            manifest, ctx.source_path, ctx.effective_mode, media_inspection,
            ctx.status_callback, ctx.config, ctx.ports, ctx.checkpoints,
        )
        # The tables (#640, M2), the pictures (M1) and the formula LaTeX (M3)
        # are enriched inside the plan. A checkpoint from before that already
        # has them enriched, so it gets no obligation for them.
        reconcile_document_steps(manifest)
        await ctx.checkpoints.save(PHASE_ENRICHED, lambda: {"manifest": manifest_payload(manifest)})
        return manifest

    async def _load_or_build_plan(
        self, ctx: _RunContext, manifest: ProcessingManifest
    ) -> _PlanningState:
        """The nominal plan and what it was built under, from the checkpoint or a new plan."""
        plan_state = ctx.checkpoints.load(PHASE_PLAN)
        if plan_state is not None:
            return _PlanningState(
                plan=NominalPlan.model_validate(plan_state["plan"]),
                comparison=(
                    PlanningComparison.model_validate(plan_state["comparison"])
                    if plan_state.get("comparison")
                    else None
                ),
                planning_manifest=ProcessingManifest.model_validate(plan_state["manifest"]),
                availability=toolbox_gate.AvailabilityDecision.from_metadata(
                    plan_state.get("availability") or {}, ctx.config.toolbox
                ),
                gated=list(plan_state.get("gated") or []),
                replans=int(plan_state.get("replans") or 0),
                discoveries=int(plan_state.get("discoveries") or 0),
                previous_signature=plan_state.get("previous_signature"),
            )
        if ctx.status_callback:
            await ctx.status_callback(t(STAGE_GENERATING_PDDL_PLAN))
        # One catalogue snapshot per document, so the first plan and every
        # replan see the same Toolbox.
        availability = await toolbox_gate.decide(manifest, ctx.config)
        _log_availability(availability)
        gated = availability.unavailable_methods
        plan, comparison = await run_blocking(
            self._build_plan, manifest, extra_unavailable=gated,
            catalogue=availability.catalogue_facts(),
        )
        await ctx.checkpoints.save_plan(plan, comparison, manifest, availability, gated, 0)
        return _PlanningState(
            plan=plan,
            comparison=comparison,
            planning_manifest=manifest,
            availability=availability,
            gated=gated,
            replans=0,
        )

    @staticmethod
    def _load_execution_state(
        checkpoints: RunCheckpoints, plan: NominalPlan
    ) -> dict[str, Any] | None:
        """The execution checkpoint of ``plan``, ``None`` when it belongs to another plan."""
        execution_state = checkpoints.load(PHASE_EXECUTION)
        if execution_state is not None and execution_state.get("plan_id") != plan.plan_id:
            # The plan checkpoint was replaced after this execution checkpoint
            # was written (a replan that crashed before it started). The old
            # progress does not apply to the new plan.
            return None
        return execution_state

    async def _run_plan(
        self,
        plan: NominalPlan,
        planning_manifest: ProcessingManifest,
        execution_state: dict[str, Any] | None,
        checkpoints: RunCheckpoints,
        status_callback: Callable[[str], Coroutine[Any, Any, None]] | None,
        loop: asyncio.AbstractEventLoop,
        *,
        executor: ExecutorAgent,
    ) -> tuple[ProcessingManifest, ExecutionReport]:
        """Execute ``plan`` with the run's ``executor``, continuing from ``execution_state`` when it exists."""
        resume = None
        if execution_state is not None:
            resume = ExecutionResume(
                # The progress of the step that was running, when there is one (#836).
                manifest=ProcessingManifest.model_validate(resumed_manifest(execution_state, plan)),
                results=[
                    ExecutionStepResult.model_validate(item)
                    for item in execution_state.get("results") or []
                ],
                replan_required=bool(execution_state.get("replan_required")),
            )
        on_step = (
            checkpoints.execution_saver(plan)
            if checkpoints.active and not self.execute_dry_run
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
        toolbox: ToolboxConfig,
        paths: PathsConfig,
        operations: RemoteOperations | None,
    ) -> ProcessingManifest:
        """The document's manifest from ``document.structure.extract``.

        A Toolbox failure becomes a ``StructuralExtractionError`` whose message
        names only the capability and the kind of failure.
        """
        try:
            return await run_blocking(
                self.information_structural.process, source_path, language="pt-BR",
                presentation=presentation, document=document, fusion=fusion,
                toolbox=toolbox, paths=paths, operations=operations,
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
        source_path: Path,
        effective_mode: str,
        media_inspection: dict[str, Any] | None,
        status_callback: Callable[[str], Coroutine[Any, Any, None]] | None,
        config: CoreConfig,
        ports: RunPorts,
        checkpoints: RunCheckpoints,
    ) -> None:
        """Classify formula regions, prepare the pictures, mark inline math.

        The steps run in this order and share the run's provider breaker,
        region cache and text-span reader (``RunPorts``) with the methods that
        enrich inside the plan: ``picture-description`` describes the
        pictures (#640, M1), ``formula-recognizer`` reads the formulas' LaTeX
        (M3) and ``table-enrichment`` reads the tables (M2).
        What derives from the media inspection stays here (``_prepare_pictures``).
        The manifest is checkpointed after each step (#407). Each step records
        per-object progress in the manifest and skips an object it already
        finished, so a restart repeats at most the step that was running.
        """
        if status_callback:
            await status_callback(t(STAGE_ENRICHING_FORMULAS))
        # Pictures, formulas and tables reach the vision provider from the
        # same pipeline, so one that went down does not get called again for
        # every remaining object; the methods inside the plan get the same
        # run breaker.
        breaker = run_breaker(ports, config.vision)
        region_cache = region_cache_for(ports, config.vision)
        progress = checkpoints.enrichment_progress(manifest)
        await _classify_formula_regions(
            manifest, source_path, mode=effective_mode, vision=config.vision,
            toolbox=config.toolbox, models=config.models, region_cache=region_cache,
            breaker=breaker, on_progress=progress,
        )
        await checkpoints.save_manifest(manifest, enriching=True)
        _prepare_pictures(manifest, media_inspection)
        await checkpoints.save_manifest(manifest, enriching=True)
        text_spans = run_text_spans(ports, manifest, source_path, config.toolbox)
        await _mark_inline_math(manifest, source_path, config.document, text_spans)
        await checkpoints.save_manifest(manifest, enriching=True)

    def _replan_allowed(
        self,
        failure: bool,
        replans: int,
        discoveries: int,
        signature: str,
        previous: str | None,
    ) -> bool:
        """Whether one more replan is within its bound (#832).

        A run with a failed step is a failure replan even if it also found
        obligations: the failure budget is never bypassed through the
        discovery one. With it spent, the loop stops, and a critical
        obligation left open (found or failed) fails the job in
        ``_check_unsatisfied``; nothing is delivered silently.
        """
        if failure:
            return replans < self.max_replans
        return discoveries < self.max_discovery_replans and signature != previous

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
        checkpoints: RunCheckpoints,
        planning_manifest: ProcessingManifest,
        availability: Any,
        replans: int,
        discoveries: int = 0,
        previous_signature: str | None = None,
        executor: ExecutorAgent,
    ) -> tuple[ProcessingManifest, ExecutionReport, Any, Any]:
        """Plan and execute again while the report asks for it, within
        ``max_replans`` (after a failed step) and ``max_discovery_replans``
        (after a run that changed the obligations).

        Returns the last manifest, report, plan and comparison. The replan count
        and the plan it produced come from the checkpoint, so a restart after a
        replan neither repeats one nor exceeds the budget.
        """
        # A `replan-required` report means the executor recorded `(tried ?o ?m)`
        # for a method that failed and left the obligation pending. Without this
        # loop the status was terminal in production: the pipeline returned a plan
        # it already knew was wrong, and `complete-job` never ran, so no document
        # was produced.
        while execution_report.replan_required and not self.execute_dry_run:
            # A replan after a failed step recovers from it and counts toward
            # ``max_replans``. One after a run where nothing failed follows
            # obligations the run changed (found, removed, replaced: #594,
            # #832): it has its own bound, and stops when the planning state
            # (`planning_signature`: targets, dependencies, statuses and tried
            # methods, not only ids) is the one the previous discovery replan
            # started from, so it cannot repeat a problem. The signature is
            # saved with the plan, so a resume keeps the guard.
            failure = any(step.status == "failed" for step in execution_report.steps)
            # Reconciled first, so the guard and the roots see the same state.
            # A table the run added is enriched before its own obligations.
            reconcile_document_steps(manifest, replan=True)
            # The guard reads the graph: a dangling reference fails here, named.
            validate_obligation_graph(manifest)
            signature = planning_signature(manifest)
            if not self._replan_allowed(failure, replans, discoveries, signature, previous_signature):
                break
            previous_signature = None if failure else signature
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
            if failure:
                replans += 1
            else:
                discoveries += 1
            logger.info(
                "PDDL: replanning after {} ({}: {}/{})",
                execution_report.status,
                "failure" if failure else "changed obligations",
                replans if failure else discoveries,
                self.max_replans if failure else self.max_discovery_replans,
            )
            # The new plan applies to the manifest the execution just produced.
            planning_manifest = manifest
            plan, comparison = await run_blocking(
                self._build_plan,
                planning_manifest,
                extra_unavailable=gated,
                selected_roots=roots,
                catalogue=availability.catalogue_facts() if availability else None,
            )
            await checkpoints.save_plan(
                plan, comparison, planning_manifest, availability, gated, replans,
                discoveries=discoveries, previous_signature=previous_signature,
            )
            # The previous execution checkpoint belongs to the previous plan.
            checkpoints.remove(PHASE_EXECUTION)
            manifest, execution_report = await self._run_plan(
                plan,
                planning_manifest,
                None,
                checkpoints,
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
        catalogue: CatalogueFacts | None = None,
    ) -> tuple[NominalPlan, PlanningComparison | None]:
        # Tell the compiler which methods the executor can actually run. Without
        # this the planner happily emits steps for methods that have no handler,
        # and the failure only surfaces at execution time -- after the model-backed
        # work has already been paid for. ``extra_unavailable`` adds the methods a
        # plan checkpoint from before domain 2.4 gated by name; ``catalogue`` is
        # the Toolbox availability as problem facts (#640).
        unavailable = sorted(
            set(self._unavailable_methods(manifest)) | set(extra_unavailable)
        )
        problem = PlanningProblem.of(
            manifest, selected_roots=selected_roots, unavailable_methods=unavailable,
            catalogue=catalogue,
        )
        result = self.planning_engine.plan(problem).verified()
        return result.plan, result.comparison

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


def _log_availability(availability: toolbox_gate.AvailabilityDecision) -> None:
    if availability.degraded:
        # Optional calls (#848): the methods stay in the plan, and run
        # degraded if the document makes the call.
        logger.warning(
            "Toolbox gate (catalogue {}): methods that may run degraded — {}",
            availability.catalog_revision or "unavailable",
            "; ".join(f"{method}: {', '.join(reasons)}" for method, reasons in availability.degraded.items()),
        )
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
