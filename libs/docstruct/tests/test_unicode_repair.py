"""Tests for the conservative Unicode repair (``docstruct.text.unicode_repair``).

The reference case is ``velocidade-instantanea.pdf`` (TeX/dvips, no
``/ToUnicode``): extraction returns NFD and ``ı`` + a combining mark. The
spacing-diacritic rules are off by default and only run with font evidence;
the negative tests pin that contract.
"""
from __future__ import annotations

from docstruct.text.unicode_repair import (
    UnicodeRepairContext,
    detect_legacy_unicode,
    repair_legacy_unicode,
)

CALCULO = "C\u00e1lculo"
BRASILIA = "Bras\u00edlia"
DIFICIL = "dif\u00edcil"
MATEMATICA = "Matem\u00e1tica"
FUNCAO = "fun\u00e7\u00e3o"
NAO = "n\u00e3o"

NFD_CALCULO = "Ca\u0301lculo"
NFD_BRASILIA = "Bras\u0131\u0301lia"
NFD_DIFICIL = "dif\u0131\u0301cil"
NFD_MATEMATICA = "Matema\u0301tica"
SPACING_CALCULO = "C\u00b4 alculo"
SPACING_NAO = "n\u02dc ao"
SPACING_FUNCAO = "fun\u00b8 c\u02dc ao"


def _decision(text: str, **context):
    return repair_legacy_unicode(text, context=UnicodeRepairContext(**context))


class TestCombiningAndDotless:
    def test_nfc_composes_a_decomposed_word(self):
        decision = _decision(NFD_MATEMATICA)
        assert decision.repaired == MATEMATICA
        assert [edit.rule for edit in decision.edits] == ["nfc"]
        assert decision.needs_review is False

    def test_calculo_in_nfd(self):
        assert _decision(NFD_CALCULO).repaired == CALCULO

    def test_dotless_i_before_the_accent(self):
        decision = _decision(NFD_BRASILIA)
        assert decision.repaired == BRASILIA
        assert [edit.rule for edit in decision.edits] == ["dotless-base"]

    def test_dificil(self):
        assert _decision(NFD_DIFICIL).repaired == DIFICIL

    def test_cedilla_and_tilde_in_nfd(self):
        assert _decision("func\u0327a\u0303o").repaired == FUNCAO

    def test_offsets_point_at_the_original_text(self):
        decision = _decision(f"Universidade de {NFD_BRASILIA}, {NFD_CALCULO}")
        assert decision.edits
        for edit in decision.edits:
            assert decision.original[edit.start : edit.end] == edit.before
        rebuilt: list[str] = []
        cursor = 0
        for edit in decision.edits:
            rebuilt.append(decision.original[cursor : edit.start])
            rebuilt.append(edit.after)
            cursor = edit.end
        rebuilt.append(decision.original[cursor:])
        assert "".join(rebuilt) == decision.repaired

    def test_idempotent(self):
        once = _decision(f"{NFD_BRASILIA} e {NFD_MATEMATICA}").repaired
        twice = _decision(once)
        assert twice.repaired == once
        assert twice.edits == ()

    def test_empty_text(self):
        decision = _decision("")
        assert decision.repaired == ""
        assert decision.skipped_reason == "empty-text"


class TestSpacingDiacritics:
    def test_off_by_default(self):
        decision = _decision(SPACING_CALCULO)
        assert decision.repaired == SPACING_CALCULO
        assert decision.edits == ()
        assert decision.needs_review is True
        assert decision.skipped_reason == "no-applicable-rule"

    def test_explicit_enablement_is_the_evidence(self):
        decision = _decision(SPACING_NAO, allow_spacing_diacritics=True)
        assert decision.repaired == NAO

    def test_enabled_by_the_caller(self):
        decision = _decision(SPACING_CALCULO, allow_spacing_diacritics=True)
        assert decision.repaired == CALCULO
        assert [edit.rule for edit in decision.edits] == ["spacing-diacritic"]

    def test_spaced_function_and_negation(self):
        decision = _decision(
            f"{SPACING_NAO} e {SPACING_FUNCAO}",
            allow_spacing_diacritics=True,
        )
        assert decision.repaired == f"{NAO} e {FUNCAO}"

    def test_word_internal_dotless_base(self):
        decision = _decision(
            "Bras\u00b4 \u0131lia",
            allow_spacing_diacritics=True,
        )
        assert decision.repaired == BRASILIA
        assert decision.needs_review is False

    def test_standalone_accent_is_not_repaired(self):
        text = "o sinal \u00b4 e usado"
        decision = _decision(text, allow_spacing_diacritics=True)
        assert decision.repaired == text
        assert decision.needs_review is True

    def test_standalone_accent_with_document_evidence(self):
        text = "o sinal \u00b4 e usado"
        decision = _decision(
            text,
            allow_spacing_diacritics=True,
            allow_standalone_spacing_diacritics=True,
        )
        assert decision.repaired == "o sinal \u00e9 usado"
        assert decision.needs_review is False

    def test_backtick_is_never_an_accent(self):
        text = "use `a` como variavel"
        assert _decision(text, allow_spacing_diacritics=True).repaired == text

    def test_base_with_a_following_combining_mark_is_left_untouched(self):
        text = "C\u00b4 a\u0301lculo"
        decision = _decision(text, allow_spacing_diacritics=True)
        assert decision.repaired == text
        assert decision.edits == ()
        assert decision.needs_review is True


class TestProtectedContent:
    def test_formula_is_not_touched(self):
        decision = _decision(NFD_MATEMATICA, block_type="math")
        assert decision.repaired == NFD_MATEMATICA
        assert decision.skipped_reason == "block-type:math"

    def test_code_is_not_touched(self):
        decision = _decision(NFD_BRASILIA, block_type="code")
        assert decision.repaired == NFD_BRASILIA

    def test_url_is_protected(self):
        text = "https://example.test/br" + NFD_BRASILIA
        assert _decision(text).repaired == text

    def test_inline_code_is_protected(self):
        text = "`" + NFD_BRASILIA + "`"
        decision = _decision(text)
        assert decision.repaired == text
        assert decision.needs_review is False

    def test_protected_spans_do_not_count_as_signal(self):
        assert detect_legacy_unicode("`C\u00b4 alculo`").spacing_diacritics == 0
        assert detect_legacy_unicode("https://x.test/C\u00b4 alculo").spacing_diacritics == 0


class TestLanguageAndSafety:
    def test_turkish_keeps_dotless_i(self):
        decision = _decision("\u0131\u0301", language="tr-TR")
        assert decision.repaired == "\u0131\u0301"
        assert decision.needs_review is True

    def test_non_composing_mark_keeps_the_letter(self):
        text = "\u0131\u0338"
        decision = _decision(text, language="pt-BR")
        assert decision.repaired == text
        assert decision.needs_review is True

    def test_detection_counts_every_signal(self):
        detection = detect_legacy_unicode(
            f"{NFD_BRASILIA} {NFD_CALCULO} {SPACING_NAO} \ufffd"
        )
        assert detection.combining_runs == 2
        assert detection.combining_marks == 2
        assert detection.dotless == 1
        assert detection.spacing_diacritics == 1
        assert detection.spacing_word_internal == 1
        assert detection.replacement_characters == 1
        assert detection.has_signal is True

    def test_detection_without_signals(self):
        detection = detect_legacy_unicode("Clean text with correct accents.")
        assert detection.has_signal is False

    def test_isolated_combining_mark_is_reported(self):
        detection = detect_legacy_unicode("\u0338")
        assert detection.combining_marks == 1
        assert detection.has_signal is True



class TestLegacyTexArtifacts:
    """The crase and split-ligature rules, enabled only with document evidence."""

    ON = UnicodeRepairContext(
        allow_spacing_diacritics=True,
        allow_standalone_spacing_diacritics=True,
        allow_legacy_tex_artifacts=True,
    )

    def repaired(self, text, context=None):
        return repair_legacy_unicode(text, context=context or self.ON).repaired

    def test_crase_is_composed(self):
        assert self.repaired("precisa ` a medida") == "precisa à medida"
        assert self.repaired("`A medida que") == "À medida que"
        assert self.repaired("precisa ‘ a medida") == "precisa à medida"

    def test_split_ligature_is_joined(self):
        assert self.repaired("quando h fi ca perto") == "quando h fica perto"
        assert self.repaired("to defi ne it") == "to define it"
        assert self.repaired("o fl uxo") == "o fluxo"

    def test_rules_record_their_edits(self):
        decision = repair_legacy_unicode("` a e fi ca", context=self.ON)
        assert {edit.rule for edit in decision.edits} == {"grave-crase", "split-ligature"}

    def test_off_without_document_evidence(self):
        context = UnicodeRepairContext(
            allow_spacing_diacritics=True, allow_standalone_spacing_diacritics=True
        )
        assert self.repaired("precisa ` a medida", context) == "precisa ` a medida"
        assert self.repaired("quando h fi ca perto", context) == "quando h fi ca perto"

    def test_code_quotes_and_hyphenated_words_are_kept(self):
        for text in ("casa `a` x", "a letra ‘a’ e", "som hi-fi sound", "Wi-Fi network",
                     "a fi Nal", "use `code` aqui"):
            assert self.repaired(text) == text, text

    def test_two_crases_do_not_protect_the_text_between_them(self):
        """A pair of crase backticks is not an inline-code span."""
        text = "` a medida e ` a esquerda, m´ edia"
        assert self.repaired(text) == "à medida e à esquerda, média"

    def test_idempotent(self):
        once = self.repaired("precisa ` a medida e fi ca")
        assert self.repaired(once) == once
