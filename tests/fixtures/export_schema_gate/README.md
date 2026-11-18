# Strict export-gate compatibility corpus

Brazilian Portuguese: [português brasileiro](README.pt-br.md).

`compatibility.json` captures the pre-gate behavior at `9845d84d` (merged #576).
A shared synthetic document plus explicit path/value/removal operations defines
17 inputs. `baseline_by_format` records all 68 TXT/HTML/DOCX/PDF/UA outcomes;
`baseline_text` retains exact TXT bytes as UTF-8 text. DOCX/PDF/UA renderers were
mocked, so the capture used no providers. `baseline_commit` identifies the code;
`normalized_schema_valid` checks the existing sanitized document against the
unchanged packaged schema. Input JSON is synthetic, without real document data.

| Before Core 0.2.0 | After Core 0.2.0 | Cases |
|---|---|---|
| Exported | Exported | Valid nested document, metadata extension, numeric table cells converted by the existing sanitizer |
| Exported | Schema rejection | Custom root/child/filtered blocks; missing block/section IDs; invalid block/document verbosity, audience, document-ID type, empty title, language, child level |
| Audit rejection | Audit rejection | Duplicate block IDs, empty section list |

The captured schema path/keyword and `strict_outcome` are the reviewed
compatibility decision, not regenerated expectations. Tests materialize each
input from `base_document` and `changes` and exercise the production gate in
all four formats through direct calls to the Core exporter. These rejected
calls may not build an AST, call a renderer, create a destination directory or
overwrite an existing artifact; inputs stay unchanged. The normalization
classification is checked against the packaged schema too.

The service worker has a separate directory lifecycle: it creates the job
output directory before invoking the exporter. `tests/test_api.py` observes
creation, export entry, schema rejection and directory removal in order, and
checks error/history and no download registration. Cleanup is a post-failure
guarantee, not a claim that the worker never created the directory.

```bash
make test-file F=tests/test_export_schema_gate.py
```

Review intentional acceptance changes as a behavior change. Keep the separate
E1.0 pure-serializer fixtures/goldens unchanged: docstruct retains its fallback.
The optional six-document dataset is absent; no provider or dataset result is
claimed and no skipped test is added. See
[ADR 0026](../../../docs/adr/0026-strict-canonical-export-gate.md).
