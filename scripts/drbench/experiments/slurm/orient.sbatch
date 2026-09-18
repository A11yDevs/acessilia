#!/bin/bash
#SBATCH --job-name=drb-orient
#SBATCH --partition=h100n2
#SBATCH --cpus-per-task=16
#SBATCH --mem=48G
#SBATCH --time=03:00:00
#SBATCH --output=/raid/user_marcospaulo/drdocbench/runs/slurm/logs/%x_%j.log
# Page-orientation classification (RapidOCR CPU) for dev-986 and test-509; writes
# runs/orientation_{dev,test}.json and rotated copies under data/rotated/{dev,test}/ (+ items.txt).
# Reentrant: orient_pages.py skips ids already in the JSON.
set -uo pipefail
source /raid/user_marcospaulo/drdocbench/runs/slurm/env.sh
cd "$WS"
PY=$WS/repos/.venv-orient/bin/python
export OMP_NUM_THREADS=2
echo "[$(date -u +%T)] dev"
$PY scripts/orient_pages.py --images-root data/hf/dev --out runs/orientation_dev.json --out-root data/rotated/dev --workers 8 2>&1 | grep -v -E "\[INFO\]|WARN"
echo "[$(date -u +%T)] test"
$PY scripts/orient_pages.py --images-root data/evalai/drdocbench-evaluation-v4/images --out runs/orientation_test.json --out-root data/rotated/test --workers 8 2>&1 | grep -v -E "\[INFO\]|WARN"
echo "[$(date -u +%T)] done"
