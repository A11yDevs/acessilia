#!/bin/bash
#SBATCH --job-name=drb-lib-fuse
#SBATCH --partition=h100n2
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --output=/raid/user_marcospaulo/drdocbench/runs/slurm/logs/%x_%j.log
# Fusão via LIB docstruct (não o script tree_differ_v2) sobre os payloads
# blocks.json de docling-lib + mineru-lib. Produz predictions no mesmo formato
# <id>.drbench.md para o avaliador oficial md2md.
#
# Objetivo do experimento de integração: verificar que a porta da lib
# (docstruct.fusion.merge_blocks + FusionPolicy.drbench_v12/v13) reproduz o
# comportamento do script de referência (tree_differ_v2.py) — mesmos outputs
# ou compatíveis (score dev-986 md2md ≈ 75.9).
#
#   sbatch --export=ALL,SPLIT=dev,POLICY=v12 runs/slurm/lib_fuse.sbatch
#   sbatch --export=ALL,SPLIT=dev,POLICY=v13 runs/slurm/lib_fuse.sbatch
#   POLICY=script  -> roda o tree_differ_v2.py de referência (baseline de comparação)
set -uo pipefail
source /raid/user_marcospaulo/drdocbench/runs/slurm/env.sh
cd "$WS/repos/acessilia"
SPLIT=${SPLIT:-dev}
POLICY=${POLICY:-v12}
[[ $SPLIT == dev ]] && OUTBASE=$WS/runs/dev-full || OUTBASE=$WS/runs/evalai
DOCLING_DIR=${DOCLING_DIR:-$OUTBASE/docling-lib/predictions}
MINERU_DIR=${MINERU_DIR:-$OUTBASE/mineru-lib/predictions}
RUN_NAME=${RUN_NAME:-lib-fuse-$POLICY-$(date +%Y%m%d)}
PRED=$OUTBASE/$RUN_NAME/predictions
PY=$WS/repos/acessilia/.venv/bin/python

echo "job=$SLURM_JOB_ID split=$SPLIT policy=$POLICY run=$RUN_NAME"
echo "docling=$DOCLING_DIR mineru=$MINERU_DIR"
echo "n_docling=$(ls "$DOCLING_DIR"/*.drbench.md 2>/dev/null | wc -l) n_mineru=$(ls "$MINERU_DIR"/*.drbench.md 2>/dev/null | wc -l)"

mkdir -p "$PRED" "$OUTBASE/$RUN_NAME"
if [[ $POLICY == script ]]; then
  # Baseline: script de referência (scipy + implementação original).
  DRB=$WS/repos/DrDocBench/.venv/bin/python
  $DRB scripts/tree_differ_v2.py --docling "$DOCLING_DIR" --mineru "$MINERU_DIR" \
      --out "$PRED" \
      --lam 0.5 --tau 0.6 --min-len 0 \
      --drop-docling group+unknown --decor-tail --junk-filter --text-pick auto \
      --merge-paragraphs --suppress-regions --pic-rule quality --pic-min-blocks 4 \
      --fuse-lines --pick-guard 1.5 --decor-wins --fuse-h-ratio 0.6 --fuse-max-len 300 \
      --running-heads 3 --pagenum-cap 4
else
  # Porta da lib: docstruct.fusion com FusionPolicy preset.
  $PY -m scripts.drbench.experiments.differ.lib_fuse \
      --docling "$DOCLING_DIR" --mineru "$MINERU_DIR" --out "$PRED" --policy "$POLICY"
fi

N=$(ls "$PRED"/*.drbench.md 2>/dev/null | wc -l)
echo "n_pred=$N"
cat > "$OUTBASE/$RUN_NAME/RUN.md" <<EOF
# $RUN_NAME
- job: $SLURM_JOB_ID  date: $(date -u +%FT%TZ)  split: $SPLIT
- policy: $POLICY (lib docstruct) | docling=$DOCLING_DIR mineru=$MINERU_DIR
- commits: acessilia=$(git rev-parse --short HEAD) toolbox=$(git -C "$WS/repos/acessilia-toolbox" rev-parse --short HEAD)
EOF
[[ $N -gt 0 ]] || { echo "no predictions produced"; exit 2; }
echo "[$(date -u +%T)] done"
