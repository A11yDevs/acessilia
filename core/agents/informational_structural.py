from __future__ import annotations

from pathlib import Path
from typing import Any

from core.agno_support import build_agent
from core.manifest.builder import build_processing_manifest
from core.manifest.docling_extractor import DoclingManifestExtractor
from core.manifest.models import ProcessingManifest


class InformationalStructuralAgent:
    """Agente Agno cuja ferramenta principal constrói o manifesto validado."""

    def __init__(
        self,
        extractor: DoclingManifestExtractor | None = None,
        *,
        model: Any | None = None,
    ) -> None:
        self.extractor = extractor or DoclingManifestExtractor()
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
        manifest = self.process(Path(document_path), language=language)
        return manifest.model_dump(mode="json", by_alias=True)

    def process(
        self,
        source_path: Path,
        *,
        language: str = "pt-BR",
    ) -> ProcessingManifest:
        extraction = self.extractor.extract(source_path)
        return build_processing_manifest(
            source_path,
            extraction,
            language=language,
        )
