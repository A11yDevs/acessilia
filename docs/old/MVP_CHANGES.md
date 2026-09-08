# Informational-Structural Agent — PMV 1.0.0

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](MVP_CHANGES.pt-br.md)

This package derives from
[`jhonata192/a11y-devs-describer`](https://github.com/jhonata192/a11y-devs-describer/)
at commit `f22e9ce02ed5f11fe3c6e6be10ceacb4157c2321`. The original project
declares the MIT license in its `README.md`.

## PMV Changes

- single, reusable Docling conversion per document;
- `InformationalStructuralAgent`;
- normalization of pages, elements, hierarchy, reading order,
  coordinates, and provenance;
- deterministic generation of candidate observations and obligations;
- executable `ProcessingManifest` model in Pydantic 2;
- JSON Schema Draft 2020-12 generated from the model;
- structural and semantic validation before writing;
- CLI `a11y-manifest`;
- unit tests and architecture documentation.

## Validation performed

- 53 repository tests passing;
- JSON Schema valid in Draft 2020-12;
- end-to-end trial with Docling 2.115.0 on an 8-page PDF;
- trial result: 145 elements, 139 elements with provenance boxes,
  144 resolved hierarchical links, and 5 candidate obligations;
- resulting manifest validated without errors by Pydantic and by the
  JSON Schema file.

The PDF used in the trial and the derived manifest are not included in the package.
