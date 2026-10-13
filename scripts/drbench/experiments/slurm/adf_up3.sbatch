#!/bin/bash
#SBATCH --job-name=drb-adfup3
#SBATCH --partition=h100n2
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=02:00:00
#SBATCH --output=runs/slurm/logs/%x_%j.log
# Test doc adf56403 (15 pages, 491x396, rotated 90 deg): Tele / dots / Qwen3-VL page OCR on upright 3x-upscaled copies.
set -uo pipefail
source "$WS/runs/slurm/env.sh"
cd "$WS"
echo "=== $(date -u +%FT%TZ) job ${SLURM_JOB_ID:-manual} on $(hostname) CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-}"
[[ -n ${CUDA_VISIBLE_DEVICES:-} && $(tr ',' '\n' <<< "$CUDA_VISIBLE_DEVICES" | wc -l) -eq 1 ]] || { echo "FATAL: expected exactly 1 GPU"; exit 4; }
python3 scripts/gpu_audit.py --root $$ --watch 30 --kill >> runs/slurm/logs/gpu_audit_${SLURM_JOB_ID:-x}.log 2>&1 &
AUDIT=$!; trap 'kill $AUDIT 2>/dev/null' EXIT
VENV=$WS/repos/acessilia-toolbox/.venv-vlm; VPY=$VENV/bin/python
export VLLM_USE_FLASHINFER_SAMPLER=0 VLLM_USE_DEEP_GEMM=0 FLASHINFER_WORKSPACE_BASE=$CACHE_ROOT/flashinfer
NVCC=$(find "$VENV/lib/python3.11/site-packages/nvidia" -name nvcc -type f | sort | head -1)
export CUDA_HOME=$(dirname "$(dirname "$NVCC")"); export PATH=$VENV/bin:$CUDA_HOME/bin:$PATH
R=data/rotated/test-adf-up3
$VPY scripts/teleocr_page_ocr.py --images-root $R --out runs/evalai/adfup3-tele/predictions --ngram 100 --max-tokens 14000
$VPY scripts/dots_page_ocr.py --images-root $R --out runs/evalai/adfup3-dots/predictions --enforce-eager --hf-end --ngram 30
$VPY scripts/vlm_page_ocr.py --images-root $R --out runs/evalai/adfup3-vlm/predictions --enforce-eager
grep -c VIOLATION runs/slurm/logs/gpu_audit_${SLURM_JOB_ID:-x}.log | sed 's/^/gpu_audit violations: /'
echo "[$(date +%T)] all done"
