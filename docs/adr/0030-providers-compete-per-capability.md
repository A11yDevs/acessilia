# 0030. Providers compete per capability; the structure suites stay structural

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](0030-providers-compete-per-capability.pt-br.md)

- **Status:** Proposed
- **Date:** 2026-11-23
- **Components:** core, SDK, Toolbox
- **Issues:** [#640](https://github.com/A11yDevs/acessilia/issues/640), [#818](https://github.com/A11yDevs/acessilia/issues/818), [#324](https://github.com/A11yDevs/acessilia/issues/324), [acessilia-toolbox#169](https://github.com/A11yDevs/acessilia-toolbox/issues/169)
- **Builds on:** [ADR-0027](0027-mcp-core-toolbox-contract.md), [ADR-0028](0028-operational-execution-in-the-toolbox.md), [ADR-0029](0029-symbolic-core-every-step-planned.md)

## Context

The bootstrap extracts a document's structure with Docling (the primary
provider) and, in `FUSION_MODE=dual`, MinerU. Both are suites: besides layout
detection, the reading order, OCR and table structure, they can recognize
formulas, describe and classify pictures, and enrich code.

The extraction was configured on purpose so that the suites focus on
structure. The Toolbox registry sets only Docling's `table_mode: accurate`,
which leaves Docling's formula enrichment, picture description and
classification, and code enrichment at their defaults, which are off. More
specialized providers do that work:
- formula LaTeX: `math.recognize`, with PP-FormulaNet;
- picture descriptions: the vision model;
- MathML and spoken math: `math.convert` and `math.verbalize`, with
  `math-speech`.

The core's enrichment steps run only where the extraction left something
missing or doubtful (`docs/architecture/workflow-actions.md`).

Three facts do not match that intent yet:
- **MinerU recognizes formulas inside the structure capability.** The
  Toolbox's MinerU 2.1 adapter sends `formula_enable=true` by default. In dual
  mode, a formula that arrives with LaTeX passes the core's gate and skips
  PP-FormulaNet.
- **The options are invisible to the core.** The core sends
  `document.structure.extract` only the language and the cache flag. The
  options that keep the suites structural live in the Toolbox's registry and
  the providers' defaults, and the manifest does not record them.
- **The provider is fixed per deployment.** `CoreConfig.toolbox.providers`
  holds one provider per key, with defaults in the SDK registry. The Toolbox,
  however, already registers competing providers:
  - `document.structure.extract`: docling, mineru, nougat;
  - `math.recognize`: pp-formulanet, docling-math, rapid-latex-ocr;
  - `document.ocr`: docling-ocr, mineru-ocr;
  - `document.layout.analyze`: docling-layout, mineru-layout;
  - `audio.synthesize` and `music.omr` have two providers each.

  Some of these providers are the suites' other abilities, exposed as their
  own capability: `docling-math`, `docling-ocr`, `mineru-ocr`.

## Decision

### The structure suites stay structural

- In `document.structure.extract`, a suite must deliver structure:
  - layout detection, with labels and boxes;
  - the reading order;
  - the OCR the text needs;
  - the table structure.

  Its options that produce other content stay off there: formula
  recognition, picture description and classification, and code enrichment.
- A suite's other abilities are used **per capability**: the suite becomes a
  provider of that capability (as `docling-math` is for `math.recognize`),
  never an extra bundled into the structure extraction.
- The pipeline options the core relies on are explicit and recorded. The
  extraction reports the options it actually ran with, and the manifest keeps
  them as provenance.

### Providers compete per capability

- Every capability may have several providers. They compete.
- The provider that performs best for a capability is **kept on merit**. A
  change of default provider needs evidence for that capability: the
  benchmark (`acessilia-benchmark`, drbench) or the measured quality, not
  convenience.
- A provider is not kept for one capability because of its results in
  another.

### Later: chosen by context and history

- The target is to choose each capability's provider per context (media type,
  language, script, document kind) and from the history of successful and
  failed executions. Investigating it is #818 (0.4.0).
- Until then, the choice stays the deployment's configuration
  (`CoreConfig.toolbox.providers`), and every run records the provider it
  used.

## Consequences

- **acessilia-toolbox#169:** turn MinerU's formula recognition off in
  `document.structure.extract`, document what MinerU 4's `--tier basic`
  enables, and report the effective options in the extraction's
  `configuration`.
- **The core gates stay meaningful.** With the suites structural, a formula
  with LaTeX or a table with structure in the extraction means the suite
  delivered structure, not a recognition that bypassed the specialized
  provider.
- **#818 (0.4.0):** selection by merit, context and history. Domain 2.4
  already models providers as objects (`(requires m c p)`, `(offered c p)`),
  so the plan can later choose among the offered providers of a capability,
  with costs from history. That is a domain change.
- **Tradeoff:** a suite's built-in recognition can be cheaper than calling
  another provider. When it is good enough, it should compete as a provider of
  that capability, not be switched on inside the structure extraction.
- **Compliance:** the Toolbox's registry and the extraction's reported options
  show the suites' configuration; benchmark evidence accompanies a change of
  default provider.
