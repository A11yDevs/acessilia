#!/bin/bash
#SBATCH --job-name=drb-matrix-v19
#SBATCH --partition=h100n2
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=04:00:00
#SBATCH --output=/raid/user_marcospaulo/drdocbench/runs/slurm/logs/%x_%j.log
# v19 matrix on dev-986: bands order, adjacent dedup, tighter fuse, chunk 800 — then eval vs 78.3.
set -uo pipefail
source /raid/user_marcospaulo/drdocbench/runs/slurm/env.sh
cd "$WS"
DRB=$WS/repos/DrDocBench/.venv/bin/python
FULL=$WS/runs/dev-full
D=$FULL/docling+rot/predictions
M=$FULL/mineru-hyb+rot/predictions

BASE="--lam 0.5 --tau 0.6 --min-len 0 --drop-docling group+unknown --decor-tail --junk-filter --text-pick auto --merge-paragraphs --suppress-regions --pic-rule quality --pic-min-blocks 4 --fuse-lines --pick-guard 1.5 --decor-wins --fuse-max-len 300 --running-heads 3 --pagenum-cap 4 --pic-need-text --line-numbers --table-eq --puzzle-filter"

declare -A V
V[v19-bands]="$BASE --fuse-h-ratio 0.6 --verse-chunk 300 --order bands"
V[v19-dedup]="$BASE --fuse-h-ratio 0.6 --verse-chunk 300 --dedup-adjacent 0.9"
V[v19-fuse04]="$BASE --fuse-h-ratio 0.4 --verse-chunk 300"
V[v19-all]="$BASE --fuse-h-ratio 0.4 --verse-chunk 300 --order bands --dedup-adjacent 0.9"
V[v19-all-c800]="$BASE --fuse-h-ratio 0.4 --verse-chunk 800 --order bands --dedup-adjacent 0.9"

RUNS=""
for name in v19-bands v19-dedup v19-fuse04 v19-all v19-all-c800; do
  echo "[$(date +%T)] $name"
  $DRB scripts/tree_differ_v2.py --docling "$D" --mineru "$M" --out "$FULL/$name/predictions" ${V[$name]} \
    | grep -E 'order-bands|dedup-adjacent|puzzle-grid|^pages' || true
  n=$(ls "$FULL/$name/predictions"/*.drbench.md | wc -l)
  echo "  n_pred=$n"
  [[ $n -eq 986 ]] || { echo "  EXPECTED 986 — abort"; exit 2; }
  RUNS="$RUNS $name"
done

echo "[$(date +%T)] eval: $RUNS"
export RUNS WINDOWS=1 PROTO=md2md CDM=auto
bash "$WS/runs/slurm/eval_full.sbatch"
echo "[$(date +%T)] done — compare against 78.3 in $FULL/LEDGER.md"
