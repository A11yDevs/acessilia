#!/bin/bash
# Score a Dr.DocBench run with the official evaluator ($WS/repos/DrDocBench,
# one-page windows). CONFIG is the evaluator's end-to-end config, e.g. the
# no-CDM one of the experiments (end2end_nocdm.yaml, kept in the evaluator fork
# marcospaulo429/DrDocBench); for CDM, install TeX Live under $OPT and source
# cdm_env.sh first.
# Submit from $WS:
#   sbatch -p <partition> --export=ALL,WS=$PWD,ROOT=$PWD/data/drdocbench/dev,RUNS="docling-v1 mineru-v1",CONFIG=<yaml>[,SPLIT=dev] \
#     repos/acessilia/scripts/bench/slurm/eval_official.sbatch
#SBATCH --job-name=bench-eval-official
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=01:30:00
#SBATCH --output=logs/slurm/%x_%j.log
set -uo pipefail
source "$WS/repos/acessilia/scripts/bench/slurm/env.sh"
: "${ROOT:?}"; : "${RUNS:?}"; : "${CONFIG:?evaluator config yaml}"
SPLIT=${SPLIT:-dev}
EVAL=$WS/repos/DrDocBench

VENV=$EVAL/.venv
if [[ ! -x $VENV/bin/python ]]; then
  uv venv --python 3.11 "$VENV"
  uv pip install --python "$VENV/bin/python" \
    "apted==1.0.3" "beautifulsoup4==4.11.1" "evaluate==0.4.3" "func-timeout==4.3.5" \
    "Levenshtein==0.25.1" "loguru==0.7.2" "lxml" "matplotlib" "nltk==3.9.1" \
    "numpy<2" "pandas" "Pillow" "pylatexenc==2.10" "PyYAML==6.0.2" "scipy" \
    "tabulate==0.9.0" "tqdm" "rapidfuzz" "mmeval" "scikit-image" || { echo "PIP FAILED"; exit 1; }
fi

for r in $RUNS; do
  RUN_DIR=$BENCH_VAR/drdocbench/$SPLIT/$r
  echo "[$(date +%T)] === $r"
  (cd "$WS/repos/acessilia" && uv run --frozen python - "$ROOT" "$RUN_DIR" <<'PY'
import sys
from pathlib import Path
from scripts.bench.datasets.drdocbench import DrDocBench
root, run = map(Path, sys.argv[1:3])
ds = DrDocBench()
n = ds.build_official_tree(ds.pages(root), run / "predictions", run / "official_pred")
print(f"{n} prediction files -> {run / 'official_pred'}")
PY
  )
  mkdir -p "$RUN_DIR/official"
  (cd "$RUN_DIR/official" && "$VENV/bin/python" "$EVAL/tools/multipage_pdf_validation.py" \
      --config "$CONFIG" --gt_root "$ROOT" --pred_path "$RUN_DIR/official_pred" --save_name "$r" \
      2>&1 | grep -v "^\s*$" | tail -60)
  cp -f "$RUN_DIR/official/result/${r}_metric_result.json" "$RUN_DIR/official_metric_result.json" 2>/dev/null \
    && echo "saved $RUN_DIR/official_metric_result.json"
done
echo "[$(date +%T)] done"
