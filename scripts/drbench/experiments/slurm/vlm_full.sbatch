#!/bin/bash
#SBATCH --job-name=drb-vlm32-full
#SBATCH --partition=h100n2
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=12:00:00
#SBATCH --signal=B:SIGUSR1@600
#SBATCH --output=/raid/user_marcospaulo/drdocbench/runs/slurm/logs/%x_%j.log
# v23: Adjudicador VLM forte (Qwen3-VL-32B-FP8) com cobertura total (--queue-sim QSIM>1 => todo par casado
# entra na fila, inclusive os "agreed": ataca erros compartilhados pelos dois parsers). dev-986 e test-509.
# Fix jobs 33371/33372 (ptxas no JIT do DeepGEMM): VLLM_USE_DEEP_GEMM=0 + --enforce-eager.
# Saída: <QDIR>/adjudications{,-notab,-tight,-sel}.jsonl; differ+eval do dev em differ_variants (afterok).
set -uo pipefail
source /raid/user_marcospaulo/drdocbench/runs/slurm/env.sh
cd "$WS"
MODEL=${MODEL:-Qwen/Qwen3-VL-32B-Instruct-FP8}
TAG=${TAG:-q32full}
QSIM=${QSIM:-1.01}
SPLITS=${SPLITS:-dev test}
DRB=$WS/repos/DrDocBench/.venv/bin/python
VENV=$WS/repos/acessilia-toolbox/.venv-vlm
ARGS="--lam 0.5 --tau 0.6 --min-len 0 --drop-docling group+unknown --decor-tail --junk-filter --text-pick auto --merge-paragraphs --suppress-regions --pic-rule quality --pic-min-blocks 4 --fuse-lines --pick-guard 1.5 --decor-wins --fuse-h-ratio 0.6 --fuse-max-len 300 --running-heads 3 --pagenum-cap 4 --pic-need-text --line-numbers --table-eq --verse-chunk 300"
nvidia-smi --query-gpu=index,name,memory.used,memory.total --format=csv || true

RT=$($VENV/bin/python -c "import importlib.metadata as m;print(m.version('nvidia-cuda-runtime').rsplit('.',1)[0])")
uv pip install -q --python "$VENV/bin/python" "nvidia-cuda-nvcc==$RT.*" "nvidia-cuda-crt==$RT.*" || { echo "nvcc pin FAILED"; exit 3; }
export VLLM_USE_FLASHINFER_SAMPLER=0 VLLM_USE_DEEP_GEMM=0
export FLASHINFER_WORKSPACE_BASE=/raid/user_marcospaulo/cache/flashinfer
NVCC=$(find "$VENV/lib/python3.11/site-packages/nvidia" -name nvcc -type f | sort | head -1)
export CUDA_HOME=$(dirname "$(dirname "$NVCC")")
export PATH=$VENV/bin:$CUDA_HOME/bin:$PATH
$VENV/bin/python -c "import vllm; print('vllm', vllm.__version__)"

for SPLIT in $SPLITS; do
  if [[ $SPLIT == dev ]]; then
    QDIR=$WS/runs/dev-full/adjq-$TAG; DD=$WS/runs/dev-full/docling+rot/predictions; MD=$WS/runs/dev-full/mineru-hyb+rot/predictions; CX=()
  else
    QDIR=$WS/runs/evalai/adjq-$TAG; DD=$WS/runs/evalai/docling-v3+rot/predictions; MD=$WS/runs/evalai/mineru-hyb+rot/predictions
    CX=(--images-root "$WS/data/evalai/drdocbench-evaluation-v4/images")
  fi
  mkdir -p "$QDIR"
  echo "########## [$(date +%T)] $SPLIT -> $QDIR (qsim=$QSIM model=$MODEL)"
  if [[ ! -s $QDIR/queue_crops.jsonl ]]; then
    $DRB scripts/tree_differ_v2.py --docling "$DD" --mineru "$MD" --out "$QDIR/requeue-predictions" \
        --dump-queue "$QDIR/queue.jsonl" --queue-sim "$QSIM" $ARGS || { echo "queue FAILED"; exit 4; }
    $DRB scripts/make_crops.py --queue "$QDIR/queue.jsonl" --out "$QDIR/queue_crops.jsonl" --crops "$QDIR/crops" "${CX[@]}" \
        || { echo "crops FAILED"; exit 4; }
  fi
  echo "queue: $(wc -l < $QDIR/queue_crops.jsonl) records"
  if [[ ! -s $QDIR/adjudications.jsonl ]]; then
    $VENV/bin/python scripts/vlm_adjudicate.py --queue "$QDIR/queue_crops.jsonl" --out "$QDIR/adjudications.jsonl" \
        --model "$MODEL" --max-records 200000 --enforce-eager || { echo "VLM FAILED"; exit 5; }
  fi
  $DRB scripts/filter_adjudications.py --queue "$QDIR/queue_crops.jsonl" --decisions "$QDIR/adjudications.jsonl" \
      --out-prefix "$QDIR/adjudications"
  wc -l "$QDIR"/adjudications*.jsonl
done
echo "[$(date +%T)] done"
