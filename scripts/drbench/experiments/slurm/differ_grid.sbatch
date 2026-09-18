#!/bin/bash
#SBATCH --job-name=drb-differ-grid
#SBATCH --partition=h100n2
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=03:00:00
#SBATCH --output=/raid/user_marcospaulo/drdocbench/runs/slurm/logs/%x_%j.log
# Sequential lam/tau grid of tree_differ_v2 on dev-120 (each point = adjudicate + full eval).
#   sbatch --export=ALL,DOCLING=docling-v3-20260916,MINERU=mineru-v3-20260916,GRID="0.3:0.6 0.7:0.6 0.5:0.5 0.5:0.7",BASELINE=differ-v2-20260916 runs/slurm/differ_grid.sbatch
set -uo pipefail
source /raid/user_marcospaulo/drdocbench/runs/slurm/env.sh
cd "$WS"
D=${DOCLING:?}; M=${MINERU:?}; GRID=${GRID:?}; BASELINE=${BASELINE:-differ-v2-20260916}
DRB=$WS/repos/DrDocBench/.venv/bin/python
for pt in $GRID; do
  lam=${pt%%:*}; tau=${pt##*:}
  R="differ-v2-l${lam/./}-t${tau/./}-$(date -u +%Y%m%d)"
  echo "=== [$(date +%T)] $R lam=$lam tau=$tau"
  $DRB scripts/tree_differ_v2.py --docling "runs/dev/$D/predictions" --mineru "runs/dev/$M/predictions" \
      --out "runs/dev/$R/predictions" --lam "$lam" --tau "$tau" | tail -3
  printf '# %s\n- job: %s  grid point lam=%s tau=%s over docling=%s mineru=%s\n' "$R" "$SLURM_JOB_ID" "$lam" "$tau" "$D" "$M" > "runs/dev/$R/RUN.md"
  BASELINE=$BASELINE NOTE="tree_differ_v2 grid lam=$lam tau=$tau over $D + $M" bash runs/slurm/eval_run.sbatch "$R" | grep -E "^\| 2026|done"
done
echo "[$(date +%T)] grid done"
