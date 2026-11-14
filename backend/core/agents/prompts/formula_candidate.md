Inspect this region before mathematical recognition. Its extractor label may be wrong.

- For a genuine mathematical expression, return kind="formula" and its visible LaTeX.
  This transcription is evidence for classification; the mathematical recognizer
  will still handle the expression separately.
- For a drawing, including a molecular structure, return kind="description"
  and an accessible description of only what is visible. Do not invent names,
  molecular formulas, atoms, or bonds that cannot be read.
- Written chemical formulas or reactions belong in the description, preserving
  printed subscripts and charges; they are not mathematical formulas.
- Preserve the language of the region when possible.
- If the region cannot be classified or described reliably, return
  kind="description", classification_uncertain=true, a short statement of that uncertainty in
  description and explain the uncertainty in warnings. Do not guess content.
- Otherwise set classification_uncertain=false.
