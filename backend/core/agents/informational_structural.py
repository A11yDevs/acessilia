from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.core.agents.agno_support import build_agent
from backend.core.config import CoreConfig, DocumentConfig, FusionConfig, PathsConfig, ToolboxConfig
from backend.core.manifest.builder import build_processing_manifest
from backend.core.manifest.models import ProcessingManifest
from backend.core.manifest.toolbox_extractor import ToolboxManifestExtractor
from backend.core.ports import RemoteOperations


class InformationalStructuralAgent:
    """Agente Agno cuja ferramenta principal constrói o manifesto validado."""

    def __init__(
        self,
        extractor: Any | None = None,
        *,
        model: Any | None = None,
        config: CoreConfig | None = None,
    ) -> None:
        """``config`` is the ``CoreConfig`` the Agno tool runs with; the
        pipeline calls :meth:`process` with its run's groups instead."""
        self.extractor = extractor or ToolboxManifestExtractor()
        self.config = config
        self.agent = build_agent(
            name="Agente Informacional-Estrutural",
            instructions=(
                "Extraia o documento uma única vez com a ferramenta fornecida.",
                "Preserve proveniência, ordem de leitura e hierarquia observadas.",
                "Não invente elementos, obrigações ou resultados perceptuais.",
                "Retorne somente o manifesto tipado e validado.",
            ),
            tools=(self.extract_processing_manifest,),
            model=model,
        )

    def extract_processing_manifest(
        self,
        document_path: str,
        language: str = "pt-BR",
    ) -> dict:
        """Extrai um documento e retorna seu manifesto de processamento."""
        config = _tool_config(self.config, "extract_processing_manifest")
        manifest = self.process(
            Path(document_path),
            language=language,
            document=config.document,
            fusion=config.fusion,
            toolbox=config.toolbox,
            paths=config.paths,
            operations=None,  # an Agno tool runs outside a job
        )
        return manifest.model_dump(mode="json", by_alias=True)

    def process(
        self,
        source_path: Path,
        *,
        document: DocumentConfig,
        fusion: FusionConfig,
        toolbox: ToolboxConfig,
        paths: PathsConfig,
        operations: RemoteOperations | None,
        language: str = "pt-BR",
        presentation: bool = False,
    ) -> ProcessingManifest:
        """Extract ``source_path`` and build its manifest.

        A ``presentation`` is extracted by the configured provider alone (no
        dual-provider fusion, which compares running text across pages) and
        structured slide by slide. ``document`` is the run's configuration
        of the slide options and the legacy Unicode repair; ``fusion``, of the
        dual extraction and the page judge's budget; ``toolbox``, of the
        extraction's Toolbox options; ``paths``, of where its fusion evidence
        is written; ``operations``, the job's registry of remote calls
        (``None`` outside a job).
        """
        extraction = self.extractor.extract(
            source_path, fusion=fusion, toolbox=toolbox, paths=paths,
            operations=operations, dual_fusion=not presentation,
        )
        return build_processing_manifest(
            source_path,
            extraction,
            language=language,
            refine_reading_order=True,
            presentation=presentation,
            slide_visual_coverage=document.slide_visual_coverage,
            slide_fold_figure_labels=document.slide_fold_figure_labels,
            legacy_unicode_repair=document.legacy_unicode_repair,
            fusion_judge_max_pages=fusion.judge_max_pages,
        )


def _tool_config(config: CoreConfig | None, tool: str) -> CoreConfig:
    """The agent's ``CoreConfig``, which its Agno tool cannot run without."""
    if config is None:
        raise RuntimeError(
            f"the {tool} tool needs the agent built with config= (ADR-0016, step 3)"
        )
    return config
