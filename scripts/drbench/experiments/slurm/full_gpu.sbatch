#!/bin/bash
# Sequential full runs on 1 GPU: docling/mineru on the 509 EvalAI pages, then on the full dev split.
# Reentrant: each stage skips pages that already have <id>.drbench.md. Runs pipeline.sbatch as a plain script.
#SBATCH --job-name=drb-gpu-full
#SBATCH --partition=h100n2
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=12:00:00
#SBATCH --signal=B:SIGUSR1@600
#SBATCH --output=/raid/user_marcospaulo/drdocbench/runs/slurm/logs/%x_%j.log
set -uo pipefail
source /raid/user_marcospaulo/drdocbench/runs/slurm/env.sh
EVALAI=$WS/data/evalai/drdocbench-evaluation-v4/images
DEV=$WS/data/hf/dev
STOP=0; CHILD=
trap 'echo "[$(date -u +%T)] signal -> forwarding to stage"; STOP=1; kill -USR1 ${CHILD:-} 2>/dev/null' SIGUSR1 SIGTERM
nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv || true

stage() { # PROVIDER IMAGES_ROOT OUT_DIR
  (( STOP )) && return
  echo; echo "########## [$(date -u +%T)] STAGE provider=$1 root=$2 out=$3"
  PROVIDER=$1 IMAGES_ROOT=$2 OUT_DIR=$3 SAMPLE=0 SLURM_JOB_NAME=${SLURM_JOB_NAME}-$1 \
    bash "$WS/runs/slurm/pipeline.sbatch" &
  CHILD=$!; wait $CHILD; echo "stage rc=$?"
}
stage docling "$EVALAI" "$WS/runs/evalai/docling/predictions"
stage mineru  "$EVALAI" "$WS/runs/evalai/mineru/predictions"
stage docling "$DEV"    "$WS/runs/dev-full/docling/predictions"
stage mineru  "$DEV"    "$WS/runs/dev-full/mineru/predictions"
echo "########## ALL STAGES DONE"
