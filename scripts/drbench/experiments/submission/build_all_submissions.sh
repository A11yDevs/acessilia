#!/bin/bash
# Build + validate EvalAI submission zips for docling-forceocr, mineru and
# adjudicator-v0 (the latter is (re)built from the two others first).
# Run via Slurm, e.g.:
#   srun -p h100n2 -c 4 --mem 16G --time 00:20:00 bash scripts/build_all_submissions.sh
set -uo pipefail
WS=/raid/user_marcospaulo/drdocbench
source $WS/runs/slurm/env.sh
PY=$WS/repos/acessilia/.venv/bin/python
EVALAI=$WS/runs/evalai
MANIFEST=$WS/data/evalai/drdocbench-evaluation-v4/evaluation_pages.json
EXPECTED=${EXPECTED:-509}

nd=$(ls $EVALAI/docling-forceocr/predictions 2>/dev/null | grep -c '\.drbench\.md$')
nm=$(ls $EVALAI/mineru/predictions 2>/dev/null | grep -c '\.drbench\.md$')
echo "[$(date +%T)] docling-forceocr=$nd mineru=$nm (expected $EXPECTED)"
if [[ "$nd" -ne "$EXPECTED" || "$nm" -ne "$EXPECTED" ]]; then
  echo "NOT COMPLETE — aborting (set EXPECTED=N to override)"; exit 2
fi

$PY $WS/scripts/adjudicate_v0.py --docling $EVALAI/docling-forceocr/predictions \
    --mineru $EVALAI/mineru/predictions --out $EVALAI/adjudicator-v0/predictions --rule v0 \
    | tee $EVALAI/adjudicator-v0/decisions_summary.txt

for run in docling-forceocr mineru adjudicator-v0; do
  echo "[$(date +%T)] === $run"
  OUT=$EVALAI/$run/submission
  mkdir -p "$OUT"
  $PY $WS/scripts/build_submission_manifest.py \
      --predictions $EVALAI/$run/predictions --manifest $MANIFEST --out "$OUT" || { echo "build FAILED for $run"; continue; }
  $PY $WS/data/evalai/drdocbench-evaluation-v4/validate_submission.py "$OUT/submission.zip" \
      --manifest $MANIFEST > "$OUT/validate.json" 2> "$OUT/validate.stderr"; rc=$?
  echo "validate rc=$rc"; head -c 600 "$OUT/validate.json"; echo
  (cd "$OUT" && sha256sum submission.zip > sha256.txt && cat sha256.txt)
done
echo "[$(date +%T)] done"
