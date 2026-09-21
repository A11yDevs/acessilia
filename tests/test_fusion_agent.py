"""Tests for the FusionAgent (Phase 5 Agno tools over docstruct)."""
from __future__ import annotations

from importlib.util import find_spec

import pytest

from backend.core.agents.fusion_agent import FusionAgent
from docstruct.types import Region


def _region(
    *,
    type_: str = "text",
    text: str = "",
    bbox=(0, 0, 100, 100),
    confidence: float = 0.9,
    page_num: int = 1,
    metadata: dict | None = None,
) -> Region:
    return Region(
        bbox=bbox,
        type=type_,
        text=text,
        image_bytes=None,
        confidence=confidence,
        page_num=page_num,
        metadata=metadata or {},
    )


def _region_dict(**kwargs) -> dict:
    r = _region(**kwargs)
    return {
        "bbox": list(r.bbox),
        "type": r.type,
        "text": r.text,
        "confidence": r.confidence,
        "page_num": r.page_num,
        "metadata": r.metadata,
    }


class TestClassifyBlock:
    def test_classifies_clean_text(self):
        agent = FusionAgent()
        region = _region(type_="text", text="x" * 50, metadata={"total_chars": 50, "text_density": 0.05})
        assert agent.process_classify_block(region) == "text_clean"

    def test_classifies_embedded_image(self):
        agent = FusionAgent()
        # image_bytes presente + confiança alta → embedded_image
        region = _region(type_="image", confidence=0.9)
        region.image_bytes = b"fake"
        assert agent.process_classify_block(region) == "embedded_image"

    def test_classify_block_tool_returns_dict(self):
        agent = FusionAgent()
        result = agent.classify_block(_region_dict(type_="image", confidence=0.9))
        # sem image_bytes, imagem grande → unknown (requer visão)
        assert result["classification"] == "unknown"
        assert result["needs_vision"] is True


class TestNeedsReinfer:
    def test_clean_text_does_not_need_reinfer(self):
        agent = FusionAgent()
        region = _region(type_="text", text="x" * 50, metadata={"total_chars": 50, "text_density": 0.05})
        assert agent.process_needs_reinfer(region) is False

    def test_scanned_text_needs_reinfer(self):
        agent = FusionAgent()
        region = _region(type_="text", text="abc", metadata={"total_chars": 3, "text_density": 0.001})
        assert agent.process_needs_reinfer(region) is True

    def test_needs_reinfer_tool_returns_reason(self):
        agent = FusionAgent()
        result = agent.needs_reinfer(_region_dict(type_="text", text="abc", metadata={"total_chars": 3, "text_density": 0.001}))
        assert result["needs_reinfer"] is True
        assert "re-inferência" in result["reason"]


class TestAuditDocument:
    def test_audit_well_formed_document(self):
        agent = FusionAgent()
        document = {
            "schema_version": "1.0.0",
            "id": "doc-1",
            "title": "Título",
            "language": "pt-BR",
            "sections": [
                {
                    "id": "s1",
                    "level": 1,
                    "title": "Seção",
                    "blocks": [
                        {"id": "b1", "type": "paragraph", "text": "Texto limpo."}
                    ],
                }
            ],
        }
        report = agent.process_audit_document(document)
        assert report["BLOCKER"] == []
        assert report["WARNING"] == []

    def test_audit_detects_missing_alt(self):
        agent = FusionAgent()
        document = {
            "schema_version": "1.0.0",
            "id": "doc-1",
            "title": "Título",
            "language": "pt-BR",
            "sections": [
                {
                    "id": "s1",
                    "level": 1,
                    "title": "Seção",
                    "blocks": [
                        {"id": "b1", "type": "image", "text": ""}
                    ],
                }
            ],
        }
        report = agent.process_audit_document(document)
        assert any("alt" in w[0] for w in report["WARNING"])

    def test_audit_tool_returns_grouped_dict(self):
        agent = FusionAgent()
        document = {
            "schema_version": "1.0.0",
            "id": "doc-1",
            "title": "Título",
            "language": "pt-BR",
            "sections": [],
        }
        result = agent.audit_document(document)
        assert set(result) == {"BLOCKER", "WARNING"}


@pytest.mark.skipif(find_spec("agno") is None, reason="Agno não instalado")
def test_agent_is_built_with_tools():
    agent = FusionAgent()
    assert agent.agent is not None
    assert len(agent.agent.tools) == 1  # um Toolkit com as 4 ferramentas
