# Serviços — Dr.DocBench

**Não há serviços persistentes.** Por regra do cluster (Slurm-only), docling-serve, mineru-api e a toolbox sobem **dentro** de cada job `runs/slurm/pipeline.sbatch` e são encerrados ao final (trap EXIT/SIGUSR1/TERM). Nada roda no login node.

| Serviço | Porta (base + (JOBID%100)*10) | Device | Comando (dentro do job) |
|---|---|---|---|
| docling-serve 1.32.0 (docling 2.127.0) | 5001+off | CPU (`CUDA_VISIBLE_DEVICES=""`) ou GPU do job | `repos/acessilia-toolbox/.venv-docling/bin/docling-serve run --host 0.0.0.0 --port $DOCLING_PORT` |
| mineru-api 3.4.5 (backend pipeline) | 5002+off | idem | `repos/acessilia-toolbox/.venv-mineru/bin/mineru-api --host 0.0.0.0 --port $MINERU_PORT` |
| acessilia-toolbox (commit 0f3292e, develop) | 8002+off | — | `PYTHONPATH=scripts/toolbox_shim .venv/bin/uvicorn acessilia_toolbox.api.app:create_app --factory --host 0.0.0.0 --port $TOOLBOX_PORT` |

Portas derivadas do `SLURM_JOB_ID` para que jobs docling e mineru coexistam no mesmo nó; `DOCLING_SERVE_URL`, `MINERU_SERVE_URL`, `TOOLBOX_BASE_URL` são exportados pelo sbatch de acordo. Health: `GET /health` (docling), `GET /openapi.json` (mineru), `GET /v1/health` (toolbox). Logs dos serviços: `runs/slurm/logs/<job>_<id>_{docling,mineru,toolbox}.log`.

Venvs (Python 3.11, uv): `repos/acessilia-toolbox/{.venv,.venv-docling,.venv-mineru}`, `repos/acessilia/.venv`. Modelos: `/raid/user_marcospaulo/cache/docling/models`, `/raid/user_marcospaulo/cache/huggingface/hub/models--opendatalab--PDF-Extract-Kit-1.0`. Ambiente: `runs/slurm/env.sh`.
