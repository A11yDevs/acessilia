#!/bin/bash
#SBATCH --job-name=drb-vlm-adjud
#SBATCH --partition=h100n2
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=08:00:00
#SBATCH --signal=B:SIGUSR1@600
#SBATCH --output=/raid/user_marcospaulo/drdocbench/runs/slurm/logs/%x_%j.log
# Job A (GPU): VLM exact-transcription adjudicator (paper's Adjudicator Agent).
#   1) venv .venv-vlm (vllm + nvcc pip — node has no /usr/local/cuda)
#   2) wide queue regen (--queue-sim 0.97, unilaterals both sides) + crops
#   3) vlm_adjudicate.py transcription mode -> adjudications.jsonl
# Differ variants + eval happen in matrix_v18.sbatch (CPU, afterany this + mineru-vlm).
set -uo pipefail
source /raid/user_marcospaulo/drdocbench/runs/slurm/env.sh
cd "$WS"
FULL=$WS/runs/dev-full
QDIR=$FULL/adjudication-queue-v2
DRB=$WS/repos/DrDocBench/.venv/bin/python
VENV=$WS/repos/acessilia-toolbox/.venv-vlm
MODEL=${MODEL:-Qwen/Qwen2.5-VL-7B-Instruct}
ARGS="--lam 0.5 --tau 0.6 --min-len 0 --drop-docling group+unknown --decor-tail --junk-filter --text-pick auto --merge-paragraphs --suppress-regions --pic-rule quality --pic-min-blocks 4 --fuse-lines --pick-guard 1.5 --decor-wins --fuse-h-ratio 0.6 --fuse-max-len 300 --running-heads 3 --pagenum-cap 4 --pic-need-text --line-numbers --table-eq --verse-chunk 300"

nvidia-smi --query-gpu=index,name,memory.used,memory.total --format=csv || true

echo "[$(date +%T)] step 1: venv vlm (+nvcc)"
if [[ ! -x $VENV/bin/python ]]; then
  uv venv "$VENV" --python 3.11 && uv pip install --python "$VENV/bin/python" "vllm>=0.9" pillow \
    || { echo "venv install FAILED"; exit 3; }
fi
uv pip install --python "$VENV/bin/python" nvidia-cuda-nvcc-cu12 || { echo "nvcc install FAILED"; exit 3; }
export CUDA_HOME=$VENV/lib/python3.11/site-packages/nvidia/cuda_nvcc
export PATH=$CUDA_HOME/bin:$PATH
"$CUDA_HOME/bin/nvcc" --version | tail -1 || { echo "nvcc missing at $CUDA_HOME"; exit 3; }
$VENV/bin/python -c "import vllm; print('vllm', vllm.__version__)"

echo "[$(date +%T)] step 2: wide queue + crops"
if [[ ! -s $QDIR/queue_crops.jsonl ]]; then
  $DRB scripts/tree_differ_v2.py --docling "$FULL/docling+rot/predictions" --mineru "$FULL/mineru-hyb+rot/predictions" \
      --out "$FULL/v16-requeue/predictions" --dump-queue "$QDIR/queue.jsonl" --queue-sim 0.97 $ARGS \
      || { echo "queue regen FAILED"; exit 4; }
  $DRB scripts/make_crops.py --queue "$QDIR/queue.jsonl" --out "$QDIR/queue_crops.jsonl" --crops "$QDIR/crops" \
      || { echo "crops FAILED"; exit 4; }
fi
echo "queue: $(wc -l < $QDIR/queue_crops.jsonl) records with crops"

echo "[$(date +%T)] step 3: VLM transcription ($MODEL)"
if [[ ! -s $QDIR/adjudications.jsonl ]]; then
  $VENV/bin/python scripts/vlm_adjudicate.py --queue "$QDIR/queue_crops.jsonl" \
      --out "$QDIR/adjudications.jsonl" --model "$MODEL" || { echo "VLM inference FAILED"; exit 5; }
else
  echo "adjudications.jsonl exists, reusing ($(wc -l < $QDIR/adjudications.jsonl) decisions)"
fi
echo "decisions: $(wc -l < $QDIR/adjudications.jsonl)"
echo "[$(date +%T)] done"
