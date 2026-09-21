#!/bin/bash
#SBATCH --job-name=drb-setup
#SBATCH --partition=h100n2
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=02:00:00
#SBATCH --output=/raid/user_marcospaulo/drdocbench/runs/slurm/logs/%x_%j.log
set -uo pipefail
source /raid/user_marcospaulo/drdocbench/runs/slurm/env.sh
cd "$WS"
step() { echo; echo "===== [$(date -u +%H:%M:%S)] $*"; }

# e. dev split download in background (network-bound)
step "dev split download (background)"
mkdir -p "$WS/data/hf"
uv run --python 3.11 --with huggingface_hub python - <<'EOF' > "$WS/runs/slurm/logs/devsplit_$SLURM_JOB_ID.log" 2>&1 &
from huggingface_hub import snapshot_download
p = snapshot_download(repo_id="2077AIDataFoundation/DrDocBench", repo_type="dataset",
    allow_patterns=["dev/**"], local_dir="/raid/user_marcospaulo/drdocbench/data/hf", max_workers=16)
print("done", p)
EOF
DL_PID=$!

# a. toolbox
step "toolbox venv"
cd "$WS/repos/acessilia-toolbox"
[[ -d .venv ]] || uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -e ".[api]" && echo "TOOLBOX_OK"

# b. docling-serve
step "docling-serve venv"
[[ -d .venv-docling ]] || uv venv --python 3.11 .venv-docling
uv pip install --python .venv-docling/bin/python docling-serve && echo "DOCLING_OK"
.venv-docling/bin/python -c "import docling, importlib.metadata as m; print('docling', docling.__version__ if hasattr(docling,'__version__') else m.version('docling')); print('docling-serve', m.version('docling-serve'))"

# c. mineru
step "mineru venv"
[[ -d .venv-mineru ]] || uv venv --python 3.11 .venv-mineru
uv pip install --python .venv-mineru/bin/python "mineru[core]" && echo "MINERU_OK"
.venv-mineru/bin/python -c "import importlib.metadata as m; print('mineru', m.version('mineru'))"

# d. acessilia
step "acessilia venv"
cd "$WS/repos/acessilia"
[[ -d .venv ]] || uv venv --python 3.11 .venv
if ! uv pip install --python .venv/bin/python -e .; then
  echo "full install failed; falling back to --no-deps + minimal deps"
  uv pip install --python .venv/bin/python -e . --no-deps
  uv pip install --python .venv/bin/python loguru httpx python-dotenv pydantic numpy pillow pymupdf jsonschema latex2mathml
fi
.venv/bin/python -c "import backend.tools.toolbox_client, scripts.drbench.run_pipeline; print('ACESSILIA_IMPORT_OK')"
.venv/bin/python -m scripts.drbench.run_pipeline --help

# f. docling models prewarm (CPU)
step "docling models"
cd "$WS/repos/acessilia-toolbox"
.venv-docling/bin/docling-tools models download 2>&1 | tail -5 || echo "docling-tools models download FAILED"

# c'. mineru models
step "mineru models"
.venv-mineru/bin/mineru-models-download --help 2>&1 | head -30
.venv-mineru/bin/mineru-models-download -s huggingface -m pipeline 2>&1 | tail -20 || echo "mineru-models-download FAILED"
echo "mineru.json:"; cat ~/mineru.json 2>/dev/null || ls "$HF_HOME" | head

step "waiting dev split download"
wait $DL_PID; echo "download exit=$?"
tail -3 "$WS/runs/slurm/logs/devsplit_$SLURM_JOB_ID.log"
echo "json: $(find $WS/data/hf/dev -path '*/json/*.json' | wc -l)"
echo "mds:  $(find $WS/data/hf/dev -path '*/mds/*.md' | wc -l)"
echo "jpg:  $(find $WS/data/hf/dev -path '*/images/*.jpg' | wc -l)"
step "SETUP DONE"
