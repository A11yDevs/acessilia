#!/bin/bash
#SBATCH --job-name=drb-rerender
#SBATCH --partition=h100n2
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=01:30:00
#SBATCH --output=/raid/user_marcospaulo/drdocbench/runs/slurm/logs/%x_%j.log
# Re-render dev predictions from saved <id>.provider.json payloads (no inference) and eval.
#   sbatch --export=ALL,RUN_ID=docling-v2-20260916,SRC=runs/dev/docling-fix-20260916/predictions,BASELINE=docling-focr,NOTE="..." \
#          runs/slurm/rerender_eval.sbatch
# SRC may be a list separated by ':' (all payloads are rendered into the same run).
set -uo pipefail
source /raid/user_marcospaulo/drdocbench/runs/slurm/env.sh
cd "$WS"
R=${RUN_ID:?}; SRC=${SRC:?}; SPLIT=${SPLIT:-dev}
ACPY=$WS/repos/acessilia/.venv/bin/python
if [[ $SPLIT == dev ]]; then PRED=$WS/runs/dev/$R/predictions; else PRED=$WS/runs/evalai/$R/predictions; fi
echo "job=$SLURM_JOB_ID run=$R split=$SPLIT src=$SRC acessilia=$(git -C repos/acessilia rev-parse --short HEAD) toolbox=$(git -C repos/acessilia-toolbox rev-parse --short HEAD)"
IFS=':' read -ra SRCS <<< "$SRC"
for s in "${SRCS[@]}"; do
  [[ $s = /* ]] || s=$WS/$s
  echo "[$(date +%T)] re-render from $s"
  (cd repos/acessilia && $ACPY "$WS/scripts/rerender_from_payloads.py" --src "$s" --out "$PRED")
done
echo "n_pred=$(ls "$PRED"/*.drbench.md | wc -l)"
cat > "$(dirname "$PRED")/RUN.md" <<EOF
# $R
- job: $SLURM_JOB_ID  date: $(date -u +%FT%TZ)  split: $SPLIT
- source payloads: $SRC (re-rendered, no re-inference)
- change: ${NOTE:-structured canonical mapping}
- commits: acessilia=$(git -C repos/acessilia rev-parse --short HEAD) toolbox=$(git -C repos/acessilia-toolbox rev-parse --short HEAD)
EOF
if [[ $SPLIT == dev ]]; then
  echo "[$(date +%T)] eval"
  export BASELINE=${BASELINE:-adjudicator-v0} NOTE=${NOTE:-rerender}
  bash "$WS/runs/slurm/eval_run.sbatch" "$R"
fi
echo "[$(date +%T)] done"
