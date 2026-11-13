"""Step messages of the PDDL handlers follow the request locale (#410).

The executor persists ``MethodResult.message`` in the obligation attempts and the
orchestrator publishes the last one as ``last_message``, so these tests check
the visible text at both locales and the persisted copy, not only the catalog.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.agents.pddl_orchestrator import _handle_latex_normalizer_method
from backend.core.pipeline.handlers.content import (
    _handle_pandoc_code_method,
    _handle_pandoc_table_method,
    _handle_vision_description_method,
)
from backend.core.pipeline.handlers.messages import (
    MSG_BLOCK_COUNT,
    MSG_CODE_NORMALIZED,
    MSG_TABLE_VALIDATED,
    MSG_VISION_VALIDATED,
)
from backend.core.pipeline.handlers.text import (
    _handle_chunk_verse_method,
    _handle_extract_line_numbers_method,
)
from backend.core.pipeline.obligations import _unsatisfied_obligations
from backend.i18n import n, reset_request_locale, set_request_locale
from backend.services.blocking import run_blocking

from tests.pddl_support import (
    build_element as _element,
    build_manifest as _manifest,
    build_obligation as _obligation,
    build_orchestrator as _orchestrator,
)

LOCALES = ("en_US", "pt_BR")

#: Three marginal numbers (step 5) in a single source block.
_LONG_VERSE_TEXT = (
    "Primeira linha do poema com bastante texto para passar do limite minimo "
    "de deteccao 3964 e continuar.\n"
    "Segunda linha do poema, tambem longa o suficiente para o detector de "
    "numeros de linha marginais considerar o bloco 3969 como candidato.\n"
    "Terceira linha do poema, mantendo o comprimento necessario para que a "
    "progressao aritmetica seja reconhecida 3974 pelo detector.\n"
)

#: One record block split into two stanzas by its blank line.
_VERSE_TEXT = (
    "Capitulo 1 .......... 10\n"
    "Capitulo 2 .......... 25\n"
    "\n"
    "Capitulo 3 .......... 40\n"
)


@pytest.fixture(params=LOCALES)
def locale(request):
    token = set_request_locale(request.param)
    try:
        yield request.param
    finally:
        reset_request_locale(token)


def _table(text: str = "Value") -> dict:
    return {"body": [{"cells": [{"text": text}]}]}


def _code_success(count: int) -> tuple[list, object]:
    elements = [
        _element(f"el-{index}", "code", text=f"def  f{index}( ):\n  return {index}")
        for index in range(1, count + 1)
    ]
    obligation = _obligation(
        "preserve-code-semantics",
        [element.id for element in elements],
        ["pandoc-code"],
    )
    return elements, obligation


def _image_success(count: int) -> tuple[list, object]:
    elements = [
        _element(f"el-{index}", "picture", text=f"Uma foto {index}.")
        for index in range(1, count + 1)
    ]
    obligation = _obligation(
        "describe-image",
        [element.id for element in elements],
        ["vision-description"],
    )
    return elements, obligation


def _table_success(count: int) -> tuple[list, object]:
    elements = [
        _element(f"el-{index}", "table", metadata={"table_ast": _table()})
        for index in range(1, count + 1)
    ]
    obligation = _obligation(
        "linearize-table",
        [element.id for element in elements],
        ["pandoc-table"],
    )
    return elements, obligation


def _formula_success(count: int) -> tuple[list, object]:
    elements = [
        _element(f"el-{index}", "formula", text=f"$ x_{index} + y $")
        for index in range(1, count + 1)
    ]
    obligation = _obligation(
        "normalize-formula",
        [element.id for element in elements],
        ["latex-normalizer"],
    )
    return elements, obligation


class TestPluralForms:
    @pytest.mark.parametrize(
        ("pair", "en", "pt"),
        [
            (
                MSG_VISION_VALIDATED,
                (
                    "Picture description validated for {count} picture",
                    "Picture descriptions validated for {count} pictures",
                ),
                (
                    "Descrição validada para {count} imagem",
                    "Descrições validadas para {count} imagens",
                ),
            ),
            (
                MSG_CODE_NORMALIZED,
                (
                    "Code normalized in {count} block",
                    "Code normalized in {count} blocks",
                ),
                (
                    "Código normalizado em {count} bloco",
                    "Código normalizado em {count} blocos",
                ),
            ),
            (
                MSG_BLOCK_COUNT,
                ("{count} block", "{count} blocks"),
                ("{count} bloco", "{count} blocos"),
            ),
        ],
    )
    @pytest.mark.parametrize("count", [0, 1, 2])
    def test_n_uses_the_locale_plural_rule(self, pair, en, pt, count) -> None:
        token = set_request_locale("en_US")
        try:
            english = n(*pair, count).format(count=count)
        finally:
            reset_request_locale(token)
        token = set_request_locale("pt_BR")
        try:
            portuguese = n(*pair, count).format(count=count)
        finally:
            reset_request_locale(token)

        assert english == en[0 if count == 1 else 1].format(count=count)
        # Portuguese treats 0 as singular; English uses the plural for 0.
        assert portuguese == pt[0 if count in (0, 1) else 1].format(count=count)


class TestHandlerMessagesFollowTheLocale:
    def test_vision_success_uses_the_count_plural(self, locale) -> None:
        elements, obligation = _image_success(2)
        manifest = _manifest(elements, [obligation])

        result = _handle_vision_description_method(manifest, "o-1")

        if locale == "en_US":
            assert result.message == "Picture descriptions validated for 2 pictures"
        else:
            assert result.message == "Descrições validadas para 2 imagens"

    def test_vision_partial_result_names_the_undescribed_pictures(self, locale) -> None:
        manifest = _manifest(
            [
                _element("el-1", "picture", text="Uma foto descrita."),
                _element("el-2", "picture"),
            ],
            [_obligation("describe-image", ["el-1", "el-2"], ["vision-description"])],
        )

        result = _handle_vision_description_method(manifest, "o-1")

        expected = (
            "Picture without a textual description: el-2"
            if locale == "en_US"
            else "Imagem sem descrição textual: el-2"
        )
        assert result.message == expected

    def test_vision_without_a_target_is_localized(self, locale) -> None:
        manifest = _manifest(
            [_element("el-1", "paragraph", text="texto")],
            [_obligation("describe-image", ["el-1"], ["vision-description"])],
        )

        result = _handle_vision_description_method(manifest, "o-1")

        expected = (
            "No picture found for the obligation"
            if locale == "en_US"
            else "Nenhuma imagem encontrada para a obrigação"
        )
        assert result.message == expected

    def test_table_success_uses_the_count_plural(self, locale) -> None:
        elements, obligation = _table_success(2)
        manifest = _manifest(elements, [obligation])

        result = _handle_pandoc_table_method(manifest, "o-1")

        expected = (
            "Table structures validated for 2 tables"
            if locale == "en_US"
            else "Estruturas tabulares validadas para 2 tabelas"
        )
        assert result.message == expected

    def test_table_without_a_target_is_localized(self, locale) -> None:
        manifest = _manifest(
            [_element("el-1", "paragraph", text="texto")],
            [_obligation("linearize-table", ["el-1"], ["pandoc-table"])],
        )

        result = _handle_pandoc_table_method(manifest, "o-1")

        expected = (
            "No table found for the obligation"
            if locale == "en_US"
            else "Nenhuma tabela encontrada para a obrigação"
        )
        assert result.message == expected

    def test_table_partial_result_names_the_ids(self, locale) -> None:
        good = _element("el-1", "table", metadata={"table_ast": _table()})
        bad = _element("el-2", "table")
        manifest = _manifest(
            [good, bad],
            [_obligation("linearize-table", ["el-1", "el-2"], ["pandoc-table"])],
        )

        result = _handle_pandoc_table_method(manifest, "o-1")

        expected = (
            "Table without tabular structure: el-2"
            if locale == "en_US"
            else "Tabela sem estrutura tabular: el-2"
        )
        assert result.message == expected

    def test_code_without_a_target_is_localized(self, locale) -> None:
        manifest = _manifest(
            [_element("el-1", "paragraph", text="texto")],
            [_obligation("preserve-code-semantics", ["el-1"], ["pandoc-code"])],
        )

        result = _handle_pandoc_code_method(manifest, "o-1")

        expected = (
            "No code block found for the obligation"
            if locale == "en_US"
            else "Nenhum bloco de código encontrado para a obrigação"
        )
        assert result.message == expected

    def test_code_success_uses_the_count_plural(self, locale) -> None:
        elements, obligation = _code_success(1)
        manifest = _manifest(elements, [obligation])

        result = _handle_pandoc_code_method(manifest, "o-1")

        expected = (
            "Code normalized in 1 block"
            if locale == "en_US"
            else "Código normalizado em 1 bloco"
        )
        assert result.message == expected

    def test_code_partial_result_uses_done_over_total(self, locale) -> None:
        manifest = _manifest(
            [
                _element("el-1", "code", text="def  f( ):\n  return 1"),
                _element("el-2", "code", text=""),
            ],
            [_obligation("preserve-code-semantics", ["el-1", "el-2"], ["pandoc-code"])],
        )

        result = _handle_pandoc_code_method(manifest, "o-1")

        expected = (
            "Code normalized in 1/2 blocks"
            if locale == "en_US"
            else "Código normalizado em 1/2 blocos"
        )
        assert result.message == expected

    def test_line_numbers_flex_numbers_and_source_blocks_independently(
        self, locale
    ) -> None:
        manifest = _manifest(
            [_element("el-1", "paragraph", text=_LONG_VERSE_TEXT)],
            [
                _obligation(
                    "extract-line-numbers", ["el-1"], ["line-number-extractor"]
                )
            ],
        )

        result = _handle_extract_line_numbers_method(manifest, "o-1")

        expected = (
            "3 marginal line numbers extracted from 1 block"
            if locale == "en_US"
            else "3 números de linha marginais extraídos de 1 bloco"
        )
        assert result.message == expected

    def test_verse_flexes_chunks_and_source_blocks_independently(self, locale) -> None:
        manifest = _manifest(
            [_element("el-1", "paragraph", text=_VERSE_TEXT)],
            [_obligation("chunk-verse", ["el-1"], ["verse-chunker"])],
        )

        result = _handle_chunk_verse_method(manifest, "o-1")

        expected = (
            "Verse split into 2 chunks from 1 block"
            if locale == "en_US"
            else "Verso fragmentado em 2 pedaços de 1 bloco"
        )
        assert result.message == expected

    def test_math_success_uses_the_count_plural(self, locale) -> None:
        elements, obligation = _formula_success(2)
        manifest = _manifest(elements, [obligation])

        result = _handle_latex_normalizer_method(manifest, "o-1")

        expected = (
            "LaTeX normalized in 2 formulas"
            if locale == "en_US"
            else "LaTeX normalizado em 2 fórmulas"
        )
        assert result.message == expected

    def test_math_without_a_formula_is_localized(self, locale) -> None:
        manifest = _manifest(
            [_element("el-1", "paragraph", text="texto")],
            [_obligation("normalize-formula", ["el-1"], ["latex-normalizer"])],
        )

        result = _handle_latex_normalizer_method(manifest, "o-1")

        expected = (
            "No formula found for the obligation"
            if locale == "en_US"
            else "Nenhuma fórmula encontrada para a obrigação"
        )
        assert result.message == expected

    def test_math_partial_result_uses_done_over_total(self, locale) -> None:
        manifest = _manifest(
            [
                _element("el-1", "formula", text="$ x + y $"),
                _element("el-2", "formula", text="   "),
            ],
            [_obligation("normalize-formula", ["el-1", "el-2"], ["latex-normalizer"])],
        )

        result = _handle_latex_normalizer_method(manifest, "o-1")

        expected = (
            "LaTeX normalized in 1/2 formulas"
            if locale == "en_US"
            else "LaTeX normalizado em 1/2 fórmulas"
        )
        assert result.message == expected


    def test_math_controlled_error_is_localized(self, locale, monkeypatch) -> None:
        from backend.agents.pddl_orchestrator import _handle_mathml_method
        from backend.tools.toolbox_client import ToolboxProviderUnavailable
        from backend.tools.toolbox_math_tools import MathCapabilityUnavailable

        def unavailable(*_args, **_kwargs):
            raise MathCapabilityUnavailable(
                "math.convert", ToolboxProviderUnavailable("offline")
            )

        monkeypatch.setattr(
            "backend.agents.pddl_orchestrator.toolbox_convert_latex", unavailable
        )
        elements, obligation = _formula_success(1)
        manifest = _manifest(elements, [obligation])

        result = _handle_mathml_method(manifest, "o-1")

        assert result.success is False
        assert "ToolboxProviderUnavailable" in (result.message or "")
        assert ("unavailable" if locale == "en_US" else "indisponível") in (
            result.message or ""
        )


class TestThePersistedMessageIsLocalized:
    def _execute(self, manifest):
        orchestrator = _orchestrator()
        plan, _ = orchestrator._build_plan(manifest)
        return orchestrator.executor.execute(plan, manifest, dry_run=False)

    @pytest.mark.parametrize(
        ("factory", "english", "portuguese"),
        [
            (
                _image_success,
                "Picture descriptions validated for 2 pictures",
                "Descrições validadas para 2 imagens",
            ),
            (
                _table_success,
                "Table structures validated for 2 tables",
                "Estruturas tabulares validadas para 2 tabelas",
            ),
            (
                _formula_success,
                "LaTeX normalized in 2 formulas",
                "LaTeX normalizado em 2 fórmulas",
            ),
        ],
    )
    def test_each_family_persists_the_localized_message(
        self, locale, factory, english, portuguese
    ) -> None:
        elements, obligation = factory(2)
        manifest = _manifest(elements, [obligation])

        updated, report = self._execute(manifest)

        assert report.status == "completed"
        expected = english if locale == "en_US" else portuguese
        assert updated.obligations[0].attempts[-1].message == expected

    def test_a_successful_attempt_keeps_the_localized_message(self, locale) -> None:
        elements, obligation = _code_success(1)
        manifest = _manifest(elements, [obligation])

        updated, report = self._execute(manifest)

        expected = (
            "Code normalized in 1 block"
            if locale == "en_US"
            else "Código normalizado em 1 bloco"
        )
        assert report.status == "completed"
        assert updated.obligations[0].attempts[-1].message == expected
        executed = [step for step in report.steps if step.method == "pandoc-code"]
        assert [step.message for step in executed] == [expected]

    def test_an_open_obligation_publishes_the_localized_last_message(
        self, locale
    ) -> None:
        manifest = _manifest(
            [_element("el-1", "paragraph", text="texto")],
            [_obligation("preserve-code-semantics", ["el-1"], ["pandoc-code"])],
        )

        updated, report = self._execute(manifest)

        expected = (
            "No code block found for the obligation"
            if locale == "en_US"
            else "Nenhum bloco de código encontrado para a obrigação"
        )
        assert updated.obligations[0].status == "failed"
        assert updated.obligations[0].attempts[-1].message == expected
        assert _unsatisfied_obligations(updated)[0]["last_message"] == expected

    def test_run_blocking_keeps_the_request_locale(self) -> None:
        elements, obligation = _code_success(1)
        manifest = _manifest(elements, [obligation])

        async def run():
            token = set_request_locale("pt_BR")
            try:
                return await run_blocking(
                    _handle_pandoc_code_method, manifest, "o-1"
                )
            finally:
                reset_request_locale(token)

        result = asyncio.run(run())

        assert result.message == "Código normalizado em 1 bloco"

    def test_the_plan_structure_is_the_same_in_both_locales(self) -> None:
        def structure(locale: str):
            token = set_request_locale(locale)
            try:
                elements, obligation = _code_success(2)
                manifest = _manifest(elements, [obligation])
                updated, report = self._execute(manifest)
            finally:
                reset_request_locale(token)
            return (
                report.status,
                updated.obligations[0].status,
                tuple(updated.obligations[0].target_ids),
                [
                    (attempt.method, attempt.status, tuple(attempt.artifact_ids))
                    for attempt in updated.obligations[0].attempts
                ],
                [element.id for element in updated.elements],
            )

        assert structure("en_US") == structure("pt_BR")
