#!/bin/bash
#SBATCH --job-name=drb-eval-full
#SBATCH --partition=h100n2
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=04:00:00
#SBATCH --output=/raid/user_marcospaulo/drdocbench/runs/slurm/logs/%x_%j.log
# Official evaluation of a full-split run (runs/dev-full/<RUN>/predictions, 986 pages) with
# 1-page windows and/or document windows (contiguous 15-page runs, like the EvalAI test docs).
# PROTO=end2end (JSON layout GT) | md2md (curated mds/*.md GT = EvalAI contract
# drdocbench-document-parsing-v3-single-page-md2md; use WINDOWS=1).
#   sbatch --export=ALL,RUNS="mineru docling differ-v2",WINDOWS="1 doc"[,PROTO=md2md,CDM=0] runs/slurm/eval_full.sbatch
set -uo pipefail
source /raid/user_marcospaulo/drdocbench/runs/slurm/env.sh
cd "$WS"
RUNS=${RUNS:?}; WINDOWS=${WINDOWS:-"1 doc"}; CDM=${CDM:-auto}; PROTO=${PROTO:-end2end}
DRB=$WS/repos/DrDocBench/.venv/bin/python
FULL=$WS/runs/dev-full; GT=$WS/data/hf/dev
mkdir -p "$FULL/official/result" "$FULL/eval-configs"
CFG_SRC=$WS/runs/dev/eval-configs/${PROTO}_nocdm.yaml
if [[ $CDM != 0 && -f $WS/runs/slurm/cdm_env.sh ]]; then
  source "$WS/runs/slurm/cdm_env.sh"
  command -v xelatex >/dev/null && command -v node >/dev/null && CFG_SRC=$WS/runs/dev/eval-configs/${PROTO}_full.yaml
fi
echo "[$(date +%T)] job=$SLURM_JOB_ID runs=$RUNS windows=$WINDOWS proto=$PROTO config=$(basename "$CFG_SRC")"
for R in $RUNS; do
  PRED=$FULL/$R/predictions
  [[ -d $PRED ]] || { echo "missing $PRED"; continue; }
  echo "[$(date +%T)] run=$R n_pred=$(ls "$PRED"/*.drbench.md | wc -l)"
  for WIN in $WINDOWS; do
    SFX=$([[ $PROTO == end2end ]] && echo "" || echo "-$PROTO")
    NAME="${R}-w${WIN}${SFX}"; TREE=$FULL/$R/official_pred_w$WIN
    $DRB scripts/build_official_pred_full.py --predictions "$PRED" --gt-root "$GT" --out "$TREE" --window "$WIN"
    CFG=$FULL/eval-configs/${NAME}.yaml
    sed -e "s#data_path: .*/official_pred.*#data_path: $TREE#" "$CFG_SRC" > "$CFG"
    (cd "$FULL/official" && $DRB "$WS/repos/DrDocBench/tools/multipage_pdf_validation.py" \
        --config "$CFG" --gt_root "$GT" --pred_path "$TREE" --save_name "$NAME" 2>&1 | grep -E "finished|Total time|Error|Traceback" | tail -3)
    mkdir -p "$FULL/$R/reports"
    $DRB scripts/official_window_summary.py "$NAME" --result-dir "$FULL/official/result" --out "$FULL/$R/reports/official_w${WIN}${SFX}.json" \
      | tee -a "$FULL/LEDGER.md"
  done
done
echo "[$(date +%T)] done"
