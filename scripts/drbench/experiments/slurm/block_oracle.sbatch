#!/bin/bash
#SBATCH --job-name=drb-probe-oracle
#SBATCH --partition=h100n2
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=02:30:00
#SBATCH --output=runs/slurm/logs/%x_%j.log
# Job 2 (CPU): 1) rerun differ v16-rec300 config on dev-986 with --dump-queue (adjudication queue),
# 2) block-level text oracle vs current differ (scripts/block_oracle.py),
# 3) materialise crops for the VLM adjudicator (scripts/make_crops.py).
#   sbatch runs/slurm/block_oracle.sbatch
set -uo pipefail
source "$WS/runs/slurm/env.sh"
cd "$WS"
DRB=$WS/repos/DrDocBench/.venv/bin/python
FULL=$WS/runs/dev-full
QDIR=$FULL/adjudication-queue
ARGS="--lam 0.5 --tau 0.6 --min-len 0 --drop-docling group+unknown --decor-tail --junk-filter --text-pick auto --merge-paragraphs --suppress-regions --pic-rule quality --pic-min-blocks 4 --fuse-lines --pick-guard 1.5 --decor-wins --fuse-h-ratio 0.6 --fuse-max-len 300 --running-heads 3 --pagenum-cap 4 --pic-need-text --line-numbers --table-eq --verse-chunk 300"

echo "[$(date +%T)] step 1: differ + queue dump"
$DRB scripts/tree_differ_v2.py --docling "$FULL/docling+rot/predictions" --mineru "$FULL/mineru-hyb+rot/predictions" \
    --out "$QDIR/predictions" --dump-queue "$QDIR/queue.jsonl" $ARGS || { echo "differ FAILED"; exit 2; }
echo "n_pred=$(ls "$QDIR"/predictions/*.drbench.md | wc -l) queue=$(wc -l < "$QDIR/queue.jsonl")"

echo "[$(date +%T)] step 2: block oracle"
$DRB scripts/block_oracle.py --docling "$FULL/docling+rot/predictions" --mineru "$FULL/mineru-hyb+rot/predictions" \
    --differ "$FULL/v16-hyb-rec300/predictions" --out "$FULL/block-oracle" || echo "oracle FAILED (rc=$?)"

echo "[$(date +%T)] step 3: crops"
$DRB scripts/make_crops.py --queue "$QDIR/queue.jsonl" --out "$QDIR/queue_crops.jsonl" --crops "$QDIR/crops" \
    || { echo "crops FAILED"; exit 3; }

cat > "$QDIR/RUN.md" <<EOF
# adjudication-queue (dev-986)
- job: $SLURM_JOB_ID  date: $(date -u +%FT%TZ)
- differ args: $ARGS over docling+rot + mineru-hyb+rot
- queue.jsonl: disputed/unilateral blocks (i,j index post-transform block lists; same args -> stable keys)
- queue_crops.jsonl + crops/: crops for the VLM adjudicator (job drb-vlm-adjud)
EOF
echo "[$(date +%T)] done"
