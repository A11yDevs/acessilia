#!/bin/bash
#SBATCH --job-name=drb-judge
#SBATCH --partition=h100n2
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=08:00:00
#SBATCH --output=runs/slurm/logs/%x_%j.log
# vlm_page_judge.py on unjudged pages whose candidates differ in block count (LOOP #53): A = v29 tj3, B = Tele-vm tj3; prompts base, para.
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
L=runs/loop/blk
TA=runs/evalai/differ-v29-adf-tj3-20261009/predictions; TB=runs/evalai/teleocr-up2m2-vm-fb-adf-tj3-20261009/predictions
for PR in base para; do
  echo "===== [$(date +%T)] dev $PR"
  $VPY scripts/vlm_page_judge.py --images-root data/hf/dev --a $L/dev-A --b $L/dev-B --keys $L/dev.keys --out $L/dev-$PR.jsonl --prompt $PR --model "$MODEL" --enforce-eager
  echo "===== [$(date +%T)] test $PR"
  $VPY scripts/vlm_page_judge.py --images-root data/evalai/drdocbench-evaluation-v4/images --a $TA --b $TB --keys $L/test.keys --out $L/test-$PR.jsonl --prompt $PR --model "$MODEL" --enforce-eager
done
grep -c VIOLATION runs/slurm/logs/gpu_audit_${SLURM_JOB_ID:-x}.log | sed 's/^/gpu_audit violations: /'
echo "[$(date +%T)] all done"
