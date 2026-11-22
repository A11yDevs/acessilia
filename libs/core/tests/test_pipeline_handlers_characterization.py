"""Characterization tests for pipeline/secondary.py and pipeline/handlers/{fusion,text,unicode_repair,rescue}.py (#612, PR 9).

Pins key branches of ``_load_secondary_extraction``, ``_handle_table_smart_fusion_method``,
``_fused_text_elements``, ``_reattach_negation_overlays``, ``_handle_tailjoin_method``,
and ``_handle_rescue_omitted_method`` so modularization keeps outcomes, metadata,
and error handling identical.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from core_config_support import core_config
from pddl_support import build_element, build_manifest, build_obligation

from acessilia_core.manifest.builder import (
    SECONDARY_EXTRACTION_ARTIFACT_ID,
    SECONDARY_EXTRACTION_KIND,
)
from acessilia_core.manifest.models import (
    Artifact,
    BoundingBox,
    Observation,
    PageDescriptor,
    ProcessingManifest,
    Provenance,
)
from acessilia_core.pipeline.handlers.fusion import (
    _fused_text_elements,
    _handle_dual_provider_fusion_method,
    _handle_table_smart_fusion_method,
)
from acessilia_core.pipeline.handlers.rescue import _handle_rescue_omitted_method
from acessilia_core.pipeline.handlers.text import (
    _handle_tailjoin_method,
    _handle_unicode_repair_method,
    _reattach_negation_overlays,
)
from acessilia_core.pipeline.secondary import _load_secondary_extraction


def _attach_secondary(
    manifest: ProcessingManifest,
    path: Path,
    payload: dict | bytes,
    *,
    sha256: str | None = None,
) -> None:
    raw = (
        payload
        if isinstance(payload, bytes)
        else json.dumps(payload).encode("utf-8")
    )
    path.write_bytes(raw)
    digest = sha256 if sha256 is not None else hashlib.sha256(raw).hexdigest()
    manifest.artifacts.append(
        Artifact(
            id=SECONDARY_EXTRACTION_ARTIFACT_ID,
            kind=SECONDARY_EXTRACTION_KIND,
            path=str(path),
            media_type="application/json",
            sha256=digest,
        )
    )


class TestSecondaryExtractionCharacterization:
    def test_load_secondary_extraction_handles_missing_unreadable_and_corrupt(
        self, tmp_path: Path
    ) -> None:
        manifest = build_manifest([build_element("e1", "paragraph", text="Hi")], [])
        loaded, msg = _load_secondary_extraction(manifest)
        assert loaded is None and msg

        # Missing file on disk.
        manifest.artifacts.append(
            Artifact(
                id=SECONDARY_EXTRACTION_ARTIFACT_ID,
                kind=SECONDARY_EXTRACTION_KIND,
                path=str(tmp_path / "missing.json"),
                media_type="application/json",
            )
        )
        loaded, msg = _load_secondary_extraction(manifest)
        assert loaded is None and "missing.json" in msg

        # SHA-256 mismatch.
        manifest.artifacts.clear()
        _attach_secondary(
            manifest,
            tmp_path / "tampered.json",
            {"provider": "mineru", "document": {}},
            sha256="0" * 64,
        )
        loaded, msg = _load_secondary_extraction(manifest)
        assert loaded is None and "tampered.json" in msg

        # Invalid JSON.
        manifest.artifacts.clear()
        _attach_secondary(manifest, tmp_path / "bad.json", b"{not-json")
        loaded, msg = _load_secondary_extraction(manifest)
        assert loaded is None and "bad.json" in msg

        # Non-dict document payload.
        manifest.artifacts.clear()
        _attach_secondary(
            manifest, tmp_path / "nodoc.json", {"provider": "mineru", "document": []}
        )
        loaded, msg = _load_secondary_extraction(manifest)
        assert loaded is None and "nodoc.json" in msg

    def test_load_secondary_extraction_parses_sizes_elements_and_replaced_primary(
        self, tmp_path: Path
    ) -> None:
        manifest = build_manifest([build_element("e1", "paragraph", text="Hi")], [])
        _attach_secondary(
            manifest,
            tmp_path / "sec.json",
            {
                "provider": "mineru",
                "document": {
                    "document": {
                        "pages": [
                            {"page_number": 1, "width": 600, "height": 800},
                            {"page_number": "bad"},
                        ],
                        "elements": [
                            {"id": "b2", "page_number": 1, "reading_order": 2, "text": "B"},
                            {"id": "b1", "page_number": 1, "reading_order": 1, "text": "A"},
                            "not-a-dict",
                        ],
                    }
                },
                "replaced_primary_pages": {
                    "1": [
                        {"id": "p2", "reading_order": 2, "text": "Second"},
                        {"id": "p1", "reading_order": 1, "text": "First"},
                    ],
                    "bad": [{"id": "x"}],
                },
            },
        )
        loaded, msg = _load_secondary_extraction(manifest)
        assert msg == ""
        assert loaded is not None
        assert loaded.provider == "mineru"
        assert loaded.sizes == {1: (600.0, 800.0)}
        assert [el["id"] for el in loaded.pages[1]] == ["b1", "b2"]
        assert [el["id"] for el in loaded.replaced_primary[1]] == ["p1", "p2"]


class TestFusionHandlersCharacterization:
    def test_table_smart_fusion_covers_adoption_spans_empty_and_no_table_reasons(
        self, tmp_path: Path
    ) -> None:
        t_adopt = build_element(
            "t-adopt",
            "table",
            text="old",
            metadata={"table_ast": {"caption": None, "header": [], "body": []}, "table_stale": True},
            reading_order=1,
        ).model_copy(update={"page_number": 1})
        t_spans = build_element(
            "t-spans",
            "table",
            text="spanned",
            metadata={
                "table_ast": {
                    "body": [
                        {
                            "cells": [
                                {"text": "A", "colspan": 2, "rowspan": 1}
                            ]
                        }
                    ]
                }
            },
            reading_order=2,
        ).model_copy(update={"page_number": 2})
        t_empty = build_element(
            "t-empty", "table", text="keep", reading_order=3
        ).model_copy(update={"page_number": 3})
        t_none = build_element(
            "t-none", "table", text="only-primary", reading_order=4
        ).model_copy(update={"page_number": 4})

        ob = build_obligation(
            "select-table-source",
            ["t-adopt", "t-spans", "t-empty", "t-none"],
            ["table-smart-fusion"],
        ).model_copy(update={"id": "ob-tbl"})
        manifest = build_manifest([t_adopt, t_spans, t_empty, t_none], [ob])
        manifest.extractor.configuration = {"toolbox_provider": "docling"}
        _attach_secondary(
            manifest,
            tmp_path / "sec.json",
            {
                "provider": "mineru",
                "document": {
                    "elements": [
                        {
                            "type": "table",
                            "page_number": 1,
                            "reading_order": 1,
                            "text": "new mineru table",
                            "metadata": {"table_rows": 2, "unrelated": "ignored"},
                        },
                        {
                            "type": "table",
                            "page_number": 2,
                            "reading_order": 1,
                            "text": "mineru flat",
                        },
                        {
                            "type": "table",
                            "page_number": 3,
                            "reading_order": 1,
                            "text": "",
                            "metadata": {},
                        },
                    ]
                },
            },
        )

        result = _handle_table_smart_fusion_method(manifest, "ob-tbl")
        assert result.success is True
        assert t_adopt.text == "new mineru table"
        assert "table_stale" not in t_adopt.metadata
        assert t_adopt.metadata["table_rows"] == 2
        assert "unrelated" not in t_adopt.metadata
        assert t_adopt.metadata["table_source"] == "mineru"
        assert t_adopt.metadata["table_source_reason"] == "preference-mineru"
        assert t_spans.metadata["table_source_reason"] == "primary-has-spans"
        assert t_empty.metadata["table_source_reason"] == "secondary-table-empty"
        assert t_none.metadata["table_source_reason"] == "no-secondary-table"

    def test_fused_text_elements_validation_and_expansion(self) -> None:
        p1 = build_element("e-1", "paragraph", text="Old", reading_order=1).model_copy(
            update={"page_number": 1}
        )
        manifest = build_manifest([p1], [])
        manifest.pages = [PageDescriptor(page_number=1, element_ids=["e-1"])]

        expanded = _fused_text_elements(
            manifest,
            ["e-1"],
            {
                "provider": "docling+mineru",
                "document": {
                    "elements": [
                        {"type": "paragraph", "text": "Updated"},
                        {"type": "paragraph", "text": "Extra block"},
                    ]
                },
            },
        )
        assert [el.id for el in expanded[:1]] == ["e-1"]
        assert expanded[1].id.startswith("element-fusion-")
        assert [el.text for el in expanded] == ["Updated", "Extra block"]
        assert all(
            el.metadata["fusion_provider"] == "docling+mineru" for el in expanded
        )

        with pytest.raises(ValueError, match="unsupported structured content"):
            _fused_text_elements(
                manifest,
                ["e-1"],
                {
                    "provider": "docling+mineru",
                    "document": {"elements": [{"type": "table", "text": "A|B"}]},
                },
            )

        with pytest.raises(ValueError, match="invalid page number"):
            _fused_text_elements(
                manifest,
                ["e-1"],
                {
                    "provider": "docling+mineru",
                    "document": {
                        "elements": [
                            {"type": "paragraph", "text": "X", "page_number": 0}
                        ]
                    },
                },
            )

    def test_dual_provider_fusion_replaces_elements_and_rejects_single_provider(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        p1 = build_element("e-1", "paragraph", text="Original", reading_order=1).model_copy(
            update={"page_number": 1}
        )
        ob = build_obligation(
            "fuse-providers", ["e-1"], ["dual-provider-fusion"]
        ).model_copy(update={"id": "ob-fuse"})
        manifest = build_manifest([p1], [ob])
        manifest.pages = [
            PageDescriptor(page_number=1, width=600.0, height=800.0, element_ids=["e-1"])
        ]
        cfg = core_config(paths={"data_dir": tmp_path})

        monkeypatch.setattr(
            "acessilia_core.pipeline.handlers.fusion._run_extract_fused",
            lambda *_a, **_kw: {
                "status": "succeeded",
                "provider": "docling",
                "document": {"elements": [{"type": "paragraph", "text": "Single"}]},
            },
        )
        single_res = _handle_dual_provider_fusion_method(manifest, "ob-fuse", config=cfg)
        assert single_res.success is False
        assert manifest.elements[0].text == "Original"

        monkeypatch.setattr(
            "acessilia_core.pipeline.handlers.fusion._run_extract_fused",
            lambda *_a, **_kw: {
                "status": "succeeded",
                "provider": "docling+mineru",
                "document": {
                    "elements": [
                        {"type": "paragraph", "text": "Fused 1", "page_number": 1},
                        {"type": "paragraph", "text": "Fused 2", "page_number": 1},
                    ]
                },
            },
        )
        dual_res = _handle_dual_provider_fusion_method(manifest, "ob-fuse", config=cfg)
        assert dual_res.success is True
        assert len(dual_res.artifacts) == 1
        assert [el.text for el in manifest.elements] == ["Fused 1", "Fused 2"]
        assert manifest.pages[0].width == 600.0
        assert manifest.pages[0].height == 800.0
        assert manifest.summary.element_count == 2
        assert manifest.summary.element_types == {"paragraph": 2}


class TestTextAndRescueHandlersCharacterization:
    def test_reattach_negation_overlays_handles_composed_latex_ambiguous_and_retry(
        self,
    ) -> None:
        host_ok = build_element("h-ok", "paragraph", text="h = 0", reading_order=1).model_copy(
            update={
                "page_number": 1,
                "provenance": [
                    Provenance(
                        page_number=1,
                        bbox=BoundingBox(
                            left=10.0, top=10.0, right=60.0, bottom=22.0, coord_origin="TOPLEFT"
                        ),
                    )
                ],
            }
        )
        slash_ok = build_element("s-ok", "paragraph", text="\u0338", reading_order=2).model_copy(
            update={
                "page_number": 1,
                "provenance": [
                    Provenance(
                        page_number=1,
                        bbox=BoundingBox(
                            left=28.0, top=11.0, right=36.0, bottom=21.0, coord_origin="TOPLEFT"
                        ),
                    )
                ],
            }
        )
        host_latex = build_element(
            "h-tex", "formula", text=r"\frac{a}{b} = 0", reading_order=3
        ).model_copy(
            update={
                "page_number": 1,
                "provenance": [
                    Provenance(
                        page_number=1,
                        bbox=BoundingBox(
                            left=10.0, top=50.0, right=90.0, bottom=65.0, coord_origin="TOPLEFT"
                        ),
                    )
                ],
            }
        )
        slash_tex = build_element("s-tex", "paragraph", text="\u0338", reading_order=4).model_copy(
            update={
                "page_number": 1,
                "provenance": [
                    Provenance(
                        page_number=1,
                        bbox=BoundingBox(
                            left=40.0, top=52.0, right=46.0, bottom=62.0, coord_origin="TOPLEFT"
                        ),
                    )
                ],
            }
        )
        slash_no_host = build_element("s-none", "paragraph", text="\u0338", reading_order=5).model_copy(
            update={"page_number": 1}
        )
        manifest = build_manifest(
            [host_ok, slash_ok, host_latex, slash_tex, slash_no_host], []
        )

        outcomes = _reattach_negation_overlays(manifest)
        assert outcomes == {"composed": 1, "host-is-latex": 1, "no-host": 1}
        assert host_ok.text == "h ≠ 0"
        assert host_ok.metadata["negation_overlays"] == 1
        assert slash_tex.metadata["negation_overlay"] == {
            "outcome": "host-is-latex",
            "host": "h-tex",
        }
        # Retry skips already-recorded overlays.
        assert _reattach_negation_overlays(manifest) == {}

    def test_unicode_repair_handler_repairs_prose_and_table_and_handles_no_eligible(
        self,
    ) -> None:
        prose = build_element(
            "p-1", "paragraph", text="Bras\u0131\u0301lia", reading_order=1
        ).model_copy(update={"page_number": 1})
        table = build_element(
            "t-1",
            "table",
            text="",
            metadata={
                "table_ast": {
                    "caption": "Regia\u0303o",
                    "body": [{"cells": [{"text": "Bras\u0131\u0301lia"}]}],
                }
            },
            reading_order=2,
        ).model_copy(update={"page_number": 1})
        ob = build_obligation(
            "repair-legacy-unicode", ["p-1", "t-1"], ["unicode-repair"]
        ).model_copy(update={"id": "ob-uni"})
        manifest = build_manifest([prose, table], [ob])
        manifest.observations = [
            Observation(
                id="obs-uni",
                kind="repair-legacy-unicode-detected",
                severity="warning",
                message="Legacy unicode",
                target_ids=["p-1", "t-1"],
                evidence={"spacing_word_internal": 0},
            )
        ]
        manifest.summary.observation_count = 1

        res = _handle_unicode_repair_method(manifest, "ob-uni")
        assert res.success is True
        assert prose.text == "Bras\u00edlia"
        assert prose.metadata["unicode_repair"]["edited"] is True
        assert table.metadata["table_ast"]["caption"] == "Regi\u00e3o"
        assert table.metadata["table_ast"]["body"][0]["cells"][0]["text"] == "Bras\u00edlia"
        assert table.metadata["unicode_repair"]["edited"] is True

        pic = build_element("pic-1", "picture", text="alt", reading_order=1)
        ob_none = build_obligation(
            "repair-legacy-unicode", ["pic-1"], ["unicode-repair"]
        ).model_copy(update={"id": "ob-uni-none"})
        manifest_none = build_manifest([pic], [ob_none])
        res_none = _handle_unicode_repair_method(manifest_none, "ob-uni-none")
        assert res_none.success is False

    def test_tailjoin_validates_all_pages_before_mutating_earlier_page(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        p1_a = build_element("p1-a", "paragraph", text="Body 1", reading_order=1).model_copy(
            update={"page_number": 1}
        )
        p1_b = build_element("p1-b", "paragraph", text="Tail 1", reading_order=2).model_copy(
            update={"page_number": 1}
        )
        p2_a = build_element("p2-a", "paragraph", text="Body 2", reading_order=3).model_copy(
            update={"page_number": 2}
        )
        p2_b = build_element("p2-b", "paragraph", text="Untargeted tail", reading_order=4).model_copy(
            update={"page_number": 2}
        )
        # Note: p2-b is NOT in target_ids -> page 2 triggers mismatch!
        ob = build_obligation(
            "join-tail-blocks", ["p1-a", "p1-b", "p2-a"], ["tailjoin"]
        ).model_copy(update={"id": "ob-tj"})
        manifest = build_manifest([p1_a, p1_b, p2_a, p2_b], [ob])

        class FakeAgent:
            def process_join_tail(self, texts: list[str], *, position: str | None) -> list[str]:
                return [" ".join(texts)]

        monkeypatch.setattr(
            "acessilia_core.pipeline.handlers.text._fusion_agent", lambda: FakeAgent()
        )
        result = _handle_tailjoin_method(manifest, "ob-tj")
        assert result.success is False
        # Page 1 must remain completely untouched because page 2 failed validation.
        assert p1_a.text == "Body 1"
        assert [el.id for el in manifest.elements] == ["p1-a", "p1-b", "p2-a", "p2-b"]

    def test_rescue_rejects_fused_pages_before_reading_secondary(self) -> None:
        el = build_element(
            "e-1",
            "paragraph",
            text="Fused",
            metadata={"fusion_provider": "docling+mineru"},
            reading_order=1,
        ).model_copy(update={"page_number": 1})
        ob = build_obligation("rescue-omitted-block", ["e-1"], ["rescue-omitted"]).model_copy(
            update={"id": "ob-res"}
        )
        manifest = build_manifest([el], [ob])
        result = _handle_rescue_omitted_method(manifest, "ob-res", config=core_config())
        assert result.success is False
        assert "1" in result.message
