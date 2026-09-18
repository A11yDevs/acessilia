#!/bin/bash
#SBATCH --job-name=drb-differ-v1
#SBATCH --partition=h100n2
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=00:30:00
#SBATCH --output=/raid/user_marcospaulo/drdocbench/runs/slurm/logs/%x_%j.log
# Tree Differ v1 (text-only block-level merge) on the dev subset: merge existing
# docling-forceocr + mineru predictions, then evaluate with local + official scorers.
set -uo pipefail
source /raid/user_marcospaulo/drdocbench/runs/slurm/env.sh
cd "$WS"
ACE=$WS/repos/acessilia/.venv/bin/python
DRB=$WS/repos/DrDocBench/.venv/bin/python
DEV=$WS/runs/dev
R=differ-v1

echo "[$(date +%T)] 1. merge"
mkdir -p $DEV/$R/reports
$ACE scripts/tree_differ_v1.py --docling $DEV/docling-forceocr/predictions --mineru $DEV/mineru/predictions \
    --out $DEV/$R/predictions | tee $DEV/$R/decisions_summary.txt
ls $DEV/$R/predictions/*.drbench.md | wc -l

echo "[$(date +%T)] 2a. local metrics"
(cd repos/acessilia && $ACE $WS/scripts/eval_local.py --run $R --subset $DEV/subset.json \
    --predictions $DEV/$R/predictions --out $DEV/$R/reports --workers 4 | tail -5)

echo "[$(date +%T)] 2b. official evaluator"
mkdir -p $DEV/official/result
cd $DEV/official
$DRB $WS/scripts/build_official_pred.py "$R"
$DRB $WS/repos/DrDocBench/tools/multipage_pdf_validation.py \
    --config $DEV/eval-configs/end2end_nocdm.yaml --gt_root $WS/data/hf/dev \
    --pred_path $DEV/$R/official_pred --save_name "$R" 2>&1 | grep -v "^\s*$" | tail -20
cp -f result/${R}_metric_result.json $DEV/$R/reports/official_metric_result.json 2>/dev/null
cd "$WS"

echo "[$(date +%T)] 2c. summaries"
RUNS="docling docling-forceocr mineru adjudicator-v0 adjudicator-v0b $R"
$DRB scripts/official_summary.py $RUNS > /dev/null && echo "official_summary ok"
$DRB scripts/adjudicator_summary.py $RUNS | head -40
echo "[$(date +%T)] done"
