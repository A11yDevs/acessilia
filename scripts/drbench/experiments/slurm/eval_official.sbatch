#!/bin/bash
#SBATCH --job-name=drb-eval-official
#SBATCH --partition=h100n2
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=01:30:00
#SBATCH --output=/raid/user_marcospaulo/drdocbench/runs/slurm/logs/%x_%j.log
set -uo pipefail
source /raid/user_marcospaulo/drdocbench/runs/slurm/env.sh
cd "$WS"
RUNS="${RUNS:-docling docling-forceocr mineru}"

VENV=$WS/repos/DrDocBench/.venv
if [[ ! -x $VENV/bin/python ]]; then
  echo "[$(date +%T)] creating venv"
  uv venv --python 3.11 "$VENV"
  uv pip install --python "$VENV/bin/python" \
    "apted==1.0.3" "beautifulsoup4==4.11.1" "evaluate==0.4.3" "func-timeout==4.3.5" \
    "Levenshtein==0.25.1" "loguru==0.7.2" "lxml" "matplotlib" "nltk==3.9.1" \
    "numpy<2" "pandas" "Pillow" "pylatexenc==2.10" "PyYAML==6.0.2" "scipy" \
    "tabulate==0.9.0" "tqdm" "rapidfuzz" "mmeval" "scikit-image" || { echo "PIP FAILED"; exit 1; }
fi
PY=$VENV/bin/python

echo "[$(date +%T)] fig3"
$PY scripts/fig3_delta_hist.py paper/figures/fig3_delta_hist.pdf || echo "fig3 failed"

mkdir -p runs/dev/official/result
cd runs/dev/official
for r in $RUNS; do
  echo "[$(date +%T)] === $r"
  $PY $WS/scripts/build_official_pred.py "$r"
  $PY $WS/repos/DrDocBench/tools/multipage_pdf_validation.py \
      --config $WS/runs/dev/eval-configs/end2end_nocdm.yaml \
      --gt_root $WS/data/hf/dev \
      --pred_path $WS/runs/dev/$r/official_pred \
      --save_name "$r" 2>&1 | grep -v "^\s*$" | tail -60
  mkdir -p $WS/runs/dev/$r/reports
  cp -f result/${r}_metric_result.json $WS/runs/dev/$r/reports/official_metric_result.json 2>/dev/null && echo "saved reports/official_metric_result.json"
done
echo "[$(date +%T)] done"
