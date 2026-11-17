# Benchmark harness

> Brazilian Portuguese version: [versão pt-BR](bench.pt-br.md)

`python -m scripts.bench` measures the structure-only harness on document
pages. It calls the Toolbox `document.structure.extract` capability, converts
that response to the benchmark's canonical document and writes Markdown. It
does not run the Core planner or executor, visual or remote math enrichment,
or final product exports. Treat its timings and scores as structure-harness measurements, not
full Core pipeline results. The scorecards for product cases 036 and 006 stay
in Core; public benchmark campaigns and their official evaluators belong in
`acessilia-benchmark`.

The existing Core Dr.DocBench downloader, submission packager and Slurm jobs
are retained as compatibility tools for local structure runs. Do not extend
them into campaign orchestration or official result ownership; the public
campaign workflow is being consolidated in `acessilia-benchmark`.

## Where things live

| Piece | Location | Dataset-specific? |
|---|---|---|
| Metrics (text edit distance, reading order, TEDS, CDM, overall) | `docstruct.evaluation.metrics` | no |
| Page scoring (pairs tables and formulas by order) | `docstruct.evaluation.markdown` | no |
| Local tune/holdout improvement gate | `docstruct.evaluation.holdout` | no |
| Canonical document → benchmark markdown | `docstruct.export.markdown` | no |
| Toolbox payload → canonical document | `scripts/bench/core.py` | no |
| Download, page layout, submission format | `scripts/bench/datasets/<name>.py` | yes |
| Public campaigns, official evaluators, campaign comparisons and Slurm workflows | `acessilia-benchmark` | yes |

The Core metrics are local approximations for tracking changes between runs.
For a number to report publicly, use the benchmark's official evaluator. The
local `scripts.bench compare` is only the Core structure harness's tune/holdout
improvement gate. It is not a parity check, public campaign comparison, or
official benchmark verdict; campaign comparisons belong in
`acessilia-benchmark`.

## Workflow

The Toolbox must be reachable. The harness configures its SDK clients itself
(`scripts/bench/toolbox.py`), from the environment or `.env`, with the core's
variable names and defaults: `TOOLBOX_BASE_URLS` (else `TOOLBOX_BASE_URL`),
`TOOLBOX_API_KEY`, `TOOLBOX_TIMEOUT_SECONDS`, `TOOLBOX_RETRIES`,
`TOOLBOX_RETRY_BACKOFF_SECONDS` and `TOOLBOX_PROVIDER`.

```bash
# 1. Materialize a split locally: var/bench/<dataset>/<split>/data
uv run python -m scripts.bench download --dataset drdocbench --split dev --limit 100

# 2. Run structure extraction and write predictions plus run-manifest.json
uv run python -m scripts.bench run --dataset drdocbench --split dev --run baseline

# 3. Score: report.json, pages.jsonl and drilldown.csv (worst pages first) in the run directory
uv run python -m scripts.bench score --dataset drdocbench --split dev --run baseline

# 4. After a change, run and score again under another name and compare
uv run python -m scripts.bench compare var/bench/drdocbench/dev/baseline var/bench/drdocbench/dev/candidate

# 5. Package a run for the benchmark (Dr.DocBench: EvalAI submission.zip)
uv run python -m scripts.bench submit --dataset drdocbench --split test --run baseline
```

`--root` points at an existing local tree instead of `var/bench/.../data`;
`run` also takes `--sample N`, `--item <id>`, `--provider` and `--save-raw`.
Each run writes `run-manifest.json` with selected input and reference hashes,
Core and package identity, effective Toolbox configuration, output hashes,
per-page status and observed durations. It never records the API key or raw
document contents in that manifest. The optional `.provider.json` payload is
content and stays with the run artifacts under `BENCH_VAR`.

Predictions and optional raw payloads can contain document content. Restrict
access to `BENCH_VAR` and apply the dataset's retention policy; this harness
does not expire or delete saved artifacts automatically. Keep `--save-raw` off
unless the raw provider response is needed.

For a materialized dataset tree that is not itself the root of a Git checkout,
pass its pinned source commit with `run --dataset-revision`. The value must be a
full 40- or 64-character commit SHA; mutable names such as `main` are rejected.
If no revision is available,
the manifest records that explicitly and `compare`
rejects an accepted verdict;
input hashes still identify the exact local bytes but do not identify their
upstream dataset release. The structure protocol records image media type and
size, declares that Core applies no crop or image transform, and marks any
Toolbox-internal transform as unobserved.

A fresh `run` replaces predictions and records the selection in `pages.txt` for
compatibility. `score` scores the selection in the run manifest, so a
`--sample` run is not scored against the whole split. `score` exits 1 when no
page has ground truth (the `test` split, for instance). `--resume` requires the
same dataset, input and reference hashes, source identity, software, hardware
and effective configuration as the saved run. It verifies output hashes before
reusing a completed page. Endpoint paths are fingerprinted without storing the
path text. If a new response contradicts the reported capability, provider or
model versions of completed pages, the page fails before writing predictions.
Old manifests without endpoint path fingerprints can be scored for diagnosis.
The gate requires those fingerprints and consistent reported provenance. A
Markdown file without a manifest remains `legacy_unverified`.

`run`, `score`, and `submit` take an exclusive lock on the run directory. `compare`
locks both run directories while checking the artifacts and writing the report.
If another process holds a required lock, the command exits with code 1.
Retry after that process exits.

The manifest reports caller-observed Toolbox-call duration, the post-call input
integrity-check duration, and page wall duration (including canonical
conversion and artifact writes). The Toolbox response does not currently expose
the waiting time, cache lookup duration, actual provider attempts/retries or
effective cache policy. When the response includes provenance, each call
records the reported provider and model versions, reported duration and cache
hit separately. On a hit, the reported duration belongs to the cached result.

Scoring computes two Levenshtein distances per page. Without `rapidfuzz`
(installed by the `dev` extra) docstruct falls back to pure Python, which takes
about 20 s for a 3,000-character page.

`report.json` records expected, executed, failed and scorable coverage for each
local metric. `compare` applies the improvement gate of
`docstruct.evaluation.holdout`:
the split is per document (1/3 held out), and a candidate is accepted only if it
gains on tune, does not lose on holdout and no metric drops beyond the
tolerance. It exits 1 when the candidate is rejected, including when one of the
subsets has no scorable pages (too small a sample) and when a metric scored in
the base has no value in the candidate (for example, it stopped emitting
tables): the metric would otherwise leave the mean and count as a gain. Values
that cannot be computed are printed as `null`.

The local evaluator v2 pairs tables and display formulas by appearance. Each
unmatched element contributes zero, including when a page omits only part of
the reference. The per-page denominator counts valid pairs plus unmatched
elements. A component absent from both sides is unscored, and local TEDS
ignores cell spans while local CDM compares bags of tokens. Rescore both runs
offline to use evaluator v2. Only structure protocol `toolbox-structure@2`
is eligible for this gate because it disables remote formula enrichment.

The comparison is written to `comparison.json` and records whether compatibility
allowed the improvement gate to run. `CDM` is diagnostic only and is not part of this
gate. A comparison is rejected when either run lacks a completed,
artifact-verified manifest, or the dataset revision, selection, references,
unit, scoring protocol or metric coverage differs. The report also lists
software, hardware and effective configuration so intentional runtime changes
remain visible. Duplicate item/page ids are rejected instead of being
overwritten.

The manifest reuses the run identity and reporting contract defined for #370.
This structure-only protocol does not call the Core processing pipeline, so it
does not apply `processing_cache_configuration()`. Any future full-pipeline
measurement must use that existing function for Core processing settings.

The current measurement boundary and proposed stage contracts are described in
[`benchmarks/regions.md`](benchmarks/regions.md); the ownership and coverage map
is in [`benchmarks/coverage-map.md`](benchmarks/coverage-map.md). Future stage
capture hooks should build on the Orchestrator modularization in #381. This
issue adds no runtime import from `scripts/bench` and does not create a second
public benchmark runner.

## Compatibility adapter and migration

`backend/tools/toolbox_client.py` is a temporary settings-based compatibility
factory retained for the pinned `acessilia-benchmark` adapter (`810c748`). It is
not a public Core API. New Core code should use
`backend.core.toolbox.toolbox_client.make_toolbox_client` and pass an explicit
`ToolboxConfig`.

Removing the bridge depends on two migrations:

- The adapter's `structure` mode should use SDK clients directly. This follows
  #402, whose acceptance requires the benchmark scripts not to import
  `backend.tools.toolbox_*`.
- The adapter's `pipeline` mode needs a stable public Core API. ADR-0016 proposes
  the separate `acessilia_core` package; this is distinct from #402's move of
  Toolbox transport into the SDK.

ADR-0018 is still Proposed and concerns the Core's own use of the SDK public
API; it does not define the public Core API needed by `pipeline` mode. Until the
adapter stops importing Core internals, the P3 dependency exception remains
unresolved. The ADR process requires an accepted ADR to record an exception's
scope, owner and exit criterion. Keep P3 unchecked until the exception is
accepted or those imports are removed.

Prefer offline scoring/replay and isolated Slurm jobs. The current run is serial
(`worker_count=1`), but that does not reserve capacity on a shared gateway. Do
not target a shared production gateway until an admission policy, execution
window and stop condition are defined.

## On a Slurm cluster

`scripts/bench/slurm/` has three jobs; each sources `env.sh`, which needs `WS`
(the workspace that holds `repos/acessilia`, `repos/acessilia-toolbox` and
`data/`) and keeps every cache and run under it (`BENCH_VAR=$WS/bench`).
Submit from `$WS` and pass the partition with `-p`.
These existing jobs are compatibility tooling for isolated local runs; public
campaign execution and official reporting belong in `acessilia-benchmark`.

| Job | What |
|---|---|
| `setup.sbatch` | Toolbox, docling-serve and MinerU venvs and models, this repo's venv; optionally a HuggingFace dataset snapshot (`HF_DATASET`, `HF_PATTERN`, `DATASET_DIR`) |
| `bench.sbatch` | starts the provider (`PROVIDER=docling\|mineru`) and the Toolbox inside the job, on ports derived from the job id, then `scripts.bench run --resume` and `score` |
| `eval_official.sbatch` | builds the official evaluator's one-page tree for each run in `RUNS` and scores it with `$WS/repos/DrDocBench` (`CONFIG` is the evaluator config; `cdm_env.sh` for CDM) |

The local Toolbox port can change between jobs. Resuming the same `RUN` still
requires the same Toolbox commit, tracked changes, provider configuration and
other run identity fields. For a materialized dataset, set `DATASET_REVISION`
to the full source commit SHA so the job can record it for comparison.

```bash
cd $WS
sbatch -p <partition> -c 8 --mem 32G --time 04:00:00 --job-name mineru-dev \
  --export=ALL,WS=$PWD,DATASET=drdocbench,ROOT=$PWD/data/drdocbench/dev,RUN=mineru,PROVIDER=mineru,DATASET_REVISION=$DATASET_REVISION \
  repos/acessilia/scripts/bench/slurm/bench.sbatch
```

## Adding a dataset

Write `scripts/bench/datasets/<name>.py` with a class that implements
`scripts.bench.datasets.base.Dataset`, and register it in
`scripts/bench/datasets/__init__.py`:

- `download(split, root, limit)` writes the split under `root`;
- `pages(root)` returns a `BenchPage` per page (image, ground-truth markdown
  path, metadata the submission needs);
- `build_submission(pages, predictions, out)` packages a run.

Predictions and scoring are shared: when the dataset's ground truth is not
markdown, convert it to markdown in `download` so that `score` applies as is.

## Math reference case

`python -m scripts.bench.math_case` scores one whole document instead of a
page dataset: `velocidade-instantanea.pdf` (id `036` in
[acessilia-dataset](https://github.com/A11yDevs/acessilia-dataset), under
`input/math-reference/`), a five-page pdfTeX calculus handout with inline and
display math, a numbered equation and math in table headers. Its ground truth
lists the expected LaTeX of every formula (`ground_truth.csv`) and the text,
structure and speech checks formulas do not cover (`expectations.json`).

```bash
# Process the PDF through the core, then score it (Toolbox and model provider needed)
uv run python -m scripts.bench.math_case run --out var/bench/math-reference/<run>

# Score outputs you already have: the canonical document JSON and the TXT,
# optionally the PDF/UA (needs pdftotext)
uv run python -m scripts.bench.math_case score --canonical doc.json --txt doc.txt --pdf-ua doc.pdf_ua.pdf
```

The dataset clone is read from `tests/dataset` or `ACESSILIA_TEST_DATASET_DIR`.
The scorecard (`scorecard.md`, `scorecard.json`) reports:

- display formulas, paired with the ground truth on the same page: CDM, the
  recall of structural tokens (`\frac`, `^`, `_`, `\lim`, `\mathbb`...), MathML,
  spoken form and where the LaTeX came from (`extractor`, `math.recognize`,
  `vision`). The structure recall is the number to watch: a formula flattened
  from the PDF text layer keeps its letters, so its bag-of-token CDM stays
  high, but it loses every structural token;
- inline expressions and table headers/cells delivered as math;
- the text, structure and speech checks, with each failure listed.

With `--pdf-ua` (and with `run`, unless `--no-pdf-ua`) the text checks run on both outputs
and the auto-numbered-headings check is added, so the scorecard starts with
the outputs it scored: compare two scorecards only when that row matches.

A PR that changes how math, text repair or structure reach the outputs pastes
the scorecard before and after in its description. `tests/test_math_case_e2e.py`
(`-m e2e`) runs the case and locks what already passes.

### Parity of a change that should not alter the output

`compare` checks two outputs of the case field by field, for a refactoring
that must leave them as they were (ADR-0017's parity of the formula chain):

```bash
uv run python -m scripts.bench.math_case compare base/canonical.json candidate/canonical.json --out var/bench/math-reference/<compare>
```

It compares every formula's LaTeX, MathML, spoken form, recognition method,
text agreement, text layer and equation number; the text and inline
expressions of each block, tables included; each table's shape and cells; the
block structure; and the technical warnings. It exits with 1 on a difference.
Its JSON and Markdown reports identify the parity gate. The slide-case
comparison for 006 is diagnostic only and does not automatically accept or
reject a candidate.

What a vision model wrote may differ between any two runs, so it is listed
apart and does not fail the comparison:
- the LaTeX of a formula it read, and what the core derives from that LaTeX
  (MathML, spoken form, text agreement, equation number) only when the LaTeX
  itself differs;
- a picture's description that the picture stage marks as the model's
  (`vision_description_complete`, `vision_confidence`);
- a table the data agent read again from its image (`table_review`).

Everything else counts, even when a vision model's answer caused it: the
recognition method, a fallback alt text, the block structure (a formula the
model took for a picture) and the technical warnings. Inspect those. Run the
base twice to see how much varies on its own.

The core and the Toolbox cache results by the source's hash, not by the code
that produced them, so each run needs a source no run has seen: append a
comment after `%%EOF` (a PDF reader ignores it). The case lives in
acessilia-dataset's `main` branch (`input/math-reference/`); point
`ACESSILIA_TEST_DATASET_DIR` at a checkout of it, since a worktree of this
repository has no `tests/dataset`.

```bash
export ACESSILIA_TEST_DATASET_DIR=/path/to/acessilia-dataset   # on its main branch
for run in base candidate; do
  cp "$ACESSILIA_TEST_DATASET_DIR/input/math-reference/velocidade-instantanea.pdf" "/tmp/036-$run.pdf"
  printf '%% %s %s\n' "$run" "$(date +%s)" >> "/tmp/036-$run.pdf"
done
# In a checkout of each commit (git worktree add ../base <commit>):
uv run python -m scripts.bench.math_case run --pdf /tmp/036-base.pdf --out var/bench/math-reference/base
```

## Dr.DocBench experiment snapshot

The shared-task experiment code (fusion variants, Slurm jobs, frozen replay)
is preserved at the tag `drbench-2026-snapshot`: what each script did and where
its algorithm went is in [CODE.md](drbench/experiments/CODE.md), and how to run
it in the [runbook](drbench/experiments/RUNBOOK.md).
