#!/bin/bash
# CPU: fila completa (qsim 1.01) + crops para dev e test (v23)
source /raid/user_marcospaulo/drdocbench/runs/slurm/env.sh; cd "$WS"
DRB=$WS/repos/DrDocBench/.venv/bin/python
ARGS="--lam 0.5 --tau 0.6 --min-len 0 --drop-docling group+unknown --decor-tail --junk-filter --text-pick auto --merge-paragraphs --suppress-regions --pic-rule quality --pic-min-blocks 4 --fuse-lines --pick-guard 1.5 --decor-wins --fuse-h-ratio 0.6 --fuse-max-len 300 --running-heads 3 --pagenum-cap 4 --pic-need-text --line-numbers --table-eq --verse-chunk 300"
run(){ Q=$1; D=$2; M=$3; shift 3; mkdir -p $Q
  $DRB scripts/tree_differ_v2.py --docling $D --mineru $M --out $Q/requeue-predictions --dump-queue $Q/queue.jsonl --queue-sim 1.01 $ARGS | tail -3
  $DRB scripts/make_crops.py --queue $Q/queue.jsonl --out $Q/queue_crops.jsonl --crops $Q/crops "$@" | tail -2
  echo "$Q: $(wc -l < $Q/queue_crops.jsonl)"; }
run runs/dev-full/adjq-q32full runs/dev-full/docling+rot/predictions runs/dev-full/mineru-hyb+rot/predictions &
run runs/evalai/adjq-q32full runs/evalai/docling-v3+rot/predictions runs/evalai/mineru-hyb+rot/predictions --images-root data/evalai/drdocbench-evaluation-v4/images &
wait
