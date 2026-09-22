#!/bin/bash
#SBATCH --job-name=drb-lib-exp
#SBATCH --partition=h100n2
#SBATCH --cpus-per-task=16
#SBATCH --mem=96G
#SBATCH --time=12:00:00
#SBATCH --signal=B:SIGUSR1@600
#SBATCH --output=/raid/user_marcospaulo/drdocbench/runs/slurm/logs/%x_%j.log
# Experimento de integração da lib docstruct — ponta a ponta:
#   1. inferência docling+mineru com --save-raw (reusa runs anteriores)
#   2. fusão via lib (preset v12) + baseline via script de referência
#   3. avaliação md2md oficial + relatório de comparação
#
#   sbatch --export=ALL,SPLIT=dev runs/slurm/lib_experiment.sbatch
#   SPLIT=test também funciona (avaliação é pulada — test não tem GT local).
#
# Dependências de runs anteriores (opcionais, aceleram):
#   DOCLING_REUSE=runs/dev-full/docling-v3-20260916/predictions
#   MINERU_REUSE=runs/dev-full/mineru-v3-20260916/predictions
#   ROT_REUSE=1  -> usa docling+rot/mineru+rot como base (v10/v12 usam +rot)
set -uo pipefail
source /raid/user_marcospaulo/drdocbench/runs/slurm/env.sh
cd "$WS"
SPLIT=${SPLIT:-dev}
[[ $SPLIT == dev ]] && OUTBASE=$WS/runs/dev-full || OUTBASE=$WS/runs/evalai
STAMP=$(date +%Y%m%d)
DOCLING_REUSE=${DOCLING_REUSE:-}
MINERU_REUSE=${MINERU_REUSE:-}
if [[ ${ROT_REUSE:-0} == 1 ]]; then
  DOCLING_REUSE=${DOCLING_REUSE:-$OUTBASE/docling+rot/predictions}
  MINERU_REUSE=${MINERU_REUSE:-$OUTBASE/mineru+rot/predictions}
fi
RUN_LIB="lib-fuse-v12-$STAMP"
RUN_SCRIPT="lib-fuse-script-$STAMP"

echo "===== [$(date -u +%T)] etapa 1: inferência (--save-raw)"
sbatch --wait --export=ALL,SPLIT=$SPLIT,DOCLING_REUSE="$DOCLING_REUSE",MINERU_REUSE="$MINERU_REUSE" \
    --job-name=${SLURM_JOB_NAME}-infer runs/slurm/lib_infer.sbatch || exit 1

echo "===== [$(date -u +%T)] etapa 2a: fusão via lib (v12)"
sbatch --wait --export=ALL,SPLIT=$SPLIT,POLICY=v12,RUN_NAME=$RUN_LIB \
    --job-name=${SLURM_JOB_NAME}-fuse runs/slurm/lib_fuse.sbatch || exit 1

echo "===== [$(date -u +%T)] etapa 2b: baseline via script de referência"
sbatch --wait --export=ALL,SPLIT=$SPLIT,POLICY=script,RUN_NAME=$RUN_SCRIPT \
    --job-name=${SLURM_JOB_NAME}-fuse runs/slurm/lib_fuse.sbatch || exit 1

if [[ $SPLIT == dev ]]; then
  echo "===== [$(date -u +%T)] etapa 3: avaliação md2md + comparação"
  sbatch --wait --export=ALL,SPLIT=$SPLIT,RUNS="$RUN_LIB $RUN_SCRIPT" \
      --job-name=${SLURM_JOB_NAME}-eval runs/slurm/lib_eval.sbatch || exit 1
  echo "Relatório: $OUTBASE/lib-integration-report.md"
else
  echo "SPLIT=test: sem GT local — pule a avaliação; use differ_test_zip.sbatch para submissão."
fi
echo "===== [$(date -u +%T)] experimento concluído"
