# syntax=docker/dockerfile:1.4
FROM python:3.13-slim AS base

# Definir variáveis de ambiente
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VERSION=1.7.1

# Instalar dependências do sistema necessárias (build-essential, libmagic, poppler-utils, tesseract-ocr, ffmpeg)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libmagic1 \
        poppler-utils \
        tesseract-ocr \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Definir diretório de trabalho
WORKDIR /app

# Copiar apenas arquivos de dependência para camada de cache
COPY pyproject.toml poetry.lock* ./

# Instalar Poetry e dependências do projeto
RUN pip install --no-cache-dir "poetry==$POETRY_VERSION" && \
    poetry config virtualenvs.create false && \
    poetry install --no-root --no-interaction --no-ansi

# Copiar todo o código da aplicação
COPY . .

# Expor a porta da API FastAPI
EXPOSE 8000

# Definir ponto de entrada

VOLUME /app/output
CMD ["python", "run.py", "--host", "0.0.0.0", "--port", "8000"]
