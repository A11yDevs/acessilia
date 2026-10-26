"""Legacy Unicode repair in the PDDL pipeline (phase B).

The obligation is opt-in: ``LEGACY_UNICODE_REPAIR=off`` must keep the manifest
exactly as before, ``detect`` only reports, and ``repair`` emits the
deterministic method that fixes NFD and dotless-i without touching formulas.
"""
from __future__ import annotations

from backend.agents import pddl_orchestrator as pddl
from backend.config.settings import settings
from backend.core.manifest.builder import _derive_v23_processing_needs
from backend.core.manifest.models import Observation, Obligation
from tests.pddl_support import build_element, build_manifest, build_orchestrator

BRASILIA = "Bras\u0131\u0301lia"
CALCULO = "Ca\u0301lculo"
SPACING_CALCULO = "C\u00b4 alculo"


def _element(text: str, element_type: str = "paragraph"):
    return build_element("element-1", element_type, text=text)


def _obligation(target: str | list[str] = "element-1") -> Obligation:
    target_ids = [target] if isinstance(target, str) else target
    return Obligation(
        id="o-unicode",
        kind="repair-legacy-unicode",
        target_ids=target_ids,
        admissible_methods=["unicode-repair", "human-review"],
        method_costs={"unicode-repair": 5, "human-review": 100},
        rationale="Legacy text needs Unicode repair",
    )


def _kinds(obligations) -> set[str]:
    return {item.kind for item in obligations}


class TestManifestEmission:
    def test_off_emits_nothing(self, monkeypatch):
        monkeypatch.setattr(settings, "legacy_unicode_repair", "off")
        observations, obligations = _derive_v23_processing_needs(
            [_element(BRASILIA)]
        )

        assert observations == []
        assert obligations == []

    def test_detect_emits_an_observation_without_an_obligation(self, monkeypatch):
        monkeypatch.setattr(settings, "legacy_unicode_repair", "detect")
        observations, obligations = _derive_v23_processing_needs(
            [_element(BRASILIA)]
        )

        assert [item.kind for item in observations] == [
            "repair-legacy-unicode-detected"
        ]
        assert obligations == []
        assert observations[0].evidence["dotless"] == 1

    def test_repair_emits_the_deterministic_obligation(self, monkeypatch):
        monkeypatch.setattr(settings, "legacy_unicode_repair", "repair")
        observations, obligations = _derive_v23_processing_needs(
            [_element(BRASILIA)]
        )

        assert len(obligations) == 1
        obligation = obligations[0]
        assert obligation.kind == "repair-legacy-unicode"
        assert obligation.admissible_methods == ["unicode-repair", "human-review"]
        assert obligation.method_costs["unicode-repair"] == 5
        assert observations[0].evidence["combining_marks"] == 1

    def test_repair_does_not_change_the_text_while_deriving(self, monkeypatch):
        monkeypatch.setattr(settings, "legacy_unicode_repair", "repair")
        element = _element(BRASILIA)

        _derive_v23_processing_needs([element])

        assert element.text == BRASILIA

    def test_spacing_only_emits_and_repairs(self, monkeypatch):
        monkeypatch.setattr(settings, "legacy_unicode_repair", "repair")
        element = _element(SPACING_CALCULO)
        observations, obligations = _derive_v23_processing_needs([element])

        assert "repair-legacy-unicode" in _kinds(obligations)
        assert observations[0].evidence["spacing_diacritics"] == 1
        assert observations[0].evidence["spacing_word_internal"] == 1

        manifest = build_manifest([element], obligations)
        result = pddl._handle_unicode_repair_method(
            manifest, obligations[0].id
        )
        assert result.success is True
        assert element.text == "C\u00e1lculo"

    def test_invalid_mode_falls_back_to_off(self, monkeypatch):
        monkeypatch.setattr(settings, "legacy_unicode_repair", "banana")
        observations, obligations = _derive_v23_processing_needs(
            [_element(BRASILIA)]
        )

        assert observations == []
        assert obligations == []

    def test_formula_is_not_a_target(self, monkeypatch):
        monkeypatch.setattr(settings, "legacy_unicode_repair", "repair")
        observations, obligations = _derive_v23_processing_needs(
            [_element(BRASILIA, "formula")]
        )

        assert "repair-legacy-unicode" not in _kinds(obligations)

    def test_page_header_is_a_target(self, monkeypatch):
        monkeypatch.setattr(settings, "legacy_unicode_repair", "repair")
        observations, obligations = _derive_v23_processing_needs(
            [_element(SPACING_CALCULO, "page_header")]
        )

        assert "repair-legacy-unicode" in _kinds(obligations)

    def test_table_cells_are_a_target(self, monkeypatch):
        monkeypatch.setattr(settings, "legacy_unicode_repair", "repair")
        table = build_element(
            "element-table",
            "table",
            metadata={
                "table_ast": {"body": [{"cells": [{"text": SPACING_CALCULO}]}]}
            },
        )
        observations, obligations = _derive_v23_processing_needs([table])

        assert "repair-legacy-unicode" in _kinds(obligations)
        assert observations[0].evidence["spacing_word_internal"] == 1


class TestHandler:
    def test_repairs_and_records_provenance(self):
        element = _element(BRASILIA)
        manifest = build_manifest([element], [_obligation()])

        result = pddl._handle_unicode_repair_method(manifest, "o-unicode")

        assert result.success is True
        assert element.text == "Bras\u00edlia"
        assert element.metadata["unicode_repair"]["rules"] == ["dotless-base"]
        assert element.metadata["unicode_repair"]["edits"] == 1
        assert element.metadata["unicode_repair"]["edited"] is True
        assert element.metadata["unicode_repair"]["needs_review"] is False
        assert element.metadata["unicode_repair"]["confidence"] is None

    def test_repairs_word_internal_spacing_diacritics(self):
        element = _element("Bras\u00b4 \u0131lia, C\u00b4 alculo e Voc\u02c6 e")
        manifest = build_manifest([element], [_obligation()])

        result = pddl._handle_unicode_repair_method(manifest, "o-unicode")

        assert result.success is True
        assert element.text == "Bras\u00edlia, C\u00e1lculo e Voc\u00ea"
        assert "spacing-diacritic" in element.metadata["unicode_repair"]["rules"]

    def test_repairs_page_header(self):
        element = _element(SPACING_CALCULO, "page_header")
        manifest = build_manifest([element], [_obligation()])

        result = pddl._handle_unicode_repair_method(manifest, "o-unicode")

        assert result.success is True
        assert element.text == "C\u00e1lculo"

    def test_repairs_table_cells_and_caption(self):
        table = build_element(
            "element-table",
            "table",
            metadata={
                "table_ast": {
                    "caption": "Tabela C\u00b4 alculo",
                    "body": [
                        {
                            "cells": [
                                {"text": "velocidade m\u00b4 edia"},
                                {"text": "n\u00b4 umero"},
                            ]
                        }
                    ],
                }
            },
        )
        manifest = build_manifest([table], [_obligation("element-table")])

        result = pddl._handle_unicode_repair_method(manifest, "o-unicode")

        assert result.success is True
        table_ast = table.metadata["table_ast"]
        assert table_ast["caption"] == "Tabela C\u00e1lculo"
        assert [cell["text"] for cell in table_ast["body"][0]["cells"]] == [
            "velocidade m\u00e9dia",
            "n\u00famero",
        ]
        assert table.metadata["unicode_repair"]["edited"] is True

    def test_standalone_accent_is_left_untouched(self):
        text = "o sinal \u00b4 e usado"
        element = _element(text)
        manifest = build_manifest([element], [_obligation()])

        result = pddl._handle_unicode_repair_method(manifest, "o-unicode")

        assert result.success is True
        assert element.text == text
        assert element.metadata["unicode_repair"]["rules"] == []
        assert element.metadata["unicode_repair"]["needs_review"] is True

    def test_standalone_accent_is_repaired_with_document_evidence(self):
        text = (
            "C\u00b4 alculo, Matem\u00b4 atica, fun\u00b8 c\u02dc ao, "
            "n\u02dc ao, Voc\u02c6 e, posi\u00b8 c\u02dc ao \u00b4 e"
        )
        element = _element(text)
        manifest = build_manifest([element], [_obligation()])

        result = pddl._handle_unicode_repair_method(manifest, "o-unicode")

        assert result.success is True
        assert element.text.endswith("posi\u00e7\u00e3o \u00e9")
        assert "spacing-diacritic" in element.metadata["unicode_repair"]["rules"]

    def test_crase_and_split_ligature_need_document_evidence(self):
        """The rules rest on the document's evidence, not the element's own accents."""
        evidence = _element("C´ alculo Matem´ atica fun¸ c˜ ao n˜ ao")
        plain = build_element(
            "element-2",
            "paragraph",
            text="mais precisa ` a medida que h fi ca perto",
            reading_order=2,
        )
        manifest = build_manifest(
            [evidence, plain], [_obligation(["element-1", "element-2"])]
        )

        pddl._handle_unicode_repair_method(manifest, "o-unicode")

        assert plain.text == "mais precisa à medida que h fica perto"
        assert set(plain.metadata["unicode_repair"]["rules"]) == {"grave-crase", "split-ligature"}

    def test_crase_is_kept_without_document_evidence(self):
        text = "mais precisa ` a medida, o sinal ´ e"
        element = _element(text)
        manifest = build_manifest([element], [_obligation()])

        pddl._handle_unicode_repair_method(manifest, "o-unicode")

        assert element.text.startswith("mais precisa ` a medida")

    def test_threshold_uses_all_targets_of_the_obligation(self):
        first = _element("C\u00b4 alculo Matem\u00b4 atica fun\u00b8 c\u02dc ao n\u02dc ao")
        second = build_element(
            "element-2",
            "paragraph",
            text="o sinal \u00b4 e usado",
            reading_order=2,
        )
        manifest = build_manifest(
            [first, second], [_obligation(["element-1", "element-2"])]
        )

        pddl._handle_unicode_repair_method(manifest, "o-unicode")

        assert second.text == "o sinal \u00e9 usado"

    def test_standalone_threshold_boundary(self):
        for count, expected in (
            (4, "o sinal \u00b4 e usado"),
            (5, "o sinal \u00e9 usado"),
        ):
            first = _element(" ".join(["C\u00b4 alculo"] * count))
            second = build_element(
                "element-2",
                "paragraph",
                text="o sinal \u00b4 e usado",
                reading_order=2,
            )
            manifest = build_manifest(
                [first, second], [_obligation(["element-1", "element-2"])]
            )

            pddl._handle_unicode_repair_method(manifest, "o-unicode")

            assert second.text == expected, count

    def test_protected_spans_do_not_reach_the_threshold(self):
        first = _element(" ".join(["`C\u00b4 alculo`"] * 5))
        second = build_element(
            "element-2",
            "paragraph",
            text="o sinal \u00b4 e usado",
            reading_order=2,
        )
        manifest = build_manifest(
            [first, second], [_obligation(["element-1", "element-2"])]
        )

        pddl._handle_unicode_repair_method(manifest, "o-unicode")

        assert second.text == "o sinal \u00b4 e usado"

    def test_observation_evidence_sets_the_document_threshold(self):
        first = _element("C\u00b4 alculo")
        second = build_element(
            "element-2",
            "paragraph",
            text="o sinal \u00b4 e usado",
            reading_order=2,
        )
        manifest = build_manifest(
            [first, second], [_obligation(["element-1", "element-2"])]
        )
        manifest.observations.append(
            Observation(
                id="observation-repair-legacy-unicode",
                kind="repair-legacy-unicode-detected",
                severity="warning",
                message="legacy Unicode",
                target_ids=["element-1", "element-2"],
                evidence={"spacing_word_internal": 5},
            )
        )

        pddl._handle_unicode_repair_method(manifest, "o-unicode")

        assert second.text == "o sinal \u00e9 usado"

    def test_idempotent(self):
        element = _element(f"{BRASILIA} e {CALCULO}")
        manifest = build_manifest([element], [_obligation()])

        first = pddl._handle_unicode_repair_method(manifest, "o-unicode")
        second = pddl._handle_unicode_repair_method(manifest, "o-unicode")

        assert first.success is True
        assert second.success is True
        assert element.text == "Bras\u00edlia e C\u00e1lculo"
        assert element.metadata["unicode_repair"]["edits"] == 0

    def test_formula_target_is_not_rewritten(self):
        element = _element(CALCULO, "formula")
        manifest = build_manifest([element], [_obligation()])

        result = pddl._handle_unicode_repair_method(manifest, "o-unicode")

        assert result.success is False
        assert element.text == CALCULO

    def test_missing_obligation(self):
        manifest = build_manifest([_element(BRASILIA)], [])

        result = pddl._handle_unicode_repair_method(manifest, "o-ausente")

        assert result.success is False
        assert "o-ausente" in (result.message or "")


class TestDetectModeTechnicalWarning:
    """``detect`` leaves the text as extracted, so the payload must warn."""

    @staticmethod
    def _payload(tmp_path, monkeypatch, *, mode: str):
        monkeypatch.setattr(settings, "legacy_unicode_repair", mode)
        observations, obligations = _derive_v23_processing_needs([_element(BRASILIA)])
        manifest = build_manifest([_element(BRASILIA)], obligations)
        manifest.observations = observations
        orchestrator = build_orchestrator()
        plan, _ = orchestrator._build_plan(manifest)
        return pddl.build_pddl_structured_payload(
            file_path=tmp_path / "legado.pdf", manifest=manifest, plan=plan,
            planner_backend="internal", execution_report=None, comparison=None,
        )

    def test_detect_warns_that_the_text_is_delivered_unrepaired(
        self, tmp_path, monkeypatch
    ):
        warnings = self._payload(tmp_path, monkeypatch, mode="detect")[
            "technical_warnings"
        ]

        assert any("LEGACY_UNICODE_REPAIR=detect" in warning for warning in warnings)

    def test_repair_does_not_warn(self, tmp_path, monkeypatch):
        warnings = self._payload(tmp_path, monkeypatch, mode="repair")[
            "technical_warnings"
        ]

        assert not any("Unicode legado" in warning for warning in warnings)


def test_kind_is_not_critical():
    assert "repair-legacy-unicode" in pddl.NON_CRITICAL_OBLIGATION_KINDS
