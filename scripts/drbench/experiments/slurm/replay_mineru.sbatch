#!/bin/bash
#SBATCH --job-name=drb-replay-mineru
#SBATCH --partition=h100n2
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --output=/raid/user_marcospaulo/drdocbench/runs/slurm/logs/%x_%j.log
# Offline re-render of MinerU predictions from middle.json already on disk, then dev eval.
#   sbatch --export=ALL,RUN_ID=mineru-v2-20260916[,SPLIT=dev|test] runs/slurm/replay_mineru.sbatch
# dev : runs/dev/<RUN_ID>/{predictions,blocks} + eval_run pipeline (official + local + ledger)
# test: runs/evalai/<RUN_ID>/predictions (509) — build the zip separately.
set -uo pipefail
source /raid/user_marcospaulo/drdocbench/runs/slurm/env.sh
cd "$WS"
R=${RUN_ID:?}; SPLIT=${SPLIT:-dev}
TBPY=$WS/repos/acessilia-toolbox/.venv/bin/python
ACPY=$WS/repos/acessilia/.venv/bin/python
if [[ $SPLIT == dev ]]; then
  IMG=$WS/runs/dev/subset-images; IDS=$WS/runs/dev/subset_ids.txt
  RAW=$WS/runs/dev/mineru-raw; PRED=$WS/runs/dev/$R/predictions
else
  IMG=$WS/data/evalai/drdocbench-evaluation-v4/images; IDS=
  RAW=$WS/runs/evalai/mineru-raw; PRED=$WS/runs/evalai/$R/predictions
fi
echo "job=$SLURM_JOB_ID run=$R split=$SPLIT acessilia=$(git -C repos/acessilia rev-parse --short HEAD) toolbox=$(git -C repos/acessilia-toolbox rev-parse --short HEAD)"

echo "[$(date +%T)] 1. manifests from middle.json"
(cd repos/acessilia-toolbox && $TBPY "$WS/scripts/replay_mineru_manifests.py" --images "$IMG" --out "$RAW" ${IDS:+--ids "$IDS"})
echo "[$(date +%T)] 2. re-render"
(cd repos/acessilia && $ACPY "$WS/scripts/rerender_from_payloads.py" --src "$RAW" --out "$PRED")
echo "n_pred=$(ls "$PRED"/*.drbench.md | wc -l)"
mkdir -p "$(dirname "$PRED")"
cat > "$(dirname "$PRED")/RUN.md" <<EOF
# $R
- job: $SLURM_JOB_ID  date: $(date -u +%FT%TZ)  split: $SPLIT
- source: MinerU middle.json replayed (no re-inference) from repos/acessilia-toolbox/output
- change: structured canonical mapping (elements -> blocks; no heuristic line parser), no placeholder title,
  table HTML passthrough, blocks.json persisted (bbox)
- commits: acessilia=$(git -C repos/acessilia rev-parse --short HEAD) toolbox=$(git -C repos/acessilia-toolbox rev-parse --short HEAD)
EOF

if [[ $SPLIT == dev ]]; then
  echo "[$(date +%T)] 3. eval"
  export BASELINE=${BASELINE:-adjudicator-v0} NOTE="mineru structured-canonical replay"
  bash "$WS/runs/slurm/eval_run.sbatch" "$R"
fi
echo "[$(date +%T)] done"
