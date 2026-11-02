# 0009. Legacy PDF Unicode repair is a pure docstruct stage orchestrated by the core

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](0009-legacy-unicode-repair.pt-br.md)

- **Status:** Accepted
- **Date:** 2026-10-23
- **Components:** docstruct, core
- **Issues:** —
- **Amended by:** [ADR-0010](0010-word-internal-spacing-diacritics.md) for the spacing-diacritic scope and the `source_font_risk` premise.

## Context

PDFs built by old TeX/dvips toolchains may ship without a reliable
`/ToUnicode` map. Extractors then infer text from the font encoding, and the
result is frequently NFD (`C` + U+0301) or uses `ı` (U+0131, dotless i) before
the combining mark. `NFC` composes the first form but not the second.

The reference sample (`velocidade-instantanea.pdf`, five pages, `dvips + MiKTeX
GPL Ghostscript 9.05`) has **211 combining marks** and **8 occurrences of `ı` +
U+0301** in its text layer, and no spacing diacritics. `pdftotext -layout`
returns the city name (the dotless i followed by U+0301), the word for
"difficult" with the same pattern, and the words for "calculation" and
"function" decomposed. The PDF/UA
generated from that input later shows spacing forms such as `C´ alculo` and
`fun¸ c˜ ao`; those are a symptom of the corrupted input reaching the renderer,
not the shape the extractor returns.

There are three places to repair this: inside the Toolbox extractor (loses
policy and provenance), in the renderer (too late for HTML, DOCX and speech),
or in the core's canonical stage. The core already owns deterministic text
policy through `docstruct.text.norm_fix` and the v2.3 obligations, so the same
split applies here.

## Decision

- **The pure function lives in docstruct.** `docstruct.text.unicode_repair`
  exposes `detect_legacy_unicode` and `repair_legacy_unicode`, uses only the
  standard library and returns the rule plus the original span of every edit.
  Ligatures, NBSP and hyphenation stay in `norm_fix`: one owner per
  transformation (ADR-0004).
- **The core decides when to run it.** The manifest emits the obligation
  `repair-legacy-unicode`, satisfied by the deterministic method
  `unicode-repair`. `LEGACY_UNICODE_REPAIR` selects the mode: `off` (default,
  no observation and no obligation), `detect` (observation and a technical
  warning, no rewrite) or `repair`.
- **Only prose-like blocks are eligible.** `paragraph`, `heading`, `title`,
  `list_item`, `caption` and `footnote` may be rewritten; `formula`, `code`,
  `table` and `picture` never are. Inline code, URLs and `$...$` spans are
  protected.
- **Phase B repairs only what is unambiguous.** It composes combining runs
  (NFC) and rewrites `ı`/`ȷ` + mark when the language does not use dotless i
  and the sequence actually composes. Spacing diacritics (`C´ alculo`) are
  detected but not rewritten until font/geometry evidence exists.
- **Ambiguity is reported, not guessed.** The decision carries
  `confidence=None` until calibration and sets `needs_review` when a known
  signal is left unrepaired; the handler records the rules and counts in
  `element.metadata["unicode_repair"]`.

## Consequences

- **Default behavior is unchanged.** Enabling the repair is a configuration
  change; the mode enters the processing cache key, and changing the domain
  description invalidates old entries as usual.
- **Precision over recall.** A word left in NFD is a known degradation; a
  genuine accent or a code span rewritten by mistake would be worse. The
  spacing-diacritic rule therefore stays off until the Toolbox can report
  `source_font_risk`.
- **Follow-up work.** Toolbox preflight (`/ToUnicode`, fonts) to fill
  `source_font_risk`; geometric and provider-divergence repair for spacing
  diacritics; an export gate comparing the canonical text with the
  re-extracted PDF/UA.
- **Compliance.** `libs/docstruct/tests/test_unicode_repair.py` covers the
  rules, the negative cases (formula, code, URL, Turkish, non-composing marks)
  and idempotency; `tests/test_legacy_unicode_repair.py` covers manifest
  emission, the handler and the non-critical contract.
