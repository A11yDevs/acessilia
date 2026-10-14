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


class TestDeterministicPostProcessingTools:
    """Tools determinísticas da PR #125 expostas pelo FusionAgent."""

    def _agent(self) -> FusionAgent:
        return FusionAgent()

    def _block(self, md: str, kind: str = "text", box=(0.0, 0.0, 1.0, 1.0)) -> dict:
        return {"md": md, "kind": kind, "box": list(box), "text": md, "type": "text"}

    def test_chunk_verse_splits_records(self):
        md = "\n".join(f"Entry {i} {i}" for i in range(1, 8))
        out = self._agent().chunk_verse([self._block(md)], max_chars=20)
        assert len(out["blocks"]) > 1
        assert out["stats"]["verse-agent-split"] == 1
        assert all(b["verse"] for b in out["blocks"])

    def test_chunk_verse_keeps_real_verse_whole(self):
        md = "Shall I compare thee\nTo a summer's day\nThou art more lovely"
        out = self._agent().chunk_verse([self._block(md)], max_chars=20)
        assert len(out["blocks"]) == 1
        assert out["stats"]["verse-agent-whole"] == 1

    def test_extract_line_numbers_moves_numbers_out(self):
        md = ("word " * 30) + " 10 more words 15 more words 20 more words 25"
        out = self._agent().extract_line_numbers([self._block(md)])
        assert out["stats"]["line-numbers-agent-count"] == 4
        assert [b["md"] for b in out["blocks"][1:]] == ["10", "15", "20", "25"]
        assert all(b["type"] == "line_number" for b in out["blocks"][1:])

    def test_join_tail_end_mode(self):
        out = self._agent().join_tail(["body", "HEAD", "42"], mode="end")
        assert out["blocks"] == ["body", "HEAD 42"]

    def test_join_tail_positioned_bottom_keeps(self):
        out = self._agent().join_tail(
            ["body", "HEAD", "42"], position="bot", bot="keep"
        )
        assert out["blocks"] == ["body", "HEAD", "42"]

    def test_join_tail_positioned_bottom_moves_number_last(self):
        out = self._agent().join_tail(
            ["body", "42", "HEAD"], position="bot", bot="hdr"
        )
        assert out["blocks"] == ["body", "HEAD", "42"]

    def test_guard_repetition_cuts_a_loop(self):
        out = self._agent().guard_repetition(" ".join(["5"] * 20))
        assert out["tokens_cut"] > 0
        assert out["text"].split().count("5") < 20

    def test_guard_repetition_detects_blank_page(self):
        out = self._agent().guard_repetition(
            "5 5 5 5 5 5", "", "There is no visible text.", blank=True
        )
        assert out["was_blank"] is True
        assert out["text"] == "\n"

    def test_normalize_text_expands_ligatures(self):
        assert self._agent().normalize_text("ﬁnal  ﬂow")["text"] == "final flow"

    def test_normalize_formula_strips_delimiters(self):
        assert self._agent().normalize_formula("$$x + y$$")["latex"] == "x + y"

    def test_refine_reading_order_returns_a_permutation(self):
        boxes = [[0.0, 0.0, 0.5, 0.5], [0.5, 0.0, 1.0, 0.5]]
        order = self._agent().refine_reading_order(boxes)["order"]
        assert sorted(order) == [0, 1]

    def test_move_header_footer_to_end(self):
        elements = [
            {"category": "Page-header", "text": "H"},
            {"category": "Text", "text": "body"},
        ]
        out = self._agent().move_header_footer_to_end(elements)["elements"]
        assert [e["text"] for e in out] == ["body", "H"]
