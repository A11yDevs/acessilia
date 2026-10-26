# 0011. Inline math is carried as `$…$` in prose and detected from the PDF's math fonts

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](0011-inline-math-from-font-runs.pt-br.md)

- **Status:** Accepted
- **Date:** 2026-10-26
- **Components:** docstruct, core, SDK, Toolbox
- **Issues:** #265

## Context

On the reference case `036` (`velocidade-instantanea.pdf`), the formulas inside sentences reach every output as spaced text. "s ( t ) = t 3" is read "t 3", and `s0 ∈ R` loses its subscript and ℝ. The scorecard of `python -m scripts.bench.math_case` gives 0% on "Inline expressions as math". Two separate gaps cause this.

**Output.** Nothing renders a formula inside prose:

- The Pandoc AST splits text into `Str` inlines (`docstruct.export.pandoc_ast._meta_inlines`).
- The HTML export escapes the text.
- The TXT export prints it as is.

No production code emits `InlineMath`. The page OCR model already writes inline math as `$…$`. That path is live today, and the `$` reach the reader literally.

**Detection.** Docling returns no inline formula region for this PDF: there is no `inline` group, and the paragraph text is flat. The PDF itself carries the signal. Variables are in `CMMI12`, `∈` in `CMSY10`, `ℝ` in `MSBM10`, and subscripts and exponents are in `CMR8`, off the baseline. Nothing reads fonts today.

Options considered for detection:

1. **Route math-heavy pages to MinerU (fusion).** The Toolbox's MinerU provider joins span contents without delimiters, so its inline math is flat too. The page router (`docstruct.fusion.adjudication.decide_v1`) does not count a single `$` either.
2. **Turn on Docling formula enrichment.** It recognizes the formula regions the layout model finds, and that model finds none inline here.
3. **Read the text spans with their fonts and geometry** and build the LaTeX from them. This works for the TeX PDFs that make up most math material, and it costs no model call.

## Decision

- **The representation is `$…$` in prose.** Inline math in a paragraph, list item or callout is written in its text as `$…$` (or `\(…\)`). The splitting rule is `docstruct.text.math_spans`: Pandoc's `tex_math_dollars`, plus an opening `$` that must not follow a letter or digit, so `R$ 10,00` stays text.
- **The canonical enrichment converts each span once.** It calls `math.convert` and `math.verbalize`, with results cached per document, and stores them in `block.metadata["inline_math"]` as `{source, latex, mathml?, speech?}` keyed by the source LaTeX. Inline speech carries no formula label (`MathEnricher.verbalize_inline`).
- **Exporters must render a span as math, never as literal delimiters:**
  - **Pandoc AST** (PDF/UA, DOCX): `InlineMath`, wrapped in the formula alt span when it has speech.
  - **HTML:** the sanitized MathML. Without MathML, the LaTeX labelled with its speech.
  - **TXT/MP3:** the speech. Without speech, the bare LaTeX.
- **Detection reads the PDF's math fonts** (option 3). Font reading is operational, so under [ADR-0003](0003-remote-only-operational-capabilities.md) it is a Toolbox capability (`document.text.spans`). Building LaTeX from the spans is a pure docstruct algorithm. The core matches each run to the element's text and splices in `$…$`. A run it cannot match leaves the text unchanged.

## Consequences

- Any producer that writes `$…$` (page OCR, MinerU, the font detector) gets math output with no extra work.
- A span `math.convert` rejects still renders as math in the Pandoc AST. The PDF/UA degrade-and-retry (`degrade_math_to_text`) covers a compilation failure, as it does for math blocks.
- Detection only covers PDFs with a math font in the text layer (TeX and most typeset math). Scanned pages go through the page OCR model, which already emits `$…$`.
- Out of scope:
  - `inline_math_promote` (a paragraph made only of math turned into display math) is still unused.
  - The fusion router's `FORMULA_RE` still ignores a single `$`.
- Compliance: `tests/test_inline_math.py` covers the splitting rule and each exporter. The detection is measured by the math reference scorecard; the target is "Inline expressions as math" ≥ 90% on case 036.
