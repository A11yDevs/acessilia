# Services — Dr.DocBench

> Brazilian Portuguese version: [versão pt-BR](SERVICES-LOOP.pt-br.md)

**There are no persistent services.** By cluster rule (Slurm-only), docling-serve, mineru-api and
the toolbox start **inside** each `runs/slurm/pipeline.sbatch` job and are shut down at the end
(trap EXIT/SIGUSR1/TERM). Nothing runs on the login node.

| Service | Port (base + (JOBID%100)*10) | Device | Command (inside the job) |
|---|---|---|---|
| docling-serve 1.32.0 (docling 2.127.0) | 5001+off | CPU (`CUDA_VISIBLE_DEVICES=""`) or the job's GPU | `repos/acessilia-toolbox/.venv-docling/bin/docling-serve run --host 0.0.0.0 --port $DOCLING_PORT` |
| mineru-api 3.4.5 (backend pipeline) | 5002+off | idem | `repos/acessilia-toolbox/.venv-mineru/bin/mineru-api --host 0.0.0.0 --port $MINERU_PORT` |
| acessilia-toolbox (commit 0f3292e, develop) | 8002+off | — | `PYTHONPATH=scripts/toolbox_shim .venv/bin/uvicorn acessilia_toolbox.api.app:create_app --factory --host 0.0.0.0 --port $TOOLBOX_PORT` |

Ports are derived from `SLURM_JOB_ID` so that docling and mineru jobs can coexist on the same
node; `DOCLING_SERVE_URL`, `MINERU_SERVE_URL` and `TOOLBOX_BASE_URL` are exported by the sbatch
accordingly. Health: `GET /health` (docling), `GET /openapi.json` (mineru), `GET /v1/health`
(toolbox). Service logs: `runs/slurm/logs/<job>_<id>_{docling,mineru,toolbox}.log`.

Virtualenvs (Python 3.11, uv): `repos/acessilia-toolbox/{.venv,.venv-docling,.venv-mineru}`,
`repos/acessilia/.venv`. Models: `$CACHE_ROOT/docling/models`,
`$CACHE_ROOT/huggingface/hub/models--opendatalab--PDF-Extract-Kit-1.0`. Environment:
`runs/slurm/env.sh` (parameterised — see `scripts/drbench/experiments/README.md`).
