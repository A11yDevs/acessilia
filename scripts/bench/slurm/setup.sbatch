#!/bin/bash
# One-off workspace setup: Toolbox, docling-serve and MinerU venvs, this repo's
# venv, provider models and (optionally) a dataset snapshot from HuggingFace.
# Submit from $WS:
#   sbatch -p <partition> --export=ALL,WS=$PWD[,HF_DATASET=2077AIDataFoundation/DrDocBench,HF_PATTERN='dev/**',DATASET_DIR=data/drdocbench] \
#     repos/acessilia/scripts/bench/slurm/setup.sbatch
#SBATCH --job-name=bench-setup
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=02:00:00
#SBATCH --output=logs/slurm/%x_%j.log
set -uo pipefail
source "$WS/repos/acessilia/scripts/bench/slurm/env.sh"
step() { echo; echo "===== [$(date -u +%H:%M:%S)] $*"; }

DL_PID=
if [[ -n "${HF_DATASET:-}" ]]; then
  step "dataset snapshot $HF_DATASET (background)"
  mkdir -p "$WS/${DATASET_DIR:?}"
  uv run --python 3.11 --with huggingface_hub python - "$HF_DATASET" "${HF_PATTERN:-*}" "$WS/$DATASET_DIR" \
      > "$WS/logs/slurm/dataset_$SLURM_JOB_ID.log" 2>&1 <<'PY' &
import sys
from huggingface_hub import snapshot_download
repo, pattern, dest = sys.argv[1:4]
print("done", snapshot_download(repo_id=repo, repo_type="dataset", allow_patterns=[pattern],
                                local_dir=dest, max_workers=16))
PY
  DL_PID=$!
fi

step "toolbox venv"
cd "$WS/repos/acessilia-toolbox"
[[ -d .venv ]] || uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -e ".[api]" && echo "TOOLBOX_OK"

step "docling-serve venv"
[[ -d .venv-docling ]] || uv venv --python 3.11 .venv-docling
uv pip install --python .venv-docling/bin/python docling-serve && echo "DOCLING_OK"
.venv-docling/bin/docling-tools models download 2>&1 | tail -5 || echo "docling models download FAILED"

step "mineru venv"
[[ -d .venv-mineru ]] || uv venv --python 3.11 .venv-mineru
uv pip install --python .venv-mineru/bin/python "mineru[core]" && echo "MINERU_OK"
.venv-mineru/bin/mineru-models-download -s huggingface -m pipeline 2>&1 | tail -20 || echo "mineru models download FAILED"

step "acessilia venv"
cd "$WS/repos/acessilia"
uv sync --frozen && uv run python -m scripts.bench --help > /dev/null && echo "ACESSILIA_OK"

if [[ -n "$DL_PID" ]]; then
  step "waiting dataset snapshot"
  wait "$DL_PID"; echo "download exit=$?"
  tail -3 "$WS/logs/slurm/dataset_$SLURM_JOB_ID.log"
fi
step "SETUP DONE"
