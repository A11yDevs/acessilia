#!/bin/bash
#SBATCH --job-name=drb-judge
#SBATCH --partition=h100n2
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=08:00:00
#SBATCH --output=/raid/user_marcospaulo/drdocbench/runs/slurm/logs/%x_%j.log
# vlm_page_judge.py: A = hyb-judge2 (dev runs/dev-full/hyb-judge2, test hyb-v29-judge2-televm-adf) vs B in dots-m vlm-page (LOOP #48).
set -uo pipefail
source /raid/user_marcospaulo/drdocbench/runs/slurm/env.sh
cd "$WS"
echo "=== $(date -u +%FT%TZ) job ${SLURM_JOB_ID:-manual} on $(hostname) CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-}"
[[ -n ${CUDA_VISIBLE_DEVICES:-} && $(tr ',' '\n' <<< "$CUDA_VISIBLE_DEVICES" | wc -l) -eq 1 ]] || { echo "FATAL: expected exactly 1 GPU"; exit 4; }
python3 scripts/gpu_audit.py --root $$ --watch 30 --kill >> runs/slurm/logs/gpu_audit_${SLURM_JOB_ID:-x}.log 2>&1 &
AUDIT=$!; trap 'kill $AUDIT 2>/dev/null' EXIT
MODEL=${MODEL:-Qwen/Qwen3-VL-32B-Instruct-FP8}
SPLITS=${SPLITS:-dev test}
VENV=$WS/repos/acessilia-toolbox/.venv-vlm; VPY=$VENV/bin/python
export VLLM_USE_FLASHINFER_SAMPLER=0 VLLM_USE_DEEP_GEMM=0 FLASHINFER_WORKSPACE_BASE=/raid/user_marcospaulo/cache/flashinfer
NVCC=$(find "$VENV/lib/python3.11/site-packages/nvidia" -name nvcc -type f | sort | head -1)
export CUDA_HOME=$(dirname "$(dirname "$NVCC")"); export PATH=$VENV/bin:$CUDA_HOME/bin:$PATH
HT=runs/evalai/hyb-v29-judge2-televm-adf-20261009/predictions
for B in dots-m vlm-page; do
  echo "===== [$(date +%T)] dev h2$B"
  $VPY scripts/vlm_page_judge.py --images-root data/hf/dev --a runs/dev-full/hyb-judge2/predictions --b runs/dev-full/$B/predictions \
      --keys runs/dev-full/judge-h2$B.keys --out runs/dev-full/judge-h2$B.jsonl --model "$MODEL" --enforce-eager
  echo "===== [$(date +%T)] test h2$B"
  $VPY scripts/vlm_page_judge.py --images-root data/evalai/drdocbench-evaluation-v4/images --a $HT --b runs/evalai/$B/predictions \
      --keys runs/evalai/judge-h2$B.keys --out runs/evalai/judge-h2$B.jsonl --model "$MODEL" --enforce-eager
done
grep -c VIOLATION runs/slurm/logs/gpu_audit_${SLURM_JOB_ID:-x}.log | sed 's/^/gpu_audit violations: /'
echo "[$(date +%T)] all done"
