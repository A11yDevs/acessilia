#!/bin/bash
#SBATCH --job-name=drb-lib-infer
#SBATCH --partition=h100n2
#SBATCH --cpus-per-task=16
#SBATCH --mem=96G
#SBATCH --time=08:00:00
#SBATCH --signal=B:SIGUSR1@600
#SBATCH --output=/raid/user_marcospaulo/drdocbench/runs/slurm/logs/%x_%j.log
# Inferência docling + mineru EM PARALELO com --save-raw (payloads blocks.json
# necessários para a fusão via lib docstruct). Reentrante: pula ids já produzidos.
#   sbatch --export=ALL,SPLIT=dev runs/slurm/lib_infer.sbatch
#     -> runs/dev-full/{docling-lib,mineru-lib}/predictions
#   sbatch --export=ALL,SPLIT=test runs/slurm/lib_infer.sbatch
#     -> runs/evalai/{docling-lib,mineru-lib}/predictions
# Reusa predictions existentes de runs anteriores quando os blocks.json já
# existem (DOCLING_REUSE/MINERU_REUSE), evitando re-inferência desnecessária.
set -uo pipefail
source /raid/user_marcospaulo/drdocbench/runs/slurm/env.sh
SPLIT=${SPLIT:-dev}
[[ $SPLIT == dev ]] && OUTBASE=$WS/runs/dev-full || OUTBASE=$WS/runs/evalai
DOCLING_REUSE=${DOCLING_REUSE:-}; MINERU_REUSE=${MINERU_REUSE:-}
STOP=0; CHILD=
trap 'echo "[$(date -u +%T)] signal -> forwarding"; STOP=1; kill -USR1 ${CHILD:-} 2>/dev/null' SIGUSR1 SIGTERM

run_provider() { # provider outdir reuse_dir
  local prov=$1 out=$2 reuse=$3
  local src_root=$IMAGES_ROOT src_items=$ITEMS_FILE
  if [[ -n $reuse && -d $reuse ]]; then
    # Copia os artefatos já produzidos (reentrante) e infere só o que falta.
    mkdir -p "$out"
    cp -a "$reuse"/. "$out"/ 2>/dev/null || true
    echo "[$(date -u +%T)] $prov: reusing $(ls "$out"/*.drbench.md 2>/dev/null | wc -l) pages from $reuse"
  fi
  PROVIDER=$prov IMAGES_ROOT=$src_root ITEMS_FILE=$src_items OUT_DIR=$out \
    SAMPLE=0 EXTRA_ARGS=--save-raw SLURM_JOB_NAME=${SLURM_JOB_NAME}-$prov \
    bash "$WS/runs/slurm/pipeline.sbatch"
}

echo "[$(date -u +%T)] lib_infer start split=$SPLIT"
run_provider docling "$OUTBASE/docling-lib/predictions" "$DOCLING_REUSE" &
P1=$!
run_provider mineru "$OUTBASE/mineru-lib/predictions" "$MINERU_REUSE" &
P2=$!
CHILD=$P1; wait $P1; echo "docling-lib rc=$?"
CHILD=$P2; wait $P2; echo "mineru-lib rc=$?"
for prov in docling-lib mineru-lib; do
  echo "$prov: $(ls "$OUTBASE/$prov/predictions"/*.drbench.md 2>/dev/null | wc -l) pages, $(ls "$OUTBASE/$prov/predictions"/*.blocks.json 2>/dev/null | wc -l) blocks.json"
done
echo "[$(date -u +%T)] done"
