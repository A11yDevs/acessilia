# Source in every Slurm job. Nothing on $HOME; caches on the cluster scratch.
#
# Override WS and CACHE_ROOT before sourcing to run outside the original cluster:
#   WS=/my/workspace CACHE_ROOT=/my/cache source runs/slurm/env.sh
# The defaults below are the historical DGX paths and are kept only so the
# recorded jobs stay reproducible as they were run.
export WS=${WS:-/raid/user_marcospaulo/drdocbench}
export CACHE_ROOT=${CACHE_ROOT:-/raid/user_marcospaulo/cache}
export HF_HOME=${HF_HOME:-$CACHE_ROOT/huggingface}
export UV_CACHE_DIR=${UV_CACHE_DIR:-$CACHE_ROOT/uv}
export PIP_CACHE_DIR=${PIP_CACHE_DIR:-$CACHE_ROOT/pip}
export TORCH_HOME=${TORCH_HOME:-$CACHE_ROOT/torch}
export XDG_CACHE_HOME=${XDG_CACHE_HOME:-$CACHE_ROOT}
export HF_HUB_ENABLE_HF_TRANSFER=0
export MINERU_MODEL_SOURCE=huggingface
export DOCLING_ARTIFACTS_PATH=${DOCLING_ARTIFACTS_PATH:-$CACHE_ROOT/docling/models}
export MINERU_TOOLS_CONFIG_JSON=${MINERU_TOOLS_CONFIG_JSON:-$CACHE_ROOT/mineru/mineru.json}
export TOOLBOX_BASE_URL=${TOOLBOX_BASE_URL:-http://localhost:8002}
export DOCLING_SERVE_URL=${DOCLING_SERVE_URL:-http://localhost:5001}
export MINERU_SERVE_URL=${MINERU_SERVE_URL:-http://localhost:5002}
export TOOLBOX_PROVIDERS_CONFIG=${TOOLBOX_PROVIDERS_CONFIG:-$WS/repos/acessilia-toolbox/providers-config.yaml}
export TOOLBOX_USE_ARTIFACT_STORE=false
export TOOLBOX_USE_REMOTE_CACHE=false
export PATH=$HOME/.local/bin:$PATH
mkdir -p "$HF_HOME" "$UV_CACHE_DIR" "$PIP_CACHE_DIR" "$TORCH_HOME" "$WS/runs/slurm/logs"
