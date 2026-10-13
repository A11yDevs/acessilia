#!/bin/bash
#SBATCH --job-name=drb-differ-variants
#SBATCH --partition=h100n2
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=02:00:00
#SBATCH --output=runs/slurm/logs/%x_%j.log
# Run several tree_differ_v2 variants on dev-986 sequentially, then evaluate them all with the
# official md2md single-page protocol (eval_full.sbatch inline).
#   VARIANTS_FILE: file with one "name|extra args[|mineru_run]" per line (base args always: --lam 0.5 --tau 0.6 --min-len 0).
#   Optional 3rd field = MinerU source run under runs/dev-full (e.g. mineru-hyb+rot) overriding MINERU_DIR.
#   EXTRA_RUNS: space-separated existing runs (e.g. mineru-hyb+rot) to evaluate together with the variants.
#   Use '+' instead of ',' inside --drop-* lists (Slurm --export splits on commas).
#   sbatch --export=ALL,VARIANTS_FILE=runs/dev-full/variants_v3.txt runs/slurm/differ_variants.sbatch
set -uo pipefail
source "$WS/runs/slurm/env.sh"
cd "$WS"
VARIANTS=$(grep -v '^\s*#' "${VARIANTS_FILE:?}"); BASE=${BASE:-"--lam 0.5 --tau 0.6 --min-len 0"}
DRB=$WS/repos/DrDocBench/.venv/bin/python
FULL=$WS/runs/dev-full
DOCLING_DIR=${DOCLING_DIR:-$FULL/docling/predictions}; MINERU_DIR=${MINERU_DIR:-$FULL/mineru/predictions}
NAMES=""
while IFS='|' read -r NAME ARGS MSRC; do
  [[ -z $NAME ]] && continue
  PRED=$FULL/$NAME/predictions
  MDIR=$MINERU_DIR; [[ -n ${MSRC// /} ]] && MDIR=$FULL/${MSRC// /}/predictions
  echo "[$(date +%T)] variant=$NAME args=$BASE $ARGS  (docling=$DOCLING_DIR mineru=$MDIR)"
  $DRB scripts/tree_differ_v2.py --docling "$DOCLING_DIR" --mineru "$MDIR" \
      --out "$PRED" $BASE $ARGS
  echo "n_pred=$(ls "$PRED"/*.drbench.md | wc -l)"
  printf '# %s\n- job: %s  date: %s\n- tree_differ_v2 %s %s over %s + %s\n' \
      "$NAME" "$SLURM_JOB_ID" "$(date -u +%FT%TZ)" "$BASE" "$ARGS" "$DOCLING_DIR" "$MDIR" > "$FULL/$NAME/RUN.md"
  NAMES="$NAMES $NAME"
done <<< "$VARIANTS"
export RUNS="$NAMES ${EXTRA_RUNS:-}" WINDOWS=1 PROTO=md2md CDM=${CDM:-auto}
bash "$WS/runs/slurm/eval_full.sbatch"
echo "[$(date +%T)] done"
