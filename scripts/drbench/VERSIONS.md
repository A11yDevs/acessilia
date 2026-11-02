# Software versions — Dr.DocBench submissions

What is known from the repository and the experiment records. Rows marked **to collect** exist
only on the cluster (logs, virtualenvs, Hugging Face cache): `collect_inputs.sh` writes them to
`versions/` in its output, and they are copied here once collected.

The model weights were **not pinned** when the jobs ran (`--revision` defaulted to `None` in the
OCR and judge scripts): the revision actually used is the one in the cluster's Hugging Face cache.

## Best submission — `hyb-v29-judge2-televm-adf-tj3-20261009`

| Component | Version | Source |
|---|---|---|
| Acessília (experiment code) | tag `drbench-2026-snapshot` (`47531dd`); the commit each job ran: **to collect** (`job-commits.txt`) | git, Slurm logs |
| Acessília Toolbox | **to collect** (`repos.txt`, `job-commits.txt`) | git, Slurm logs |
| Python | 3.11 for the Toolbox, Docling, MinerU and core venvs; the VLM venv (`.venv-vlm`): **to collect** | `setup.sbatch`, `pip-*.txt` |
| Python packages of the core | `uv.lock` at the tag (90 packages) | git |
| Python packages of each provider / VLM venv | **to collect** (`pip-*.txt`) | virtualenvs |
| Docling | `docling-serve` 1.32 (provider `docling`, `force_ocr`) | `providers-config-vlm.yaml` at the tag |
| MinerU | 3.4, backend `hybrid-engine` (provider `mineru-hyb`) | `providers-config-vlm.yaml` at the tag |
| MinerU model weights | **to collect** (`models.txt`, `mineru.json`) | HF cache |
| Qwen3-VL judge / adjudication / page selection | `Qwen/Qwen3-VL-32B-Instruct-FP8` via vLLM; revision **to collect** | job scripts, HF cache |
| TeleOCR | `XingChen-AGI/TeleOCR` via vLLM; revision **to collect** | `teleocr_page_ocr.py`, HF cache |
| dots.ocr | `dots-studio/dots.ocr` via vLLM; revision **to collect** | `dots_page_ocr.py`, HF cache |
| Orientation | `rapidocr-orient` (RapidOCR) | `providers-config-vlm.yaml` at the tag |
| Hardware | 1 × NVIDIA H100 (partition `h100n2`), 16 CPUs, 128 GB; driver / CUDA **to collect** (`hardware.txt`) | job scripts |
| Dataset | EvalAI test package `drdocbench-evaluation-v4` (509 pages) | workspace layout |

## Paper's experiment

*Pending* — filled in together with `submissions/paper/`.
