#!/bin/bash
#SBATCH --job-name=drb-probe-zip
#SBATCH --partition=h100n2
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=00:30:00
#SBATCH --output=runs/slurm/logs/%x_%j.log
# build & validate submission.zip from raw provider predictions: sbatch --export=ALL,RUN_ID=<dir under runs/evalai> probe_zip.sbatch
set -uo pipefail
source "$WS/runs/slurm/env.sh"
cd "$WS"; R=${RUN_ID:?}
PY=$WS/repos/acessilia/.venv/bin/python; EVALAI=$WS/runs/evalai; MANIFEST=$WS/data/evalai/drdocbench-evaluation-v4/evaluation_pages.json
PRED=$EVALAI/$R/predictions; OUT=$EVALAI/$R/submission
N=$(ls "$PRED"/*.drbench.md | wc -l); echo "run=$R n_pred=$N"; [[ $N -eq 509 ]] || exit 2
mkdir -p "$OUT"
$PY scripts/build_submission_manifest.py --predictions "$PRED" --manifest "$MANIFEST" --out "$OUT" || exit 3
$PY data/evalai/drdocbench-evaluation-v4/validate_submission.py "$OUT/submission.zip" --manifest "$MANIFEST" > "$OUT/validate.json" 2> "$OUT/validate.stderr"; echo "validate rc=$?"; cat "$OUT/validate.json"
(cd "$OUT" && sha256sum submission.zip | tee sha256.txt)
