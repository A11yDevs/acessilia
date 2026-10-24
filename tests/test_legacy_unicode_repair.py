"""Legacy Unicode repair in the PDDL pipeline (phase B).

The obligation is opt-in: ``LEGACY_UNICODE_REPAIR=off`` must keep the manifest
exactly as before, ``detect`` only reports, and ``repair`` emits the
deterministic method that fixes NFD and dotless-i without touching formulas.
"""
from __future__ import annotations

from backend.agents import pddl_orchestrator as pddl
from backend.config.settings import settings
from backend.core.manifest.builder import _derive_v23_processing_needs
from backend.core.manifest.models import Obligation
from tests.pddl_support import build_element, build_manifest, build_orchestrator

BRASILIA = "Bras\u0131\u0301lia"
CALCULO = "Ca\u0301lculo"
SPACING_CALCULO = "C\u00b4 alculo"


def _element(text: str, element_type: str = "paragraph"):
    return build_element("element-1", element_type, text=text)


def _obligation(target: str = "element-1") -> Obligation:
    return Obligation(
        id="o-unicode",
        kind="repair-legacy-unicode",
        target_ids=[target],
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

    def test_spacing_only_does_not_emit_in_phase_b(self, monkeypatch):
        monkeypatch.setattr(settings, "legacy_unicode_repair", "repair")
        observations, obligations = _derive_v23_processing_needs(
            [_element(SPACING_CALCULO)]
        )

        assert "repair-legacy-unicode" not in _kinds(obligations)
        assert "repair-legacy-unicode-detected" not in {
            item.kind for item in observations
        }

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


class TestHandler:
    def test_repairs_and_records_provenance(self):
        element = _element(BRASILIA)
        manifest = build_manifest([element], [_obligation()])

        result = pddl._handle_unicode_repair_method(manifest, "o-unicode")

        assert result.success is True
        assert element.text == "Bras\u00edlia"
        assert element.metadata["unicode_repair"]["rules"] == ["dotless-base"]
        assert element.metadata["unicode_repair"]["edits"] == 1
        assert element.metadata["unicode_repair"]["confidence"] is None

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
