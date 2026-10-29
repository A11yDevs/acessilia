# Formula candidate classification

[Brazilian Portuguese](formula-classification.pt-br.md)

## Problem and symptoms

An extractor's `formula` label is not proof that a region contains mathematics.
A molecular drawing sent to `math.recognize` can produce plausible but incorrect
LaTeX. Successful mathematical OCR alone cannot detect the wrong input type.

## Processing policy

Before picture enrichment and mathematical recognition, the Core inspects
renderable formula regions that do not already contain LaTeX markup. It uses
the existing vision provider, a dedicated candidate prompt, and the shared
chemistry instructions. The mathematical transcription prompt shared with the
data agent remains unchanged.

- **Mathematics:** keep the formula and use `math.recognize` as before. The
  classifier's LaTeX does not replace the mathematical recognizer's result.
- **Non-mathematical content:** change the element to `picture`, retain its
  location, original type, label and text, and reuse the accessible description.
  Reconcile its processing obligations with
  `reconcile_reclassified_element_processing_needs`. The picture-enrichment pass
  skips this completed description, avoiding another visual request.
- **Unresolved:** retain the source content and region, record classification
  metadata, skip mathematical recognition, and restrict the formula obligation
  to `human-review`. This is an explicit escalation and may prevent automatic
  job completion; it does not certify the region as mathematics.

The classifier explicitly signals uncertainty with `classification_uncertain`.
Model-reported confidence remains metadata, not a calibrated acceptance gate.
Missing crops, failed visual requests and an open provider breaker also leave
the classification unresolved. A usable description returned by the existing
mathematical vision fallback likewise reclassifies the region as a picture.

## Operational cost and limits

Every candidate adds a visual inspection before mathematical OCR. Concurrency,
provider failure handling and prompt-sensitive caching use existing vision
infrastructure. The classification and subsequent recognition may request the
same crop separately. No chemical recognition model or chemistry capability is
installed, and no molecular identity is inferred from a drawing.

Formula regions already carrying LaTeX and non-renderable source types keep
their existing paths. This protection does not correct an extractor that has
already converted a molecule to LaTeX before the Core receives it.

Regression tests exercise controlled classifications and the real Core
reconciliation and export-block transformations. A forced `formula` label on a
chemical crop is a controlled test, not evidence that a particular extraction
provider emitted that label. Real-document validation must record the source
page and region, extraction and recognition providers, their outputs and the
exported result (see [issue #290](https://github.com/A11yDevs/acessilia/issues/290)).
