# Benchmark harness

> Brazilian Portuguese version: [versão pt-BR](bench.pt-br.md)

`python -m scripts.bench` runs the core on a document-parsing dataset, scores
the result and compares runs. It is how the core's structure extraction is
measured on Dr.DocBench, and how it will be measured on OmniDocBench and later
datasets.

## Where things live

| Piece | Location | Dataset-specific? |
|---|---|---|
| Metrics (text edit distance, reading order, TEDS, CDM, overall) | `docstruct.evaluation.metrics` | no |
| Page scoring (pairs tables and formulas by order) | `docstruct.evaluation.markdown` | no |
| Tune/holdout acceptance | `docstruct.evaluation.holdout` | no |
| Canonical document → benchmark markdown | `docstruct.export.markdown` | no |
| Toolbox payload → canonical document | `scripts/bench/core.py` | no |
| Download, page layout, submission format | `scripts/bench/datasets/<name>.py` | yes |

The metrics are local approximations for tracking deltas between runs. For a
number you report, run the benchmark's official evaluator on the predictions.

## Workflow

The Toolbox must be reachable (the core's `TOOLBOX_*` settings apply).

```bash
# 1. Materialize a split locally: var/bench/<dataset>/<split>/data
uv run python -m scripts.bench download --dataset drdocbench --split dev --limit 100

# 2. Run the core: var/bench/<dataset>/<split>/<run>/predictions/<item>.md (+ .blocks.json)
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
`run` replaces the run's previous predictions and records the pages it covered
in `pages.txt`; `score` scores only those pages, so a `--sample` run is not
scored against the whole split. `score` exits 1 when no page has ground truth
(the `test` split, for instance). `--resume` continues an interrupted run
instead: earlier predictions stay and `pages.txt` keeps covering every page the
selection included.

Scoring computes two Levenshtein distances per page. Without `rapidfuzz`
(installed by the `dev` extra) docstruct falls back to pure Python, which takes
about 20 s for a 3,000-character page.

`compare` applies the acceptance criterion of `docstruct.evaluation.holdout`:
the split is per document (1/3 held out), and a candidate is accepted only if it
gains on tune, does not lose on holdout and no metric drops beyond the
tolerance. It exits 1 when the candidate is rejected, including when one of the
subsets has no scorable pages (too small a sample) and when a metric scored in
the base has no value in the candidate (for example, it stopped emitting
tables): the metric would otherwise leave the mean and count as a gain. Values
that cannot be computed are printed as `null`.

A metric that disappears only on some pages still leaves those pages out of
its mean; in `drilldown.csv` that component is blank on those pages.

## On a Slurm cluster

`scripts/bench/slurm/` has three jobs; each sources `env.sh`, which needs `WS`
(the workspace that holds `repos/acessilia`, `repos/acessilia-toolbox` and
`data/`) and keeps every cache and run under it (`BENCH_VAR=$WS/bench`).
Submit from `$WS` and pass the partition with `-p`.

| Job | What |
|---|---|
| `setup.sbatch` | Toolbox, docling-serve and MinerU venvs and models, this repo's venv; optionally a HuggingFace dataset snapshot (`HF_DATASET`, `HF_PATTERN`, `DATASET_DIR`) |
| `bench.sbatch` | starts the provider (`PROVIDER=docling\|mineru`) and the Toolbox inside the job, on ports derived from the job id, then `scripts.bench run --resume` and `score`; resubmitting the same `RUN` resumes |
| `eval_official.sbatch` | builds the official evaluator's one-page tree for each run in `RUNS` and scores it with `$WS/repos/DrDocBench` (`CONFIG` is the evaluator config; `cdm_env.sh` for CDM) |

```bash
cd $WS
sbatch -p <partition> -c 8 --mem 32G --time 04:00:00 --job-name mineru-dev \
  --export=ALL,WS=$PWD,DATASET=drdocbench,ROOT=$PWD/data/drdocbench/dev,RUN=mineru,PROVIDER=mineru \
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

A PR that changes how math, text repair or structure reach the outputs pastes
the scorecard before and after in its description. `tests/test_math_case_e2e.py`
(`-m e2e`) runs the case and locks what already passes.

## Dr.DocBench experiment snapshot

The shared-task experiment code (fusion variants, Slurm jobs, frozen replay)
is preserved at the tag `drbench-2026-snapshot`: what each script did and where
its algorithm went is in [CODE.md](drbench/experiments/CODE.md), and how to run
it in the [runbook](drbench/experiments/RUNBOOK.md).
