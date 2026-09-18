#!/bin/bash
# Generic Dr.DocBench inference job. Services (provider + toolbox) run INSIDE the job.
# Submit: sbatch -c 8 --mem 32G --time 00:40:00 --job-name X \
#   --export=ALL,PROVIDER=docling,IMAGES_ROOT=...,OUT_DIR=...,SAMPLE=2[,ITEMS_FILE=...] pipeline.sbatch
#SBATCH --partition=h100n2
#SBATCH --signal=B:SIGUSR1@300
#SBATCH --output=/raid/user_marcospaulo/drdocbench/runs/slurm/logs/%x_%j.log
set -uo pipefail
source /raid/user_marcospaulo/drdocbench/runs/slurm/env.sh

: "${PROVIDER:?docling|mineru}"; : "${IMAGES_ROOT:?}"; : "${OUT_DIR:?}"
SAMPLE=${SAMPLE:-0}; ITEMS_FILE=${ITEMS_FILE:-}; EXTRA_ARGS=${EXTRA_ARGS:-}
HEALTH_TIMEOUT=${HEALTH_TIMEOUT:-600}
TB=$WS/repos/acessilia-toolbox; ACC=$WS/repos/acessilia
mkdir -p "$OUT_DIR"; RUNLOG=$(dirname "$OUT_DIR")/run.log

# Ports derived from job id so docling and mineru jobs can share the node.
B=$(( (SLURM_JOB_ID % 100) * 10 ))
DOCLING_PORT=$((5001 + B)); MINERU_PORT=$((5002 + B)); TOOLBOX_PORT=$((8002 + B))
export DOCLING_SERVE_URL=http://localhost:$DOCLING_PORT
export MINERU_SERVE_URL=http://localhost:$MINERU_PORT
export TOOLBOX_BASE_URL=http://localhost:$TOOLBOX_PORT
export TOOLBOX_PROVIDER=$PROVIDER
export TOOLBOX_TIMEOUT_SECONDS=3600
# CPU-only unless the job got a GPU
if [[ -z "${CUDA_VISIBLE_DEVICES:-}" || -z "${SLURM_JOB_GPUS:-}" ]]; then
  export CUDA_VISIBLE_DEVICES=""
  export DOCLING_DEVICE=cpu MINERU_DEVICE_MODE=cpu
  echo "DEVICE=cpu"
else
  echo "DEVICE=gpu CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES"
fi
export OMP_NUM_THREADS=${SLURM_CPUS_PER_TASK:-8} DOCLING_NUM_THREADS=${SLURM_CPUS_PER_TASK:-8}
export DOCLING_SERVE_ENABLE_UI=0 DOCLING_SERVE_ENG_LOC_NUM_WORKERS=1 MINERU_MODEL_SOURCE=${MINERU_MODEL_SOURCE_OVERRIDE:-local}
echo "JOB=$SLURM_JOB_ID PROVIDER=$PROVIDER ports docling=$DOCLING_PORT mineru=$MINERU_PORT toolbox=$TOOLBOX_PORT"
echo "IMAGES_ROOT=$IMAGES_ROOT OUT_DIR=$OUT_DIR SAMPLE=$SAMPLE ITEMS_FILE=$ITEMS_FILE EXTRA_ARGS=$EXTRA_ARGS"
echo "acessilia=$(git -C "$ACC" rev-parse --short HEAD) toolbox=$(git -C "$TB" rev-parse --short HEAD)"

PIDS=()
cleanup() {
  echo "[$(date -u +%T)] cleanup: killing services ${PIDS[*]:-}"
  for p in "${PIDS[@]:-}"; do [[ -n "$p" ]] && kill "$p" 2>/dev/null; done
  sleep 3; for p in "${PIDS[@]:-}"; do [[ -n "$p" ]] && kill -9 "$p" 2>/dev/null; done
  echo "FINAL .drbench.md count in $OUT_DIR: $(ls "$OUT_DIR"/*.drbench.md 2>/dev/null | wc -l)"
}
on_signal() { echo "[$(date -u +%T)] signal received — stopping"; STOP=1; kill "${CHILD:-}" 2>/dev/null; }
STOP=0; CHILD=
trap on_signal SIGUSR1 SIGTERM SIGINT
trap cleanup EXIT

SVCLOG=$WS/runs/slurm/logs/${SLURM_JOB_NAME}_${SLURM_JOB_ID}
cd "$TB"
if [[ "$PROVIDER" == docling ]]; then
  .venv-docling/bin/docling-serve run --host 0.0.0.0 --port "$DOCLING_PORT" > "${SVCLOG}_docling.log" 2>&1 &
  PIDS+=($!); PROV_URL=$DOCLING_SERVE_URL/health
elif [[ "$PROVIDER" == mineru ]]; then
  .venv-mineru/bin/mineru-api --host 0.0.0.0 --port "$MINERU_PORT" > "${SVCLOG}_mineru.log" 2>&1 &
  PIDS+=($!); PROV_URL=$MINERU_SERVE_URL/openapi.json
else echo "unknown PROVIDER=$PROVIDER"; exit 2; fi
# PYTHONPATH shim patches MineruDocument (toolbox bug, see scripts/toolbox_shim/sitecustomize.py)
PYTHONPATH=$WS/scripts/toolbox_shim .venv/bin/uvicorn acessilia_toolbox.api.app:create_app --factory --host 0.0.0.0 --port "$TOOLBOX_PORT" > "${SVCLOG}_toolbox.log" 2>&1 &
PIDS+=($!)

wait_health() { # url timeout
  local t=0; until curl -sf -o /dev/null "$1"; do
    sleep 5; t=$((t+5)); (( STOP )) && exit 1
    if (( t >= $2 )); then echo "health timeout: $1"; return 1; fi
  done; echo "[$(date -u +%T)] healthy: $1 (${t}s)"; }
wait_health "$PROV_URL" "$HEALTH_TIMEOUT" || exit 1
wait_health "$TOOLBOX_BASE_URL/v1/health" 120 || exit 1
curl -s "$TOOLBOX_BASE_URL/v1/capabilities" | .venv/bin/python -c "import sys,json; d=json.load(sys.stdin); print('capabilities:', [c.get('id') or c.get('name') for c in (d if isinstance(d,list) else d.get('capabilities',d.get('items',[])))][:20])" || true

# Build item list (reentrant: skip ids already produced)
cd "$ACC"
if [[ -n "$ITEMS_FILE" ]]; then
  ALL=$(grep -v '^\s*$' "$ITEMS_FILE")
else
  ALL=$(find "$IMAGES_ROOT" -name 'page_*.jpg' | sort | while read -r f; do
    d=$(dirname "$f"); [[ $(basename "$d") == images ]] && d=$(dirname "$d")
    n=$(basename "$f" .jpg); echo "$(basename "$d")_p${n#page_}"; done)
fi
TODO=(); for id in $ALL; do [[ -s "$OUT_DIR/$id.drbench.md" ]] || TODO+=("$id"); done
if (( SAMPLE > 0 )); then TODO=("${TODO[@]:0:$SAMPLE}"); fi
echo "total=$(echo "$ALL" | wc -l) todo=${#TODO[@]}"

OK=0; FAIL=0; T0=$(date +%s)
for id in "${TODO[@]}"; do
  (( STOP )) && break
  t=$(date +%s)
  .venv/bin/python -m scripts.drbench.run_pipeline --images-root "$IMAGES_ROOT" --provider "$PROVIDER" \
      --out-dir "$OUT_DIR" --item "$id" --sample 0 $EXTRA_ARGS >> "$RUNLOG" 2>&1 &
  CHILD=$!; wait $CHILD; rc=$?
  if [[ $rc -eq 0 && -s "$OUT_DIR/$id.drbench.md" ]]; then OK=$((OK+1)); st=OK; else FAIL=$((FAIL+1)); st="FAIL(rc=$rc)"; fi
  echo "[$(date -u +%T)] $st $id $(( $(date +%s) - t ))s  (ok=$OK fail=$FAIL)"
done
T1=$(date +%s)
echo "SUMMARY provider=$PROVIDER ok=$OK fail=$FAIL elapsed=$((T1-T0))s avg=$(( OK>0 ? (T1-T0)/OK : 0 ))s/page"
