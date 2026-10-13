#!/bin/bash
#SBATCH --job-name=drb-adjmax-v24
#SBATCH --partition=h100n2
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=10:00:00
#SBATCH --output=/raid/user_marcospaulo/drdocbench/runs/slurm/logs/%x_%j.log
# v24 "adjudicador máximo" (paper: VLM especialista generate-compare-adjudicate + adjudicador select/edit).
# Por split (dev-986, test-509), Qwen3-VL-32B-FP8 (fallback BF16), estágios retomáveis:
#   B tabelas: vlm_tables.py (1 greedy + 3 amostras, medoide TEDS vs Docling/MinerU) -> tab-{medoid,greedy}.jsonl
#   A texto:   vlm_adjudicate.py --skip-kinds table + filter -> adjudications{,-sel,-tight,-notab}.jsonl
#   C ordem:   vlm_order.py (caixas numeradas na página) -> order-{sel,vlm}.jsonl
# Depois (CPU, no mesmo job p/ não esperar fila): zips de teste de todas as combinações + eval dev md2md.
set -uo pipefail
source /raid/user_marcospaulo/drdocbench/runs/slurm/env.sh
cd "$WS"
MODEL=${MODEL:-Qwen/Qwen3-VL-32B-Instruct-FP8}
FALLBACK=${FALLBACK:-Qwen/Qwen3-VL-32B-Instruct}
TAG=${TAG:-v24}
DATE=${DATE:-20261008}
SPLITS=${SPLITS:-dev test}
STAGES=${STAGES:-B A C}
DRB=$WS/repos/DrDocBench/.venv/bin/python
PY=$WS/repos/acessilia/.venv/bin/python
VENV=$WS/repos/acessilia-toolbox/.venv-vlm
VPY=$VENV/bin/python
MANIFEST=$WS/data/evalai/drdocbench-evaluation-v4/evaluation_pages.json
ARGS="--lam 0.5 --tau 0.6 --min-len 0 --drop-docling group+unknown --decor-tail --junk-filter --text-pick auto --merge-paragraphs --suppress-regions --pic-rule quality --pic-min-blocks 4 --fuse-lines --pick-guard 1.5 --decor-wins --fuse-h-ratio 0.6 --fuse-max-len 300 --running-heads 3 --pagenum-cap 4 --pic-need-text --line-numbers --table-eq --verse-chunk 300"
nvidia-smi --query-gpu=index,name,memory.used,memory.total --format=csv || true

RT=$($VPY -c "import importlib.metadata as m;print(m.version('nvidia-cuda-runtime').rsplit('.',1)[0])")
uv pip install -q --python "$VPY" "nvidia-cuda-nvcc==$RT.*" "nvidia-cuda-crt==$RT.*" || { echo "nvcc pin FAILED"; exit 3; }
export VLLM_USE_FLASHINFER_SAMPLER=0 VLLM_USE_DEEP_GEMM=0
export FLASHINFER_WORKSPACE_BASE=/raid/user_marcospaulo/cache/flashinfer
NVCC=$(find "$VENV/lib/python3.11/site-packages/nvidia" -name nvcc -type f | sort | head -1)
export CUDA_HOME=$(dirname "$(dirname "$NVCC")")
export PATH=$VENV/bin:$CUDA_HOME/bin:$PATH
$VPY -c "import vllm; print('vllm', vllm.__version__)"

# run a VLM stage with MODEL, retry once with FALLBACK (BF16) if it fails
vlm() { $VPY "$@" --model "$MODEL" --enforce-eager && return 0
        echo "!! stage failed with $MODEL -> retry $FALLBACK"; $VPY "$@" --model "$FALLBACK" --enforce-eager; }

split_vars() {
  if [[ $1 == dev ]]; then
    QDIR=$WS/runs/dev-full/adjq-$TAG; DD=$WS/runs/dev-full/docling+rot/predictions; MD=$WS/runs/dev-full/mineru-hyb+rot/predictions; CX=()
  else
    QDIR=$WS/runs/evalai/adjq-$TAG; DD=$WS/runs/evalai/docling-v3+rot/predictions; MD=$WS/runs/evalai/mineru-hyb+rot/predictions
    CX=(--images-root "$WS/data/evalai/drdocbench-evaluation-v4/images")
  fi
}

for SPLIT in $SPLITS; do
  split_vars $SPLIT; mkdir -p "$QDIR"
  echo "########## [$(date +%T)] $SPLIT -> $QDIR (model=$MODEL stages=$STAGES)"
  if [[ ! -s $QDIR/queue_crops.jsonl || ! -s $QDIR/order.jsonl ]]; then
    $DRB scripts/tree_differ_v2.py --docling "$DD" --mineru "$MD" --out "$QDIR/requeue-predictions" $ARGS \
        --dump-queue "$QDIR/queue.jsonl" --queue-sim 1.01 --queue-tables --dump-order "$QDIR/order.jsonl" \
        | tail -3 || { echo "queue FAILED"; exit 4; }
    $DRB scripts/make_crops.py --queue "$QDIR/queue.jsonl" --out "$QDIR/tab_crops.jsonl" --crops "$QDIR/crops-tab" \
        --kinds table --max-side 2240 "${CX[@]}" || { echo "tab crops FAILED"; exit 4; }
    $DRB scripts/make_crops.py --queue "$QDIR/queue.jsonl" --out "$QDIR/queue_crops.jsonl" --crops "$QDIR/crops" \
        "${CX[@]}" || { echo "crops FAILED"; exit 4; }
  fi
  echo "queue: $(wc -l < $QDIR/queue_crops.jsonl) text+tab, $(wc -l < $QDIR/tab_crops.jsonl) tab, $(wc -l < $QDIR/order.jsonl) order pages"
  for ST in $STAGES; do
    echo "===== [$(date +%T)] $SPLIT stage $ST"
    case $ST in
      B) [[ -s $QDIR/tab-raw.jsonl ]] || vlm scripts/vlm_tables.py --queue "$QDIR/tab_crops.jsonl" \
             --out-prefix "$QDIR/tab" --generate-only || echo "!! stage B FAILED ($SPLIT)"
         [[ -s $QDIR/tab-raw.jsonl ]] && $DRB scripts/vlm_tables.py --queue "$QDIR/tab_crops.jsonl" \
             --out-prefix "$QDIR/tab" --select-only --workers 15 ;;
      A) if [[ ! -s $QDIR/adjudications.jsonl ]]; then
           vlm scripts/vlm_adjudicate.py --queue "$QDIR/queue_crops.jsonl" --out "$QDIR/adjudications.jsonl" \
               --max-records 200000 --skip-kinds table || echo "!! stage A FAILED ($SPLIT)"
         fi
         [[ -s $QDIR/adjudications.jsonl ]] && $DRB scripts/filter_adjudications.py --queue "$QDIR/queue_crops.jsonl" \
             --decisions "$QDIR/adjudications.jsonl" --out-prefix "$QDIR/adjudications" ;;
      C) [[ -s $QDIR/order-vlm.jsonl ]] || vlm scripts/vlm_order.py --order "$QDIR/order.jsonl" --out-prefix "$QDIR/order" \
             --images-dir "$QDIR/order-pages" "${CX[@]}" || echo "!! stage C FAILED ($SPLIT)" ;;
    esac
  done
  wc -l "$QDIR"/{tab-*,adjudications*,order-*}.jsonl 2>/dev/null
done
echo "[$(date +%T)] VLM stages done"
[[ ${SKIP_POST:-0} == 1 ]] && exit 0

# ---------- combinations: name|text-adj|table-adj|order-adj (empty = none)
COMBOS="T||tab-medoid|
Tg||tab-greedy|
Asel|adjudications-sel||
Atight|adjudications-tight||
AT|adjudications-sel|tab-medoid|
ATg|adjudications-sel|tab-greedy|
Osel|||order-sel
Ovlm|||order-vlm
ATOs|adjudications-sel|tab-medoid|order-sel
ATOv|adjudications-sel|tab-medoid|order-vlm"
combo_args() {  # $1=QDIR $2=name $3=text $4=tab $5=order -> echoes extra args ("" if some input missing)
  local Q=$1 N=$2 X=""; local F=$Q/combo-$2.jsonl
  : > "$F"
  for k in $3 $4; do [[ -s $Q/$k.jsonl ]] || { echo MISSING; return; }; cat "$Q/$k.jsonl" >> "$F"; done
  [[ -s $F ]] && X="--adjudications $F"
  if [[ -n $5 ]]; then [[ -s $Q/$5.jsonl ]] || { echo MISSING; return; }; X="$X --order-adjudications $Q/$5.jsonl"; fi
  echo "$X"
}

echo "########## [$(date +%T)] test zips"
split_vars test
while IFS='|' read -r N TX TB OR; do
  X=$(combo_args "$QDIR" "$N" "$TX" "$TB" "$OR"); [[ $X == MISSING ]] && { echo "skip $N (missing inputs)"; continue; }
  RUN=$WS/runs/evalai/differ-$TAG-$N-$DATE; PRED=$RUN/predictions; OUT=$RUN/submission
  $DRB scripts/tree_differ_v2.py --docling "$DD" --mineru "$MD" --out "$PRED" $ARGS $X | grep -E "adjudications|forced" | tr '\n' ' '
  NP=$(ls "$PRED"/*.drbench.md 2>/dev/null | wc -l)
  printf '# differ-%s-%s\n- job %s %s\n- tree_differ_v2 %s %s\n- docling=%s mineru=%s model=%s\n' "$TAG" "$N" \
      "$SLURM_JOB_ID" "$(date -u +%FT%TZ)" "$ARGS" "$X" "$DD" "$MD" "$MODEL" > "$RUN/RUN.md"
  [[ $NP -eq 509 ]] || { echo "!! $N: $NP predictions"; continue; }
  mkdir -p "$OUT"
  $PY scripts/build_submission_manifest.py --predictions "$PRED" --manifest "$MANIFEST" --out "$OUT" >/dev/null || { echo "!! $N build FAILED"; continue; }
  $PY data/evalai/drdocbench-evaluation-v4/validate_submission.py "$OUT/submission.zip" --manifest "$MANIFEST" \
      > "$OUT/validate.json" 2> "$OUT/validate.stderr"; RC=$?
  (cd "$OUT" && sha256sum submission.zip > sha256.txt)
  echo "zip $N rc=$RC $(cut -c1-12 $OUT/sha256.txt) -> $OUT/submission.zip"
done <<< "$COMBOS"

echo "########## [$(date +%T)] dev eval"
split_vars dev
VF=$WS/runs/dev-full/variants_$TAG.txt; : > "$VF"
while IFS='|' read -r N TX TB OR; do
  X=$(combo_args "$QDIR" "$N" "$TX" "$TB" "$OR"); [[ $X == MISSING ]] && { echo "skip $N"; continue; }
  echo "$TAG-$N|${ARGS#--lam 0.5 --tau 0.6 --min-len 0 } $X|mineru-hyb+rot" >> "$VF"
done <<< "$COMBOS"
cat "$VF" | cut -d'|' -f1
VARIANTS_FILE=$VF DOCLING_DIR=$WS/runs/dev-full/docling+rot/predictions EXTRA_RUNS="v16-hyb-rec300 v20-vlm-sel" \
    bash "$WS/runs/slurm/differ_variants.sbatch"
echo "[$(date +%T)] all done"
