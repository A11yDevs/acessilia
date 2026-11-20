"""Characterization tests for PR 1 core utility deduplication and bbox delegation (#612).

Covers:
- ``write_atomic_artifact`` shared by ``_persist_fusion_payload`` and ``_save_region_artifact``;
- ``_element_bbox`` and ``_SecondaryExtraction.bbox`` delegating to ``OrientedBox.page_fractions``;
- ``_rescue_page`` reusing ``unique_element_id`` on colliding element identifiers.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from acessilia_core.manifest.models import (
    BoundingBox,
    ManifestElement,
    PageDescriptor,
    Provenance,
)
from acessilia_core.pipeline.elements import _element_bbox
from acessilia_core.pipeline.handlers import common as handler_common
from acessilia_core.pipeline.handlers.fusion import _persist_fusion_payload
from acessilia_core.pipeline.handlers.inspection import _save_region_artifact
from acessilia_core.pipeline.handlers.rescue import _rescue_page
from acessilia_core.pipeline.secondary import _SecondaryExtraction
from pddl_support import build_element, build_manifest


def _box(**overrides: object) -> dict[str, object]:
    """A raw Toolbox bounding box, as the secondary extraction reads it."""
    return {"left": 0.0, "top": 0.0, "right": 1.0, "bottom": 1.0, **overrides}


def test_write_atomic_artifact_writes_content_addressed_file_and_cleans_up_on_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"artifact-bytes"
    scope = "a" * 64
    artifact = handler_common.write_atomic_artifact(
        payload,
        category="regions",
        scope=scope,
        kind="region-crop",
        suffix="png",
        media_type="image/png",
        data_dir=tmp_path,
    )
    digest = hashlib.sha256(payload).hexdigest()
    expected_path = tmp_path / "artifacts" / "regions" / scope / f"{digest}.png"

    assert artifact.id == f"artifact-region-crop-{scope[:16]}-{digest[:16]}"
    assert artifact.kind == "region-crop"
    assert artifact.path == str(expected_path)
    assert artifact.media_type == "image/png"
    assert artifact.sha256 == digest
    assert expected_path.read_bytes() == payload

    # Content addressed: the same bytes and scope land on the same file and id.
    again = handler_common.write_atomic_artifact(
        payload,
        category="regions",
        scope=scope,
        kind="region-crop",
        suffix="png",
        media_type="image/png",
        data_dir=tmp_path,
    )
    assert (again.path, again.id) == (artifact.path, artifact.id)

    def fail_replace(_src: Path, _dst: Path) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(handler_common.os, "replace", fail_replace)
    with pytest.raises(OSError, match="disk full"):
        handler_common.write_atomic_artifact(
            b"failed-bytes",
            category="regions",
            scope="b" * 64,
            kind="region-crop",
            suffix="png",
            media_type="image/png",
            data_dir=tmp_path,
        )
    failed_dir = tmp_path / "artifacts" / "regions" / ("b" * 64)
    assert list(failed_dir.iterdir()) == []


def test_persist_fusion_payload_and_save_region_artifact_preserve_id_and_path_contract(
    tmp_path: Path,
) -> None:
    manifest = build_manifest([build_element("el-1", "paragraph", text="Body")], [])
    payload = {"status": "succeeded", "provider": "docling+mineru"}
    fusion_artifact = _persist_fusion_payload(
        manifest,
        payload,
        "obligation-fuse-1",
        kind="fusion-payload",
        data_dir=tmp_path,
    )
    expected_bytes = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    expected_digest = hashlib.sha256(expected_bytes).hexdigest()
    expected_scope = hashlib.sha256(
        json.dumps([
            manifest.manifest_id,
            manifest.source.document_id,
            manifest.source.sha256,
            manifest.revision,
            "obligation-fuse-1",
        ]).encode()
    ).hexdigest()

    assert fusion_artifact.id == f"artifact-fusion-{expected_scope[:16]}-{expected_digest[:16]}"
    assert fusion_artifact.kind == "fusion-payload"
    assert fusion_artifact.media_type == "application/json"
    assert fusion_artifact.sha256 == expected_digest
    assert Path(fusion_artifact.path) == (
        tmp_path / "artifacts" / "fusion" / expected_scope / f"{expected_digest}.json"
    )
    assert Path(fusion_artifact.path).read_bytes() == expected_bytes

    region_bytes = b"\x89PNG\r\n\x1a\n"
    region_scope = "c" * 64
    region_artifact = _save_region_artifact(
        region_bytes,
        region_scope,
        "page-render",
        "png",
        "image/png",
        data_dir=tmp_path,
    )
    region_digest = hashlib.sha256(region_bytes).hexdigest()
    assert region_artifact.id == f"artifact-page-render-{region_scope[:16]}-{region_digest[:16]}"
    assert region_artifact.sha256 == region_digest
    assert Path(region_artifact.path) == (
        tmp_path / "artifacts" / "regions" / region_scope / f"{region_digest}.png"
    )
    assert Path(region_artifact.path).read_bytes() == region_bytes


@pytest.mark.parametrize(
    ("origin", "coords", "expected"),
    [
        ("TOPLEFT", (50.0, 100.0, 250.0, 200.0), (0.1, 0.1, 0.5, 0.2)),
        ("BOTTOMLEFT", (50.0, 900.0, 250.0, 800.0), (0.1, 0.1, 0.5, 0.2)),
        ("UNKNOWN", (50.0, 900.0, 250.0, 800.0), (0.1, 0.1, 0.5, 0.2)),
        ("UNKNOWN", (50.0, 100.0, 250.0, 200.0), (0.1, 0.1, 0.5, 0.2)),
    ],
)
def test_element_bbox_and_secondary_bbox_delegate_to_oriented_box(
    origin: str,
    coords: tuple[float, float, float, float],
    expected: tuple[float, float, float, float],
) -> None:
    left, top, right, bottom = coords
    element = ManifestElement(
        id="el-1",
        type="paragraph",
        raw_label="text",
        reading_order=1,
        hierarchy_level=0,
        page_number=1,
        text="Sample",
        provenance=[
            Provenance(
                page_number=1,
                bbox=BoundingBox(
                    left=left,
                    top=top,
                    right=right,
                    bottom=bottom,
                    coord_origin=origin,
                ),
            )
        ],
    )
    manifest = SimpleNamespace(
        pages=[PageDescriptor(page_number=1, width=500.0, height=1000.0, element_ids=["el-1"])]
    )
    secondary = _SecondaryExtraction(provider="mineru", pages={}, sizes={1: (500.0, 1000.0)})
    raw = {
        "page_number": 1,
        "provenance": [
            {
                "bbox": {
                    "left": left,
                    "top": top,
                    "right": right,
                    "bottom": bottom,
                    "coord_origin": origin,
                }
            }
        ],
    }

    assert _element_bbox(element, manifest) == pytest.approx(expected)
    assert secondary.bbox(raw) == pytest.approx(expected)


def test_element_bbox_and_secondary_bbox_return_none_for_missing_or_invalid_inputs() -> None:
    element = ManifestElement(
        id="el-1",
        type="paragraph",
        raw_label="text",
        reading_order=1,
        hierarchy_level=0,
        page_number=1,
        text="Sample",
        provenance=[
            Provenance(
                page_number=1,
                bbox=BoundingBox(left=10.0, top=20.0, right=30.0, bottom=40.0, coord_origin="TOPLEFT"),
            )
        ],
    )
    no_size_manifest = SimpleNamespace(
        pages=[PageDescriptor(page_number=1, width=None, height=1000.0, element_ids=["el-1"])]
    )
    other_page_manifest = SimpleNamespace(
        pages=[PageDescriptor(page_number=2, width=500.0, height=1000.0, element_ids=[])]
    )
    assert _element_bbox(element, no_size_manifest) is None
    assert _element_bbox(element, other_page_manifest) is None

    secondary = _SecondaryExtraction(provider="mineru", pages={}, sizes={1: (500.0, 1000.0)})
    other_page = {"page_number": 2, "provenance": [{"bbox": _box()}]}
    assert secondary.bbox(other_page) is None
    assert secondary.bbox({"page_number": 1, "provenance": [{"bbox": _box(left="bad")}]}) is None

    unpositioned = {"page_number": 1, "provenance": [{"bbox": _box()}]}
    no_size = _SecondaryExtraction(provider="mineru", pages={}, sizes={})
    zero_width = _SecondaryExtraction(provider="mineru", pages={}, sizes={1: (0.0, 1000.0)})
    assert no_size.bbox(unpositioned) is None
    assert zero_width.bbox(unpositioned) is None


def test_element_bbox_uses_the_first_provenance_that_has_a_box() -> None:
    """The loop, not ``detectors.oriented_bbox``, picks the box: that helper
    reads ``provenance[0]`` alone and would answer ``None`` here."""
    element = ManifestElement(
        id="el-1",
        type="paragraph",
        raw_label="text",
        reading_order=1,
        hierarchy_level=0,
        page_number=1,
        text="Sample",
        provenance=[
            Provenance(page_number=1),
            Provenance(
                page_number=1,
                bbox=BoundingBox(left=50.0, top=100.0, right=250.0, bottom=200.0),
            ),
        ],
    )
    manifest = SimpleNamespace(
        pages=[PageDescriptor(page_number=1, width=500.0, height=1000.0, element_ids=["el-1"])]
    )
    unboxed = element.model_copy(update={"provenance": [Provenance(page_number=1)]})

    assert _element_bbox(element, manifest) == pytest.approx((0.1, 0.1, 0.5, 0.2))
    assert _element_bbox(unboxed, manifest) is None


def test_rescue_page_uses_unique_element_id_on_id_collisions() -> None:
    existing_rescued = ManifestElement(
        id="element-rescued-p1-orig-1",
        type="paragraph",
        raw_label="paragraph",
        reading_order=1,
        hierarchy_level=0,
        page_number=1,
        text="Existing paragraph on routed page",
    )
    manifest = build_manifest([existing_rescued], [])
    rows = [
        {
            "id": "orig-1",
            "type": "paragraph",
            "raw_label": "paragraph",
            "reading_order": 1,
            "hierarchy_level": 0,
            "page_number": 1,
            "text": "Legitimate omitted paragraph text from primary provider.",
        }
    ]

    added = _rescue_page(manifest, 1, [existing_rescued], rows)

    assert added == 1
    assert [element.id for element in manifest.elements] == [
        "element-rescued-p1-orig-1-2",
        "element-rescued-p1-orig-1",
    ]
