#!/bin/bash
#SBATCH --job-name=drb-eval
#SBATCH --partition=h100n2
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --output=/raid/user_marcospaulo/drdocbench/runs/slurm/logs/%x_%j.log
# Generic dev-120 evaluation of one run (PLAN.md §8.2.8):
#   sbatch [--export=ALL,CDM=1,BASELINE=adjudicator-v0,NOTE="..."] runs/slurm/eval_run.sbatch RUN_ID
# Requires runs/dev/RUN_ID/predictions/*.drbench.md. Produces reports/{local,official}*.json,
# summaries, a LEDGER.md line and a paired comparison against BASELINE.
set -uo pipefail
source /raid/user_marcospaulo/drdocbench/runs/slurm/env.sh
cd "$WS"
R=${1:?RUN_ID}
CDM=${CDM:-auto}
BASELINE=${BASELINE:-adjudicator-v0}
NOTE=${NOTE:-}
ACE=$WS/repos/acessilia/.venv/bin/python
DRB=$WS/repos/DrDocBench/.venv/bin/python
DEV=$WS/runs/dev
PRED=$DEV/$R/predictions
[[ -d $PRED ]] || { echo "missing $PRED"; exit 1; }
mkdir -p "$DEV/$R/reports"
echo "[$(date +%T)] run=$R n_pred=$(ls "$PRED"/*.drbench.md 2>/dev/null | wc -l) baseline=$BASELINE job=$SLURM_JOB_ID"
{ echo "job=$SLURM_JOB_ID date=$(date -u +%FT%TZ) baseline=$BASELINE note=$NOTE"; } >> "$DEV/$R/run.log"

# CDM: use the local TeX stack when installed (runs/slurm/cdm_env.sh) unless CDM=0
CFG=$DEV/eval-configs/end2end_nocdm.yaml
if [[ $CDM != 0 && -f $WS/runs/slurm/cdm_env.sh ]]; then
  source "$WS/runs/slurm/cdm_env.sh"
  if command -v xelatex >/dev/null && command -v node >/dev/null; then CFG=$DEV/eval-configs/end2end_full.yaml; fi
fi
echo "[$(date +%T)] config=$(basename "$CFG")"

echo "[$(date +%T)] 1. local metrics"
(cd repos/acessilia && $ACE "$WS/scripts/eval_local.py" --run "$R" --subset "$DEV/subset.json" \
    --predictions "$PRED" --out "$DEV/$R/reports" --workers "$SLURM_CPUS_PER_TASK" | tail -3)

echo "[$(date +%T)] 2. official evaluator"
mkdir -p "$DEV/official/result"
cd "$DEV/official"
$DRB "$WS/scripts/build_official_pred.py" "$R"
$DRB "$WS/repos/DrDocBench/tools/multipage_pdf_validation.py" \
    --config "$CFG" --gt_root "$WS/data/hf/dev" \
    --pred_path "$DEV/$R/official_pred" --save_name "$R" 2>&1 | grep -v "^\s*$" | tail -25
cp -f "result/${R}_metric_result.json" "$DEV/$R/reports/official_metric_result.json" 2>/dev/null
cd "$WS"

echo "[$(date +%T)] 3. summaries + ledger"
$DRB scripts/official_summary.py docling-forceocr mineru adjudicator-v0 differ-v1 "$R" > /dev/null && echo "official_summary ok"
$DRB scripts/paired_compare.py "$BASELINE" "$R" --json "$DEV/$R/reports/paired_vs_${BASELINE}.json"
$DRB scripts/ledger_append.py "$R" --baseline "$BASELINE" --note "$NOTE job=$SLURM_JOB_ID"
echo "[$(date +%T)] done"
