from __future__ import annotations

import asyncio
import re
from collections import Counter
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

import fitz
from docstruct.fusion.line_numbers import extract_line_numbers
from docstruct.fusion.tailjoin import join_tail
from docstruct.fusion.verse import chunk_verse
from docstruct.tables.ast import effective_section_width, linearize_table_for_text
from docstruct.text.norm_fix import norm_fix

from backend.services.blocking import run_blocking
from backend.agents.data_agent import DataAgent
from backend.agents.output_schemas import DataOutput, VisionOutput
from backend.agents.vision_agent import VisionAgent
from backend.core.agents.informational_structural import InformationalStructuralAgent
from backend.core.execution.executor import ExecutorAgent, MethodRegistry
from backend.core.execution.models import ExecutionReport, MethodResult
from backend.core.execution.messages import EXE_COMPLETED_OBLIGATIONS_UNSATISFIED
from backend.core.manifest.builder import (
    _derive_processing_needs,
    reconcile_reclassified_element_processing_needs,
)
from backend.core.manifest.models import (
    Artifact,
    ManifestElement,
    ProcessingManifest,
)
from backend.core.manifest.toolbox_extractor import ToolboxManifestExtractor
from backend.core.planning.domain_bundle import DomainBundle
from backend.core.planning.models import NominalPlan, PlanningComparison
from backend.core.planning.planner_agent import PlannerAgent
from backend.i18n import t
from backend.log_messages import (
    LOG_PDDL_ELEMENT_CROP_FAILED,
    LOG_PDDL_EMPTY_VISION_DESCRIPTION,
    LOG_PDDL_IGNORED_OPTIONS,
    LOG_PDDL_IMAGES_ENRICHED,
    LOG_PDDL_PREFERRED_PLAN_MISSING,
    LOG_PDDL_TABLES_ENRICHED,
)
from backend.stage_messages import (
    STAGE_ANALYZING_STRUCTURAL,
    STAGE_ENRICHING_IMAGE_DESCRIPTIONS,
    STAGE_ENRICHING_TABLES_OCR,
    STAGE_GENERATING_PDDL_PLAN,
    STAGE_VALIDATING_PLAN_DRY_RUN,
    STAGE_EXECUTING_PLAN,
)
from backend.tools.code_tools import normalize_code_text
from backend.tools.formula_tools import (
    latex_to_mathml,
    normalize_latex,
    verbalize_latex_fallback,
)
from backend.tools.logger import logger
from backend.tools.media_inspect import inspect_source_media


def _formula_elements_for_obligation(
    manifest: ProcessingManifest, obligation_id: str
) -> list[ManifestElement]:
    obligation = next(
        (o for o in manifest.obligations if o.id == obligation_id), None
    )
    if obligation is None:
        return []
    targets = set(obligation.target_ids)
    return [
        el for el in manifest.elements if el.id in targets and el.type == "formula"
    ]


def _handle_mathml_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Converte o LaTeX das fórmulas alvo em MathML (metadata.mathml)."""
    elements = _formula_elements_for_obligation(manifest, obligation_id)
    if not elements:
        return MethodResult(
            success=False,
            validated=False,
            message="Nenhuma fórmula encontrada para a obrigação",
        )
    converted = 0
    for element in elements:
        mathml = latex_to_mathml(element.text or "")
        if mathml:
            element.metadata["mathml"] = mathml
            converted += 1
    if converted == len(elements):
        return MethodResult(
            success=True,
            validated=True,
            message=f"MathML gerado para {converted} fórmula(s)",
        )
    return MethodResult(
        success=False,
        validated=False,
        message=f"MathML gerado para {converted}/{len(elements)} fórmula(s)",
    )


def _handle_latex_verbalizer_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Gera verbalização pt-BR determinística das fórmulas (metadata.verbalization)."""
    elements = _formula_elements_for_obligation(manifest, obligation_id)
    if not elements:
        return MethodResult(
            success=False,
            validated=False,
            message="Nenhuma fórmula encontrada para a obrigação",
        )
    verbalized = 0
    for element in elements:
        latex = normalize_latex(element.text or "")
        spoken = verbalize_latex_fallback(latex) if latex else ""
        if spoken:
            element.metadata["verbalization"] = spoken
            verbalized += 1
    if verbalized == len(elements):
        return MethodResult(
            success=True,
            validated=True,
            message=f"Verbalização gerada para {verbalized} fórmula(s)",
        )
    return MethodResult(
        success=False,
        validated=False,
        message=f"Verbalização gerada para {verbalized}/{len(elements)} fórmula(s)",
    )


def _run_extract_fused(source_path: Path) -> dict:
    """Executa ``extract_fused`` respeitando o contexto de event loop.

    Detecta a presença de um event loop **antes** de criar a coroutine,
    evitando criar um objeto coroutine que ficaria sem ``await`` (e
    produziria ``RuntimeWarning: coroutine ... was never awaited``).

    Nota de arquitetura: quando chamado a partir de um thread com event
    loop ativo (Agno Workflow, API), ``.result()`` ainda bloqueia o loop
    chamador até a fusão terminar. O contrato dos handlers permanece
    síncrono; quem invoca o executor a partir de código async deve rodar
    o executor inteiro via ``await run_blocking(...)`` para não
    bloquear o event loop principal.
    """
    import concurrent.futures

    from backend.pipeline.fusion import extract_fused

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # Contexto síncrono (executor determinístico, CLI, testes):
        # não existe event loop ativo neste thread.
        return asyncio.run(extract_fused(source_path))

    # Já existe um event loop neste thread; como o handler é síncrono,
    # a coroutine é executada em um thread dedicado com seu próprio loop.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(
            lambda: asyncio.run(extract_fused(source_path))
        ).result()


def _target_elements(
    manifest: ProcessingManifest, obligation_id: str
) -> list[ManifestElement]:
    """Elements an obligation points at, in reading order."""
    obligation = next(
        (o for o in manifest.obligations if o.id == obligation_id), None
    )
    if obligation is None:
        return []
    targets = set(obligation.target_ids)
    return sorted(
        (el for el in manifest.elements if el.id in targets),
        key=lambda el: el.reading_order,
    )


def _missing_obligation(obligation_id: str) -> MethodResult:
    return MethodResult(
        success=False,
        validated=False,
        message=f"Obrigação não encontrada: {obligation_id}",
    )


def _handle_vision_description_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Require every picture target to already carry a description.

    The description itself is produced before planning (`_enrich_picture_descriptions`
    tries the vision model and falls back to a deterministic description), so this
    method validates that the work the planner is asking for actually happened
    instead of pretending to perform it. A picture that is still undescribed is a
    real failure and keeps the next admissible method available.
    """
    elements = [
        el
        for el in _target_elements(manifest, obligation_id)
        if el.type == "picture"
    ]
    if not elements:
        return MethodResult(
            success=False,
            validated=False,
            message="Nenhuma imagem encontrada para a obrigação",
        )

    undescribed = [
        el for el in elements
        if not (
            bool((el.text or "").strip())
            if el.metadata.get("vision_description_complete")
            else _has_meaningful_text(el)
        )
    ]
    if undescribed:
        return MethodResult(
            success=False,
            validated=False,
            message=(
                "Imagem sem descrição textual: "
                + ", ".join(el.id for el in undescribed)
            ),
        )
    return MethodResult(
        success=True,
        validated=True,
        message=f"Descrição validada para {len(elements)} imagem(ns)",
    )


def _handle_pandoc_table_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Require the table targets to carry a structured AST."""
    elements = [
        el for el in _target_elements(manifest, obligation_id) if el.type == "table"
    ]
    if not elements:
        return MethodResult(
            success=False,
            validated=False,
            message="Nenhuma tabela encontrada para a obrigação",
        )

    missing = []
    for element in elements:
        try:
            usable = _table_element_has_structured_content(element)
            table_ast = element.metadata.get("table_ast")
            if usable:
                usable = any(
                    value.strip() for row in _rows_from_table_ast(table_ast) for value in row
                )
                linearize_table_for_text({"table_ast": table_ast})
        except (TypeError, ValueError, AttributeError):
            usable = False
        if not usable:
            missing.append(element)
    if missing:
        return MethodResult(
            success=False,
            validated=False,
            message=(
                "Tabela sem estrutura tabular: "
                + ", ".join(el.id for el in missing)
            ),
        )
    return MethodResult(
        success=True,
        validated=True,
        message=f"Estrutura tabular validada para {len(elements)} tabela(s)",
    )


def _handle_pandoc_code_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Normalize code targets in place and record the normalized language."""
    elements = [
        el for el in _target_elements(manifest, obligation_id) if el.type == "code"
    ]
    if not elements:
        return MethodResult(
            success=False,
            validated=False,
            message="Nenhum bloco de código encontrado para a obrigação",
        )

    normalized = 0
    for element in elements:
        text = normalize_code_text(element.text or "")
        if not text:
            continue
        element.text = text
        element.metadata["code_normalized"] = True
        normalized += 1

    if normalized != len(elements):
        return MethodResult(
            success=False,
            validated=False,
            message=(
                f"Código normalizado em {normalized}/{len(elements)} bloco(s)"
            ),
        )
    return MethodResult(
        success=True,
        validated=True,
        message=f"Código normalizado em {normalized} bloco(s)",
    )


def _handle_pymupdf_region_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Require a region crop for every target so the region was actually inspected."""
    elements = _target_elements(manifest, obligation_id)
    if not elements:
        return _missing_obligation(obligation_id)

    missing = [el for el in elements if not (el.metadata or {}).get("region_crop")]
    if missing:
        return MethodResult(
            success=False,
            validated=False,
            message=(
                "Região não inspecionada (sem recorte): "
                + ", ".join(el.id for el in missing)
            ),
        )
    return MethodResult(
        success=True,
        validated=True,
        message=f"Região inspecionada para {len(elements)} elemento(s)",
    )


def _handle_latex_normalizer_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Normalize the LaTeX of every formula target in place."""
    elements = [
        el
        for el in _target_elements(manifest, obligation_id)
        if el.type == "formula"
    ]
    if not elements:
        return MethodResult(
            success=False,
            validated=False,
            message="Nenhuma fórmula encontrada para a obrigação",
        )

    normalized = 0
    for element in elements:
        cleaned = normalize_latex(element.text or "")
        if not cleaned:
            continue
        element.metadata["latex_normalized"] = cleaned
        normalized += 1

    if normalized != len(elements):
        return MethodResult(
            success=False,
            validated=False,
            message=(
                f"LaTeX normalizado em {normalized}/{len(elements)} fórmula(s)"
            ),
        )
    return MethodResult(
        success=True,
        validated=True,
        message=f"LaTeX normalizado em {normalized} fórmula(s)",
    )


def _handle_norm_fix_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Apply the deterministic text cleanups (ligatures, hyphenation, NBSP)."""
    elements = _target_elements(manifest, obligation_id)
    if not elements:
        return _missing_obligation(obligation_id)

    fixed = 0
    for element in elements:
        current = element.text or ""
        if not current:
            continue
        cleaned = norm_fix(current)
        if cleaned != current:
            element.text = cleaned
            element.metadata["norm_fixed"] = True
        fixed += 1

    if not fixed:
        return MethodResult(
            success=False,
            validated=False,
            message="Nenhum texto elegível para normalização",
        )
    return MethodResult(
        success=True,
        validated=True,
        message=f"Normalização determinística aplicada em {fixed} elemento(s)",
    )


def _handle_extract_line_numbers_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Record the marginal line numbers the extractor found on the target text."""
    elements = _target_elements(manifest, obligation_id)
    if not elements:
        return _missing_obligation(obligation_id)

    total = 0
    for element in elements:
        numbers = extract_line_numbers(element.text or "")
        element.metadata["line_numbers"] = numbers
        total += len(numbers)

    if not total:
        return MethodResult(
            success=False,
            validated=False,
            message="Nenhum número de linha marginal encontrado",
        )
    return MethodResult(
        success=True,
        validated=True,
        message=f"{total} número(s) de linha extraído(s)",
    )


def _handle_chunk_verse_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Split the target text into verse-sized chunks recorded in metadata."""
    elements = _target_elements(manifest, obligation_id)
    if not elements:
        return _missing_obligation(obligation_id)

    chunked = 0
    for element in elements:
        chunks = chunk_verse(element.text or "")
        if not chunks:
            continue
        element.metadata["verse_chunks"] = chunks
        chunked += 1

    if not chunked:
        return MethodResult(
            success=False,
            validated=False,
            message="Nenhum bloco de verso elegível para fragmentação",
        )
    return MethodResult(
        success=True,
        validated=True,
        message=f"Verso fragmentado em {chunked} elemento(s)",
    )


def _handle_tailjoin_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Join the trailing short blocks of the target text into the recorded result."""
    elements = _target_elements(manifest, obligation_id)
    if not elements:
        return _missing_obligation(obligation_id)

    joined = 0
    for element in elements:
        merged = join_tail(element.text or "")
        if not merged:
            continue
        element.metadata["tailjoined"] = merged
        joined += 1

    if not joined:
        return MethodResult(
            success=False,
            validated=False,
            message="Nenhum bloco de cauda elegível para união",
        )
    return MethodResult(
        success=True,
        validated=True,
        message=f"Blocos de cauda unidos em {joined} elemento(s)",
    )


def _handle_human_review_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Record the obligation as escalated to a human reviewer.

    `human-review` is the terminal method every obligation lists as its last
    admissible option. It is not an automated method that can succeed on its own,
    so resolving it must be an explicit decision: an obligation reaching this
    handler is escalated and stays visible in the execution report, instead of
    being marked satisfied by a handler that did nothing.
    """
    obligation = next(
        (o for o in manifest.obligations if o.id == obligation_id), None
    )
    if obligation is None:
        return _missing_obligation(obligation_id)

    return MethodResult(
        success=False,
        validated=False,
        message=(
            "Escalonado para revisão humana: nenhum método automático satisfez "
            f"{obligation.kind} ({obligation_id})"
        ),
    )


def _handle_deterministic_heading_repair_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Clamp a heading whose level skips ahead of its predecessor.

    The compiled obligation carries the previous level as evidence; the repair is
    deterministic, so a missing level is a real failure rather than something to
    guess at.
    """
    obligation = next(
        (o for o in manifest.obligations if o.id == obligation_id), None
    )
    if obligation is None:
        return _missing_obligation(obligation_id)

    elements = {
        el.id: el for el in _target_elements(manifest, obligation_id)
    }
    repaired = 0
    for element in elements.values():
        if element.type != "heading":
            continue
        previous = _previous_heading_level(manifest, element)
        if previous and element.hierarchy_level > previous + 1:
            element.hierarchy_level = previous + 1
            element.metadata["heading_repaired"] = True
        repaired += 1

    if not repaired:
        return MethodResult(
            success=False,
            validated=False,
            message="Nenhum título encontrado para a obrigação",
        )
    return MethodResult(
        success=True,
        validated=True,
        message=f"Hierarquia de títulos verificada em {repaired} título(s)",
    )


def _previous_heading_level(
    manifest: ProcessingManifest, element: ManifestElement
) -> int:
    """Level of the closest heading that precedes the element in reading order."""
    previous = 0
    for candidate in sorted(
        (el for el in manifest.elements if el.type == "heading"),
        key=lambda el: el.reading_order,
    ):
        if candidate.id == element.id:
            return previous
        previous = candidate.hierarchy_level
    return previous


DETERMINISTIC_METHOD_HANDLERS: dict[
    str, Callable[[ProcessingManifest, str], MethodResult]
] = {
    #: Method name -> handler for every method whose work is already done before
    #: planning (or can be done without a model call). A method the manifest can
    #: require but that is absent from here is reported to the planner as
    #: unavailable, so the plan never contains a step that can only fail.
    "vision-description": _handle_vision_description_method,
    "pandoc-table": _handle_pandoc_table_method,
    "pandoc-code": _handle_pandoc_code_method,
    "pymupdf-region": _handle_pymupdf_region_method,
    "latex-normalizer": _handle_latex_normalizer_method,
    "norm-fix": _handle_norm_fix_method,
    "line-number-extractor": _handle_extract_line_numbers_method,
    "verse-chunker": _handle_chunk_verse_method,
    "tailjoin": _handle_tailjoin_method,
    "tailjoin-positioned": _handle_tailjoin_method,
    "deterministic-heading-repair": _handle_deterministic_heading_repair_method,
}


def _handle_dual_provider_fusion_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Funde dois providers (docling+mineru) para a obrigação alvo.

    Reutiliza ``backend.pipeline.fusion.extract_fused`` (Fase 4) para
    produzir o payload fundido, persiste o JSON em ``data_dir/artifacts/
    fusion/`` e o retorna em ``MethodResult.artifacts`` — deixando o
    ``ExecutorAgent`` responsável por incorporá-lo ao manifesto e registrar
    a proveniência na tentativa.

    Em modo single (FUSION_MODE=single) o método não é admissível e não
    deve ser selecionado pelo compilador.
    """
    import json

    from backend.config.settings import settings

    obligation = next(
        (o for o in manifest.obligations if o.id == obligation_id), None
    )
    if obligation is None:
        return MethodResult(
            success=False,
            validated=False,
            message=f"Obrigação não encontrada: {obligation_id}",
        )
    source_path = Path(manifest.source.path)
    try:
        payload = _run_extract_fused(source_path)
    except Exception as exc:  # noqa: BLE001
        return MethodResult(
            success=False,
            validated=False,
            message=f"Fusão dual-provider falhou: {type(exc).__name__}: {exc}",
        )
    if payload.get("status") != "succeeded":
        return MethodResult(
            success=False,
            validated=False,
            message="Fusão dual-provider não concluiu com sucesso",
        )

    # A ação planejada é dual-provider: se apenas um provider participou,
    # a semântica planejada não foi executada → falha para permitir replanning
    # para um método single-provider.
    provider = str(payload.get("provider") or "")
    if "+" not in provider:
        return MethodResult(
            success=False,
            validated=False,
            message=(
                "Fusão dual-provider executou com um único provider "
                f"({provider or 'desconhecido'}); replanning necessário"
            ),
        )

    output_path = (
        settings.data_dir / "artifacts" / "fusion" / f"{obligation_id}.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    artifact = Artifact(
        id=f"artifact-fusion-{obligation_id}",
        kind="fusion-payload",
        path=str(output_path),
        media_type="application/json",
    )
    return MethodResult(
        success=True,
        validated=True,
        message="Fusão dual-provider concluída com sucesso",
        artifacts=[artifact],
    )


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
                "PDDL extractor_backend={}: usando ToolboxManifestExtractor",
                self.extractor_backend,
            )
            extractor = ToolboxManifestExtractor(enable_ocr=enable_ocr)
        else:
            raise ValueError(
                f"Extractor local '{self.extractor_backend}' desativado. "
                f"Use extractor_backend='toolbox' para o pipeline PDDL+Toolbox."
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
        for method, handler in DETERMINISTIC_METHOD_HANDLERS.items():
            registry.register(method, handler)

        # `human-review` has its own semantics: it is the terminal escalation the
        # pipeline performs when no automated method can satisfy an obligation.
        registry.register("human-review", _handle_human_review_method)

        return ExecutorAgent(registry, domain=DomainBundle.load())

    async def executar(
        self,
        file_path: Path,
        tmpdir: Path,
        status_callback: Callable[[str], Coroutine] | None = None,
        mode: str | None = None,
        structured_output: bool = False,
        custom_prompt: str | None = None,
        thinking_mode: bool = False,
    ) -> str | dict[str, Any]:
        effective_mode = mode or "medio"

        if custom_prompt or thinking_mode:
            raise ValueError("Custom instructions and thinking mode are unavailable for this pipeline")

        if status_callback:
            await status_callback(t(STAGE_ANALYZING_STRUCTURAL))
        manifest = await run_blocking(
            self.information_structural.process,
            file_path.resolve(),
            language="pt-BR",
        )

        source_path = file_path.resolve()
        media_inspection = await inspect_source_media(source_path)
        if media_inspection is None:
            logger.warning(
                "Inspeção de mídia indisponível para %s; seguindo sem o "
                "sinal de imagem isolada",
                source_path.name,
            )

        if status_callback:
            await status_callback(t(STAGE_ENRICHING_IMAGE_DESCRIPTIONS))
        await _enrich_picture_descriptions(
            manifest,
            source_path,
            mode=effective_mode,
            media_inspection=media_inspection,
        )

        if status_callback:
            await status_callback(t(STAGE_ENRICHING_TABLES_OCR))
        await _enrich_table_structures(
            manifest,
            file_path.resolve(),
        )

        if status_callback:
            await status_callback(t(STAGE_GENERATING_PDDL_PLAN))
        plan, comparison = await run_blocking(self._build_plan, manifest)

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
        manifest, execution_report = await run_blocking(
            self.executor.execute,
            plan,
            manifest,
            dry_run=self.execute_dry_run,
        )

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
            replans += 1
            logger.info(
                "PDDL: replanejando ({}/{}) após {}",
                replans,
                self.max_replans,
                execution_report.status,
            )
            plan, comparison = await run_blocking(self._build_plan, manifest)
            manifest, execution_report = await run_blocking(
                self.executor.execute,
                plan,
                manifest,
                dry_run=False,
            )

        if execution_report.status not in {"completed", "dry-run-completed"}:
            raise RuntimeError(_unsatisfied_execution_message(manifest))

        payload = build_pddl_structured_payload(
            file_path=file_path,
            manifest=manifest,
            plan=plan,
            planner_backend=self.planner_backend,
            execution_report=execution_report,
            comparison=comparison,
        )

        if structured_output:
            return payload
        return payload["text"]

    def _build_plan(
        self,
        manifest: ProcessingManifest,
    ) -> tuple[NominalPlan, PlanningComparison | None]:
        # Tell the compiler which methods the executor can actually run. Without
        # this the planner happily emits steps for methods that have no handler,
        # and the failure only surfaces at execution time -- after the model-backed
        # work has already been paid for.
        unavailable = self._unavailable_methods(manifest)
        if self.planner_backend == "both":
            _, plans, comparison = self.planner.compare(
                manifest,
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


async def _enrich_picture_descriptions(
    manifest: ProcessingManifest,
    source_file: Path,
    *,
    mode: str,
    media_inspection: dict[str, Any] | None = None,
) -> None:
    _inject_full_page_picture(manifest, media_inspection)

    pictures = [
        element
        for element in manifest.elements
        if element.type == "picture"
        and not element.metadata.get("vision_description_complete")
    ]
    if not pictures and _is_mostly_visual_manifest(manifest):
        pictures = [
            element
            for element in manifest.elements
            if _is_placeholder_visual_element(element)
            and not element.metadata.get("vision_description_complete")
        ]

    if (
        not pictures
        and _is_mostly_visual_manifest(manifest)
        and len(manifest.pages) == 1
        and manifest.elements
    ):
        pictures = [element for element in manifest.elements
                    if not element.metadata.get("vision_description_complete")][:1]

    if not pictures:
        return

    vision = VisionAgent(mode=mode)
    total_pages = len(manifest.pages)
    enriched = 0

    for element in pictures:
        fallback_page_number = element.page_number
        if fallback_page_number is None and len(manifest.pages) == 1:
            fallback_page_number = manifest.pages[0].page_number

        image_bytes, page_number = await run_blocking(
            _extract_picture_bytes,
            source_file,
            element,
            fallback_page_number,
        )
        if not image_bytes:
            continue

        vision_output = await vision.describe_region(
            image_bytes=image_bytes,
            classification="embedded_image",
            page_num=page_number,
            total_pages=total_pages,
            mode=mode,
        )
        if isinstance(vision_output, VisionOutput):
            element.metadata["vision_description_complete"] = True
            element.metadata["vision_language"] = vision_output.language
            element.metadata["vision_confidence"] = vision_output.confidence
            element.metadata["vision_elements"] = list(vision_output.mentioned_elements)
            if vision_output.warnings:
                element.metadata["vision_warnings"] = list(vision_output.warnings)

            if vision_output.kind == "formula":
                element.text = vision_output.formula_latex or ""
                if element.type != "formula":
                    previous_type = element.type
                    element.metadata["original_type"] = element.type
                    element.type = "formula"
                    element.raw_label = "formula"
                    reconcile_reclassified_element_processing_needs(
                        manifest,
                        element,
                        previous_type=previous_type,
                    )
            else:
                element.text = vision_output.description
                if element.type != "picture":
                    previous_type = element.type
                    element.metadata["original_type"] = element.type
                    element.type = "picture"
                    element.raw_label = "picture"
                    reconcile_reclassified_element_processing_needs(
                        manifest,
                        element,
                        previous_type=previous_type,
                    )
            if element.page_number is None and page_number >= 1:
                element.page_number = page_number
            # A model that answers with an empty description used to be counted as
            # an enrichment, producing an element that still had no text and an
            # obligation that could not be satisfied. Report it so the operator
            # sees the model refused instead of a silent gap.
            if _has_meaningful_text(element):
                enriched += 1
            else:
                logger.warning(
                    t(LOG_PDDL_EMPTY_VISION_DESCRIPTION).format(
                        element_id=element.id
                    )
                )

    if enriched:
        logger.info(t(LOG_PDDL_IMAGES_ENRICHED).format(count=enriched))


def _inject_full_page_picture(
    manifest: ProcessingManifest,
    media_inspection: dict[str, Any] | None,
) -> None:
    """Injeta um elemento `picture` sintético de página inteira.

    Quando a entrada é uma imagem raster isolada (``media_inspect`` classifica
    como imagem e sinaliza ``requires_visual_inspection=true``) e o extrator
    estrutural não produziu nenhum bloco visual (picture/formula), o orquestrador
    não teria alvo para audiodescrição. Este fallback cria um elemento `picture`
    que cobre a página inteira para que o VisionAgent descreva a imagem.

    O sinal é consumido apenas como heurística de enriquecimento: não altera o
    problema PDDL (predicados ``media_inspected``/``media_profile_classified``
    pertencem ao domínio da Toolbox).
    """
    if not isinstance(media_inspection, dict):
        return
    if not media_inspection.get("is_image"):
        return
    if not media_inspection.get("requires_visual_inspection"):
        return

    has_visual_element = any(
        element.type in {"picture", "formula"} for element in manifest.elements
    )
    if has_visual_element:
        return

    max_reading_order = max(
        (element.reading_order for element in manifest.elements), default=0
    )
    page_number = (
        manifest.pages[0].page_number if manifest.pages else 1
    )

    element = ManifestElement(
        id=f"element-injected-picture-{len(manifest.elements) + 1:06d}",
        type="picture",
        raw_label="picture",
        reading_order=max_reading_order + 1,
        hierarchy_level=1,
        text=None,
        page_number=page_number,
        metadata={
            "injected_picture": True,
            "media_inspection": media_inspection,
        },
    )
    manifest.elements.append(element)

    if manifest.pages:
        manifest.pages[0].element_ids.append(element.id)

    observations, obligations = _derive_processing_needs([element])
    manifest.observations.extend(observations)
    manifest.obligations.extend(obligations)

    manifest.summary.element_count = len(manifest.elements)
    manifest.summary.observation_count = len(manifest.observations)
    manifest.summary.obligation_count = len(manifest.obligations)
    manifest.summary.element_types = dict(
        sorted(Counter(item.type for item in manifest.elements).items())
    )


async def _enrich_table_structures(
    manifest: ProcessingManifest,
    source_file: Path,
) -> None:
    table_elements = [
        element
        for element in manifest.elements
        if element.type == "table" and not _table_element_has_structured_content(element)
    ]
    if not table_elements:
        return

    data_agent = DataAgent()
    enriched = 0
    for element in table_elements:
        if _backfill_table_from_existing_text(element):
            enriched += 1
            continue

        fallback_page_number = element.page_number
        if fallback_page_number is None and len(manifest.pages) == 1:
            fallback_page_number = manifest.pages[0].page_number

        image_bytes, page_number = await run_blocking(
            _extract_picture_bytes,
            source_file,
            element,
            fallback_page_number,
        )
        if not image_bytes:
            continue

        table_output = await data_agent.process_region(
            image_bytes=image_bytes,
            classification="table",
            page_num=page_number,
            fallback_text=element.text or "",
        )
        if not isinstance(table_output, DataOutput) or table_output.kind != "table":
            continue

        rows = table_output.table_rows()
        table_ast = table_output.table_ast()

        element.metadata["table_ast"] = table_ast
        element.metadata["table_linearization_hint"] = "data-agent-structured"
        element.metadata["table_row_count"] = len(rows)
        element.metadata["table_column_count"] = _table_ast_column_count(table_ast)
        element.metadata["table_has_header"] = any(
            cell.header or cell.scope != "none"
            for row in table_output.rows
            for cell in row.cells
        )
        element.metadata["data_language"] = table_output.language
        element.metadata["data_confidence"] = table_output.confidence
        if table_output.warnings:
            element.metadata["data_warnings"] = list(table_output.warnings)
        element.text = ""
        if element.page_number is None and page_number >= 1:
            element.page_number = page_number
        enriched += 1

    if enriched:
        logger.info(t(LOG_PDDL_TABLES_ENRICHED).format(count=enriched))


def _table_element_has_structured_content(element: ManifestElement) -> bool:
    metadata = element.metadata or {}
    table_ast = metadata.get("table_ast")
    if not isinstance(table_ast, dict):
        return False

    rows = _rows_from_table_ast(table_ast)
    if not rows:
        return False

    width = max((len(row) for row in rows), default=0)
    if len(rows) >= 2 and width >= 2:
        return True

    return not _rows_look_like_placeholder(rows)


def _table_ast_column_count(table_ast: dict[str, Any]) -> int:
    """Return the widest logical section, including cell spans."""
    widths: list[int] = []
    for section_name in ("header", "body", "footer"):
        section = table_ast.get(section_name)
        if isinstance(section, list):
            widths.append(effective_section_width(section))
    return max(widths, default=0)


def _backfill_table_from_existing_text(element: ManifestElement) -> bool:
    text = (element.text or "").strip()
    if not text:
        return False

    rows = _rows_from_visual_table_text(text)
    if not rows:
        return False

    table_ast = _table_ast_from_rows(rows)
    if table_ast is None:
        return False

    element.metadata["table_ast"] = table_ast
    element.metadata["table_linearization_hint"] = "text-heuristic"
    element.metadata["table_row_count"] = len(rows)
    element.metadata["table_column_count"] = max((len(row) for row in rows), default=0)
    element.metadata["table_has_header"] = bool(rows and len(rows[0]) >= 2)
    element.text = ""
    return True


def _rows_from_visual_table_text(raw_text: str) -> list[list[str]]:
    text = raw_text.strip()
    if not text:
        return []

    rows = _rows_from_pipe_table(text)
    if rows:
        return rows

    rows = _rows_from_delimited_lines(text, delimiter="\t")
    if rows:
        return rows

    semicolon_rows = _rows_from_delimited_lines(text, delimiter=";")
    comma_rows = _rows_from_delimited_lines(text, delimiter=",")
    if _score_rows(semicolon_rows) >= _score_rows(comma_rows):
        return semicolon_rows
    return comma_rows


def _rows_from_pipe_table(text: str) -> list[list[str]]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    rows: list[list[str]] = []
    for line in lines:
        if "|" not in line:
            continue
        if _looks_like_markdown_separator(line):
            continue
        cleaned = line.strip().strip("|")
        cells = [cell.strip() for cell in cleaned.split("|")]
        cells = [cell for cell in cells if cell]
        if len(cells) >= 2:
            rows.append(cells)
    if _score_rows(rows) >= 4:
        return rows
    return []


def _rows_from_delimited_lines(text: str, *, delimiter: str) -> list[list[str]]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    rows: list[list[str]] = []
    for line in lines:
        if delimiter not in line:
            continue
        if "|" in line and delimiter != "|":
            continue
        cells = [cell.strip() for cell in line.split(delimiter)]
        cells = [cell for cell in cells if cell]
        if len(cells) >= 2:
            rows.append(cells)
    if _score_rows(rows) >= 4:
        return rows
    return []


def _looks_like_markdown_separator(line: str) -> bool:
    cleaned = line.strip().strip("|").replace(" ", "")
    if not cleaned:
        return False
    parts = cleaned.split("|")
    if not parts:
        return False
    return all(re.fullmatch(r":?-{2,}:?", part or "") for part in parts)


def _score_rows(rows: list[list[str]]) -> int:
    if not rows:
        return 0
    row_count = len(rows)
    width = max((len(row) for row in rows), default=0)
    return row_count * width


def _rows_look_like_placeholder(rows: list[list[str]]) -> bool:
    if len(rows) != 1 or len(rows[0]) != 1:
        return False
    return rows[0][0].strip().lower() == "tabela detectada"


def _extract_picture_bytes(
    source_file: Path,
    element: ManifestElement,
    fallback_page_number: int | None,
) -> tuple[bytes | None, int]:
    provenance = element.provenance[0] if element.provenance else None
    page_number = provenance.page_number if provenance is not None else (fallback_page_number or 0)
    if page_number < 1:
        return None, 0

    doc = fitz.open(source_file)
    try:
        page = doc.load_page(page_number - 1)
        rect = _clip_rect_from_provenance(page, provenance)
        pixmap = page.get_pixmap(clip=rect, dpi=160, alpha=False)
        return pixmap.tobytes("png"), page_number
    except Exception:
        logger.exception(
            t(LOG_PDDL_ELEMENT_CROP_FAILED).format(element_id=element.id)
        )
        return None, page_number
    finally:
        doc.close()


def _clip_rect_from_provenance(page: fitz.Page, provenance: Any) -> fitz.Rect:
    bbox = getattr(provenance, "bbox", None)
    if bbox is None:
        return page.rect

    left = float(bbox.left)
    right = float(bbox.right)
    top = float(bbox.top)
    bottom = float(bbox.bottom)

    if getattr(bbox, "coord_origin", "UNKNOWN") == "BOTTOMLEFT":
        page_height = float(page.rect.height)
        top_from_top = page_height - top
        bottom_from_top = page_height - bottom
        y0 = min(top_from_top, bottom_from_top)
        y1 = max(top_from_top, bottom_from_top)
    else:
        y0 = min(top, bottom)
        y1 = max(top, bottom)

    x0 = min(left, right)
    x1 = max(left, right)

    rect = fitz.Rect(x0, y0, x1, y1) & page.rect
    if rect.width < 4 or rect.height < 4:
        return page.rect
    return rect


def _is_mostly_visual_manifest(manifest: ProcessingManifest) -> bool:
    for element in manifest.elements:
        if element.type in {"heading", "title", "paragraph", "list_item", "table", "code", "formula"}:
            text = (element.text or "").strip()
            if text and not _is_placeholder_text(text) and not _is_ocr_noise(text):
                return False
    return True


def _is_ocr_noise(text: str) -> bool:
    """Retorna True se o texto parece ser ruído de OCR (muito curto, sem
    estrutura de linguagem natural), não devendo ser considerado como
    conteúdo textual significativo para efeitos de detecção de manifesto
    majoritariamente visual."""
    normalized = text.strip()
    if not normalized:
        return True
    # Texto muito curto (≤4 caracteres) é quase sempre OCR noise
    if len(normalized) <= 4:
        return True
    # Texto sem espaços e com ≤8 caracteres também é suspeito
    if " " not in normalized and len(normalized) <= 8:
        return True
    return False


def _is_placeholder_visual_element(element: ManifestElement) -> bool:
    if element.type not in {"group", "unknown", "paragraph"}:
        return False
    text = (element.text or "").strip()
    raw_label = (element.raw_label or "").strip().lower()
    return (not text) or _is_placeholder_text(text) or _is_ocr_noise(text) or raw_label in {"body", "unspecified", "group"}


def _is_placeholder_text(text: str) -> bool:
    normalized = text.strip().lower()
    return normalized in {"body", "_root_", "root", "unspecified", "group"}


def _has_meaningful_text(element: ManifestElement) -> bool:
    """Retorna True se o elemento contém texto significativo (não é OCR noise
    nem placeholder). Usado para filtrar elementos do tipo 'picture' que já
    vieram com descrição textual válida do extrator."""
    text = (element.text or "").strip()
    if not text:
        return False
    if _is_placeholder_text(text):
        return False
    if _is_ocr_noise(text):
        return False
    return True


def _unsatisfied_execution_message(manifest: ProcessingManifest) -> str:
    return t(EXE_COMPLETED_OBLIGATIONS_UNSATISFIED).format(
        unsatisfied=", ".join(
            obligation.id for obligation in manifest.obligations
            if obligation.selected and obligation.status != "satisfied"
        )
    )


def build_pddl_structured_payload(
    *,
    file_path: Path,
    manifest: ProcessingManifest,
    plan: NominalPlan,
    planner_backend: str,
    execution_report: ExecutionReport | None,
    comparison: PlanningComparison | None,
) -> dict[str, Any]:
    pages_payload = _manifest_pages_to_payload(manifest)
    text_output = _render_text_from_pages(pages_payload)

    technical_warnings: list[str] = []
    if execution_report is None:
        technical_warnings.append(
            "Executor nao foi executado; somente manifesto e plano foram gerados."
        )
    elif execution_report.status in {"failed", "replan-required"}:
        technical_warnings.append(_unsatisfied_execution_message(manifest))

    if comparison is not None:
        technical_warnings.append(
            f"Comparacao de planners: {comparison.comparison.verdict}."
        )

    return {
        "text": text_output,
        "pages": pages_payload,
        "page_count": len(pages_payload),
        "mode": f"pddl-{planner_backend}",
        "source_path": str(file_path),
        "canonical_metadata": {
            "pipeline_engine": "pddl",
            "pddl_validation_only": True,
            "accessibility_verified": False,
            "pddl_manifest_id": manifest.manifest_id,
            "pddl_manifest_revision": manifest.revision,
            "pddl_plan_id": plan.plan_id,
            "pddl_planner": plan.planner,
            "pddl_expected_total_cost": plan.expected_total_cost,
            "pddl_execution_id": execution_report.execution_id
            if execution_report
            else None,
            "pddl_execution_status": execution_report.status
            if execution_report
            else None,
            "pddl_comparison_verdict": comparison.comparison.verdict
            if comparison
            else None,
        },
        "technical_warnings": technical_warnings,
    }


def _manifest_pages_to_payload(manifest: ProcessingManifest) -> list[dict[str, Any]]:
    elements_by_id = {element.id: element for element in manifest.elements}
    pages: list[dict[str, Any]] = []

    if manifest.pages:
        sorted_pages = sorted(manifest.pages, key=lambda page: page.page_number)
        for page in sorted_pages:
            block_elements = [
                elements_by_id[element_id]
                for element_id in page.element_ids
                if element_id in elements_by_id
            ]
            if not block_elements:
                # Some extractors can fill in pages without element_ids; in that
                # case we fall back to page_number so no content is lost.
                block_elements = [
                    element
                    for element in manifest.elements
                    if (element.page_number or 1) == page.page_number
                ]
            block_elements.sort(key=lambda item: item.reading_order)
            blocks = [_element_to_block(item) for item in block_elements]
            _dedupe_callout_titles(blocks)
            pages.append(
                {
                    "page_number": page.page_number,
                    "text": _render_text_from_blocks(blocks),
                    "blocks": blocks,
                }
            )
        return pages

    grouped: dict[int, list[ManifestElement]] = {}
    for element in manifest.elements:
        page_number = element.page_number or 1
        grouped.setdefault(page_number, []).append(element)

    for page_number in sorted(grouped):
        page_elements = sorted(
            grouped[page_number],
            key=lambda item: item.reading_order,
        )
        blocks = [_element_to_block(item) for item in page_elements]
        _dedupe_callout_titles(blocks)
        pages.append(
            {
                "page_number": page_number,
                "text": _render_text_from_blocks(blocks),
                "blocks": blocks,
            }
        )

    return pages


def _element_to_block(element: ManifestElement) -> dict[str, Any]:
    provenance = element.provenance[0] if element.provenance else None
    metadata: dict[str, Any] = {
        "raw_label": element.raw_label,
        "source_ref": element.source_ref,
        "parent_id": element.parent_id,
        "confidence": element.confidence,
        "manifest_element_id": element.id,
    }
    if element.metadata:
        metadata.update(element.metadata)
    metadata = _normalize_metadata_links(metadata)

    source_location: dict[str, Any] = {}
    if provenance is not None:
        source_location["page_number"] = provenance.page_number
        if provenance.bbox is not None:
            source_location["bbox"] = {
                "left": provenance.bbox.left,
                "top": provenance.bbox.top,
                "right": provenance.bbox.right,
                "bottom": provenance.bbox.bottom,
            }

    text = element.text or ""
    callout_id = metadata.get("callout_id")
    callout_role = str(metadata.get("callout_role", "")).lower()
    callout_type = str(metadata.get("callout_type", "note")).lower()
    callout_title = str(metadata.get("callout_title", "")).strip()
    callout_block_type = "warning" if callout_type in {"warning", "aviso", "importante", "caution"} else "note"
    block: dict[str, Any] = {
        "id": element.id,
        "source_location": source_location,
        "metadata": metadata,
    }

    if callout_id and callout_role != "title":
        block.update(
            {
                "type": callout_block_type,
                "title": callout_title,
                "text": text,
            }
        )
        return block

    if element.type in {"title", "heading"}:
        block.update(
            {
                "type": "heading",
                "level": 1 if element.type == "title" else max(1, element.hierarchy_level),
                "text": text or element.raw_label,
            }
        )
    elif element.type == "list_item":
        block.update(
            {
                "type": "list",
                "ordered": False,
                "items": [text] if text else [],
            }
        )
    elif element.type == "table":
        table_ast = _table_ast_from_metadata(metadata)
        rows = _rows_from_table_ast(table_ast) if table_ast else None
        if not rows:
            rows = [[text]] if text else [["Tabela detectada"]]
            if table_ast is None:
                table_ast = _table_ast_from_rows(rows)
        block.update(
            {
                "type": "table",
                "rows": rows,
                "table_ast": table_ast,
            }
        )
    elif element.type == "picture":
        block.update(
            {
                "type": "image",
                "alt_text": text or "Imagem detectada sem descricao textual.",
            }
        )
    elif element.type == "code":
        block.update({"type": "code", "text": normalize_code_text(text)})
    elif element.type == "formula":
        if text:
            block.update({"type": "math", "text": text})
        else:
            block.update({"type": "paragraph", "text": "Formula detectada."})
    else:
        block.update({"type": "paragraph", "text": text or element.raw_label})

    return block


def _dedupe_callout_titles(blocks: list[dict[str, Any]]) -> None:
    seen_callout_ids: set[str] = set()
    for block in blocks:
        metadata = block.get("metadata") or {}
        callout_id = str(metadata.get("callout_id") or "").strip()
        if not callout_id:
            continue
        if block.get("type") not in {"note", "warning"}:
            continue
        if callout_id in seen_callout_ids:
            block.pop("title", None)
            continue
        seen_callout_ids.add(callout_id)


def _normalize_metadata_links(metadata: dict[str, Any]) -> dict[str, Any]:
    def normalize_value(value: Any) -> Any:
        if isinstance(value, str) and value.startswith("#/"):
            return value[1:]
        if isinstance(value, list):
            return [normalize_value(item) for item in value]
        if isinstance(value, dict):
            return {key: normalize_value(item) for key, item in value.items()}
        return value

    return {key: normalize_value(value) for key, value in metadata.items()}


def _render_text_from_blocks(blocks: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for block in blocks:
        block_type = block.get("type")
        if block_type == "heading":
            level = int(block.get("level", 1))
            prefix = "#" * max(1, min(level, 6))
            lines.append(f"{prefix} {block.get('text', '').strip()}")
        elif block_type == "list":
            for item in block.get("items", []):
                lines.append(f"- {str(item).strip()}")
        elif block_type == "table":
            rows = block.get("rows")
            if not rows and isinstance(block.get("table_ast"), dict):
                rows = _rows_from_table_ast(block["table_ast"])
            for row in rows or []:
                if isinstance(row, list):
                    lines.append(" | ".join(str(cell).strip() for cell in row))
        elif block_type == "image":
            lines.append(block.get("alt_text", "Imagem"))
        else:
            text = block.get("text", "")
            if isinstance(text, str) and text.strip():
                lines.append(text.strip())
    return "\n".join(lines).strip()


def _render_text_from_pages(pages: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for page in pages:
        page_number = page.get("page_number", "?")
        text = str(page.get("text", "")).strip()
        if text:
            chunks.append(f"=== Pagina {page_number} ===\n{text}")
    return "\n\n".join(chunks)


def _table_ast_from_metadata(metadata: dict[str, Any]) -> dict[str, Any] | None:
    raw = metadata.get("table_ast")
    if not isinstance(raw, dict):
        return None

    table_ast: dict[str, Any] = {}
    caption = raw.get("caption")
    if isinstance(caption, str) and caption.strip():
        table_ast["caption"] = caption.strip()

    for section_name in ("header", "body", "footer"):
        section = raw.get(section_name)
        if not isinstance(section, list):
            continue
        normalized_rows: list[dict[str, Any]] = []
        for row in section:
            if not isinstance(row, dict):
                continue
            cells = row.get("cells")
            if not isinstance(cells, list):
                continue
            normalized_cells: list[dict[str, Any]] = []
            for cell in cells:
                if not isinstance(cell, dict) or "text" not in cell:
                    continue
                text = str(cell.get("text", "")).strip()
                normalized_cell: dict[str, Any] = {"text": text}
                if isinstance(cell.get("header"), bool):
                    normalized_cell["header"] = cell["header"]
                scope = cell.get("scope")
                if isinstance(scope, str) and scope in {
                    "none",
                    "row",
                    "col",
                    "rowgroup",
                    "colgroup",
                }:
                    normalized_cell["scope"] = scope
                for span_key in ("rowspan", "colspan"):
                    span = cell.get(span_key)
                    if isinstance(span, int) and span >= 1:
                        normalized_cell[span_key] = span
                normalized_cells.append(normalized_cell)
            if normalized_cells:
                normalized_rows.append({"cells": normalized_cells})
        if normalized_rows:
            table_ast[section_name] = normalized_rows

    metadata_obj = raw.get("metadata")
    if isinstance(metadata_obj, dict):
        table_ast["metadata"] = metadata_obj

    return table_ast if table_ast.get("body") else None


def _table_ast_from_rows(rows: list[list[str]]) -> dict[str, Any]:
    body: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, list):
            continue
        cells = []
        for cell in row:
            text = str(cell).strip()
            cells.append({"text": text})
        if cells:
            body.append({"cells": cells})
    return {"body": body}


def _rows_from_table_ast(table_ast: dict[str, Any]) -> list[list[str]]:
    rows: list[list[str]] = []
    for section_name in ("header", "body", "footer"):
        section = table_ast.get(section_name)
        if not isinstance(section, list):
            continue
        for row in section:
            if not isinstance(row, dict):
                continue
            cells = row.get("cells")
            if not isinstance(cells, list):
                continue
            row_values = [
                str(cell.get("text", "")).strip()
                for cell in cells
                if isinstance(cell, dict)
            ]
            if row_values:
                rows.append(row_values)
    return rows


# Backward compatibility with the PMV naming.
PmvAccessibilityOrchestrator = PddlAccessibilityOrchestrator
build_pmv_structured_payload = build_pddl_structured_payload
