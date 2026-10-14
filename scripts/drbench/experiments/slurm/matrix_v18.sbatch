#!/bin/bash
#SBATCH --job-name=drb-matrix-v18
#SBATCH --partition=h100n2
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=05:00:00
#SBATCH --output=runs/slurm/logs/%x_%j.log
# Job C (CPU): v18 ablation matrix on dev-986 vs baseline v16-hyb-rec300 (78.3 md2md evalai_style).
#   v18-norm   = v16 + --norm-text            v18-xy    = v16 + --order xy
#   v18-vlmreg = v16 + VLM adjudications      v18-pswap = v16 + page swap -> mineru-vlm
#   v18-all    = everything that can be combined
# Submit with:  sbatch --dependency=afterany:<jobA>:<jobB> runs/slurm/matrix_v18.sbatch
set -uo pipefail
source "$WS/runs/slurm/env.sh"
cd "$WS"
FULL=$WS/runs/dev-full
QDIR=$FULL/adjudication-queue-v2
DRB=$WS/repos/DrDocBench/.venv/bin/python
D=$FULL/docling+rot/predictions
M=$FULL/mineru-hyb+rot/predictions
ARGS="--lam 0.5 --tau 0.6 --min-len 0 --drop-docling group+unknown --decor-tail --junk-filter --text-pick auto --merge-paragraphs --suppress-regions --pic-rule quality --pic-min-blocks 4 --fuse-lines --pick-guard 1.5 --decor-wins --fuse-h-ratio 0.6 --fuse-max-len 300 --running-heads 3 --pagenum-cap 4 --pic-need-text --line-numbers --table-eq --verse-chunk 300"
AGREE_THR=${AGREE_THR:-0.45}

differ() { # OUT EXTRA...
  local out=$1; shift
  $DRB scripts/tree_differ_v2.py --docling "$D" --mineru "$M" --out "$FULL/$out/predictions" $ARGS "$@" \
    && echo "$out: $(ls "$FULL/$out/predictions"/*.drbench.md | wc -l) pages"
}

RUNS=""
if [[ -z ${VLM_ONLY:-} ]]; then  # VLM_ONLY=1: norm/xy/pswap já no LEDGER (33244)
echo "[$(date +%T)] v18-norm"; differ v18-norm --norm-text && RUNS="$RUNS v18-norm"
echo "[$(date +%T)] v18-xy";   differ v18-xy --order xy   && RUNS="$RUNS v18-xy"
fi

if [[ -s $QDIR/adjudications.jsonl ]]; then
  echo "[$(date +%T)] v18-vlmreg ($(wc -l < $QDIR/adjudications.jsonl) decisions)"
  differ v18-vlmreg --adjudications "$QDIR/adjudications.jsonl" && RUNS="$RUNS v18-vlmreg"
else
  echo "SKIP v18-vlmreg: no adjudications"
fi

ALT=$FULL/mineru-vlm/predictions
if [[ -n ${VLM_ONLY:-} ]]; then
  echo "SKIP v18-pswap (VLM_ONLY)"
elif compgen -G "$ALT/*.drbench.md" >/dev/null; then
  echo "[$(date +%T)] v18-pswap (alt=$(ls "$ALT"/*.drbench.md | wc -l) pages, thr=$AGREE_THR)"
  $DRB scripts/page_swap.py --base "$FULL/v16-hyb-rec300/predictions" --alt "$ALT" --docling "$D" --mineru "$M" \
      --out "$FULL/v18-pswap/predictions" --agree-thr "$AGREE_THR" --list "$FULL/v18-pswap/swapped.txt" \
    && RUNS="$RUNS v18-pswap"
else
  echo "SKIP v18-pswap: no mineru-vlm predictions yet"
fi

echo "[$(date +%T)] v18-all"
EXTRA=(--norm-text --order xy)
[[ -s $QDIR/adjudications.jsonl ]] && EXTRA+=(--adjudications "$QDIR/adjudications.jsonl")
differ v18-all-pre "${EXTRA[@]}"
if compgen -G "$ALT/*.drbench.md" >/dev/null; then
  $DRB scripts/page_swap.py --base "$FULL/v18-all-pre/predictions" --alt "$ALT" --docling "$D" --mineru "$M" \
      --out "$FULL/v18-all/predictions" --agree-thr "$AGREE_THR" --list "$FULL/v18-all/swapped.txt"
else
  mkdir -p "$FULL/v18-all" && rm -rf "$FULL/v18-all/predictions" && cp -r "$FULL/v18-all-pre/predictions" "$FULL/v18-all/predictions"
fi
RUNS="$RUNS v18-all"

# no-chunk twin: EvalAI showed --verse-chunk 300 trades text (-2.4) for RO (+3.0); test whether
# xy/vlm/pswap keep the RO without that cost
echo "[$(date +%T)] v18-all-nc (sem verse-chunk)"
ARGS_NC=${ARGS/--verse-chunk 300/--verse-chunk 0}
$DRB scripts/tree_differ_v2.py --docling "$D" --mineru "$M" --out "$FULL/v18-all-nc-pre/predictions" $ARGS_NC "${EXTRA[@]}"
if compgen -G "$ALT/*.drbench.md" >/dev/null; then
  $DRB scripts/page_swap.py --base "$FULL/v18-all-nc-pre/predictions" --alt "$ALT" --docling "$D" --mineru "$M" \
      --out "$FULL/v18-all-nc/predictions" --agree-thr "$AGREE_THR" --list "$FULL/v18-all-nc/swapped.txt"
else
  mkdir -p "$FULL/v18-all-nc" && rm -rf "$FULL/v18-all-nc/predictions" && cp -r "$FULL/v18-all-nc-pre/predictions" "$FULL/v18-all-nc/predictions"
fi
RUNS="$RUNS v18-all-nc"

echo "[$(date +%T)] eval matrix:$RUNS"
export RUNS WINDOWS=1 PROTO=md2md CDM=auto
bash "$WS/runs/slurm/eval_full.sbatch"
echo "[$(date +%T)] done — compare against v16-hyb-rec300 78.3 in $FULL/LEDGER.md"
