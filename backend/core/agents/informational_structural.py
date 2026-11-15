from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.core.agents.agno_support import build_agent
from backend.core.config import DocumentConfig, FusionConfig
from backend.core.manifest.builder import build_processing_manifest
from backend.core.manifest.models import ProcessingManifest
from backend.core.manifest.toolbox_extractor import ToolboxManifestExtractor


class InformationalStructuralAgent:
    """Agente Agno cuja ferramenta principal constrói o manifesto validado."""

    def __init__(
        self,
        extractor: Any | None = None,
        *,
        model: Any | None = None,
    ) -> None:
        self.extractor = extractor or ToolboxManifestExtractor()
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
        # The Agno tool has no run to take a config from: the bridge of
        # ADR-0016's step 3 builds one from the settings until the last
        # step-3 pull request gives the agent its configuration.
        from backend.config.core_config import core_config_from_settings

        config = core_config_from_settings()
        manifest = self.process(
            Path(document_path),
            language=language,
            document=config.document,
            fusion=config.fusion,
        )
        return manifest.model_dump(mode="json", by_alias=True)

    def process(
        self,
        source_path: Path,
        *,
        document: DocumentConfig,
        fusion: FusionConfig,
        language: str = "pt-BR",
        presentation: bool = False,
    ) -> ProcessingManifest:
        """Extract ``source_path`` and build its manifest.

        A ``presentation`` is extracted by the configured provider alone (no
        dual-provider fusion, which compares running text across pages) and
        structured slide by slide. ``document`` is the run's configuration
        of the slide options and the legacy Unicode repair; ``fusion``, of the
        dual extraction and the page judge's budget.
        """
        extraction = self.extractor.extract(
            source_path, fusion=fusion, dual_fusion=not presentation
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
