#!/usr/bin/env bash
# Run ON THE CLUSTER, in the experiment workspace, to freeze what `run.sh best replay`
# needs and the software versions of the best submission (README.md, "Freezing").
#
#   WS=/raid/user_marcospaulo/drdocbench scripts/drbench/collect_inputs.sh OUT_DIR
#
# The page-number positions (tj3) come from TeleOCR and dots.ocr raw outputs whose exact
# run names were not recorded: pass PNPOS=<json> (a saved pnpos.py output), or
# TELE_RAW=<jsonl> DOTS_RAW=<jsonl>. Without them the script lists the candidates and stops.
# It ends by replaying the bundle against the frozen submission: IDENTICAL confirms the inputs.
set -euo pipefail

: "${WS:?export WS=<experiment workspace>}"
OUT=${1:?collect_inputs.sh OUT_DIR}
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
EVALAI=$WS/runs/evalai
B=$OUT/inputs
V=$OUT/versions
HF=${HF_HOME:-${CACHE_ROOT:-/raid/user_marcospaulo/cache}/huggingface}

if [[ -z ${PNPOS:-} && ( -z ${TELE_RAW:-} || -z ${DOTS_RAW:-} ) ]]; then
  echo "Set PNPOS, or TELE_RAW and DOTS_RAW. Candidates:"
  find "$WS/runs" \( -name '*pnpos*' -o -name '*pos*.json' \) -newermt 2026-10-08 2>/dev/null | sed 's/^/  PNPOS?    /' || true
  find "$EVALAI" -name '*-raw.jsonl' \( -path '*tele*' -o -path '*dots*' \) 2>/dev/null | sed 's/^/  RAW?      /' || true
  exit 2
fi

mkdir -p "$B" "$V"
cp -r "$EVALAI/differ-v29-adf-20261009/predictions" "$B/v29-adf"
cp -r "$EVALAI/teleocr-up2m2-vm-fb-adf-20261009/predictions" "$B/televm-fb"
cp "$EVALAI/judge-televm.jsonl" "$EVALAI/judge-tele.jsonl" "$B/"
if [[ -n ${PNPOS:-} ]]; then cp "$PNPOS" "$B/pnpos.json"; else cp "$TELE_RAW" "$B/tele-raw.jsonl"; cp "$DOTS_RAW" "$B/dots-raw.jsonl"; fi
{
  echo "v29-adf    $EVALAI/differ-v29-adf-20261009/predictions"
  echo "televm-fb  $EVALAI/teleocr-up2m2-vm-fb-adf-20261009/predictions"
  echo "judges     $EVALAI/judge-televm.jsonl $EVALAI/judge-tele.jsonl"
  echo "pnpos      ${PNPOS:-from $TELE_RAW + $DOTS_RAW}"
  echo "zip        $EVALAI/hyb-v29-judge2-televm-adf-tj3-20261009/submission/submission.zip"
} > "$OUT/SOURCES.txt"
(cd "$B" && find . -type f | sort | xargs sha256sum) > "$OUT/inputs.sha256"
sha256sum "$EVALAI/hyb-v29-judge2-televm-adf-tj3-20261009/submission/submission.zip" >> "$OUT/SOURCES.txt" || true

# Code, environments, models, hardware.
for r in "$WS"/repos/*/; do
  echo "$(basename "$r") $(git -C "$r" rev-parse HEAD) $(git -C "$r" log -1 --format=%cI) $(git -C "$r" status --porcelain | wc -l) dirty"
done > "$V/repos.txt"
for venv in "$WS"/repos/*/.venv*; do
  [[ -x $venv/bin/python ]] || continue
  name=$(basename "$(dirname "$venv")")-$(basename "$venv")
  { "$venv/bin/python" --version; uv pip freeze --python "$venv/bin/python" 2>/dev/null || "$venv/bin/python" -m pip freeze; } > "$V/pip-$name.txt"
done
for m in Qwen/Qwen3-VL-32B-Instruct-FP8 XingChen-AGI/TeleOCR dots-studio/dots.ocr; do
  d=$HF/hub/models--${m//\//--}
  echo "$m refs/main=$(cat "$d/refs/main" 2>/dev/null || echo '?') snapshots=$(ls "$d/snapshots" 2>/dev/null | tr '\n' ' ')"
done > "$V/models.txt"
ls -d "$HF"/hub/models--opendatalab--* 2>/dev/null | while read -r d; do
  echo "$(basename "$d" | sed 's/^models--//; s/--/\//') refs/main=$(cat "$d/refs/main" 2>/dev/null || echo '?')"
done >> "$V/models.txt"
cp "${MINERU_TOOLS_CONFIG_JSON:-$HOME/mineru.json}" "$V/mineru.json" 2>/dev/null || true
# Jobs of the 2026-10-09 chain print the commits they ran (acessilia=<sha> toolbox=<sha>).
grep -H "acessilia=\|toolbox=\|DEVICE=\|=== .* job " "$WS"/runs/slurm/logs/*_344[0-9][0-9].log 2>/dev/null > "$V/job-commits.txt" || true
{ nvidia-smi --query-gpu=name,driver_version --format=csv,noheader; nvidia-smi | grep -o 'CUDA Version: [0-9.]*'; uname -a; } > "$V/hardware.txt" 2>&1 || true

tar -C "$OUT" -czf "$OUT/drbench-best-inputs.tar.gz" inputs inputs.sha256 SOURCES.txt versions
sha256sum "$OUT/drbench-best-inputs.tar.gz"

echo "== replay against the frozen submission"
"$HERE/run.sh" best replay "$B"
