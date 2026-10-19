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

`compare` applies the acceptance criterion of `docstruct.evaluation.holdout`:
the split is per document (1/3 held out), and a candidate is accepted only if it
gains on tune, does not lose on holdout and no metric drops beyond the
tolerance. It exits 1 when the candidate is rejected, including when one of the
subsets has no scorable pages (too small a sample).

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

## Dr.DocBench experiment snapshot

The shared-task experiment code (fusion variants, Slurm jobs, frozen replay)
is preserved at the tag `drbench-2026-snapshot`: what each script did and where
its algorithm went is in [CODE.md](drbench/experiments/CODE.md), and how to run
it in the [runbook](drbench/experiments/RUNBOOK.md).
