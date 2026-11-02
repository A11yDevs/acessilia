from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from backend.core.manifest.builder import build_processing_manifest
from backend.core.manifest.builder import _derive_v23_processing_needs
from backend.core.manifest.models import BoundingBox, ManifestElement, Provenance
from tests.pddl_support import build_orchestrator


def _element(
    element_id: str,
    element_type: str,
    text: str,
    page_number: int,
    order: int,
) -> ManifestElement:
    return ManifestElement(
        id=element_id,
        type=element_type,
        raw_label=element_type,
        reading_order=order,
        hierarchy_level=0,
        text=text,
        page_number=page_number,
    )


def _positioned_element(
    element_id: str,
    text: str,
    order: int,
    box: tuple[float, float, float, float],
) -> ManifestElement:
    return ManifestElement(
        id=element_id,
        type="paragraph",
        raw_label="paragraph",
        reading_order=order,
        hierarchy_level=0,
        text=text,
        page_number=3,
        provenance=[
            Provenance(
                page_number=3,
                bbox=BoundingBox(
                    left=box[0],
                    top=box[1],
                    right=box[2],
                    bottom=box[3],
                ),
            )
        ],
    )


def test_v23_obligations_require_concrete_signals_and_cover_catalog():
    elements = [
        _element("element-1", "paragraph", "ﬁnal\u00a0text", 1, 1),
        _element("element-2", "formula", "$α$", 1, 2),
        _element(
            "element-3",
            "paragraph",
            "\n".join(f"Entry {index} {index}" for index in range(1, 45)),
            1,
            3,
        ),
        _element(
            "element-4",
            "paragraph",
            ("word " * 30) + " 10 more words 15 more words 20 more words 25",
            1,
            4,
        ),
        _element("element-5", "table", "table content", 1, 5),
        _element("element-6", "paragraph", "A long body block", 2, 6),
        _element("element-7", "page_header", "Running head", 2, 7),
        _element("element-8", "page_footer", "42", 2, 8),
        _positioned_element("element-9", "Left top", 9, (10, 10, 40, 20)),
        _positioned_element("element-10", "Right top", 10, (60, 10, 90, 20)),
        _positioned_element("element-11", "Left bottom", 11, (10, 30, 40, 40)),
        _positioned_element("element-12", "Right bottom", 12, (60, 30, 90, 40)),
    ]
    evidence = {
        "pages": [
            {
                "page_number": 1,
                "stats": {
                    "provider_count": 2,
                    "provider_divergence": True,
                    "text_divergence": True,
                    "table_divergence": True,
                    "pair-text-auto->docling(longer)": 1,
                    "dropped-docling-short": 1,
                    "pair-table->docling": 1,
                    "repetition_tokens_cut": 3,
                },
            }
        ]
    }

    observations, obligations = _derive_v23_processing_needs(
        elements,
        page_sizes={1: (100, 100), 3: (100, 100)},
        fusion_evidence=evidence,
    )

    expected = {
        "adjudicate-page",
        "fuse-providers",
        "refine-reading-order",
        "normalize-formula",
        "rescue-omitted-block",
        "guard-repetition",
        "join-tail-blocks",
        "select-table-source",
        "chunk-verse",
        "extract-line-numbers",
        "normalize-text",
    }
    assert {item.kind for item in obligations} == expected
    assert len(observations) == len(obligations)
    assert all(item.target_ids for item in obligations)


def test_v23_obligations_do_not_emit_without_a_trigger():
    observations, obligations = _derive_v23_processing_needs(
        [_element("element-clean", "paragraph", "Clean text.", 1, 1)]
    )

    assert observations == []
    assert obligations == []


def test_toolbox_manifest_needs_are_derived_by_the_core(
    tmp_path: Path,
):
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF-test")
    timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    payload = {
        "document": {
            "manifest_id": "toolbox-manifest",
            "created_at": timestamp.isoformat(),
            "source": {
                "document_id": "toolbox-doc",
                "filename": "sample.pdf",
                "path": "sample.pdf",
                "media_type": "application/pdf",
                "byte_size": 9,
                "sha256": "0" * 64,
            },
            "extractor": {
                "version": "1",
                "started_at": timestamp.isoformat(),
                "completed_at": timestamp.isoformat(),
                "duration_ms": 1,
                "configuration": {},
            },
            "title": "Sample",
            "language": "en",
            "pages": [{"page_number": 1, "element_ids": ["element-1"]}],
            "elements": [
                {
                    "id": "element-1",
                    "type": "paragraph",
                    "raw_label": "paragraph",
                    "reading_order": 1,
                    "hierarchy_level": 0,
                    "text": "ﬁnal text",
                    "page_number": 1,
                }
            ],
            "observations": [],
            "obligations": [
                {
                    "id": "toolbox-obligation",
                    "kind": "custom",
                    "target_ids": ["element-1"],
                    "admissible_methods": ["human-review"],
                    "method_costs": {"human-review": 100},
                    "rationale": "Provided by the Toolbox.",
                }
            ],
            "summary": {
                "page_count": 1,
                "element_count": 1,
                "observation_count": 0,
                "obligation_count": 1,
                "element_types": {"paragraph": 1},
            },
        },
        "fusion_evidence": {
            "pages": [
                {
                    "page_number": 1,
                    "stats": {
                        "provider_count": 2,
                        "provider_divergence": True,
                        "text_divergence": True,
                        "pair-text-auto->docling(longer)": 1,
                    },
                }
            ]
        },
    }
    extraction = SimpleNamespace(
        document=payload,
        version="1",
        started_at=timestamp,
        completed_at=timestamp,
        duration_ms=1,
        configuration={},
    )

    manifest = build_processing_manifest(source, extraction)

    # Planning policy belongs to the core: the Toolbox's own obligation is
    # dropped and the needs come from the core's rules plus fusion evidence.
    assert "toolbox-obligation" not in {item.id for item in manifest.obligations}
    assert {item.kind for item in manifest.obligations} == {
        "normalize-text",
        "adjudicate-page",
        "fuse-providers",
    }
    assert manifest.summary.obligation_count == len(manifest.obligations)
    assert manifest.summary.observation_count == len(manifest.observations)


def test_toolbox_table_obligation_uses_the_core_methods(tmp_path: Path):
    """Older Toolbox images emit ``docling-table``, which the core never runs."""
    source = tmp_path / "table.pdf"
    source.write_bytes(b"%PDF-test")
    timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    payload = {
        "document": {
            "title": "Table",
            "language": "en",
            "source": {
                "document_id": "toolbox-doc",
                "filename": "table.pdf",
                "path": "table.pdf",
                "media_type": "application/pdf",
                "byte_size": 9,
                "sha256": "0" * 64,
            },
            "extractor": {
                "version": "1",
                "started_at": timestamp.isoformat(),
                "completed_at": timestamp.isoformat(),
                "duration_ms": 1,
                "configuration": {},
            },
            "pages": [{"page_number": 1, "element_ids": ["element-1"]}],
            "elements": [
                {
                    "id": "element-1",
                    "type": "table",
                    "raw_label": "table",
                    "reading_order": 1,
                    "hierarchy_level": 0,
                    "text": "a | b",
                    "page_number": 1,
                }
            ],
            "observations": [
                {
                    "id": "observation-linearize-table-1",
                    "kind": "table-requires-processing",
                    "severity": "warning",
                    "message": "The table must have headers.",
                    "target_ids": ["element-1"],
                }
            ],
            "obligations": [
                {
                    "id": "obligation-linearize-table-1",
                    "kind": "linearize-table",
                    "target_ids": ["element-1"],
                    "admissible_methods": [
                        "docling-table",
                        "pandoc-table",
                        "human-review",
                    ],
                    "method_costs": {
                        "docling-table": 10,
                        "pandoc-table": 15,
                        "human-review": 100,
                    },
                    "rationale": "The table must have headers.",
                }
            ],
            "summary": {
                "page_count": 1,
                "element_count": 1,
                "observation_count": 1,
                "obligation_count": 1,
                "element_types": {"table": 1},
            },
        }
    }
    extraction = SimpleNamespace(
        document=payload,
        version="1",
        started_at=timestamp,
        completed_at=timestamp,
        duration_ms=1,
        configuration={},
    )

    manifest = build_processing_manifest(source, extraction)

    [table] = [o for o in manifest.obligations if o.kind == "linearize-table"]
    assert table.admissible_methods == ["pandoc-table", "human-review"]
    assert "docling-table" not in table.method_costs
    assert len(manifest.observations) == manifest.summary.observation_count


def _reading_order_manifest(
    tmp_path: Path, *, secondary_path: Path | None = None, remove_secondary: bool = False
):
    source = tmp_path / "reading-order.pdf"
    source.write_bytes(b"%PDF-test")
    timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    elements = [
        _positioned_element("element-1", "Left top", 1, (10, 10, 40, 20)),
        _positioned_element("element-2", "Right top", 2, (60, 10, 90, 20)),
        _positioned_element("element-3", "Left bottom", 3, (10, 30, 40, 40)),
        _positioned_element("element-4", "Right bottom", 4, (60, 30, 90, 40)),
    ]
    extraction_document = {
        "document": {
            "manifest_id": "manifest-reading-order",
            "title": "Reading order",
            "language": "en",
            "source": {
                "document_id": "toolbox-doc",
                "filename": source.name,
                "path": str(source),
                "media_type": "application/pdf",
                "byte_size": source.stat().st_size,
                "sha256": "0" * 64,
            },
            "extractor": {
                "version": "1",
                "started_at": timestamp.isoformat(),
                "completed_at": timestamp.isoformat(),
                "duration_ms": 1,
                "configuration": {},
            },
            "pages": [
                {
                    "page_number": 3,
                    "width": 100,
                    "height": 100,
                    "element_ids": [element.id for element in elements],
                }
            ],
            "elements": [element.model_dump(mode="json") for element in elements],
            "observations": [],
            "obligations": [],
            "summary": {
                "page_count": 1,
                "element_count": len(elements),
                "observation_count": 0,
                "obligation_count": 0,
                "element_types": {"paragraph": len(elements)},
            },
        }
    }
    if secondary_path is not None:
        secondary_bytes = b"{}"
        secondary_path.write_bytes(secondary_bytes)
        extraction_document["secondary_extraction"] = {
            "path": str(secondary_path),
            "sha256": hashlib.sha256(secondary_bytes).hexdigest(),
        }
        if remove_secondary:
            secondary_path.unlink()
    extraction = SimpleNamespace(
        document=extraction_document,
        version="1",
        started_at=timestamp,
        completed_at=timestamp,
        duration_ms=1,
        configuration={},
    )
    return build_processing_manifest(source, extraction)


def test_skeleton_order_is_planned_only_when_secondary_extraction_is_recorded(
    tmp_path: Path,
):
    single_manifest = _reading_order_manifest(tmp_path)
    [single_obligation] = [
        item
        for item in single_manifest.obligations
        if item.kind == "refine-reading-order"
    ]

    assert single_obligation.admissible_methods == ["xycut-order", "human-review"]
    assert "skeleton-order" not in single_obligation.method_costs
    plan, _ = build_orchestrator()._build_plan(single_manifest)
    assert [step.method for step in plan.steps if step.method] == ["xycut-order"]

    dual_manifest = _reading_order_manifest(
        tmp_path, secondary_path=tmp_path / "secondary.json"
    )
    [dual_obligation] = [
        item
        for item in dual_manifest.obligations
        if item.kind == "refine-reading-order"
    ]
    assert dual_obligation.admissible_methods == [
        "xycut-order",
        "skeleton-order",
        "human-review",
    ]
    assert dual_manifest.artifacts[0].kind == "provider-extraction"


def test_skeleton_order_is_not_planned_when_the_recorded_file_is_gone(tmp_path: Path):
    secondary = tmp_path / "secondary.json"
    manifest = _reading_order_manifest(tmp_path, secondary_path=secondary, remove_secondary=True)

    [obligation] = [
        item for item in manifest.obligations if item.kind == "refine-reading-order"
    ]
    assert obligation.admissible_methods == ["xycut-order", "human-review"]
    # The record is kept, so the handler can still say what went missing.
    assert manifest.artifacts[0].path == str(secondary)
