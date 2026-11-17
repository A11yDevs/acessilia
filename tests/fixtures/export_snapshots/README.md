# Export characterization baseline (E1.0 of #371)

[Brazilian Portuguese](README.pt-br.md).

These are the outputs of the **unchanged** docstruct 0.5.0 exporters at Core
commit `027b87f13bf061603d94b736a90ac62bd89b458e`. `manifest.json` records that
baseline and the 30 calls. Four synthetic inputs produce 39 golden files.
No provider, network, model, generated identifier or timestamp is needed to render
them. Tests load each input afresh and check it for mutation after each call.

| Input | Characterized behavior |
|---|---|
| `blocks` | All eleven schema block types, ordered/unordered lists, table scopes and row/column spans, math with/without speech, equation numbers, image descriptions, escaping, and basic/detailed/technical blocks in parent and child sections |
| `sections` | Legacy headings stored as `text` or `title`, distinct alias ids, repeated title after a paragraph, mismatched heading level, nested/untitled children, and custom TXT formula labels |
| `unknown` | Unknown block types accepted through each existing fallback, including the current profile filtering |
| `empty` | Empty section lists and exact empty-output/newline behavior |

Every case records TXT, HTML, Markdown and Pandoc AST for `docx` and `pdf_ua`. `blocks` additionally records every current TXT/HTML
profile (`txt`, `html`, `pdf`, `pdf_ua`, `docx`) and an unrecognized profile's
existing fallback. Labels are explicit English inputs to the APIs.

## What must remain identical through E1.7

- TXT's joined lines, HTML and Markdown are compared as exact UTF-8 bytes:
  no trimming, whitespace or content normalization. TXT also records the line
  array so changes to its public line boundaries cannot hide behind a join.
  The core wrapper's existing file-write/strip behavior is a separate boundary.
  Empty list markers currently end in a space; the TXT-only Git attribute
  preserves that intentional data without blank-at-eol review warnings.
- Pandoc JSON is compared structurally: object key order is immaterial, but
  array order and all text, metadata, attributes and target-specific math stay.
- Each export must leave its input unchanged. The tests also check fixture
  coverage against the eleven-value schema enum and freeze selected differences.

Markdown currently drops **every** heading equal to its section title; TXT,
HTML and Pandoc drop only the matching first legacy heading. TXT currently
loses the custom `formula_label` when descending into children. Markdown and
the direct Pandoc builder do not apply the TXT/HTML profile filters. These are
recorded behaviors, not fixes to apply when introducing the walker. The two
Pandoc targets retain their different equation-number representations.

The `custom` input deliberately fails the schema's block-type enum but exports
today. Eager strict validation would change accepted inputs; that remains the
separate E1.2b compatibility decision. Schema packaging/injection (E1.2a),
public-type deprecation (E1.3), the walker/migration (E1.6/E1.7), format catalogue
(E1.9), labels (E1.8) and verbosity changes (E1.11) are not implemented here.

## Run the parity gate

From the repository root, in its locked development environment:

```bash
uv run --locked --extra dev python -m pytest libs/docstruct/tests/test_export_characterization.py
make test-all
```

CI also runs the tests against the isolated docstruct wheel and in a test-only
container using the library's own lock and `--no-editable`. Its runtime
dependencies remain empty. Reproduce the container step with Docker available:

```bash
docker build --file tests/fixtures/export_snapshots/Dockerfile --tag acessilia-export-characterization .
docker run --rm --volume "$PWD:/workspace:ro" acessilia-export-characterization
```

The image contains only pinned Python/uv; the checkout is mounted read-only.
Its temporary environment installs docstruct and its locked development tools,
and runs Python in isolated mode. It uses no production Toolbox or renderer.

## Review a capture without replacing the baseline

The tests never generate expected output. `capture.py` requires a **new output
directory outside these fixtures**, so it cannot overwrite the committed
baseline. To verify the original capture, first create a detached checkout of
the recorded source, then use that checkout's docstruct with this PR's harness:

```bash
git worktree add --detach /tmp/acessilia-export-baseline 027b87f13bf061603d94b736a90ac62bd89b458e
PYTHONPATH=/tmp/acessilia-export-baseline/libs/docstruct/src \
  .venv/bin/python tests/fixtures/export_snapshots/capture.py --output-dir /tmp/export-capture-review
diff -r tests/fixtures/export_snapshots/expected /tmp/export-capture-review
```

Keep these files unchanged for E1.6/E1.7. A deliberate behavior change needs
its own review, compatibility decision and explicit snapshot diff, as required
by the [final issue review](https://github.com/A11yDevs/acessilia/issues/371#issuecomment-6731172790).
