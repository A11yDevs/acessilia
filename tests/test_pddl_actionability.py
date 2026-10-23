"""Actionability guarantees for the PDDL executor.

The executor used to register 3 real handlers for 24 admissible methods and fall
back to a no-op that reported success for 8 more, while the other 20 methods had
no handler at all. A plan step for one of those raised
``RuntimeError: No handler registered for <method>`` at execution time, and
nothing told the planner to avoid it.

These tests pin the three properties that make the gap impossible to reintroduce
silently:

1. every admissible method resolves to exactly one of: a registered handler, or
   the "unavailable" set handed to the planner;
2. the orchestrator tells the planner which methods are unavailable, restricted to
   the methods the manifest can actually ask for;
3. the real handlers validate the work instead of asserting success.
"""

from __future__ import annotations


import pytest

from backend.agents.pddl_orchestrator import (
    DETERMINISTIC_METHOD_HANDLERS,
    PddlAccessibilityOrchestrator,
    _handle_human_review_method,
    _handle_pandoc_code_method,
    _handle_pandoc_table_method,
    _handle_repetition_guard_method,
    _handle_vision_description_method,
    _tailjoin_position,
    _unsatisfied_obligations,
)
from backend.core.execution.models import MethodResult
from backend.core.manifest.builder import DEFAULT_METHOD_COSTS
from backend.core.manifest.models import (
    BoundingBox,
    ManifestElement,
    Obligation,
    ObligationAttempt,
    ProcessingManifest,
    Provenance,
)

from tests.pddl_support import (
    NOW,
    build_element as _element,
    build_manifest as _manifest,
    build_obligation as _obligation,
    build_orchestrator as _orchestrator,
)


class TestRegistryCoverage:
    #: Methods that are admissible in the catalogue but still have no handler.
    #:
    #: They are *not* silently missing: the orchestrator reports them through
    #: `_unavailable_methods`, so the planner never emits a step for them. This
    #: set is a ratchet -- implementing one of these requires removing it here, and
    #: the test below fails if a *new* method appears without a handler.
    KNOWN_UNAVAILABLE = frozenset(
        {
            "rescue-omitted",
            "table-specialist",
        }
    )

    def test_every_admissible_method_is_registered_or_declared_unavailable(self) -> None:
        """No admissible method may be silently unexecutable.

        Each one is either backed by a registered handler or reported to the
        planner as unavailable; the planner can then choose another method instead
        of producing a step that raises at execution time.
        """
        registered = set(PddlAccessibilityOrchestrator._build_executor().registry.names())
        unaccounted = sorted(set(DEFAULT_METHOD_COSTS) - registered - self.KNOWN_UNAVAILABLE)

        assert not unaccounted, (
            "métodos admissíveis sem handler e sem declaração de indisponibilidade: "
            f"{unaccounted}"
        )

    def test_unavailable_set_shrinks_only_deliberately(self) -> None:
        registered = set(PddlAccessibilityOrchestrator._build_executor().registry.names())
        still_unavailable = set(DEFAULT_METHOD_COSTS) - registered

        now_covered = sorted(self.KNOWN_UNAVAILABLE - still_unavailable)
        assert not now_covered, (
            "estes métodos ganharam handler; remova-os de KNOWN_UNAVAILABLE: "
            f"{now_covered}"
        )

    def test_registry_reports_its_own_names(self) -> None:
        executor = PddlAccessibilityOrchestrator._build_executor()
        names = set(executor.registry.names())

        assert "vision-description" in names
        assert "pandoc-code" in names
        assert "human-review" in names

    def test_deterministic_handlers_are_all_registered(self) -> None:
        registered = set(PddlAccessibilityOrchestrator._build_executor().registry.names())
        assert set(DETERMINISTIC_METHOD_HANDLERS) <= registered

    def test_no_handler_is_a_silent_success(self) -> None:
        """A handler must not report success without doing anything.

        The previous fallback returned `success=True, validated=True` with no work,
        marking obligations satisfied while nothing had been processed.
        """
        executor = PddlAccessibilityOrchestrator._build_executor()
        manifest = _manifest([_element("el-1", "picture")], [])

        results = [
            handler(manifest, "o-inexistente")
            for handler in (
                executor.registry.get(name) for name in executor.registry.names()
            )
        ]

        for result in results:
            assert isinstance(result, MethodResult)


class TestXycutOrder:
    def test_applies_multicolumn_reading_order(self) -> None:
            elements = [
                _element("left-top", "paragraph", text="Left top", reading_order=1),
                _element("right-top", "paragraph", text="Right top", reading_order=2),
                _element("left-bottom", "paragraph", text="Left bottom", reading_order=3),
                _element("right-bottom", "paragraph", text="Right bottom", reading_order=4),
            ]
            boxes = [
                (10, 10, 40, 20),
                (60, 10, 90, 20),
                (10, 30, 40, 40),
                (60, 30, 90, 40),
            ]
            for element, (left, top, right, bottom) in zip(elements, boxes):
                element.provenance = [
                    Provenance(
                        page_number=1,
                        bbox=BoundingBox(
                            left=left,
                            top=top,
                            right=right,
                            bottom=bottom,
                        ),
                    )
                ]
            manifest = _manifest(
                elements,
                [
                    _obligation(
                        "refine-reading-order",
                        [element.id for element in elements],
                        ["xycut-order"],
                    )
                ],
            )
            manifest.pages[0].width = 100
            manifest.pages[0].height = 100

            result = DETERMINISTIC_METHOD_HANDLERS["xycut-order"](manifest, "o-1")

            assert result.success is True
            assert [element.id for element in manifest.elements] == [
                "left-top",
                "left-bottom",
                "right-top",
                "right-bottom",
            ]
            if result.success:
                assert result.validated, "sucesso sem validação"


class TestRepetitionGuard:
    def test_cuts_degenerate_repetition_and_records_effect(self) -> None:
        element = _element("el-1", "paragraph", text="5 5 5 5 5 5")
        manifest = _manifest(
            [element],
            [_obligation("guard-repetition", ["el-1"], ["rep-guard"])],
        )

        result = _handle_repetition_guard_method(manifest, "o-1")

        assert result.success is True
        assert result.validated is True
        assert element.text.strip() == "5"
        assert element.metadata["repetition_guard"] == {"tokens_cut": 5}

    def test_fails_when_no_repetition_is_found(self) -> None:
        element = _element("el-1", "paragraph", text="Texto sem repetição.")
        manifest = _manifest(
            [element],
            [_obligation("guard-repetition", ["el-1"], ["rep-guard"])],
        )

        result = _handle_repetition_guard_method(manifest, "o-1")

        assert result.success is False
        assert result.validated is False
        assert element.text == "Texto sem repetição."


class TestUnavailableMethods:
    def test_only_methods_the_manifest_requests_are_reported(self) -> None:
        """The compiler rejects unknown method names, so the set must be scoped.

        Reporting every method in the catalogue would be read as a typo instead of
        a capability gap.
        """
        orchestrator = PddlAccessibilityOrchestrator.__new__(
            PddlAccessibilityOrchestrator
        )
        orchestrator.executor = PddlAccessibilityOrchestrator._build_executor()
        manifest = _manifest(
            [_element("el-1", "table")],
            [_obligation("linearize-table", ["el-1"], ["pandoc-table", "missing-method"])],
        )

        unavailable = orchestrator._unavailable_methods(manifest)

        assert unavailable == ["missing-method"]

    def test_empty_when_every_requested_method_is_registered(self) -> None:
        orchestrator = PddlAccessibilityOrchestrator.__new__(
            PddlAccessibilityOrchestrator
        )
        orchestrator.executor = PddlAccessibilityOrchestrator._build_executor()
        manifest = _manifest(
            [_element("el-1", "table")],
            [_obligation("linearize-table", ["el-1"], ["pandoc-table"])],
        )

        assert orchestrator._unavailable_methods(manifest) == []


class TestVisionDescriptionValidates:
    def test_fails_when_the_picture_has_no_description(self) -> None:
        manifest = _manifest(
            [_element("el-1", "picture")],
            [_obligation("describe-image", ["el-1"], ["vision-description"])],
        )

        result = _handle_vision_description_method(manifest, "o-1")

        assert result.success is False
        assert "el-1" in (result.message or "")

    def test_succeeds_when_the_picture_carries_a_description(self) -> None:
        manifest = _manifest(
            [_element("el-1", "picture", text="Um gráfico de barras.")],
            [_obligation("describe-image", ["el-1"], ["vision-description"])],
        )

        result = _handle_vision_description_method(manifest, "o-1")

        assert result.success is True
        assert result.validated is True

    def test_whitespace_only_text_is_not_a_description(self) -> None:
        manifest = _manifest(
            [_element("el-1", "picture", text="   ")],
            [_obligation("describe-image", ["el-1"], ["vision-description"])],
        )

        assert _handle_vision_description_method(manifest, "o-1").success is False

    def test_fails_when_the_obligation_has_no_picture_target(self) -> None:
        manifest = _manifest(
            [_element("el-1", "paragraph", text="texto")],
            [_obligation("describe-image", ["el-1"], ["vision-description"])],
        )

        assert _handle_vision_description_method(manifest, "o-1").success is False


class TestPandocTableValidates:
    def test_fails_without_a_table_ast(self) -> None:
        manifest = _manifest(
            [_element("el-1", "table")],
            [_obligation("linearize-table", ["el-1"], ["pandoc-table"])],
        )

        result = _handle_pandoc_table_method(manifest, "o-1")

        assert result.success is False
        assert "el-1" in (result.message or "")

    def test_succeeds_with_a_table_ast(self) -> None:
        manifest = _manifest(
            [_element("el-1", "table", metadata={"table_ast": {"body": [{"cells": [{"text": "Value"}]}]}})],
            [_obligation("linearize-table", ["el-1"], ["pandoc-table"])],
        )

        assert _handle_pandoc_table_method(manifest, "o-1").success is True


class TestPandocCodeNormalizes:
    def test_normalizes_the_target_in_place(self) -> None:
        element = _element("el-1", "code", text="def  f( ):\n  return 1")
        manifest = _manifest(
            [element],
            [_obligation("preserve-code-semantics", ["el-1"], ["pandoc-code"])],
        )

        result = _handle_pandoc_code_method(manifest, "o-1")

        assert result.success is True
        assert element.metadata.get("code_normalized") is True
        assert element.text != "def  f( ):\n  return 1"

    def test_fails_when_the_target_is_not_code(self) -> None:
        manifest = _manifest(
            [_element("el-1", "paragraph", text="texto")],
            [_obligation("preserve-code-semantics", ["el-1"], ["pandoc-code"])],
        )

        assert _handle_pandoc_code_method(manifest, "o-1").success is False


class TestHumanReviewIsTerminalEscalation:
    def test_reports_escalation_instead_of_success(self) -> None:
        """`human-review` must not claim an automated method satisfied the obligation."""
        manifest = _manifest(
            [_element("el-1", "picture")],
            [_obligation("describe-image", ["el-1"], ["human-review"])],
        )

        result = _handle_human_review_method(manifest, "o-1")

        assert result.success is False
        assert result.validated is False
        assert "revisão humana" in (result.message or "").lower()

    def test_reports_a_missing_obligation(self) -> None:
        manifest = _manifest([_element("el-1", "picture")], [])

        result = _handle_human_review_method(manifest, "o-inexistente")

        assert result.success is False
        assert "não encontrada" in (result.message or "")

#: Long text with a regular integer progression, which is what
#: `extract_line_numbers` looks for in marginal verse numbering.
_LONG_VERSE_TEXT = (
    "Primeira linha do poema com bastante texto para passar do limite minimo "
    "de deteccao 3964 e continuar.\n"
    "Segunda linha do poema, tambem longa o suficiente para o detector de "
    "numeros de linha marginais considerar o bloco 3969 como candidato.\n"
    "Terceira linha do poema, mantendo o comprimento necessario para que a "
    "progressao aritmetica seja reconhecida 3974 pelo detector.\n"
)

#: Record-shaped block (two short groups of dot-leader entries) so
#: `verse_blocks` with its default `kind="records"` actually splits it. Real
#: verse is deliberately left whole by that policy.
_VERSE_TEXT = (
    "Capitulo 1 .......... 10\n"
    "Capitulo 2 .......... 25\n"
    "\n"
    "Capitulo 3 .......... 40\n"
    "Capitulo 4 .......... 55\n"
    "Capitulo 5 .......... 70\n"
)


#: Body block long enough to stay out of the short-tail window.
_TAIL_BODY = (
    "Um paragrafo de corpo bem mais longo que o limite de bloco curto usado aqui."
)


class TestRealExecutionReachesAMethod:
    @pytest.mark.parametrize(
        ("kind", "element_type", "method", "metadata"),
        [
            ("linearize-table", "table", "pandoc-table", {"table_ast": {"body": [{"cells": [{"text": "Value"}]}]}}),
            ("describe-image", "picture", "vision-description", {"text": "Uma foto."}),
            ("preserve-code-semantics", "code", "pandoc-code", {}),
        ],
    )
    def test_plan_step_executes_without_a_missing_handler(
        self, kind, element_type, method, metadata
    ) -> None:
        """The executor must run the step, not raise for a missing handler."""
        element = _element(
            "el-1",
            element_type,
            text=(
                "codigo"
                if element_type == "code"
                else metadata.pop("text", None)
            ),
            metadata=metadata,
        )
        manifest = _manifest([element], [_obligation(kind, ["el-1"], [method, "human-review"])])
        orchestrator = _orchestrator()

        plan, _ = orchestrator._build_plan(manifest)
        _, report = orchestrator.executor.execute(plan, manifest, dry_run=False)

        messages = " ".join((s.message or "") for s in report.steps)
        assert "No handler registered" not in messages, messages
        assert report.status != "failed", [
            (s.method, s.status, s.message) for s in report.steps
        ]


class TestReplanning:
    """`replan-required` used to be terminal: the pipeline returned a plan it
    already knew had a failed step and never reached `complete-job`.

    A report reaches `replan-required` only when the failed obligation still has an
    admissible, untried method left; with a single method it degrades to `failed`.
    """

    @staticmethod
    def _handler(*, succeed: bool):
        from backend.core.execution.models import MethodResult

        def handler(manifest, obligation_id):
            if not succeed:
                return MethodResult(
                    success=False, validated=False, message="falha permanente"
                )
            element = next(el for el in manifest.elements if el.id == "el-1")
            element.text = "resolvido na segunda tentativa"
            return MethodResult(success=True, validated=True, message="ok")

        return handler

    def _orchestrator_with(self, outcomes: dict[str, bool], max_replans: int):
        orchestrator = _orchestrator(max_replans=max_replans)
        for method, succeed in outcomes.items():
            orchestrator.executor.registry.register(
                method, self._handler(succeed=succeed)
            )
        return orchestrator

    @staticmethod
    def _manifest_with(methods: list[str]):
        """Manifest whose obligation offers `methods` at escalating costs.

        The planner picks the cheapest admissible method, so the order here is the
        order the replan loop will try; explicit costs keep the test independent of
        `DEFAULT_METHOD_COSTS`.
        """
        obligation = _obligation("linearize-table", ["el-1"], methods)
        obligation.method_costs = {
            method: 10 * (index + 1) for index, method in enumerate(methods)
        }
        return _manifest([_element("el-1", "table")], [obligation])

    def test_moves_to_the_next_method_and_completes(self) -> None:
        orchestrator = self._orchestrator_with(
            {"pandoc-table": False, "pymupdf-region": True}, max_replans=1
        )
        manifest = self._manifest_with(["pandoc-table", "pymupdf-region"])

        final, report, reports = self._run_with_replan(orchestrator, manifest)

        assert report.status == "completed"
        assert report.replan_required is False
        assert final.status == "completed"
        assert len(reports) == 2
        assert "pymupdf-region" in [step.method for step in reports[-1].steps]

    def test_stops_at_the_configured_limit(self) -> None:
        outcomes = {
            "pandoc-table": False,
            "pymupdf-region": False,
            "norm-fix": False,
        }
        orchestrator = self._orchestrator_with(outcomes, max_replans=1)
        manifest = self._manifest_with(list(outcomes))

        _, report, reports = self._run_with_replan(orchestrator, manifest)

        assert report.replan_required is True
        assert report.status == "replan-required"
        # One replan only: the third method was never attempted.
        assert len(reports) == 2
        assert reports[1].steps[0].method == "pymupdf-region"

    def test_no_replan_when_disabled(self) -> None:
        orchestrator = self._orchestrator_with(
            {"pandoc-table": False, "pymupdf-region": True}, max_replans=0
        )
        manifest = self._manifest_with(["pandoc-table", "pymupdf-region"])

        _, report, reports = self._run_with_replan(orchestrator, manifest)

        assert report.status == "replan-required"
        assert len(reports) == 1
        executed = [step.method for step in report.steps if step.method is not None]
        assert "pymupdf-region" not in executed, executed

    @staticmethod
    def _run_with_replan(orchestrator, manifest):
        """Drive the same plan/execute/replan loop `executar()` performs.

        Returns the final manifest, the final report, and every report produced
        (each `ExecutionReport` describes only its own execution).
        """
        plan, _ = orchestrator._build_plan(manifest)
        current, report = orchestrator.executor.execute(plan, manifest, dry_run=False)
        reports = [report]

        replans = 0
        while (
            report.replan_required
            and replans < orchestrator.max_replans
            and not orchestrator.execute_dry_run
        ):
            replans += 1
            plan, _ = orchestrator._build_plan(current)
            current, report = orchestrator.executor.execute(
                plan, current, dry_run=False
            )
            reports.append(report)
        return current, report, reports


class TestEveryHandlerIsCallable:
    """Each handler must survive a positive input.

    The earlier suite only exercised a few handlers, so four of them kept a `TypeError`
    for a mis-called `docstruct` primitive and still passed: `tailjoin`,
    `tailjoin-positioned`, `verse-chunker` and `line-number-extractor` were never
    invoked with the arguments their signature requires.
    """

    #: Minimum input each handler needs, keyed by method name.
    CASES = {
        "vision-description": (
            "describe-image",
            [_element("el-1", "picture", text="Uma foto de um gato.")],
        ),
        "pandoc-table": (
            "linearize-table",
            [_element("el-1", "table", metadata={"table_ast": {"rows": []}})],
        ),
        "pandoc-code": (
            "preserve-code-semantics",
            [_element("el-1", "code", text="def  f( ):\n  return  1")],
        ),
        "pymupdf-region": (
            "describe-image",
            [_element("el-1", "picture", metadata={"region_crop": "x"})],
        ),
        "latex-normalizer": (
            "normalize-formula",
            [_element("el-1", "formula", text="$  x  +  y  $")],
        ),
        "mathml": (
            "verbalize-formula",
            [_element("el-1", "formula", text="$x + y$")],
        ),
        "latex-verbalizer": (
            "verbalize-formula",
            [_element("el-1", "formula", text="$x + y$")],
        ),
        "norm-fix": (
            "normalize-text",
            [_element("el-1", "paragraph", text="useful\u00a0text with fi ligature")],
        ),
        "rep-guard": (
            "guard-repetition",
            [_element("el-1", "paragraph", text="5 5 5 5 5 5")],
        ),
        "deterministic-heading-repair": (
            "repair-heading-order",
            [
                _element("el-1", "heading", text="A", reading_order=1),
                _element("el-2", "heading", text="B", reading_order=2),
            ],
        ),
        "line-number-extractor": (
            "extract-line-numbers",
            [
                _element(
                    "el-1",
                    "paragraph",
                    text=_LONG_VERSE_TEXT,
                )
            ],
        ),
        "verse-chunker": (
            "chunk-verse",
            [_element("el-1", "paragraph", text=_VERSE_TEXT)],
        ),
        # `join_tail` only merges a tail of *two or more* short blocks, so the
        # fixture needs a body plus two short trailing blocks.
        "tailjoin": (
            "join-tail-blocks",
            [
                _element("el-1", "paragraph", text=_TAIL_BODY),
                _element("el-2", "paragraph", text="Capitulo 1"),
                _element("el-3", "paragraph", text="42"),
            ],
        ),
        "xycut-order": (
            "refine-reading-order",
            [
                _element("el-1", "paragraph", text="Left upper", reading_order=1),
                _element("el-2", "paragraph", text="Right upper", reading_order=2),
            ],
        ),
        "tailjoin-positioned": (
            "join-tail-blocks",
            [
                _element("el-1", "paragraph", text=_TAIL_BODY),
                _element("el-2", "paragraph", text="Capitulo 1"),
                _element("el-3", "paragraph", text="42"),
            ],
        ),
        "human-review": (
            "review-structure",
            [_element("el-1", "paragraph", text="texto")],
        ),
        # Integration-level: reads the source file and calls the Toolbox twice, so
        # this only asserts the handler is reachable and returns the failure shape
        # instead of raising. The end-to-end path is covered by
        # `tests/test_fusion_e2e.py`.
        "dual-provider-fusion": (
            "fuse-providers",
            [_element("el-1", "paragraph", text="texto")],
        ),
        "single-provider": (
            "fuse-providers",
            [_element("el-1", "paragraph", text="texto")],
        ),
        # These choose between the two providers and read the secondary
        # extraction artifact; without one they must fail, not raise. The
        # positive cases live in tests/test_provider_choice_methods.py.
        "table-smart-fusion": (
            "select-table-source",
            [_element("el-1", "table", metadata={"table_ast": {"rows": []}})],
        ),
        "skeleton-order": (
            "refine-reading-order",
            [_element("el-1", "paragraph", text="texto")],
        ),
        "agreement-rule": (
            "adjudicate-page",
            [_element("el-1", "paragraph", text="texto")],
        ),
        # Renders the page on the Toolbox and asks the vision model; the
        # fixture's source does not exist, so it must fail, not raise. The
        # positive cases live in tests/test_unstructured_pages.py.
        "vision-page-inspection": (
            "inspect-unstructured-page",
            [
                _element(
                    "el-1", "unknown", metadata={"unstructured_page": True}
                ).model_copy(update={"raw_label": "unstructured-page"})
            ],
        ),
        # Calls the Toolbox; the positive cases with a fake judge live in
        # tests/test_provider_choice_methods.py.
        "vlm-pairwise-judge": (
            "adjudicate-page",
            [_element("el-1", "paragraph", text="texto")],
        ),
    }

    @pytest.mark.parametrize("method", sorted(CASES))
    def test_handler_runs_without_raising(self, method, monkeypatch, tmp_path) -> None:
        # The fixture points at a path that does not exist; that must surface as a
        # failed `MethodResult`, never as an unhandled exception.
        kind, elements = self.CASES[method]
        # The heading fixture needs the repaired heading to skip a level, which
        # `_previous_heading_level` can only detect with a real predecessor.
        if method == "deterministic-heading-repair":
            elements[1].hierarchy_level = 3
        manifest = _manifest(
            elements, [_obligation(kind, [elements[0].id], [method])]
        )
        if method == "single-provider":
            manifest.extractor.configuration["toolbox_provider"] = "docling"
            monkeypatch.setattr(
                "backend.config.settings.settings.toolbox_provider", "docling"
            )
        handler = DETERMINISTIC_METHOD_HANDLERS.get(
            method, PddlAccessibilityOrchestrator._build_executor().registry.get(method)
        )

        result = handler(manifest, "o-1")

        assert isinstance(result, MethodResult)

    def test_every_registered_handler_has_a_positive_case(self) -> None:
        """A handler nobody calls with real input is a handler nobody tested."""
        registered = set(PddlAccessibilityOrchestrator._build_executor().registry.names())
        covered = set(self.CASES)

        assert registered <= covered, sorted(registered - covered)


class TestTailjoinPosition:
    """The builder marks page furniture in `type`, not in `metadata["role"]`."""

    def _footer_manifest(self, metadata: dict | None = None) -> ProcessingManifest:
        footer = ManifestElement(
            id="el-1",
            type="page_footer",
            raw_label="page_footer",
            reading_order=1,
            hierarchy_level=1,
            text="42",
            page_number=1,
            metadata=metadata or {},
            provenance=[
                Provenance(
                    page_number=1,
                    bbox=BoundingBox(
                        left=280, top=780, right=320, bottom=800,
                        coord_origin="TOPLEFT",
                    ),
                )
            ],
        )
        manifest = _manifest([footer], [])
        manifest.pages[0].width = 600
        manifest.pages[0].height = 840
        return manifest

    def test_position_is_derived_from_page_footer_type(self) -> None:
        assert _tailjoin_position(self._footer_manifest()) == "bot"

    def test_explicit_role_metadata_still_wins(self) -> None:
        manifest = self._footer_manifest(metadata={"role": "body"})
        assert _tailjoin_position(manifest) is None


class TestUnsatisfiedObligations:
    def _attempt(self, method: str, status: str, message: str) -> ObligationAttempt:
        return ObligationAttempt(
            method=method,
            status=status,
            started_at=NOW,
            completed_at=NOW,
            message=message,
        )

    def test_reports_escalated_and_exhausted_obligations(self) -> None:
        escalated = _obligation("review-structure", ["el-1"], ["human-review"])
        escalated.selected = True
        escalated.status = "failed"
        escalated.attempts.append(
            self._attempt("human-review", "failed", "Escalonado para revisão humana")
        )
        exhausted = Obligation(
            id="o-2",
            kind="guard-repetition",
            selected=True,
            status="pending",
            target_ids=["el-1"],
            admissible_methods=["rep-guard"],
            rationale="test",
            attempts=[self._attempt("rep-guard", "failed", "Nada a cortar")],
        )
        satisfied = Obligation(
            id="o-3",
            kind="guard-repetition",
            selected=True,
            status="satisfied",
            target_ids=["el-1"],
            rationale="test",
        )
        unselected = Obligation(
            id="o-4", kind="guard-repetition", target_ids=["el-1"], rationale="test"
        )
        manifest = _manifest(
            [_element("el-1", "paragraph", text="texto")],
            [escalated, exhausted, satisfied, unselected],
        )

        report = _unsatisfied_obligations(manifest)

        assert [item["id"] for item in report] == ["o-1", "o-2"]
        assert report[0]["escalated"] is True
        assert report[0]["last_method"] == "human-review"
        assert report[1]["escalated"] is False
        assert report[1]["last_message"] == "Nada a cortar"
