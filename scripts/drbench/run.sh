#!/usr/bin/env bash
# Reproduce the Dr.DocBench (DocInsights 2026) results. See README.md.
#
#   run.sh best verify              check the frozen submission and its EvalAI result (seconds, no data)
#   run.sh best replay INPUTS_DIR   redo the model-free last stage from frozen intermediate outputs and
#                                   compare predictions.jsonl byte for byte (minutes, CPU, python3 only)
#   run.sh best full                the GPU chain that produced the intermediate outputs (documented, not automated)
#   run.sh paper ...                the paper's experiment (pending)
set -euo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO=$(git -C "$HERE" rev-parse --show-toplevel)
TAG=drbench-2026-snapshot
BEST=$HERE/submissions/best
PREDICTIONS_SHA256=2b83be1409b50a4051e2081dffc401cf501631b018c7f56b2d31513a883b11e3

usage() { sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
sha256() { if command -v sha256sum > /dev/null; then sha256sum "$@"; else shasum -a 256 "$@"; fi; }

verify_best() {
  (cd "$BEST" && sha256 -c SHA256SUMS)
  local got
  got=$(unzip -p "$BEST/submission.zip" predictions.jsonl | sha256 | cut -d' ' -f1)
  [[ $got == "$PREDICTIONS_SHA256" ]] || { echo "predictions.jsonl: FAILED ($got)"; exit 1; }
  echo "predictions.jsonl: OK"
  unzip -p "$BEST/submission.zip" predictions.jsonl | python3 -c '
import json, sys
rows = [json.loads(line) for line in sys.stdin]
pages = {(r["document_id"], r["page"]) for r in rows}
assert len(rows) == len(pages) == 509, (len(rows), len(pages))
docs = {r["document_id"] for r in rows}
subjects = {r["subject"] for r in rows}
print(len(rows), "pages,", len(docs), "documents,", len(subjects), "subjects")'
  # EvalAI serves the result as a Python literal (single quotes), kept byte for byte.
  python3 -c 'import ast, sys; print("EvalAI:", ast.literal_eval(open(sys.argv[1]).read())[0])' "$BEST/evalai-result.json"
}

replay_best() {
  local inputs=${1:?run.sh best replay INPUTS_DIR}
  WORK=$(mktemp -d)
  trap 'rm -rf "$WORK"' EXIT
  local work=$WORK
  git -C "$REPO" rev-parse -q --verify "refs/tags/$TAG" > /dev/null || git -C "$REPO" fetch -q origin tag "$TAG"
  git -C "$REPO" archive "$TAG" scripts/drbench/experiments/pages | tar -x -C "$work"
  unzip -p "$BEST/submission.zip" predictions.jsonl > "$work/frozen.jsonl"
  python3 "$HERE/replay_best.py" "$inputs" "$work/scripts/drbench/experiments/pages" "$work/frozen.jsonl" \
      "${OUT:-$work/out}"
}

case "${1:-} ${2:-}" in
  "best verify") verify_best ;;
  "best replay") replay_best "${3:-}" ;;
  "best full")
    echo "The GPU chain is documented step by step in README.md (\"How the best result was produced\");"
    echo "its jobs are at the tag $TAG (scripts/drbench/experiments/slurm). It is not bit-exact:"
    echo "GPU inference is not deterministic, so compare scores, not hashes."
    exit 2 ;;
  "paper "*) echo "The paper's experiment is not frozen yet: see README.md (\"Paper's experiment\")."; exit 2 ;;
  *) usage ;;
esac
