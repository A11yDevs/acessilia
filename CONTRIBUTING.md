# Contribuindo para acessilia

Obrigado por considerar contribuir! Este documento define as diretrizes do projeto baseadas em um **Git Flow simplificado**, pensado para manter a agilidade típica de projetos open source.

## Modelo de branches

```
main  ──────────────●──────────────────●──  (versões estáveis)
   \              /  \                /
    develop ─────●─── release/x.y.z ─●────  (integração / BHS)
        \        /  \       |       /
         feat/* ──   fix/* ─┴──────
```

### Branches eternas

| Branch | Finalidade |
|--------|------------|
| `main` | **Produção.** Código estável e revisado. Apenas merges vindos de `develop` ou `hotfix/*`. |
| `develop` | **Integração.** Onde as funcionalidades em desenvolvimento se encontram. Branch padrão para colaboração. |

### Papéis e permissões

| Papel | Quem | Permissões |
|-------|------|------------|
| **Mantenedores** | [@marceloakira](https://github.com/marceloakira), [@jhonata192](https://github.com/jhonata192) e [@fragaeduardo](https://github.com/fragaeduardo) | Únicos autorizados a mesclar `develop → main` e criar releases. |
| **Colaboradores** | Todos os demais | Podem abrir PRs para `develop` e revisar. |

> **Importante:** branches temporárias devem ser deletadas após o merge.

### Branches temporárias

| Prefixo | Finalidade | Nasce de | Mergeia em |
|---------|------------|----------|------------|
| `feat/*` | Nova funcionalidade | `develop` | `develop` |
| `fix/*` | Correção de bug | `develop` | `develop` (ou `release/*` durante o BHS, ver [seção 5.1](#51-bug-huntingsquashing-bhs)) |
| `docs/*` | Documentação | `develop` | `develop` |
| `refactor/*` | Refatoração | `develop` | `develop` |
| `chore/*` | Manutenção (deps, CI, config) | `develop` | `develop` |
| `release/*` | Estabilização de uma release (ciclo de BHS) | `develop` | `main` e `develop` |
| `hotfix/*` | Correção crítica em produção | `main` | `main` e `develop` |

> **Importante:** Branches temporárias devem ser deletadas após o merge.

## Executar localmente com Docker

Para instruções detalhadas sobre como subir a Acessília com Docker — tanto com
build local quanto com imagens pré-publicadas do GHCR (sem precisar do código-fonte) —
consulte o guia dedicado:

📄 [`docs/docker-compose.md`](docs/docker-compose.md)

## Fluxo de trabalho diário

### 1. Iniciar uma tarefa

```bash
# Sincronizar com a develop
git checkout develop
git pull

# Criar branch para a tarefa
git checkout -b feat/minha-feature
```

### 2. Desenvolver

Faça commits atômicos seguindo a [convenção de commits](#convenção-de-commits).

```bash
git add .
git commit -m "feat(api): adiciona endpoint de exportação EPUB"
```

### 3. Manter sincronizado

Sempre faça rebase com a `develop` para evitar conflitos grandes:

```bash
git fetch origin
git rebase origin/develop
```

### 4. Enviar para revisão

Antes de abrir o Pull Request, garanta que os testes estão passando:

```bash
poetry run pytest tests/ -v
```

A esteira de CI rodará automaticamente os testes no GitHub. O PR só poderá ser revisado se **todos os testes estiverem verdes**.

```bash
# Opção A — via GitHub (recomendado)
git push origin feat/minha-feature
# Abra um Pull Request de feat/minha-feature → develop

# Opção B — merge local (para mudanças simples)
git checkout develop
git merge feat/minha-feature
git push origin develop
git branch -d feat/minha-feature
```

### 5. Homologação (QA)

Após o merge de um PR na `develop`, a **esteira de CD** (`.github/workflows/delivery.yml`)
constrói automaticamente uma imagem Docker e a publica no GHCR com as tags
`develop` e `sha-<commit>`.

O ambiente de homologação usa um **timer systemd** (`staging-update.timer`) que
verifica a cada 60s se há uma nova imagem e reinicia o container automaticamente.
Veja [docs/homologacao-systemd.md](docs/homologacao-systemd.md) para instruções
detalhadas de instalação e gerenciamento.

O setup completo do ambiente de homologação está em:

- `docker-compose.staging.yml` — define o container
- `scripts/staging-update.sh` — script de atualização
- `scripts/setup-homologacao.sh` — script de configuração inicial

```bash
# Consultar qual imagem está no ar (via API de health)
curl http://homologacao:8000/api/v1/health | jq .

# Ou puxar manualmente uma imagem específica para testar
 docker pull ghcr.io/a11ydevs/acessilia:sha-abc1234

# Verificar qual tag está rodando no container
docker inspect acessilia-staging | jq '.[0].Config.Image'
```

O setup completo do ambiente de homologação está em:

- `docker-compose.staging.yml` — define o container + Watchtower
- `scripts/setup-homologacao.sh` — script de configuração inicial

### 5.1 Bug Hunting/Squashing (BHS)

Antes de cada release, há um ciclo de **Bug Hunting/Squashing (BHS)**: um período em
que o staging testa exatamente o candidato a release, sem misturar features ainda
em desenvolvimento. Para isso, criamos uma branch efêmera `release/x.y.z` a partir
da `develop`.

1. **Cut** — no início do BHS, corte a branch de release a partir da `develop`:

   ```bash
   git checkout develop && git pull
   git checkout -b release/0.0.1 origin/develop
   git push origin release/0.0.1
   ```

2. **Durante o BHS**:
   - PRs `fix/*` que corrigem bugs encontrados no staging vão para `release/0.0.1`
     (em vez de `develop`).
   - PRs `feat/*` continuam mirando `develop` normalmente — a `develop` nunca é
     bloqueada, pois o escopo da release já foi travado no cut.
   - A **esteira de CI** (`ci.yml`) roda os mesmos testes slim/docling em PRs e
     pushes para `release/**`.
   - A **esteira de CD** (`delivery.yml`) publica a imagem da `release/0.0.1` no
     GHCR com as tags `release-0.0.1` e `sha-<commit>`.

3. **Staging aponta para a release** — defina `TRACK_BRANCH=release/0.0.1` no
   `.env` do servidor de homologação para que `scripts/staging-update.sh` passe
   a rastrear a branch de release (tag de imagem `release-0.0.1`) em vez da
   `develop`:

   ```bash
   echo "TRACK_BRANCH=release/0.0.1" >> .env
   ```

4. **Fechamento do BHS** — quando a release estiver estável:

   ```bash
   # Merge para main (gera a release oficial, ver seção 6)
   # Abra um PR de release/0.0.1 → main e mescle após aprovação

   # Propaga as correções para develop
   # Abra um PR de release/0.0.1 → develop e mescle após aprovação

   git push origin --delete release/0.0.1
   ```

   Depois, remova (ou reverta) `TRACK_BRANCH` do `.env` de homologação para que
   o staging volte a rastrear a `develop`.

### 6. Release (develop → main)

Apenas mantenedores ([@marceloakira](https://github.com/marceloakira),
[@jhonata192](https://github.com/jhonata192) e
[@fragaeduardo](https://github.com/fragaeduardo)) podem mesclar `develop → main`.

1. **QA homologou?** → siga em frente.
2. Abra um Pull Request de `develop` para `main` no GitHub.
3. Solicite revisão de outro mantenedor.
4. Após aprovação, faça o merge (preferencialmente "Create a merge commit").
5. A **esteira de CD** na `main` publica as tags `main`, `latest` e `sha-<commit>`.

Para criar uma **Release oficial** com versão semântica:

```bash
# 1. Atualize a versão no pyproject.toml
#    (ex: bump de "0.2.0" para "0.3.0")
git checkout main && git pull
# edite pyproject.toml
git add pyproject.toml
git commit -m "chore(release): bump to 0.3.0"

# 2. Crie a tag semântica
git tag v0.3.0
git push origin main --tags

# 3. O workflow Release (release.yml) builda, publica v0.3.0 no GHCR
#    e cria a GitHub Release com changelog automático
```

Depois do release, mergeie `main` de volta para `develop`:

```bash
git checkout develop
git merge main
git push origin develop
```

### 7. Hotfix (correção crítica)

Hotfixes seguem o mesmo fluxo de PR, não push direto. A CI cria a tag e release automaticamente.

```bash
git checkout main
git checkout -b hotfix/crash-upload
# faz a correção
git commit -m "fix: corrige crash ao fazer upload de PDF corrompido"
git push origin hotfix/crash-upload
# Abra um Pull Request de hotfix/crash-upload → main no GitHub
# Após aprovação e merge, a CI cria a imagem main + sha-xxx

# Se for crítica a ponto de merecer release imediata:
git tag v0.3.1 && git push origin v0.3.1

# Propaga para develop
git checkout develop
git merge main
git push origin develop
git branch -d hotfix/crash-upload
```

## Convenção de commits

Usamos [Conventional Commits](https://www.conventionalcommits.org/):

```
<tipo>(<escopo opcional>): <descrição>

[corpo opcional]
```

### Tipos

| Tipo | Uso |
|------|-----|
| `feat` | Nova funcionalidade |
| `fix` | Correção de bug |
| `docs` | Documentação |
| `refactor` | Refatoração sem mudar comportamento |
| `test` | Testes |
| `chore` | Manutenção (deps, CI, config) |
| `style` | Formatação, lint |
| `perf` | Melhoria de performance |

### Exemplos

```
feat(api): adiciona endpoint de exportação em EPUB
fix(telegram): corrige timeout em arquivos grandes (>10MB)
docs(readme): atualiza exemplos de uso da API
refactor(agents): extrai lógica de OCR para serviço separado
test(pipeline): adiciona teste para fluxo PDDL com Docling
chore(deps): atualiza fastapi para 0.115
perf(ocr): reduz uso de memória no RapidOCR
```

## Versionamento

Seguimos [Semantic Versioning](https://semver.org/):

```
vMAJOR.MINOR.PATCH
```

- **MAJOR**: mudança incompatível na API pública
- **MINOR**: nova funcionalidade compatível com versões anteriores
- **PATCH**: correção de bug compatível

## Regras do time

1. **Nunca commitar direto na `main`** — sempre usar branches + PR.
2. **Nunca commitar direto na `develop`** — exceto merges de branches temporárias.
3. **Sempre fazer rebase** antes do merge para manter histórico linear.
4. **Branches são temporárias** — duram apenas o necessário para a tarefa.
5. **PRs pequenos e focados** — mais fáceis de revisar e com menos conflitos.
6. **Commits atômicos** — um commit = uma mudança lógica completa.
7. **Testes obrigatórios** — toda `feat` ou `fix` deve incluir ou atualizar testes.
8. **Rodar `pytest` antes do push** — garantir que nada está quebrado.

## Rulesets (proteção de branches)

O repositório utiliza **GitHub Rulesets** para proteger a branch `main` contra deleção, force-push e merges sem revisão. Rulesets são configurados **via API REST**, não por arquivos no repositório.

O arquivo `.github/rulesets/main.json.example` contém o modelo da configuração atual. Para aplicar ou atualizar os rulesets, execute:

```bash
# Aplica/atualiza os rulesets via GitHub API
./scripts/setup-rulesets.sh

# Apenas visualiza o payload sem modificar nada
DRY_RUN=1 ./scripts/setup-rulesets.sh
```

> **Importante:** O ruleset permite bypass para administradores do repositório (`RepositoryRole`), para que mantenedores possam gerenciar a branch sem bloqueios.

## Setup do ambiente

```bash
# Clone e instale dependências
git clone git@github.com:A11yDevs/acessilia.git
cd acessilia
poetry install

# Configure as variáveis de ambiente
cp .env.example .env

# Execute os testes para verificar se está tudo ok
poetry run pytest
```

## Pull Requests

1. Certifique-se de que sua branch está atualizada com a `develop` (`git rebase origin/develop`).
2. Execute `poetry run pytest` e veja se todos os testes passam.
3. Descreva claramente o que o PR faz e qual problema resolve.
4. Referencie issues relacionadas (ex.: `Closes #42`).
5. Aguarde a revisão e ajuste se necessário.

## Integração contínua (CI/CD)

A esteira de CI/CD está definida em três workflows:

- **`.github/workflows/ci.yml`** — executa os testes em duas variantes (`slim` e `docling`) para todo PR direcionado à `main` ou `develop`, e após pushes nessas branches.
- **`.github/workflows/delivery.yml`** — após o CI passar, constrói e publica imagens Docker no GHCR.
- **`.github/workflows/release.yml`** — quando um mantenedor cria uma tag `v*`, builda, publica e cria GitHub Release.

| Workflow | Evento | Ação |
|----------|--------|------|
| **CI** | PR para `main` ou `develop` | Testa as variantes slim e docling |
| **CI** | Push na `main` ou `develop` | Testa as variantes slim e docling |
| **Delivery** | CI concluído na `main` | Build, smoke test + push: `main`, `latest`, `sha-xxx`, `main-slim`, `sha-xxx-slim` |
| **Delivery** | CI concluído na `develop` | Build, smoke test + push: `develop`, `sha-xxx`, `develop-slim`, `sha-xxx-slim` |
| **Release** | Tag `v*` criada no git | Build, smoke test + push: `vX.Y.Z`, `vX.Y.Z-slim` + GitHub Release |

São publicadas as seguintes referências no `ghcr.io/a11ydevs/acessilia`:

| Tag | Branch de origem | Finalidade |
|-----|-----------------|------------|
| `develop` / `develop-slim` | `develop` | Homologação (atualizada via systemd timer) |
| `main` / `main-slim` | `main` | Produção (CD) |
| `latest` / `latest-slim` | `main` | Produção (aponta pro último) |
| `sha-<commit>` / `sha-<commit>-slim` | `main` ou `develop` | Referência imutável |
| `vX.Y.Z` / `vX.Y.Z-slim` | Tag git `v*` | Release oficial |

## Dúvidas?

Abra uma [issue](https://github.com/A11yDevs/acessilia/issues) ou inicie uma [discussão](https://github.com/A11yDevs/acessilia/discussions).