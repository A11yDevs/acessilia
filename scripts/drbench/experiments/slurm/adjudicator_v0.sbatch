#!/bin/bash
#SBATCH --job-name=drb-adjudicator-v0
#SBATCH --partition=h100n2
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=00:30:00
#SBATCH --output=/raid/user_marcospaulo/drdocbench/runs/slurm/logs/%x_%j.log
# Adjudicator v0/v0b on the dev subset: route pages between existing
# docling-forceocr and mineru predictions, evaluate (local + official), append
# tables to runs/dev/summary.md; then, if the 509-page EvalAI runs are complete,
# build+validate the three submission zips.
set -uo pipefail
source /raid/user_marcospaulo/drdocbench/runs/slurm/env.sh
cd "$WS"
ACE=$WS/repos/acessilia/.venv/bin/python
DRB=$WS/repos/DrDocBench/.venv/bin/python
DEV=$WS/runs/dev

echo "[$(date +%T)] 1. adjudicate (dev subset)"
mkdir -p $DEV/adjudicator-v0/reports $DEV/adjudicator-v0b/reports
$ACE scripts/adjudicate_v0.py --docling $DEV/docling-forceocr/predictions --mineru $DEV/mineru/predictions \
    --out $DEV/adjudicator-v0/predictions --rule v0 | tee $DEV/adjudicator-v0/decisions_summary.txt
$ACE scripts/adjudicate_v0.py --docling $DEV/docling-forceocr/predictions --mineru $DEV/mineru/predictions \
    --out $DEV/adjudicator-v0b/predictions --rule agreement --agree-thr 0.85 | tee $DEV/adjudicator-v0b/decisions_summary.txt

echo "[$(date +%T)] 2a. local metrics"
for r in adjudicator-v0 adjudicator-v0b; do
  (cd repos/acessilia && $ACE $WS/scripts/eval_local.py --run $r --subset $DEV/subset.json \
      --predictions $DEV/$r/predictions --out $DEV/$r/reports --workers 4 | tail -5)
done

echo "[$(date +%T)] 2b. official evaluator"
mkdir -p $DEV/official/result
cd $DEV/official
for r in adjudicator-v0 adjudicator-v0b; do
  echo "=== $r"
  $DRB $WS/scripts/build_official_pred.py "$r"
  $DRB $WS/repos/DrDocBench/tools/multipage_pdf_validation.py \
      --config $DEV/eval-configs/end2end_nocdm.yaml --gt_root $WS/data/hf/dev \
      --pred_path $DEV/$r/official_pred --save_name "$r" 2>&1 | grep -v "^\s*$" | tail -30
  cp -f result/${r}_metric_result.json $DEV/$r/reports/official_metric_result.json 2>/dev/null
done
cd "$WS"

echo "[$(date +%T)] 2c. summaries"
RUNS="docling docling-forceocr mineru adjudicator-v0 adjudicator-v0b"
$DRB scripts/eval_summary.py --runs $RUNS --primary docling-forceocr --secondary mineru > /dev/null && echo "eval_summary ok"
$DRB scripts/official_summary.py $RUNS > /dev/null && echo "official_summary ok"
$DRB scripts/adjudicator_summary.py $RUNS | head -60

echo "[$(date +%T)] 3. EvalAI submissions (only if both 509-page runs complete)"
bash scripts/build_all_submissions.sh || echo "submissions skipped/failed (rc=$?) — run later: srun -p h100n2 -c 4 --mem 16G bash scripts/build_all_submissions.sh"
echo "[$(date +%T)] done"
