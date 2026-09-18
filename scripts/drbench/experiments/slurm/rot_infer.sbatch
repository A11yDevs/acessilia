#!/bin/bash
#SBATCH --job-name=drb-rot-infer
#SBATCH --partition=h100n2
#SBATCH --cpus-per-task=16
#SBATCH --mem=96G
#SBATCH --time=06:00:00
#SBATCH --signal=B:SIGUSR1@600
#SBATCH --output=/raid/user_marcospaulo/drdocbench/runs/slurm/logs/%x_%j.log
# Re-infer the rotated pages (data/rotated/<SPLIT>/items.txt) with docling then mineru on upright copies.
# CPU-only unless the job got a GPU (pipeline.sbatch decides). Reentrant.
#   sbatch --export=ALL,SPLIT=dev runs/slurm/rot_infer.sbatch     # -> runs/dev-full/{docling,mineru}-rot/predictions
#   sbatch --export=ALL,SPLIT=test runs/slurm/rot_infer.sbatch    # -> runs/evalai/{docling,mineru}-rot/predictions
set -uo pipefail
source /raid/user_marcospaulo/drdocbench/runs/slurm/env.sh
SPLIT=${SPLIT:-dev}
ROOT=$WS/data/rotated/$SPLIT
[[ $SPLIT == dev ]] && OUTBASE=$WS/runs/dev-full || OUTBASE=$WS/runs/evalai
echo "items=$(wc -l < "$ROOT/items.txt")"
STOP=0; CHILD=
trap 'echo "[$(date -u +%T)] signal -> forwarding"; STOP=1; kill -USR1 ${CHILD:-} 2>/dev/null' SIGUSR1 SIGTERM
for prov in docling mineru; do
  (( STOP )) && break
  echo; echo "########## [$(date -u +%T)] provider=$prov"
  PROVIDER=$prov IMAGES_ROOT=$ROOT ITEMS_FILE=$ROOT/items.txt OUT_DIR=$OUTBASE/$prov-rot/predictions \
    SAMPLE=0 EXTRA_ARGS=--save-raw SLURM_JOB_NAME=${SLURM_JOB_NAME}-$prov bash "$WS/runs/slurm/pipeline.sbatch" &
  CHILD=$!; wait $CHILD; echo "rc=$?"
done
for prov in docling mineru; do
  echo "$prov-rot: $(ls "$OUTBASE/$prov-rot/predictions"/*.drbench.md 2>/dev/null | wc -l) pages"
done
