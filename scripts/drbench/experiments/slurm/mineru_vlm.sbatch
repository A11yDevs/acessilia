#!/bin/bash
#SBATCH --job-name=drb-mineru-vlm
#SBATCH --partition=h100n2
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=10:00:00
#SBATCH --signal=B:SIGUSR1@600
#SBATCH --output=/raid/user_marcospaulo/drdocbench/runs/slurm/logs/%x_%j.log
# Lever E: MinerU 3.x VLM backend (MinerU2.5 1.2B) as third voter. Same pipeline.sbatch, but the
# toolbox `mineru` provider gets config.backend=${MINERU_BACKEND} (runs/slurm/providers-config-vlm.yaml).
# Stages (reentrant, each skips pages already done): dev-120 subset -> dev-986 -> test-509.
#   sbatch runs/slurm/mineru_vlm.sbatch            # hybrid-engine (VLM + pipeline; auto engine: vllm/lmdeploy/transformers)
#   sbatch --export=ALL,MINERU_BACKEND=vlm-engine,TAG=mineru-vlm runs/slurm/mineru_vlm.sbatch
set -uo pipefail
source /raid/user_marcospaulo/drdocbench/runs/slurm/env.sh
export MINERU_BACKEND=${MINERU_BACKEND:-hybrid-engine}   # MinerU 3.4.5 choices: pipeline | vlm-engine | hybrid-engine
export TOOLBOX_PROVIDERS_CONFIG=$WS/runs/slurm/providers-config-vlm.yaml
export MINERU_MODEL_SOURCE_OVERRIDE=huggingface   # VLM weights are fetched from HF into $HF_HOME on first use
TAG=${TAG:-mineru-hybrid}
EVALAI=$WS/data/evalai/drdocbench-evaluation-v4/images
DEV=$WS/data/hf/dev
nvidia-smi --query-gpu=index,name,memory.used,memory.total --format=csv || true
STOP=0; CHILD=
trap 'echo "[$(date -u +%T)] signal -> forwarding"; STOP=1; kill -USR1 ${CHILD:-} 2>/dev/null' SIGUSR1 SIGTERM
stage() { # IMAGES_ROOT OUT_DIR [ITEMS_FILE]
  (( STOP )) && return
  echo; echo "########## [$(date -u +%T)] STAGE backend=$MINERU_BACKEND root=$1 out=$2 items=${3:-all}"
  PROVIDER=mineru IMAGES_ROOT=$1 OUT_DIR=$2 ITEMS_FILE=${3:-} SAMPLE=0 EXTRA_ARGS=--save-raw \
    HEALTH_TIMEOUT=1800 SLURM_JOB_NAME=${SLURM_JOB_NAME} bash "$WS/runs/slurm/pipeline.sbatch" &
  CHILD=$!; wait $CHILD; echo "stage rc=$?"
}
stage "$DEV"    "$WS/runs/dev/$TAG/predictions"       "$WS/runs/dev/subset_ids.txt"
stage "$DEV"    "$WS/runs/dev-full/$TAG/predictions"
stage "$EVALAI" "$WS/runs/evalai/$TAG/predictions"
for d in runs/dev/$TAG runs/dev-full/$TAG runs/evalai/$TAG; do
  echo "$d: $(ls "$WS/$d/predictions"/*.drbench.md 2>/dev/null | wc -l) pages"
done
echo "########## ALL STAGES DONE"
