# Docker Compose — Subindo a Acessília

Este documento descreve como executar a Acessília localmente usando Docker, tanto
com **build a partir do código-fonte** quanto com **imagens pré-publicadas no GHCR**
(sem precisar baixar o repositório nem compilar nada).

---

## Pré-requisitos

- [Docker](https://docs.docker.com/get-docker/) (com Compose V2 integrado)
- Acesso à internet para baixar imagens ou dependências

---

## 1. Subindo com build local (a partir do código-fonte)

Usa o `docker-compose.yml` padrão, que faz o build da imagem localmente.

```bash
# 1. Clone o repositório (se ainda não tiver)
git clone git@github.com:A11yDevs/acessilia.git
cd acessilia

# 2. Configure o ambiente
cp .env.example .env
# Edite .env com suas credenciais (pelo menos BOT_TOKEN se for usar Telegram)

# 3. Suba o container (build automático)
docker compose up -d
```

Isso constrói a imagem a partir do `infra/Dockerfile` com a variante **docling**
(completa, ~4-6 GB). O container expõe:

| Porta | Serviço        |
|-------|----------------|
| 8000  | API REST       |
| 8001  | Painel web     |

### Variante slim (sem Docling)

Para uma imagem mais leve (~2 GB), sem OCR do Docling:

```bash
docker compose build --build-arg WITH_DOCLING=false
docker compose up -d
```

---

## 2. Subindo com imagem do GHCR (sem build)

Usa o `docker-compose.staging.yml`, que já referencia as imagens publicadas
no GitHub Container Registry. **Não requer o código-fonte.**

```bash
# 1. Crie um diretório para o ambiente
mkdir acessilia-staging && cd acessilia-staging

# 2. Baixe apenas o compose file e o .env.example
curl -O https://raw.githubusercontent.com/A11yDevs/acessilia/develop/docker-compose.staging.yml
curl -O https://raw.githubusercontent.com/A11yDevs/acessilia/develop/.env.example

# 3. Configure o ambiente
cp .env.example .env
# Edite .env com suas credenciais

# 4. Crie os diretórios de dados
mkdir -p var/temp var/data var/logs

# 5. Suba o container (baixa a imagem automaticamente)
docker compose -f docker-compose.staging.yml up -d
```

Isso baixa e executa `ghcr.io/a11ydevs/acessilia:develop` (variante docling).

### Usando a variante slim

Edite o `docker-compose.staging.yml` e altere a tag da imagem:

```yaml
image: ghcr.io/a11ydevs/acessilia:develop-slim
```

Ou via sed:

```bash
sed -i '' 's/:develop$/:develop-slim/' docker-compose.staging.yml
docker compose -f docker-compose.staging.yml up -d
```

---

## 3. Tags disponíveis no GHCR

O CI/CD publica automaticamente as seguintes imagens:

| Tag                              | Variante | Descrição                          |
|----------------------------------|----------|------------------------------------|
| `:develop`                       | docling  | Último build da branch `develop`   |
| `:develop-slim`                  | slim     | Último build da `develop` (leve)   |
| `:main`                          | docling  | Último build da branch `main`      |
| `:main-slim`                     | slim     | Último build da `main` (leve)      |
| `:latest`                        | docling  | Aponta para `main`                 |
| `:latest-slim`                   | slim     | Aponta para `main` (leve)          |
| `:sha-<7-char-commit>`           | docling  | Build de um commit específico      |
| `:sha-<7-char-commit>-slim`      | slim     | Build de um commit específico (leve)|
| `:vX.Y.Z`                        | docling  | Release versionada                 |
| `:vX.Y.Z-slim`                   | slim     | Release versionada (leve)          |

Exemplo para puxar uma imagem manualmente:

```bash
docker pull ghcr.io/a11ydevs/acessilia:develop
docker pull ghcr.io/a11ydevs/acessilia:sha-abc1234
```

---

## 4. Configuração do `.env`

O mínimo necessário para testar:

```env
# Interfaces ativas
ENABLED_INTERFACES=api,web

# API
API_HOST=0.0.0.0
API_PORT=8000
API_BASE_URL=http://localhost:8000
WEB_PORT=8001

# Diretórios
TEMP_DIR=var/temp
DATA_DIR=var/data
LOGS_DIR=var/logs

# Log
LOG_LEVEL=INFO

# AI Client (escolha um)
AI_CLIENT=ollama
OLLAMA_BASE_URL=http://host.docker.internal:11434/v1/chat/completions
OLLAMA_MODEL=llama3.2-vision

# Estruturação de documentos
STRUCTURER=docling   # ou pymupdf (mais leve, sem dependências extras)

# Pipeline
PIPELINE_ENGINE=legacy
```

> **Dica para Ollama local:** Use `host.docker.internal` no lugar de `localhost`
> para que o container alcance o servidor Ollama rodando no host.

---

## 5. Comandos úteis

```bash
# Ver logs em tempo real
docker compose logs -f

# Parar e remover o container
docker compose down

# Executar comando interativo no container
docker compose exec acessilia python -c "from backend.core.version import __version__; print(__version__)"

# Verificar health check da API
curl http://localhost:8000/api/v1/health

# Inspecionar qual imagem está rodando
docker inspect acessilia-instance --format '{{.Config.Image}}'

# Puxar manualmente uma imagem específica
docker pull ghcr.io/a11ydevs/acessilia:sha-abc1234
```

---

## 6. Update automático (staging)

Se você estiver rodando um servidor de homologação, pode configurar **update
automático** via systemd timer. O script consulta a **GitHub API** a cada
**5 minutos** e só executa `docker pull` quando há um commit novo na `develop`.

```bash
# Setup completo (recomendado)
./scripts/setup-homologacao.sh

# Ou fazer manualmente
# Consulte docs/homologacao-systemd.md para instruções manuais
```

**Requer:** `jq` e um token GitHub com escopo `read:packages`.

---

## 7. Variantes de imagem

| Variante | Tamanho aprox. | Docling | OCR | Uso recomendado |
|----------|----------------|---------|-----|-----------------|
| **docling** | ~4-6 GB | ✅ Sim | ✅ Nativo (CPU) | Precisão máxima em documentos |
| **slim**   | ~2 GB   | ❌ Não | ❌ Fallback pymupdf | Testes rápidos, recursos limitados |

A variante **docling** é a padrão e oferece:
- Detecção de tabelas, figuras e fórmulas
- OCR nativo CPU-only (sem GPU)
- Extração estrutural mais precisa

A variante **slim** faz fallback automático para `pymupdf` com um aviso no log.

---

## 8. Solução de problemas

### Container não sobe — porta ocupada

```bash
# Verifique se a porta já está em uso
lsof -i :8000
# Altere as portas no docker-compose.yml ou pare o serviço conflitante
```

### Health check falhando

```bash
# Verifique os logs
docker compose logs acessilia
# Confirme que o .env tem ENABLED_INTERFACES=api (mínimo para health check)
```

### Ollama não acessível do container

Certifique-se de que:
1. O Ollama está rodando no host
2. A variável `OLLAMA_BASE_URL` usa `http://host.docker.internal:11434/...`
3. No Linux, use `--network host` ou o IP do gateway: `http://172.17.0.1:11434/...`

### Imagem não encontrada no GHCR

```bash
# Verifique se a tag existe
docker pull ghcr.io/a11ydevs/acessilia:develop
# Se falhar, faça login no GHCR
echo $GITHUB_TOKEN | docker login ghcr.io -u <seu-user> --password-stdin
```