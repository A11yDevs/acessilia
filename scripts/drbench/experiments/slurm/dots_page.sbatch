#!/bin/bash
#SBATCH --job-name=drb-dots
#SBATCH --partition=h100n2
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=08:00:00
#SBATCH --output=runs/slurm/logs/%x_%j.log
# dots.ocr whole-page layout parse (scripts/dots_page_ocr.py) as another source, dev then test. Resumable.
set -uo pipefail
source "$WS/runs/slurm/env.sh"
cd "$WS"
echo "=== $(date -u +%FT%TZ) job ${SLURM_JOB_ID:-manual} on $(hostname) CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-}"
[[ -n ${CUDA_VISIBLE_DEVICES:-} && $(tr ',' '\n' <<< "$CUDA_VISIBLE_DEVICES" | wc -l) -eq 1 ]] || { echo "FATAL: expected exactly 1 GPU"; exit 4; }
python3 scripts/gpu_audit.py --root $$ --watch 30 --kill >> runs/slurm/logs/gpu_audit_${SLURM_JOB_ID:-x}.log 2>&1 &
AUDIT=$!; trap 'kill $AUDIT 2>/dev/null' EXIT
MODEL=${MODEL:-dots-studio/dots.ocr}
SPLITS=${SPLITS:-dev test}
VENV=$WS/repos/acessilia-toolbox/.venv-vlm; VPY=$VENV/bin/python
export VLLM_USE_FLASHINFER_SAMPLER=0 VLLM_USE_DEEP_GEMM=0 FLASHINFER_WORKSPACE_BASE=$CACHE_ROOT/flashinfer
NVCC=$(find "$VENV/lib/python3.11/site-packages/nvidia" -name nvcc -type f | sort | head -1)
export CUDA_HOME=$(dirname "$(dirname "$NVCC")"); export PATH=$VENV/bin:$CUDA_HOME/bin:$PATH
for SPLIT in $SPLITS; do
  echo "===== [$(date +%T)] $SPLIT"
  [[ $SPLIT == dev ]] && EXTRA_SPLIT=${EXTRA_DEV:-} || EXTRA_SPLIT=${EXTRA_TEST:-}
  if [[ $SPLIT == dev ]]; then
    $VPY scripts/dots_page_ocr.py --images-root data/hf/dev --only-gt data/hf/dev --out runs/dev-full/${OUTNAME:-dots-page}/predictions \
        --model "$MODEL" --enforce-eager ${EXTRA:-} ${EXTRA_SPLIT:-}
  else
    $VPY scripts/dots_page_ocr.py --images-root data/evalai/drdocbench-evaluation-v4/images --out runs/evalai/${OUTNAME:-dots-page}/predictions \
        --model "$MODEL" --enforce-eager ${EXTRA:-} ${EXTRA_SPLIT:-}
  fi
done
grep -c VIOLATION runs/slurm/logs/gpu_audit_${SLURM_JOB_ID:-x}.log | sed 's/^/gpu_audit violations: /'
echo "[$(date +%T)] all done"
