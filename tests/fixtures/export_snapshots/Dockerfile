# Test-only environment. The pins match infra/Dockerfile; no source is copied
# into the image. Mount a checkout read-only and install docstruct from its lock.
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
COPY --from=ghcr.io/astral-sh/uv:0.11.17@sha256:03bdc89bb9798628846e60c3a9ad19006c8c3c724ccd2985a33145c039a0577b /uv /bin/uv
ENV UV_PROJECT_ENVIRONMENT=/tmp/export-characterization-venv \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /workspace/libs/docstruct
CMD ["uv", "run", "--locked", "--extra", "dev", "--no-editable", "python", "-I", "-m", "pytest", "tests/test_export_characterization.py", "tests/test_export_walk.py", "tests/test_export_walk_parity.py", "-p", "no:cacheprovider", "-q"]
