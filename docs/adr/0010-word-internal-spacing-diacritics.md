# 0010. Word-internal spacing diacritics are repaired; standalone ones require document evidence

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](0010-word-internal-spacing-diacritics.pt-br.md)

- **Status:** Accepted
- **Date:** 2026-10-24
- **Components:** docstruct, core
- **Issues:** #244
- **Amends:** the phase-B scope of [ADR-0009](0009-legacy-unicode-repair.md): spacing diacritics are no longer report-only.

## Context

[ADR-0009](0009-legacy-unicode-repair.md) shipped phase B with NFC and
dotless-i repair, and left spacing diacritics (`C´ alculo`) detected but not
rewritten. The assumption was that the extraction of a legacy TeX PDF returns
NFD and dotless i, and that spacing forms only appeared in the rendered output.

The actual pipeline extraction disagrees. `document.structure.extract` with the
Docling provider on the reference sample returns **206 spacing diacritics** and
only 6 combining marks:

```text
Universidade de Bras´ ılia
Departamento de Matem´ atica
C´ alculo 1
n˜ ao ´ e dif´ ıcil notar que a fun¸ c˜ ao ...
```

Phase B skipped every element whose only signal was a spacing diacritic, so the
canonical text reached the renderer unchanged and the exported PDF/UA kept the
defect.

The renderer is not the cause. Exporting an NFC AST through the same
`document.export.pdf_ua` capability returns a text layer with the correct
precomposed characters. The defect is upstream, in the text the core receives.

## Decision

- **Spacing repair is part of `repair` mode.** When `LEGACY_UNICODE_REPAIR=repair`,
  the core enables spacing repair for prose-like blocks (`paragraph`, `heading`,
  `title`, `list_item`, `caption`, `footnote`).
- **Two tiers, based on where the accent appears.**
  - *Word-internal*: the accent is glued to the preceding letter (`C´ alculo`,
    `Bras´ ılia`). This is the shape a legacy TeX extraction produces; it is
    repaired whenever the block is eligible.
  - *Standalone*: the accent is separated from the preceding word (`... posi¸ c˜ ao ´ e ...`,
    including the verb). The same shape appears in prose that discusses an
    accent, so it is only repaired when the document has at least
    `5` word-internal occurrences, which supplies document-level evidence.
- **`ı` and `ȷ` are valid bases.** A spacing acute over the dotless i
  (`Bras´ ılia`) composes to the precomposed acute i; the same applies to the
  circumflex.
- **Nothing else changes.** Formulas, code, tables, pictures, inline code,
  URLs and `$...$` spans are never rewritten. The decision records
  `needs_review=True` when spacing was involved, so the audit keeps the
  ambiguity visible.
- **The core owns the policy.** The docstruct API exposes
  `allow_spacing_diacritics` and `allow_standalone_spacing_diacritics`; only the
  core decides when the document evidence is sufficient.

## Consequences

- **The reference sample is repaired end to end.** In the extraction above,
  all 206 spacing diacritics are rewritten across 36 of the 53 eligible
  elements; the known words from the sample come out correct.
- **Accent-heavy prose is protected.** A text about accents that has no
  word-internal legacy shape keeps its standalone examples untouched, because
  the document-level threshold is not met.
- **The opt-in and the audit remain.** `off` and `detect` keep their previous
  behavior; `repair` still marks spacing edits for review.
- **Phase D is still needed.** A clean canonical text does not prove the
  exported PDF/UA is clean; comparing the canonical text with the re-extracted
  output remains the next gate.
- **Compliance.** `libs/docstruct/tests/test_unicode_repair.py` covers the two
  tiers, the dotless base and the protected spans;
  `tests/test_legacy_unicode_repair.py` covers the handler, the document
  threshold and the standalone behavior.
