"""PDDL processes a real PDF; remote services are mocked."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import fitz

from backend import service
from backend.agents.state_manager import StateManager
from backend.config.settings import settings
from backend.export.pandoc_exporter import export_accessible_document
from backend.pipeline.validators import validate_canonical_document
from backend.tools.toolbox_client import ToolboxClient


def test_pdf_to_canonical_and_exports(monkeypatch, tmp_path):
    text = "Accessible content preserved by the PDDL workflow."
    source = tmp_path / "document.pdf"
    with fitz.open() as pdf:
        pdf.new_page(width=500, height=300).insert_text((20, 50), text, fontsize=7)
        pdf.save(source)

    monkeypatch.setattr(settings, "pipeline_engine", "pddl")
    monkeypatch.setattr(settings, "structurer", "pymupdf")
    monkeypatch.setattr(settings, "fusion_mode", "single")
    monkeypatch.setattr(settings, "pddl_planner_backend", "internal")
    monkeypatch.setattr(settings, "pddl_preferred_plan", "internal")
    monkeypatch.setattr(settings, "pddl_execute_dry_run", True)
    response = {
        "status": "succeeded", "provider": "docling",
        "document": {
            "title": "document",
            "summary": {
                "page_count": 1, "element_count": 1, "observation_count": 0,
                "obligation_count": 0, "element_types": {"paragraph": 1},
            },
            "elements": [{
                "id": "paragraph-1", "type": "paragraph", "raw_label": "paragraph",
                "reading_order": 1, "hierarchy_level": 0,
                "text": text, "page_number": 1,
            }],
            "pages": [{"page_number": 1, "width": 500, "height": 300,
                       "element_ids": ["paragraph-1"]}],
        },
    }
    extraction = AsyncMock(return_value=response)
    monkeypatch.setattr(ToolboxClient, "upload_artifact", AsyncMock(return_value="pdf-1"))
    monkeypatch.setattr(ToolboxClient, "extract_structure", extraction)
    monkeypatch.setattr(service, "get_cached", AsyncMock(return_value=None))
    monkeypatch.setattr(service, "set_cache", AsyncMock())
    monkeypatch.setattr(service, "registrar_conversao", AsyncMock())
    monkeypatch.setattr(service, "finalizar_conversao", AsyncMock())
    monkeypatch.setattr(service, "_salvar_json_canonico", lambda *_args: None)
    monkeypatch.setattr(service, "state_manager", StateManager())
    monkeypatch.setattr(service, "agente", service._build_orchestrator())

    canonical = asyncio.run(service.process(source))
    assert validate_canonical_document(canonical) == []
    assert canonical["source"]["path"] == str(source)
    assert text in json.dumps(canonical)
    extraction.assert_awaited_once()
    assert service._cache_version().startswith(f"{settings.ai_client}-pddl-")
    for fmt in ("txt", "html"):
        output = tmp_path / f"document.{fmt}"
        export_accessible_document(canonical, output, format_name=fmt)
        assert text in output.read_text()
