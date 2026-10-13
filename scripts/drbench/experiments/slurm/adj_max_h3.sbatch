#!/bin/bash
#SBATCH --job-name=drb-adjmax-home
#SBATCH --partition=h100n2,h100n3,b200n1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=10:00:00
#SBATCH --output=runs/slurm/logs/%x_%j.log
# v24 VLM stages, runnable on ANY GPU node. Each node has its own /raid (drdocbench only exists on dgx-H100-02's
# /raid: 34161 died on h100n3 "no /raid/user_marcospaulo", 34169 on b200n1 "env.sh: No such file"), so
# everything is staged on /home (NFS, the only shared fs): venv, crops (paths rewritten), images, model cache.
# GPU-only: B generate-only, A raw adjudications, C order. TEDS selection, filter, zips and dev eval run
# afterwards on dgx-H100-02 (CPU) with outputs copied back to /raid.
# GPU safety: Slurm here has no device cgroup (proctrack/pgid, task/affinity) and only exports
# CUDA_VISIBLE_DEVICES; scripts/gpu_audit.py SIGTERMs any process of this job seen on a GPU outside it.
set -uo pipefail
# Staging root on the shared NFS filesystem; override with S=<path> sbatch ... to relocate.
S=${S:-/home/user_marcospaulo/v24stage}
echo "=== $(date -u +%FT%TZ) job ${SLURM_JOB_ID:-manual} on $(hostname) CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-} SLURM_JOB_GPUS=${SLURM_JOB_GPUS:-}"
# --- preflight: fail fast with a readable reason instead of a 0 s FAILED
[[ -n ${CUDA_VISIBLE_DEVICES:-} && ${CUDA_VISIBLE_DEVICES} != NoDevFiles ]] || { echo "FATAL: no GPU allocation"; exit 4; }
[[ $(tr ',' '\n' <<< "$CUDA_VISIBLE_DEVICES" | wc -l) -eq 1 ]] || { echo "FATAL: expected exactly 1 GPU"; exit 4; }
for p in "$S/repos/acessilia-toolbox/.venv-vlm/bin/python" "$S/scripts/vlm_tables.py" "$S/scripts/gpu_audit.py" \
         "$S/runs/evalai/adjq-v24/queue_crops.jsonl" "$S/runs/dev-full/adjq-v24/queue_crops.jsonl"; do
  [[ -e $p ]] || { echo "FATAL: missing $p"; exit 4; }
done
python3 "$S/scripts/gpu_audit.py" --root $$ --watch 30 --kill >> "$S/runs/slurm/logs/gpu_audit_${SLURM_JOB_ID:-x}.log" 2>&1 &
AUDIT=$!; trap 'kill $AUDIT 2>/dev/null' EXIT

export HF_HOME=$S/hf HF_HUB_OFFLINE=1 XDG_CACHE_HOME=$S/cache TORCH_HOME=$S/cache/torch HF_HUB_ENABLE_HF_TRANSFER=0
export PATH=$HOME/.local/bin:$PATH UV_CACHE_DIR=$S/cache/uv
MODEL=${MODEL:-Qwen/Qwen3-VL-32B-Instruct-FP8}
SPLITS=${SPLITS:-test dev}
STAGES=${STAGES:-B A C}
VENV=$S/repos/acessilia-toolbox/.venv-vlm
VPY=$VENV/bin/python
nvidia-smi --query-gpu=index,name,memory.used --format=csv || true
NVCC=$(find "$VENV/lib/python3.11/site-packages/nvidia" -name nvcc -type f | sort | head -1)
export CUDA_HOME=$(dirname "$(dirname "$NVCC")") PATH=$VENV/bin:$(dirname "$NVCC"):$PATH VIRTUAL_ENV=$VENV
export VLLM_USE_FLASHINFER_SAMPLER=0 VLLM_USE_DEEP_GEMM=0 FLASHINFER_WORKSPACE_BASE=$S/cache/flashinfer
$VPY -c "import vllm; print('vllm', vllm.__version__)" || exit 3
for SPLIT in $SPLITS; do
  if [[ $SPLIT == dev ]]; then Q=$S/runs/dev-full/adjq-v24; CX=()
  else Q=$S/runs/evalai/adjq-v24; CX=(--images-root "$S/data/evalai/drdocbench-evaluation-v4/images"); fi
  for ST in $STAGES; do
    echo "===== [$(date +%T)] $SPLIT stage $ST"
    case $ST in
      B) [[ -s $Q/tab-raw.jsonl ]] || $VPY scripts/vlm_tables.py --queue "$Q/tab_crops.jsonl" --out-prefix "$Q/tab" \
             --generate-only --model "$MODEL" --enforce-eager || echo "!! stage B FAILED ($SPLIT)" ;;
      A) [[ -s $Q/adjudications.jsonl ]] || $VPY scripts/vlm_adjudicate.py --queue "$Q/queue_crops.jsonl" \
             --out "$Q/adjudications.jsonl" --max-records 200000 --skip-kinds table --model "$MODEL" --enforce-eager \
             || echo "!! stage A FAILED ($SPLIT)" ;;
      C) [[ -s $Q/order-vlm.jsonl ]] || $VPY scripts/vlm_order.py --order "$Q/order.jsonl" --out-prefix "$Q/order" \
             --images-dir "$Q/order-pages" "${CX[@]}" --model "$MODEL" --enforce-eager || echo "!! stage C FAILED ($SPLIT)" ;;
    esac
  done
  ls -la "$Q"/{tab-raw,adjudications,order-*}.jsonl 2>/dev/null
done
grep -c VIOLATION "$S/runs/slurm/logs/gpu_audit_${SLURM_JOB_ID:-x}.log" 2>/dev/null | sed 's/^/gpu_audit violations: /'
echo "[$(date +%T)] all done"
