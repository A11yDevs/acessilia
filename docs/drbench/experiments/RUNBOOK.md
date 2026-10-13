# Reproduction runbook — Dr.DocBench

> Brazilian Portuguese version: [versão pt-BR](RUNBOOK.pt-br.md)

How to rebuild the environment, freeze a run, replay it and compare the results.
This is the single entry point for resuming the performance work.

## 0. What is deterministic and what needs a model

| Step | Deterministic? | Needs GPU? |
|---|---|---|
| Library tests (`libs/docstruct/tests`) | yes | no |
| Core tests (`tests/`) | yes | no |
| Differ / fusion over frozen raw JSON | yes | no |
| Official evaluation (md2md, TEDS, CDM) | yes | no (CDM needs the TeX stack) |
| Provider extraction (Docling, MinerU) | no | yes (MinerU hybrid-VLM) |
| Whole-page VLM OCR (Qwen3-VL, dots.ocr, DeepSeek-OCR-2, TeleOCR) | no | yes |
| Pairwise VLM judge | no | yes |
| Orientation detection (RapidOCR) | no | CPU only |

The replay (`frozen_replay.py`) **never runs OCR again**: it consumes the raw
inference JSON. That is what makes a recorded run reproducible without a GPU.

## 1. Rebuild the environment

```bash
# Core + library, pinned by the lockfile
uv sync --frozen

# Library tests must pass without the backend installed
uv run pytest libs/docstruct/tests

# Core tests (6 pre-existing failures in test_formula_enrichment.py and
# test_pddl_orchestrator.py are expected; 0 skips)
uv run pytest -m "not e2e"
```

The lockfile is `uv.lock` (91 packages). `pyproject.toml` declares
`acessilia-docstruct` as an editable path source, so `uv sync` installs the
library from `libs/docstruct`.

The experiment workspace is separate from this repository. `slurm/env.sh` is
parameterised; override the roots to relocate:

```bash
WS=/my/workspace CACHE_ROOT=/my/cache source runs/slurm/env.sh
```

Expected layout under `$WS`:

```
repos/acessilia, repos/acessilia-toolbox, repos/DrDocBench
data/hf/dev/<SUBJECT>/<doc>/{images,mds,json}
data/evalai/drdocbench-evaluation-v4/images
runs/slurm/*.sbatch
```

## 2. Freeze a run

Pick a spec from `scripts/drbench/experiments/eval/specs/`:

| Spec | Split | Pages |
|---|---|---|
| `dev120.spec.json` | dev | 120 (selection versioned) |
| `dev986.spec.json` | dev | 986 (generate `pages.json`) |
| `test509.spec.json` | evalai | 509 (generate `pages.json`) |

The two full-split specs declare a `pages_generator`; run it once in the
workspace:

```bash
python scripts/drbench/experiments/eval/make_replay_pages.py \
    --images-root $WS/data/hf/dev --out dev986-pages.json
```

Then freeze:

```bash
python scripts/drbench/experiments/eval/frozen_replay.py freeze \
    --spec scripts/drbench/experiments/eval/specs/dev986.spec.json \
    --out $WS/runs/replay/dev986-<label>
```

The freeze records: the page selection, the raw provider payloads, the images,
the ground truth, the Git exports of both variants and the evaluator, the
lockfile, the model revisions and the source hashes. It refuses a dirty working
tree and refuses to write inside a source repository.

## 3. Replay and compare

```bash
python scripts/drbench/experiments/eval/frozen_replay.py evaluate \
    --run $WS/runs/replay/dev986-<label> --require-zero-regressions
```

The replay writes `per-page.csv`, `summary.json` and `REPORT.md`. The quality
gate rejects per-page losses and asymmetric metric coverage, even when the mean
improves. `overall` is the competition ranking metric (per-page mean of the
available components).

## 4. GPU cost of each step

The recorded jobs ran on `h100n2` (1 GPU, 16 CPUs, 128 GB). Approximate costs:

| Step | Job | Cost |
|---|---|---|
| Provider extraction, dev-986 (Docling + MinerU) | `full_gpu.sbatch` | ~2 h GPU |
| MinerU hybrid-VLM, dev-986 + test-509 | `mineru_vlm.sbatch` | ~10 h GPU (3 stages) |
| Whole-page VLM OCR (Qwen3-VL-32B), dev-986 | `vlm_page.sbatch` | ~4 h GPU |
| TeleOCR page parse, dev + test | `teleocr_page.sbatch` | ~3 h GPU |
| Pairwise VLM judge, divergent pages only | `vlm_judge*.sbatch` | ~1 h GPU |
| Orientation detection (RapidOCR) | `orient.sbatch` | ~20 min CPU |
| Differ variants over frozen raw JSON | `differ_variants.sbatch` | minutes, CPU |
| Official evaluation | `eval_official.sbatch` | ~30 min CPU (CDM needs TeX) |

The judge only runs on pages where the candidates diverge (ratio < 0.97), which
is ~17% of the test split — that is why it is cheap relative to full OCR.

## 5. What to check before promoting a method

1. **Confirm on the leaderboard.** The dev best (87.33) was never confirmed; the
   observed dev→test gap is ~8 points. A dev gain is not a result.
2. **Check the metric that moved.** TEDS did not transfer (dev +5.9 → test +0.2);
   the real test gain came from reading order with the MinerU hybrid-VLM source.
3. **Respect the holdout.** The split is by document (`md5(doc) % 3`). Acceptance
   requires Δtune ≥ +0.10, Δhold ≥ 0 and no metric −0.3.
4. **Run the frozen replay** as the regression gate before submitting.

## 6. Frozen artifacts

`docs/drbench/experiments/RESULTS.json` holds the numbers, the submission zip
hashes and the composition of each run. The run outputs themselves live outside
the repository (on the cluster scratch).

## 7. References

- `scripts/drbench/experiments/eval/FROZEN_REPLAY.md` — spec format and discipline
- `scripts/drbench/experiments/README.md` — workspace layout and relocation
- `docs/drbench/experiments/SERVICES-LOOP.md` — services started inside each job
- `docs/drbench/experiments/LOOP.md` — the experiment loop and its decisions
- `docs/drbench/experiments/SUBMISSIONS-LEADERBOARD.md` — submissions and scores
