#!/bin/bash
# Run the core on a dataset with scripts.bench. The provider and the Toolbox
# run INSIDE the job, on ports derived from the job id, so several jobs can
# share a node. Re-submitting the same RUN resumes where it stopped.
# Submit from $WS:
#   sbatch -p <partition> -c 8 --mem 32G --time 04:00:00 --job-name X \
#     --export=ALL,WS=$PWD,DATASET=drdocbench,ROOT=$PWD/data/drdocbench/dev,RUN=docling-v1,PROVIDER=docling[,SPLIT=dev,SAMPLE=20,SCORE=1] \
#     repos/acessilia/scripts/bench/slurm/bench.sbatch
#SBATCH --signal=B:SIGUSR1@300
#SBATCH --output=logs/slurm/%x_%j.log
set -uo pipefail
source "$WS/repos/acessilia/scripts/bench/slurm/env.sh"

: "${DATASET:?}"; : "${ROOT:?}"; : "${RUN:?}"; : "${PROVIDER:?docling|mineru}"
SPLIT=${SPLIT:-dev}; SAMPLE=${SAMPLE:-}; SCORE=${SCORE:-1}
HEALTH_TIMEOUT=${HEALTH_TIMEOUT:-600}
TB=$WS/repos/acessilia-toolbox; ACC=$WS/repos/acessilia

B=$(( (SLURM_JOB_ID % 100) * 10 ))
DOCLING_PORT=$((5001 + B)); MINERU_PORT=$((5002 + B)); TOOLBOX_PORT=$((8002 + B))
export DOCLING_SERVE_URL=http://localhost:$DOCLING_PORT
export MINERU_SERVE_URL=http://localhost:$MINERU_PORT
export TOOLBOX_BASE_URL=http://localhost:$TOOLBOX_PORT
export TOOLBOX_PROVIDER=$PROVIDER
export TOOLBOX_TIMEOUT_SECONDS=3600
if [[ -z "${CUDA_VISIBLE_DEVICES:-}" || -z "${SLURM_JOB_GPUS:-}" ]]; then
  export CUDA_VISIBLE_DEVICES="" DOCLING_DEVICE=cpu MINERU_DEVICE_MODE=cpu
  echo "DEVICE=cpu"
else
  echo "DEVICE=gpu CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES"
fi
export OMP_NUM_THREADS=${SLURM_CPUS_PER_TASK:-8} DOCLING_NUM_THREADS=${SLURM_CPUS_PER_TASK:-8}
export DOCLING_SERVE_ENABLE_UI=0 DOCLING_SERVE_ENG_LOC_NUM_WORKERS=1 MINERU_MODEL_SOURCE=local
echo "JOB=$SLURM_JOB_ID DATASET=$DATASET SPLIT=$SPLIT RUN=$RUN PROVIDER=$PROVIDER ROOT=$ROOT"
echo "acessilia=$(git -C "$ACC" rev-parse --short HEAD) toolbox=$(git -C "$TB" rev-parse --short HEAD)"

PIDS=(); CHILD=; STOP=0
cleanup() {
  for p in "${PIDS[@]:-}"; do [[ -n "$p" ]] && kill "$p" 2>/dev/null; done
  sleep 3; for p in "${PIDS[@]:-}"; do [[ -n "$p" ]] && kill -9 "$p" 2>/dev/null; done
}
on_signal() { echo "[$(date -u +%T)] signal received, stopping (resubmit to resume)"; STOP=1; kill "${CHILD:-}" 2>/dev/null; }
trap on_signal SIGUSR1 SIGTERM SIGINT
trap cleanup EXIT

SVCLOG=$WS/logs/slurm/${SLURM_JOB_NAME}_${SLURM_JOB_ID}
cd "$TB"
case "$PROVIDER" in
  docling) .venv-docling/bin/docling-serve run --host 0.0.0.0 --port "$DOCLING_PORT" > "${SVCLOG}_docling.log" 2>&1 &
           PROV_URL=$DOCLING_SERVE_URL/health ;;
  mineru)  .venv-mineru/bin/mineru-api --host 0.0.0.0 --port "$MINERU_PORT" > "${SVCLOG}_mineru.log" 2>&1 &
           PROV_URL=$MINERU_SERVE_URL/openapi.json ;;
  *) echo "unknown PROVIDER=$PROVIDER"; exit 2 ;;
esac
PIDS+=($!)
.venv/bin/uvicorn acessilia_toolbox.api.app:create_app --factory --host 0.0.0.0 --port "$TOOLBOX_PORT" \
    > "${SVCLOG}_toolbox.log" 2>&1 &
PIDS+=($!)

wait_health() { # url timeout
  local t=0; until curl -sf -o /dev/null "$1"; do
    sleep 5; t=$((t+5)); (( STOP )) && exit 1
    if (( t >= $2 )); then echo "health timeout: $1"; return 1; fi
  done; echo "[$(date -u +%T)] healthy: $1 (${t}s)"; }
wait_health "$PROV_URL" "$HEALTH_TIMEOUT" || exit 1
wait_health "$TOOLBOX_BASE_URL/v1/health" 120 || exit 1

cd "$ACC"
BENCH=(uv run --frozen python -m scripts.bench)
"${BENCH[@]}" run --dataset "$DATASET" --split "$SPLIT" --root "$ROOT" --run "$RUN" \
    --provider "$PROVIDER" --resume ${SAMPLE:+--sample "$SAMPLE"} &
CHILD=$!; wait $CHILD; rc=$?
echo "[$(date -u +%T)] run exit=$rc"
if (( ! STOP )) && [[ "$SCORE" == 1 ]]; then
  "${BENCH[@]}" score --dataset "$DATASET" --split "$SPLIT" --root "$ROOT" --run "$RUN"
fi
exit $rc
