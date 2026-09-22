#!/bin/bash
#SBATCH --job-name=drb-lib-eval
#SBATCH --partition=h100n2
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=04:00:00
#SBATCH --output=/raid/user_marcospaulo/drdocbench/runs/slurm/logs/%x_%j.log
# Avaliação md2md oficial (janela 1) das runs de fusão via lib + comparação
# com o baseline do script de referência.
#
#   sbatch --export=ALL,SPLIT=dev,RUNS="lib-fuse-v12-YYYYMMDD lib-fuse-v13-YYYYMMDD" \
#          [SCRIPT_RUN=differ-v12-rh3-pc4-20260918] runs/slurm/lib_eval.sbatch
#
# Saídas:
#   - reports/official_w1-md2md.json por run (protocolo oficial)
#   - runs/dev-full/lib-integration-report.md (resumo da comparação)
set -uo pipefail
source /raid/user_marcospaulo/drdocbench/runs/slurm/env.sh
cd "$WS"
SPLIT=${SPLIT:-dev}
RUNS=${RUNS:?}; SCRIPT_RUN=${SCRIPT_RUN:-differ-v12-rh3-pc4-20260918}
[[ $SPLIT == dev ]] && OUTBASE=$WS/runs/dev-full || OUTBASE=$WS/runs/evalai
DRB=$WS/repos/DrDocBench/.venv/bin/python
GT=$WS/data/hf/dev
FULL=$OUTBASE

export RUNS WINDOWS=1 PROTO=md2md CDM=${CDM:-auto}
bash "$WS/runs/slurm/eval_full.sbatch"

# ── Comparação de outputs: lib vs script de referência ──────────────────
REPORT=$FULL/lib-integration-report.md
{
  echo "# Relatório de integração lib docstruct — $SPLIT ($(date -u +%FT%TZ))"
  echo
  echo "| run | evalai_style | text | RO | TEDS |"
  echo "|---|---|---|---|---|"
  for R in $RUNS $SCRIPT_RUN; do
    J=$FULL/$R/reports/official_w1-md2md.json
    [[ -f $J ]] || { echo "| $R | (sem relatório) | | | |"; continue; }
    $DRB -c "
import json
d = json.load(open('$J'))
a = d.get('evalai_style') or {}
print(f\"| $R | {a.get('overall','–')} | {a.get('text','–')} | {a.get('reading_order','–')} | {a.get('teds','–')} |\")
"
  done
  echo
  echo "## Diferença de outputs (lib vs script)"
  echo
  for R in $RUNS; do
    LIB=$FULL/$R/predictions; REF=$FULL/$SCRIPT_RUN/predictions
    [[ -d $LIB && -d $REF ]] || continue
    SAME=0; DIFF=0; MISSING=0
    for f in "$REF"/*.drbench.md; do
      n=$(basename "$f")
      if [[ ! -f "$LIB/$n" ]]; then MISSING=$((MISSING+1)); continue; fi
      if cmp -s "$f" "$LIB/$n"; then SAME=$((SAME+1)); else DIFF=$((DIFF+1)); fi
    done
    echo "- **$R vs $SCRIPT_RUN**: idênticos=$SAME diferentes=$DIFF ausentes=$MISSING (de $(ls "$REF"/*.drbench.md | wc -l))"
  done
  echo
  echo "## Decisões de fusão (agregado)"
  for R in $RUNS; do
    C=$FULL/$R/predictions/decisions.csv
    [[ -f $C ]] || continue
    echo "### $R"
    $DRB -c "
import csv
from collections import Counter
rows = list(csv.DictReader(open('$C')))
tot = Counter()
for r in rows:
    for k, v in r.items():
        if k != 'item' and v:
            try: tot[k] += int(v)
            except ValueError: pass
for k, v in sorted(tot.items()):
    print(f'  {k}: {v}')
"
  done
} | tee "$REPORT"
echo "[$(date -u +%T)] report: $REPORT"
echo "[$(date -u +%T)] done"
