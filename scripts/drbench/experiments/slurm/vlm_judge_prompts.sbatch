#!/bin/bash
#SBATCH --job-name=drb-judge
#SBATCH --partition=h100n2
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=08:00:00
#SBATCH --output=runs/slurm/logs/%x_%j.log
# vlm_page_judge.py: Qwen3-VL pairwise A (v29-pn dev / v29-adf test) vs B (Tele-vm-fb; LOOP #42), dev then test.
set -uo pipefail
source "$WS/runs/slurm/env.sh"
cd "$WS"
echo "=== $(date -u +%FT%TZ) job ${SLURM_JOB_ID:-manual} on $(hostname) CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-}"
[[ -n ${CUDA_VISIBLE_DEVICES:-} && $(tr ',' '\n' <<< "$CUDA_VISIBLE_DEVICES" | wc -l) -eq 1 ]] || { echo "FATAL: expected exactly 1 GPU"; exit 4; }
python3 scripts/gpu_audit.py --root $$ --watch 30 --kill >> runs/slurm/logs/gpu_audit_${SLURM_JOB_ID:-x}.log 2>&1 &
AUDIT=$!; trap 'kill $AUDIT 2>/dev/null' EXIT
MODEL=${MODEL:-Qwen/Qwen3-VL-32B-Instruct-FP8}
SPLITS=${SPLITS:-dev test}
VENV=$WS/repos/acessilia-toolbox/.venv-vlm; VPY=$VENV/bin/python
export VLLM_USE_FLASHINFER_SAMPLER=0 VLLM_USE_DEEP_GEMM=0 FLASHINFER_WORKSPACE_BASE=$CACHE_ROOT/flashinfer
NVCC=$(find "$VENV/lib/python3.11/site-packages/nvidia" -name nvcc -type f | sort | head -1)
export CUDA_HOME=$(dirname "$(dirname "$NVCC")"); export PATH=$VENV/bin:$CUDA_HOME/bin:$PATH
MODEL=${MODEL:-Qwen/Qwen3-VL-32B-Instruct-FP8}
for PR in para err; do B=televm
  echo "===== [$(date +%T)] dev $B $PR"
  $VPY scripts/vlm_page_judge.py --images-root data/hf/dev --a runs/dev-full/v29-pn/predictions --b runs/dev-full/teleocr-vm-fb/predictions \
      --keys runs/dev-full/judge-$B.keys --out runs/dev-full/judge-$B-$PR.jsonl --prompt $PR --model "$MODEL" --enforce-eager
done
for PR in para err; do B=televm
  echo "===== [$(date +%T)] test $B $PR"
  $VPY scripts/vlm_page_judge.py --images-root data/evalai/drdocbench-evaluation-v4/images --a runs/evalai/differ-v29-adf-20261009/predictions \
      --b runs/evalai/teleocr-up2m2-vm-fb-adf-20261009/predictions --keys runs/evalai/judge-$B.keys --out runs/evalai/judge-$B-$PR.jsonl --prompt $PR --model "$MODEL" --enforce-eager
done
grep -c VIOLATION runs/slurm/logs/gpu_audit_${SLURM_JOB_ID:-x}.log | sed 's/^/gpu_audit violations: /'
echo "[$(date +%T)] all done"
