# Docker Compose — Subindo a Acessília

Também disponível em **inglês (EUA)**: [English version](docker-compose.md)

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

Isso constrói a imagem de `infra/Dockerfile`. A extração estrutural usa a Toolbox remota. O container expõe:

| Porta | Serviço        |
|-------|----------------|
| 8000  | API REST       |
| 8001  | Painel web     |

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

Isso baixa e executa `ghcr.io/a11ydevs/acessilia:develop`; a extração usa a Toolbox.

---

## 3. Tags disponíveis no GHCR

O CI/CD publica automaticamente as seguintes imagens:

| Tag | Descrição |
|-----|-----------|
| `:develop` | Build aprovado da branch develop |
| `:main` | Build aprovado da branch main |
| `:latest` | Alias de main |
| `:sha-<7-char-commit>` | Commit específico |
| `:release-<nome>` | Branch release, com `/` convertido em `-` |

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
STRUCTURER=toolbox
TOOLBOX_BASE_URL=http://host.docker.internal:8002
TOOLBOX_PROVIDER=docling

# Pipeline
PIPELINE_ENGINE=pddl
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

## 6. Update automático (staging e produção)

Se você estiver rodando um servidor de homologação, pode configurar **update
automático** via systemd timer. O script consulta a **GitHub API** a cada
**5 minutos** e só executa `docker pull` quando há um commit novo na `develop`.

```bash
# Setup completo (recomendado)
./scripts/setup-homologacao.sh

# Ou fazer manualmente
# Consulte docs/homologacao-systemd.md para instruções manuais
```

Para producao, use [docs/producao-systemd.md](docs/producao-systemd.md) ou rode
`./scripts/setup-producao.sh`. O ambiente rastreia `main` por padrao com
`docker-compose.production.yml` e `scripts/production-update.sh`.

**Requer:** `jq` e um token GitHub com escopo `read:packages`.

---

## 7. Extração e modelos

A aplicação publica uma imagem e depende da API Toolbox para extração estrutural. Configure o provedor e seu cache no serviço Toolbox. O Dockerfile da aplicação não aceita `WITH_DOCLING` e o workflow atual não publica variantes `-slim`.

Para diagnosticar a conexão e validar uma extração:

```bash
docker compose exec acessilia python -m scripts.check_toolbox
docker compose exec acessilia python -m scripts.manifest /app/path/to/document.pdf
```

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

