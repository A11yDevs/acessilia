# Benchmark evaluation contracts

The math and presentation scorecards consume Dataset references through
`references/manifest.csv` (contract `1.2.0`). A valid new manifest takes
precedence over the old `input/*-reference/` case folders. The `references/`
directory or the `input_path` column in `input/manifest.csv` declares the new
layout. Its manifest and required references must be present and valid. Public readers
still accept `--dataset`, `ACESSILIA_TEST_DATASET_DIR`, and exported local trees
without `.git`.

CI and pinned E2E checks use the revision in
[`scripts/bench/dataset.lock.json`](../scripts/bench/dataset.lock.json). The
effective revision, references digest, task availability, coverage scope,
selected criteria, and protocol are recorded in scorecards and per-run
metadata. A pinned exported tree without `.git` is validated against the lock
digest and records the locked source revision. Unpinned local trees without
Git metadata are identified by their reference digest.

When one task has more than one manifest row, scorecards preserve each
reference record's type, selector, provenance, coverage scope and count. They
do not overwrite one row with another or combine counts that describe separate
references.

## Reference-to-evaluator coverage

Counts below describe the declared reference, not an exhaustive inventory of
all possible document elements. The scorecard records the criteria it actually
ran and the reasons it left other criteria unevaluated.

| Input/task | Reference and declared coverage | Evaluator criterion | Artifact | Unit and denominator |
|---|---|---|---|---|
| `036` `math_formula_transcription` | Complete, 91 of 91 formula records | Display match, inline-as-math, table header/cell checks | Canonical JSON; rows filtered by `manifest_id=036` | 91 records total: 16 display, 68 inline, 6 table-header, 1 table-cell |
| `036` `math_text_quality` | Partial, 14 rules; eligible total unknown | Required/forbidden text patterns | TXT and, when provided, PDF/UA text | 14 annotated rules per output mode; each check ID is reported |
| `036` `math_document_structure` | Partial, 14 declared rules; eligible total unknown | Headings, page numbers, lists, table dimensions, equation numbers | Canonical JSON; page/object-linked expectations | Executed rule count only; image/callout/page-header checks are marked unsupported by this scorecard |
| `036` `math_formula_speech` | Partial, 8 lexical rules for 16 eligible display formulas | Accepted word marker for each listed formula | Canonical formula `alt_text` | 8 lexical checks; `8/16` is reference coverage, not a speech-quality score |
| `006` `presentation_slide_content` | Partial, 237 assertions; eligible total unknown | Text, image/chemical-description terms, table rows, formulas | TXT or text extracted from PDF/UA | Supported selected assertions; 12 `table` shape rows are not evaluated by this text-only reader |
| `006` `presentation_output_safety` | Partial, 9 patterns; eligible total unknown | Forbidden-output pattern per selected slide | TXT or text extracted from PDF/UA | 9 patterns × selected slides, with one criterion ID per pattern and slide |
| `006` `presentation_structure` | Partial, 14 expectation checks plus 12 shared CSV table-shape assertions | Slide count, deck title, selected slide titles; table shapes are explicitly unsupported by the text-only reader | TXT or text extracted from PDF/UA | The 14 expectation checks and 12 table-shape references retain separate selectors and counts; slide count and deck title are unevaluated for partial page/object scope |
| `006` `presentation_degraded_run_behavior` | Partial, 2 declared rules | Preserve selected text assertions and disable caching after degradation | Run behavior/cache state | Not evaluated by the text scorecard; reported as an orchestration-level limitation |

The `036` scorecard reports speech presence separately: it counts non-empty
spoken forms across the selected display formulas (16 in the full case). The
eight lexical checks are a selected subset and do not establish complete or
correct verbalization. A speech-only selection still reports presence for its
selected display-formula dependencies; the lexical-check denominator remains
separate.

Reference availability, evaluator support, output artifacts, and execution
are separate states. A task marked `unannotated` is not scored. Invalid
manifest/schema data is an error; an unsupported criterion or out-of-scope
expectation appears in `not_evaluated`; a missing output is `missing_artifact`;
and a failed processing run is `execution_failure`. These states must not be
collapsed into an ambiguous `0/0`.

## Partial selection and comparison gates

Page, object, and task selection applies to the ground-truth selectors and
their expectation dependencies. A formula speech check is selected with its
formula ID/page. Table shape assertions and slide titles are selected with the
related page or table row. Document-wide expectations without a page/object
link are left out of partial runs and reported as unevaluated. A selected,
supported criterion missing from the output remains a failed check; a broken
reference selector, missing required task, or unknown criterion ID is an
error. Selected unsupported criteria remain in the criterion-ID scope and
carry an explicit `not_evaluated` reason.

`slide_case.compare()` produces a regression verdict only when both scorecards
have the same selected scope, criterion IDs, Dataset input/revision/reference
digest, task coverage, protocol, and output mode. Scorecards created directly
from rows and expectations derive a digest from those reference contents.
If the scope has zero evaluated criteria, the comparison reports insufficient
evidence and the CLI exits with code 2.
TXT versus PDF/UA comparison
requires the explicit `pdftotext-layout-raw-v1` extraction method.
Protocol `presentation-reference-v3` preserves the degraded-image threshold
in partial evaluations and reports regressions by criterion ID even when the
slide total stays equal.

The Dr.DocBench `report.compare_runs()` applies the same identity gate using the
selected page IDs, verified source-image identities, reference-content digest,
protocol, and Markdown output mode. Its acceptance gate checks CDM alongside
text, reading order, and TEDS.
Protocol `drdocbench-markdown-v2` determines CDM and TEDS eligibility from
the reference. Missing expected formulas and tables score zero, including when
a page prediction is entirely absent. Both runs must cover the same pages
for each metric. Rescore v1 runs before comparison.
A single score run also rejects pages whose Dataset identifiers or
revisions differ, so one revision cannot be hidden behind the first page's
metadata. Rescore reports created before the input digest was added. If the
extraction predates input tracking, rerun extraction before scoring for the gate.

## Historical pipeline comparator

`scripts/compare_pipelines.py` remains protocol `historical-heuristic-v1` over
canonical schema `1.0.0`. Its verdict is a heuristic, not a structural or
content-fidelity proof:

- `_extract_formulas()` recognizes blocks typed `formula`, not canonical
  `math` blocks.
- `_extract_text()` reads table `rows` but not cells in `table_ast`.
- Text similarity uses token sets, and structural comparison uses block-count
  tolerances; neither proves full content or structural equivalence.

The five historical canonicals and the hashes of their corresponding Dataset
inputs are recorded in `tests/fixtures/pipeline-comparison/manifest.json`.
The canonicals were copied byte for byte. The inputs are read from the Dataset
checkout. Any change to this comparator's protocol needs a separate version
and regression tests.

## Run artifacts and retention

Each evaluation writes its snapshots, configuration, scorecard, effective
Dataset identity, selected criterion IDs, protocol, Core revision, and runtime
version together in its run directory under `var/bench/` (or the explicit
`--out` path). The metadata includes input/output hashes and safe provider/model
selectors where applicable; credentials and service URLs are not recorded.
Artifacts stay outside observability and are not uploaded by these readers. Retention is
operator-managed with no automatic pruning; remove a run only under the data
owner's retention policy. Snapshots can contain source documents and model
responses.

Dr.DocBench runs bind each page prediction to its Dataset identifier/revision,
document/page identity and source-image SHA-256 in `inputs.json` and the page's
extraction metadata. Resume checks these identities before changing the run;
scoring checks them again, so using a different root cannot relabel old
predictions as a new Dataset revision. Moving an identical local tree is valid.
Runs created before this binding remain scoreable, with
`prediction_inputs_verified=false`. The comparison gate and resume require
verified inputs. A new input or Dataset revision requires a new run name.
