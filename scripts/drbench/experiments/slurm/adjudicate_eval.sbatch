#!/bin/bash
#SBATCH --job-name=drb-adjudicate
#SBATCH --partition=h100n2
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=01:30:00
#SBATCH --output=/raid/user_marcospaulo/drdocbench/runs/slurm/logs/%x_%j.log
# Page-level adjudication of two dev runs + eval.
#   sbatch --export=ALL,RUN_ID=adjudicator-v1-20260916,DOCLING=docling-v3-20260916,MINERU=mineru-v3-20260916[,ARGS="--table-pref mineru",BASELINE=adjudicator-v0,SPLIT=dev] \
#          runs/slurm/adjudicate_eval.sbatch
set -uo pipefail
source /raid/user_marcospaulo/drdocbench/runs/slurm/env.sh
cd "$WS"
R=${RUN_ID:?}; D=${DOCLING:?}; M=${MINERU:?}; SPLIT=${SPLIT:-dev}; ARGS=${ARGS:-}
SCRIPT=${SCRIPT:-scripts/adjudicate_v1.py}
DRB=$WS/repos/DrDocBench/.venv/bin/python
if [[ $SPLIT == dev ]]; then ROOT=$WS/runs/dev; elif [[ $SPLIT == test ]]; then ROOT=$WS/runs/evalai; else ROOT=$WS/runs/$SPLIT; fi
PRED=$ROOT/$R/predictions
echo "job=$SLURM_JOB_ID run=$R split=$SPLIT docling=$D mineru=$M script=$SCRIPT args=$ARGS"
echo "n_docling=$(ls "$ROOT/$D/predictions"/*.drbench.md | wc -l) n_mineru=$(ls "$ROOT/$M/predictions"/*.drbench.md | wc -l)"
$DRB "$WS/$SCRIPT" --docling "$ROOT/$D/predictions" --mineru "$ROOT/$M/predictions" --out "$PRED" $ARGS
echo "n_pred=$(ls "$PRED"/*.drbench.md | wc -l)"
cat > "$ROOT/$R/RUN.md" <<EOF
# $R
- job: $SLURM_JOB_ID  date: $(date -u +%FT%TZ)  split: $SPLIT
- $SCRIPT $ARGS over docling=$D mineru=$M (decisions.csv in predictions/)
- commits: acessilia=$(git -C repos/acessilia rev-parse --short HEAD) toolbox=$(git -C repos/acessilia-toolbox rev-parse --short HEAD)
EOF
if [[ $SPLIT == dev ]]; then
  export BASELINE=${BASELINE:-adjudicator-v0} NOTE=${NOTE:-"$(basename $SCRIPT .py) $ARGS over $D + $M"}
  bash "$WS/runs/slurm/eval_run.sbatch" "$R"
fi
echo "[$(date +%T)] done"
