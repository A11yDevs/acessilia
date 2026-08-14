# Contribuindo para acessilia

Obrigado por considerar contribuir! Este documento define as diretrizes do projeto baseadas em um **Git Flow simplificado**, pensado para manter a agilidade típica de projetos open source.

## Modelo de branches

```
main  ──────────────●──────────────────●──  (versões estáveis)
   \              / \                /
    develop ─────●───●──────────────●────  (integração)
        \        /      \          /
         feat/* ──       fix/* ────
```

### Branches eternas

| Branch | Finalidade |
|--------|------------|
| `main` | **Produção.** Código estável e revisado. Apenas merges vindos de `develop` ou `hotfix/*`. |
| `develop` | **Integração.** Onde as funcionalidades em desenvolvimento se encontram. Branch padrão para colaboração. |

### Papéis e permissões

| Papel | Quem | Permissões |
|-------|------|------------|
| **Mantenedores** | [@marceloakira](https://github.com/marceloakira) e [@jhonata192](https://github.com/jhonata192) | Únicos autorizados a mesclar `develop → main` e criar releases. |
| **Colaboradores** | Todos os demais | Podem abrir PRs para `develop` e revisar. |

> **Importante:** branches temporárias devem ser deletadas após o merge.

### Branches temporárias

| Prefixo | Finalidade | Nasce de | Mergeia em |
|---------|------------|----------|------------|
| `feat/*` | Nova funcionalidade | `develop` | `develop` |
| `fix/*` | Correção de bug | `develop` | `develop` |
| `docs/*` | Documentação | `develop` | `develop` |
| `refactor/*` | Refatoração | `develop` | `develop` |
| `chore/*` | Manutenção (deps, CI, config) | `develop` | `develop` |
| `hotfix/*` | Correção crítica em produção | `main` | `main` e `develop` |

> **Importante:** Branches temporárias devem ser deletadas após o merge.

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

### 5. Release (develop → main)

Apenas mantenedores ([@marceloakira](https://github.com/marceloakira) e [@jhonata192](https://github.com/jhonata192)) podem mesclar `develop → main`.

1. Abra um Pull Request de `develop` para `main` no GitHub.
2. Solicite revisão de outro mantenedor.
3. Após aprovação, faça o merge (preferencialmente "Create a merge commit").
4. A **CI/CD** dispara automaticamente:
   - Testes são executados.
   - Uma nova imagem Docker é built e publicada em `ghcr.io/A11yDevs/acessilia` com as tags `latest` e `v<versão>`.
   - Uma **Release** é criada no GitHub com as notas de versão geradas automaticamente.
   - Uma **tag semântica** (`v<versão>`) é criada no repositório.

> A versão é lida automaticamente do campo `version` no `pyproject.toml`.

```bash
# Fluxo manual (alternativa)
git checkout main
git merge develop
git push origin main
# O CI/CD fará o resto automaticamente
```

Depois do release, mergeie a tag de volta para `develop`:

```bash
git checkout develop
git merge v0.2.0
git push origin develop
```

### 6. Hotfix (correção crítica)

```bash
git checkout main
git checkout -b hotfix/crash-upload
# faz a correção
git commit -m "fix: corrige crash ao fazer upload de PDF corrompido"
git checkout main
git merge hotfix/crash-upload
git tag -a v0.2.1 -m "v0.2.1: hotfix crash upload"
git push origin main --tags

# Mergeia também na develop
git checkout develop
git merge hotfix/crash-upload
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

A esteira de CI/CD está definida em dois workflows:

- **`.github/workflows/ci.yml`** — executa os testes em duas variantes (`slim` e `docling`) para todo PR direcionado à `main` e após pushes na `main`.
- **`.github/workflows/delivery.yml`** — após o CI passar na `main`, constrói, testa e publica as imagens Docker no GitHub Container Registry.

| Workflow | Evento | Ação |
|----------|--------|------|
| **CI** | PR para `main` | Testa as variantes slim e docling |
| **CI** | Push na `main` | Testa as variantes slim e docling |
| **Delivery** | CI concluído na `main` | Build, teste e push das imagens para o GHCR |

São publicadas quatro referências no `ghcr.io/A11yDevs/acessilia`:

- `main` — imagem completa com Docling, RapidOCR e PyTorch CPU
- `main-slim` — variante sem Docling
- `sha-<commit>` — imagem Docling imutável
- `sha-<commit>-slim` — slim imutável

Nenhum modelo é embutido nas imagens. Os modelos são baixados em tempo de execução e persistidos no volume `/app/var`. O Delivery verifica isso antes de publicar.

## Dúvidas?

Abra uma [issue](https://github.com/A11yDevs/acessilia/issues) ou inicie uma [discussão](https://github.com/A11yDevs/acessilia/discussions).