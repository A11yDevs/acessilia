# Sourced by every job in this directory. Nothing on $HOME; caches under $CACHE_ROOT.
#
# Workspace layout (WS is required; submit jobs from $WS so the relative
# `#SBATCH --output=logs/slurm/...` resolves there):
#   $WS/repos/acessilia          this repository
#   $WS/repos/acessilia-toolbox  the Toolbox (.venv, .venv-docling, .venv-mineru from setup.sbatch)
#   $WS/repos/DrDocBench         the official evaluator (eval_official.sbatch)
#   $WS/data/<dataset>/<split>   local dataset trees (scripts.bench --root)
#   $WS/bench                    harness runs (BENCH_VAR)
: "${WS:?export WS=<workspace> before sourcing env.sh}"
export CACHE_ROOT=${CACHE_ROOT:-$WS/cache}
export BENCH_VAR=${BENCH_VAR:-$WS/bench}
export HF_HOME=${HF_HOME:-$CACHE_ROOT/huggingface}
export UV_CACHE_DIR=${UV_CACHE_DIR:-$CACHE_ROOT/uv}
export PIP_CACHE_DIR=${PIP_CACHE_DIR:-$CACHE_ROOT/pip}
export TORCH_HOME=${TORCH_HOME:-$CACHE_ROOT/torch}
export XDG_CACHE_HOME=${XDG_CACHE_HOME:-$CACHE_ROOT}
export HF_HUB_ENABLE_HF_TRANSFER=0
export MINERU_MODEL_SOURCE=${MINERU_MODEL_SOURCE:-huggingface}
export DOCLING_ARTIFACTS_PATH=${DOCLING_ARTIFACTS_PATH:-$CACHE_ROOT/docling/models}
export MINERU_TOOLS_CONFIG_JSON=${MINERU_TOOLS_CONFIG_JSON:-$CACHE_ROOT/mineru/mineru.json}
# For the VLM capabilities (page OCR, judge, table, orientation) and mineru-hyb, point it at
# $WS/repos/acessilia/scripts/bench/slurm/providers-config-vlm.yaml.
export TOOLBOX_PROVIDERS_CONFIG=${TOOLBOX_PROVIDERS_CONFIG:-$WS/repos/acessilia-toolbox/providers-config.yaml}
export TOOLBOX_USE_ARTIFACT_STORE=false
export TOOLBOX_USE_REMOTE_CACHE=false
export PATH=$HOME/.local/bin:$PATH
mkdir -p "$HF_HOME" "$UV_CACHE_DIR" "$PIP_CACHE_DIR" "$TORCH_HOME" "$BENCH_VAR" "$WS/logs/slurm"
