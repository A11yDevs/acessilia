#!/bin/bash
#SBATCH --job-name=drb-vlm3-zip
#SBATCH --partition=h100n2
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=06:00:00
#SBATCH --signal=B:SIGUSR1@600
#SBATCH --output=/raid/user_marcospaulo/drdocbench/runs/slurm/logs/%x_%j.log
# Fast path: reuse existing test crops → VLM adjudicate → filter → differ + submission.zip
#   sbatch --export=ALL,MODEL=Qwen/Qwen3-VL-8B-Instruct,RUN_ID=differ-v21-qwen3vl8b-20260927 \
#          runs/slurm/vlm_test_zip.sbatch
set -uo pipefail
source /raid/user_marcospaulo/drdocbench/runs/slurm/env.sh
cd "$WS"

MODEL=${MODEL:-Qwen/Qwen3-VL-8B-Instruct}
RUN_ID=${RUN_ID:-differ-v21-qwen3vl8b-20260927}
TAG=${TAG:-qwen3vl8b}
SRC_Q=${SRC_Q:-$WS/runs/evalai/adjudication-queue}
QDIR=${QDIR:-$WS/runs/evalai/adjudication-queue-$TAG}
DOCLING=${DOCLING:-docling-v3+rot}
MINERU=${MINERU:-mineru-hyb+rot}
ADJ_FILTER=${ADJ_FILTER:-sel}   # sel | tight | notab | raw
GPU_MEM=${GPU_MEM:-0.90}
MAX_LEN=${MAX_LEN:-8192}
TP=${TP:-1}

ARGS="--lam 0.5 --tau 0.6 --min-len 0 --drop-docling group+unknown --decor-tail --junk-filter --text-pick auto --merge-paragraphs --suppress-regions --pic-rule quality --pic-min-blocks 4 --fuse-lines --pick-guard 1.5 --decor-wins --fuse-h-ratio 0.6 --fuse-max-len 300 --running-heads 3 --pagenum-cap 4 --pic-need-text --line-numbers --table-eq --verse-chunk 300"

DRB=$WS/repos/DrDocBench/.venv/bin/python
PY=$WS/repos/acessilia/.venv/bin/python
VENV=$WS/repos/acessilia-toolbox/.venv-vlm
EVALAI=$WS/runs/evalai
MANIFEST=$WS/data/evalai/drdocbench-evaluation-v4/evaluation_pages.json
PRED=$EVALAI/$RUN_ID/predictions
OUT=$EVALAI/$RUN_ID/submission

echo "[$(date +%T)] MODEL=$MODEL RUN_ID=$RUN_ID TAG=$TAG filter=$ADJ_FILTER TP=$TP"
nvidia-smi --query-gpu=index,name,memory.used,memory.total --format=csv || true

echo "[$(date +%T)] step 1: venv"
if [[ ! -x $VENV/bin/python ]]; then
  uv venv "$VENV" --python 3.11 && uv pip install --python "$VENV/bin/python" "vllm>=0.9" pillow \
    || { echo "venv install FAILED"; exit 3; }
fi
RT=$($VENV/bin/python -c "import importlib.metadata as m;print(m.version('nvidia-cuda-runtime').rsplit('.',1)[0])")
uv pip install -q --python "$VENV/bin/python" "nvidia-cuda-nvcc==$RT.*" "nvidia-cuda-crt==$RT.*" || { echo "nvcc pin FAILED"; exit 3; }
export VLLM_USE_FLASHINFER_SAMPLER=0
export FLASHINFER_WORKSPACE_BASE=/raid/user_marcospaulo/cache/flashinfer
NVCC=$(find "$VENV/lib/python3.11/site-packages/nvidia" -name nvcc -type f | sort | head -1)
[[ -x $NVCC ]] || { echo "nvcc missing"; exit 3; }
export CUDA_HOME=$(dirname "$(dirname "$NVCC")")
export PATH=$VENV/bin:$CUDA_HOME/bin:$PATH
command -v ninja || uv pip install --python "$VENV/bin/python" ninja || exit 3
$VENV/bin/python -c "import vllm; print('vllm', vllm.__version__)"

echo "[$(date +%T)] step 2: reuse test crops → $QDIR"
mkdir -p "$QDIR"
if [[ ! -s $QDIR/queue_crops.jsonl ]]; then
  [[ -s $SRC_Q/queue_crops.jsonl ]] || { echo "missing $SRC_Q/queue_crops.jsonl"; exit 4; }
  # Rewrite crop paths to this QDIR via symlink of crops/
  ln -sfn "$SRC_Q/crops" "$QDIR/crops"
  # Keep absolute crop paths from SRC (they still point at SRC_Q/crops) — fine for vLLM
  cp -a "$SRC_Q/queue_crops.jsonl" "$QDIR/queue_crops.jsonl"
  [[ -f $SRC_Q/queue.jsonl ]] && cp -a "$SRC_Q/queue.jsonl" "$QDIR/queue.jsonl" || true
fi
echo "queue: $(wc -l < $QDIR/queue_crops.jsonl) records"

echo "[$(date +%T)] step 3: VLM ($MODEL)"
ADJ_RAW=$QDIR/adjudications.jsonl
if [[ ! -s $ADJ_RAW ]]; then
  $VENV/bin/python scripts/vlm_adjudicate.py \
      --queue "$QDIR/queue_crops.jsonl" \
      --out "$ADJ_RAW" \
      --model "$MODEL" \
      --max-model-len "$MAX_LEN" \
      --gpu-memory-utilization "$GPU_MEM" \
      --tensor-parallel-size "$TP" \
      || { echo "VLM inference FAILED"; exit 5; }
else
  echo "reusing $ADJ_RAW ($(wc -l < $ADJ_RAW) decisions)"
fi
$DRB scripts/filter_adjudications.py --queue "$QDIR/queue_crops.jsonl" \
    --decisions "$ADJ_RAW" --out-prefix "$QDIR/adjudications"

case "$ADJ_FILTER" in
  raw) ADJ_FILE=$ADJ_RAW ;;
  sel|tight|notab) ADJ_FILE=$QDIR/adjudications-$ADJ_FILTER.jsonl ;;
  *) echo "bad ADJ_FILTER=$ADJ_FILTER"; exit 6 ;;
esac
[[ -s $ADJ_FILE ]] || { echo "missing $ADJ_FILE"; exit 6; }
echo "using adjudications: $ADJ_FILE ($(wc -l < $ADJ_FILE))"

echo "[$(date +%T)] step 4: differ + zip"
FULL_ARGS="$ARGS --adjudications $ADJ_FILE"
echo "job=$SLURM_JOB_ID run=$RUN_ID docling=$DOCLING mineru=$MINERU"
echo "n_docling=$(ls "$EVALAI/$DOCLING/predictions"/*.drbench.md | wc -l) n_mineru=$(ls "$EVALAI/$MINERU/predictions"/*.drbench.md | wc -l)"
$DRB scripts/tree_differ_v2.py \
    --docling "$EVALAI/$DOCLING/predictions" \
    --mineru "$EVALAI/$MINERU/predictions" \
    --out "$PRED" $FULL_ARGS \
    || { echo "differ FAILED"; exit 7; }
N=$(ls "$PRED"/*.drbench.md 2>/dev/null | wc -l); echo "n_pred=$N"
mkdir -p "$EVALAI/$RUN_ID"
cat > "$EVALAI/$RUN_ID/RUN.md" <<EOF
# $RUN_ID
- job: $SLURM_JOB_ID  date: $(date -u +%FT%TZ)  split: test
- VLM model: $MODEL (filter=$ADJ_FILTER)
- scripts/tree_differ_v2.py $FULL_ARGS over docling=$DOCLING mineru=$MINERU
- adjudications: $ADJ_FILE
- commits: acessilia=$(git -C repos/acessilia rev-parse --short HEAD) toolbox=$(git -C repos/acessilia-toolbox rev-parse --short HEAD)
EOF
[[ $N -eq 509 ]] || { echo "expected 509 predictions, got $N"; exit 2; }
mkdir -p "$OUT"
$PY scripts/build_submission_manifest.py --predictions "$PRED" --manifest "$MANIFEST" --out "$OUT" \
    || { echo "build FAILED"; exit 3; }
$PY data/evalai/drdocbench-evaluation-v4/validate_submission.py "$OUT/submission.zip" --manifest "$MANIFEST" \
    > "$OUT/validate.json" 2> "$OUT/validate.stderr"
echo "validate rc=$?"; cat "$OUT/validate.json"
(cd "$OUT" && sha256sum submission.zip > sha256.txt && cat sha256.txt)
echo "[$(date +%T)] done → $OUT/submission.zip"
