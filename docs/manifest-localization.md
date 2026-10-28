# Manifest messages must follow the current request locale

## Problem

The manifest golden-file test failed on a Portuguese-language machine even
though the structural fields matched. The generated payload differed in six
text fields: the `message` and `rationale` values for tables, images and formulas.
The golden file expects English for these messages.

`OBLIGATION_BY_TYPE` called `t()` while `builder.py` was imported. Translated
strings were then stored globally. Requests using another locale continued to
receive the import-time translations, including during element reclassification.
Changing locale after import did not repair those cached strings.

## Correction

The global table now stores canonical message IDs. Both processing-need
creation and element reclassification translate those IDs when called, using
the current request locale. No manifest schema, identifiers, planner methods or
golden fixture was changed.

The characterization suite explicitly selects `en_US` and restores the previous
request locale after each test. The golden file therefore has a declared locale,
independent of shell settings. Runtime locale tests separately switch English,
Portuguese and English again without reimporting the builder, check translated
messages, and verify that the non-message manifest fields remain unchanged.
Reclassification is tested in both locales as well.

## Validation scope

The new request-switching regression failed before the correction. The combined
runtime-locale/characterization checks pass with the process started under either
`LOCALE=pt_BR` or `LOCALE=en_US` (40 checks per run). This fixes both the runtime
translation defect and the test's implicit environment assumption; it does not
merely regenerate the expected snapshot or force production to use English.

These are functional checks using synthetic fixtures, not dataset evaluation.
The correction is included in [PR #309](https://github.com/A11yDevs/acessilia/pull/309).
Complete CI evidence is linked in the
[consolidated report](extraction-resilience-fixes.md). No production deployment
was performed. The golden JSON fixtures remain unchanged.
