"""Characterization tests for manifest/models.py, manifest/builder.py, and manifest/slides.py (#612, PR 8).

Pins the key branches of ``ProcessingManifest.validate_references``,
``reconcile_reclassified_element_processing_needs``, ``_build_from_toolbox_json``,
``structure_as_slides``, and ``_split_across_slides`` so modularization keeps
validation errors, reconciled needs, secondary artifacts, and slide restructuring
identical.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest
from acessilia_core.manifest.builder import (
    SECONDARY_EXTRACTION_ARTIFACT_ID,
    build_processing_manifest,
    reconcile_reclassified_element_processing_needs,
)
from acessilia_core.manifest.models import (
    Artifact,
    ManifestElement,
    Obligation,
    ObligationAttempt,
    Observation,
    PageDescriptor,
    ProcessingManifest,
    Provenance,
)
from acessilia_core.manifest.slides import (
    _split_across_slides,
    structure_as_slides,
)
from acessilia_core.manifest.toolbox_extractor import ToolboxExtraction
from pddl_support import NOW, build_element, build_manifest, build_obligation
from pydantic import ValidationError

TOOLBOX_FIXTURE = Path(__file__).parent / "fixtures" / "toolbox-v2-contract.json"


def _manifest_dict() -> dict:
    el = build_element("element-1", "paragraph", text="Hello")
    manifest = build_manifest([el], [])
    return manifest.model_dump(mode="python", by_alias=True)


def _attempt(
    *,
    method: str = "vision-description",
    artifact_ids: list[str] | None = None,
) -> dict:
    return ObligationAttempt(
        method=method,
        status="succeeded",
        started_at=NOW,
        completed_at=NOW,
        artifact_ids=artifact_ids or [],
    ).model_dump(mode="python")


class TestValidateReferencesCharacterization:
    def test_rejects_extractor_ending_before_starting(self) -> None:
        data = _manifest_dict()
        data["extractor"]["completed_at"] = NOW - timedelta(seconds=5)
        with pytest.raises(ValidationError):
            ProcessingManifest.model_validate(data)

    def test_rejects_duplicate_observation_obligation_and_artifact_ids(self) -> None:
        obs = Observation(
            id="obs-dup",
            kind="k",
            severity="info",
            message="msg",
            target_ids=["element-1"],
        ).model_dump(mode="python")
        data = _manifest_dict()
        data["observations"] = [obs, dict(obs)]
        data["summary"]["observation_count"] = 2
        with pytest.raises(ValidationError):
            ProcessingManifest.model_validate(data)

        ob = build_obligation(
            "describe-image", ["element-1"], ["vision-description"]
        ).model_copy(update={"id": "ob-dup"}).model_dump(mode="python")
        data = _manifest_dict()
        data["obligations"] = [ob, dict(ob)]
        data["summary"]["obligation_count"] = 2
        with pytest.raises(ValidationError):
            ProcessingManifest.model_validate(data)

        art = Artifact(
            id="art-dup", kind="k", path="/tmp/a", media_type="application/json"
        ).model_dump(mode="python")
        data = _manifest_dict()
        data["artifacts"] = [art, dict(art)]
        with pytest.raises(ValidationError):
            ProcessingManifest.model_validate(data)

    def test_rejects_unknown_observation_and_obligation_targets_and_dependencies(
        self,
    ) -> None:
        data = _manifest_dict()
        data["observations"] = [
            Observation(
                id="obs-1",
                kind="k",
                severity="info",
                message="msg",
                target_ids=["missing-el"],
            ).model_dump(mode="python")
        ]
        data["summary"]["observation_count"] = 1
        with pytest.raises(ValidationError, match="missing-el"):
            ProcessingManifest.model_validate(data)

        data = _manifest_dict()
        data["obligations"] = [
            build_obligation("describe-image", ["missing-el"], ["vision-description"])
            .model_copy(update={"id": "ob-1"})
            .model_dump(mode="python")
        ]
        data["summary"]["obligation_count"] = 1
        with pytest.raises(ValidationError, match="missing-el"):
            ProcessingManifest.model_validate(data)

        data = _manifest_dict()
        data["obligations"] = [
            build_obligation("describe-image", ["element-1"], ["vision-description"])
            .model_copy(update={"id": "ob-1", "dependencies": ["missing-dep"]})
            .model_dump(mode="python")
        ]
        data["summary"]["obligation_count"] = 1
        with pytest.raises(ValidationError, match="missing-dep"):
            ProcessingManifest.model_validate(data)

        data = _manifest_dict()
        data["obligations"] = [
            build_obligation("describe-image", ["element-1"], ["vision-description"])
            .model_copy(update={"id": "ob-self", "dependencies": ["ob-self"]})
            .model_dump(mode="python")
        ]
        data["summary"]["obligation_count"] = 1
        with pytest.raises(ValidationError, match="ob-self"):
            ProcessingManifest.model_validate(data)

    def test_rejects_inadmissible_attempt_method_and_unknown_artifact(self) -> None:
        data = _manifest_dict()
        ob = build_obligation(
            "describe-image", ["element-1"], ["vision-description"]
        ).model_copy(update={"id": "ob-1"})
        ob_dict = ob.model_dump(mode="python")
        ob_dict["attempts"] = [_attempt(method="bad-method")]
        data["obligations"] = [ob_dict]
        data["summary"]["obligation_count"] = 1
        with pytest.raises(ValidationError, match="bad-method"):
            ProcessingManifest.model_validate(data)

        ob_dict["attempts"] = [_attempt(artifact_ids=["art-missing"])]
        with pytest.raises(ValidationError, match="art-missing"):
            ProcessingManifest.model_validate(data)

    def test_rejects_dependency_cycle_unsatisfied_predecessor_and_summary_mismatch(
        self,
    ) -> None:
        ob_a = build_obligation(
            "describe-image", ["element-1"], ["vision-description"]
        ).model_copy(update={"id": "ob-a", "dependencies": ["ob-b"]})
        ob_b = build_obligation(
            "linearize-table", ["element-1"], ["pandoc-table"]
        ).model_copy(update={"id": "ob-b", "dependencies": ["ob-a"]})
        data = _manifest_dict()
        data["obligations"] = [
            ob_a.model_dump(mode="python"),
            ob_b.model_dump(mode="python"),
        ]
        data["summary"]["obligation_count"] = 2
        with pytest.raises(ValidationError):
            ProcessingManifest.model_validate(data)

        pred = build_obligation(
            "describe-image", ["element-1"], ["vision-description"]
        ).model_copy(update={"id": "ob-pred", "status": "pending"})
        succ = build_obligation(
            "linearize-table", ["element-1"], ["pandoc-table"]
        ).model_copy(
            update={"id": "ob-succ", "status": "satisfied", "dependencies": ["ob-pred"]}
        )
        data = _manifest_dict()
        data["obligations"] = [
            pred.model_dump(mode="python"),
            succ.model_dump(mode="python"),
        ]
        data["summary"]["obligation_count"] = 2
        with pytest.raises(ValidationError, match="ob-pred"):
            ProcessingManifest.model_validate(data)

        data = _manifest_dict()
        data["summary"]["page_count"] = 99
        with pytest.raises(ValidationError, match="summary.page_count=99"):
            ProcessingManifest.model_validate(data)

    def test_validation_error_precedence_across_multiple_violations(self) -> None:
        # Extractor interval is checked before observation targets and summary counts.
        data = _manifest_dict()
        data["extractor"]["completed_at"] = NOW - timedelta(seconds=1)
        data["observations"] = [
            Observation(
                id="obs-bad",
                kind="k",
                severity="info",
                message="msg",
                target_ids=["missing-el"],
            ).model_dump(mode="python")
        ]
        data["summary"]["page_count"] = 99
        with pytest.raises(ValidationError) as exc_info:
            ProcessingManifest.model_validate(data)
        err = str(exc_info.value)
        assert "missing-el" not in err
        assert "summary.page_count" not in err

        # Observation target check precedes obligation targets and summary counts.
        data = _manifest_dict()
        data["observations"] = [
            Observation(
                id="obs-first",
                kind="k",
                severity="info",
                message="msg",
                target_ids=["missing-obs-el"],
            ).model_dump(mode="python")
        ]
        data["obligations"] = [
            build_obligation(
                "describe-image", ["missing-ob-el"], ["vision-description"]
            )
            .model_copy(update={"id": "ob-second"})
            .model_dump(mode="python")
        ]
        data["summary"]["page_count"] = 99
        with pytest.raises(ValidationError, match="missing-obs-el") as exc_info:
            ProcessingManifest.model_validate(data)
        assert "missing-ob-el" not in str(exc_info.value)
        assert "summary.page_count" not in str(exc_info.value)


class TestReconcileAndBuildFromToolboxCharacterization:
    def test_reconcile_replaces_standard_and_type_bound_needs_and_rewires_deps(
        self,
    ) -> None:
        el = build_element("element-001", "formula", text="x = 1")
        other = build_element("element-002", "paragraph", text="Keep")
        ob_formula = Obligation(
            id="obligation-verbalize-formula-001",
            kind="verbalize-formula",
            target_ids=["element-001"],
            admissible_methods=["mathml", "human-review"],
            method_costs={"mathml": 10, "human-review": 100},
            rationale="formula",
        )
        ob_norm = Obligation(
            id="obligation-normalize-formula-001",
            kind="normalize-formula",
            target_ids=["element-001"],
            admissible_methods=["latex-normalizer", "human-review"],
            method_costs={"latex-normalizer": 10, "human-review": 100},
            rationale="normalize",
        )
        ob_dependent = Obligation(
            id="obligation-downstream-002",
            kind="normalize-text",
            target_ids=["element-002"],
            dependencies=["obligation-verbalize-formula-001"],
            admissible_methods=["norm-fix", "human-review"],
            method_costs={"norm-fix": 5, "human-review": 100},
            rationale="downstream",
        )
        manifest = build_manifest([el, other], [ob_formula, ob_norm, ob_dependent])
        manifest.observations = [
            Observation(
                id="observation-verbalize-formula-001",
                kind="formula-requires-processing",
                severity="warning",
                message="formula",
                target_ids=["element-001"],
            ),
            Observation(
                id="observation-normalize-formula-001",
                kind="normalize-formula-detected",
                severity="info",
                message="norm",
                target_ids=["element-001"],
            ),
            Observation(
                id="observation-fusion-keep",
                kind="adjudicate-page-detected",
                severity="info",
                message="keep",
                target_ids=["element-001"],
            ),
        ]
        manifest.summary.observation_count = 3

        # Reclassify formula -> picture.
        el.type = "picture"
        reconcile_reclassified_element_processing_needs(
            manifest, el, previous_type="formula"
        )

        ob_kinds = {ob.kind for ob in manifest.obligations}
        assert ob_kinds == {"describe-image", "normalize-text"}
        downstream = next(
            ob for ob in manifest.obligations if ob.id == "obligation-downstream-002"
        )
        assert downstream.dependencies == ["obligation-describe-image-001"]

        obs_kinds = {obs.kind for obs in manifest.observations}
        assert obs_kinds == {
            "picture-requires-processing",
            "adjudicate-page-detected",
        }
        assert manifest.summary.obligation_count == 2
        assert manifest.summary.observation_count == 2
        assert manifest.summary.element_types == {"paragraph": 1, "picture": 1}

    def test_reconcile_noops_for_same_type_or_non_obligation_target_type(self) -> None:
        el = build_element("element-001", "picture", text="")
        manifest = build_manifest([el], [])
        reconcile_reclassified_element_processing_needs(
            manifest, el, previous_type="picture"
        )
        assert manifest.obligations == []

        el.type = "paragraph"
        reconcile_reclassified_element_processing_needs(
            manifest, el, previous_type="picture"
        )
        assert manifest.obligations == []

    def test_reconcile_from_untracked_previous_type_and_existing_target_obligation(
        self,
    ) -> None:
        el = build_element("element-010", "paragraph", text="Caption")
        manifest = build_manifest([el], [])

        # Reclassify paragraph (no OBLIGATION_BY_TYPE spec) -> picture.
        el.type = "picture"
        reconcile_reclassified_element_processing_needs(
            manifest, el, previous_type="paragraph"
        )
        assert [ob.kind for ob in manifest.obligations] == ["describe-image"]
        assert [obs.kind for obs in manifest.observations] == [
            "picture-requires-processing"
        ]

        # When target obligation/observation already exist, keep them without duplicating.
        existing_ob = manifest.obligations[0]
        existing_obs = manifest.observations[0]
        reconcile_reclassified_element_processing_needs(
            manifest, el, previous_type="table"
        )
        assert manifest.obligations == [existing_ob]
        assert manifest.observations == [existing_obs]

    def test_build_from_toolbox_json_handles_present_missing_and_blank_secondary(
        self, tmp_path: Path
    ) -> None:
        source = tmp_path / "doc.pdf"
        source.write_bytes(b"%PDF-1.4")
        secondary_file = tmp_path / "secondary.json"
        secondary_file.write_text("{}", encoding="utf-8")

        def run(secondary_payload: dict | None) -> ProcessingManifest:
            response = json.loads(TOOLBOX_FIXTURE.read_text(encoding="utf-8"))
            if secondary_payload is not None:
                response["secondary_extraction"] = secondary_payload
            extraction = ToolboxExtraction(
                document=response,
                started_at=NOW,
                completed_at=NOW,
                duration_ms=3,
                version="test",
                configuration={"toolbox_provider": "docling"},
            )
            return build_processing_manifest(source, extraction)

        present_manifest = run(
            {"path": str(secondary_file), "sha256": "a" * 64}
        )
        assert any(
            art.id == SECONDARY_EXTRACTION_ARTIFACT_ID
            and art.path == str(secondary_file)
            and art.sha256 == "a" * 64
            for art in present_manifest.artifacts
        )

        # Recorded path missing on disk still attaches artifact, but is not readable.
        missing_path = str(tmp_path / "deleted-secondary.json")
        missing_manifest = run({"path": missing_path, "sha256": "b" * 64})
        assert any(
            art.id == SECONDARY_EXTRACTION_ARTIFACT_ID and art.path == missing_path
            for art in missing_manifest.artifacts
        )

        blank_manifest = run({"path": "   ", "sha256": "c" * 64})
        assert not any(
            art.id == SECONDARY_EXTRACTION_ARTIFACT_ID
            for art in blank_manifest.artifacts
        )


class TestSlidesCharacterization:
    def test_split_across_slides_splits_consecutive_same_page_runs(self) -> None:
        el = build_element("e-1", "paragraph", text="Line one\nLine two\nSlide two").model_copy(
            update={
                "page_number": 1,
                "provenance": [
                    Provenance(page_number=1, char_start=0, char_end=8),
                    Provenance(page_number=1, char_start=9, char_end=17),
                    Provenance(page_number=2, char_start=18, char_end=27),
                ],
                "metadata": {"origin": "test"},
            }
        )
        parts = _split_across_slides(el)
        assert [p.id for p in parts] == ["e-1-part-1", "e-1-part-2"]
        assert [p.page_number for p in parts] == [1, 2]
        assert [p.text for p in parts] == ["Line one\nLine two", "Slide two"]
        assert len(parts[0].provenance) == 2
        assert parts[0].metadata["split_from"] == "e-1"

    @pytest.mark.parametrize(
        ("element_type", "text", "provenance"),
        [
            (
                "table",
                "A | B\nC | D",
                [
                    Provenance(page_number=1, char_start=0, char_end=5),
                    Provenance(page_number=2, char_start=6, char_end=11),
                ],
            ),
            (
                "paragraph",
                "First Second",
                [
                    Provenance(page_number=1, char_start=None, char_end=5),
                    Provenance(page_number=2, char_start=6, char_end=12),
                ],
            ),
            (
                "paragraph",
                "First GAP Second",
                [
                    Provenance(page_number=1, char_start=0, char_end=5),
                    Provenance(page_number=2, char_start=10, char_end=16),
                ],
            ),
            (
                "paragraph",
                "First Second TRAILING",
                [
                    Provenance(page_number=1, char_start=0, char_end=5),
                    Provenance(page_number=2, char_start=6, char_end=12),
                ],
            ),
            (
                "paragraph",
                "First   ",
                [
                    Provenance(page_number=1, char_start=0, char_end=5),
                    Provenance(page_number=2, char_start=5, char_end=8),
                ],
            ),
        ],
        ids=[
            "non-splittable-table",
            "missing-char-offsets",
            "non-empty-gap-between-runs",
            "uncovered-trailing-text",
            "whitespace-only-slice",
        ],
    )
    def test_split_across_slides_returns_original_when_invalid(
        self,
        element_type: str,
        text: str,
        provenance: list[Provenance],
    ) -> None:
        el = build_element("e-keep", element_type, text=text).model_copy(
            update={"page_number": 1, "provenance": provenance}
        )
        assert _split_across_slides(el) == [el]

    def test_structure_as_slides_demotes_inner_titles_and_keeps_loose_elements(
        self,
    ) -> None:
        slide_title = build_element("s1-t", "title", text="Intro", reading_order=1).model_copy(
            update={"page_number": 1, "hierarchy_level": 1}
        )
        inner_title = build_element("s1-sub", "title", text="Subtopic", reading_order=2).model_copy(
            update={"page_number": 1, "hierarchy_level": 1}
        )
        body = build_element("s1-p", "paragraph", text="Details", reading_order=3).model_copy(
            update={"page_number": 1}
        )
        loose_group = ManifestElement(
            id="grp-loose",
            type="group",
            raw_label="group",
            reading_order=4,
            hierarchy_level=0,
            page_number=None,
        )
        manifest = build_manifest([slide_title, inner_title, body, loose_group], [])
        manifest.pages = [
            PageDescriptor(
                page_number=1,
                width=960.0,
                height=540.0,
                element_ids=["s1-t", "s1-sub", "s1-p"],
            )
        ]
        manifest.summary.page_count = 1

        structure_as_slides(
            manifest,
            page_fractions=lambda _: None,
        )

        assert manifest.elements[0].id == "element-slide-deck-title"
        assert manifest.elements[0].text == "Intro"
        demoted = next(el for el in manifest.elements if el.id == "s1-sub")
        assert demoted.type == "heading"
        assert demoted.metadata["original_type"] == "title"
        assert demoted.hierarchy_level == 3
        assert manifest.elements[-1].id == "grp-loose"
        assert [el.reading_order for el in manifest.elements] == list(
            range(1, len(manifest.elements) + 1)
        )

    def test_structure_as_slides_converts_visual_slide_and_falls_back_deck_title(
        self,
    ) -> None:
        pic = build_element("s1-pic", "picture", text="", reading_order=1).model_copy(
            update={"page_number": 1}
        )
        caption = build_element(
            "s1-cap", "paragraph", text="Figure note", reading_order=2
        ).model_copy(update={"page_number": 1})
        manifest = build_manifest([pic, caption], [])
        manifest.pages = [
            PageDescriptor(
                page_number=1,
                width=960.0,
                height=540.0,
                element_ids=["s1-pic", "s1-cap"],
            )
        ]
        manifest.summary.page_count = 1

        boxes = {
            "s1-pic": (0.05, 0.05, 0.90, 0.85),
            "s1-cap": (0.05, 0.88, 0.25, 0.93),
        }
        structure_as_slides(
            manifest,
            page_fractions=lambda el: boxes.get(el.id),
        )

        # Slide 1 has no title, so deck title falls back to source filename stem.
        assert manifest.elements[0].id == "element-slide-deck-title"
        assert manifest.elements[0].text == manifest.source.filename.rsplit(".", 1)[0]
        visual = next(
            el for el in manifest.elements if el.metadata.get("slide_visual")
        )
        assert visual.type == "picture"
        assert visual.metadata["replaced_element_ids"] == ["s1-pic", "s1-cap"]
        assert visual.metadata["replaced_text"] == "Figure note"
