#!/bin/bash
#SBATCH --job-name=drb-test-zip
#SBATCH --partition=h100n2
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=01:00:00
#SBATCH --output=/raid/user_marcospaulo/drdocbench/runs/slurm/logs/%x_%j.log
# tree_differ_v2 over the test-509 docling/mineru predictions + build & validate submission.zip.
#   sbatch --export=ALL,RUN_ID=differ-v4-merge-20260918,ARGS="--lam 0.5 ... --merge-paragraphs" \
#          [DOCLING=docling-v3-20260916,MINERU=mineru-v3-20260916] runs/slurm/differ_test_zip.sbatch
set -uo pipefail
source /raid/user_marcospaulo/drdocbench/runs/slurm/env.sh
cd "$WS"
R=${RUN_ID:?}; D=${DOCLING:-docling-v3-20260916}; M=${MINERU:-mineru-v3-20260916}; ARGS=${ARGS:?}
DRB=$WS/repos/DrDocBench/.venv/bin/python; PY=$WS/repos/acessilia/.venv/bin/python
EVALAI=$WS/runs/evalai; MANIFEST=$WS/data/evalai/drdocbench-evaluation-v4/evaluation_pages.json
PRED=$EVALAI/$R/predictions; OUT=$EVALAI/$R/submission
echo "job=$SLURM_JOB_ID run=$R docling=$D mineru=$M args=$ARGS"
echo "n_docling=$(ls "$EVALAI/$D/predictions"/*.drbench.md | wc -l) n_mineru=$(ls "$EVALAI/$M/predictions"/*.drbench.md | wc -l)"
$DRB scripts/tree_differ_v2.py --docling "$EVALAI/$D/predictions" --mineru "$EVALAI/$M/predictions" --out "$PRED" $ARGS
N=$(ls "$PRED"/*.drbench.md | wc -l); echo "n_pred=$N"
cat > "$EVALAI/$R/RUN.md" <<EOF
# $R
- job: $SLURM_JOB_ID  date: $(date -u +%FT%TZ)  split: test
- scripts/tree_differ_v2.py $ARGS over docling=$D mineru=$M (decisions.csv in predictions/)
- commits: acessilia=$(git -C repos/acessilia rev-parse --short HEAD) toolbox=$(git -C repos/acessilia-toolbox rev-parse --short HEAD)
EOF
[[ $N -eq 509 ]] || { echo "expected 509 predictions, got $N — not building zip"; exit 2; }
mkdir -p "$OUT"
$PY scripts/build_submission_manifest.py --predictions "$PRED" --manifest "$MANIFEST" --out "$OUT" || { echo "build FAILED"; exit 3; }
$PY data/evalai/drdocbench-evaluation-v4/validate_submission.py "$OUT/submission.zip" --manifest "$MANIFEST" > "$OUT/validate.json" 2> "$OUT/validate.stderr"
echo "validate rc=$?"; cat "$OUT/validate.json"
(cd "$OUT" && sha256sum submission.zip > sha256.txt && cat sha256.txt)
echo "[$(date -u +%T)] done"
