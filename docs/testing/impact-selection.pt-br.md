# Seleção de testes orientada pela arquitetura (modo observação)

> [impact-selection.md](impact-selection.md). A versão em inglês é a fonte.

Este é o próximo passo da [issue #644](https://github.com/A11yDevs/acessilia/issues/644):
um seletor que mapeia arquivos alterados para as suítes dos componentes que eles
podem afetar. Ele roda em **modo observação** nos pull requests: registra o que
uma CI orientada por impacto executaria, enquanto a suíte completa continua
sendo o gate de merge.

- **Script:** [`scripts/tests/select_suites.py`](../../scripts/tests/select_suites.py).
- **Job de CI:** `detect changed components (shadow)`, artefato
  `test-selection-shadow`.
- **Saída legível por máquina:** `var/selection.json`.

## Modelo de dependências

A seleção segue a direção de dependências de
[dependencies.md](../architecture/dependencies.md) para as arestas do
serviço/SDK/docstruct e do ADR-0016 para `libs/core`. Neste documento, **core**
significa `libs/core` (`acessilia_core`), não o serviço `backend/`/`frontend/`:

| Componente alterado | docstruct | SDK | core | aplicação |
|---|---:|---:|---:|---:|
| docstruct | obrigatório | obrigatório | obrigatório | obrigatório |
| SDK | — | obrigatório | obrigatório | obrigatório |
| core | — | — | obrigatório | obrigatório |
| backend/frontend/tests | — | — | — | obrigatório |
| schemas/contratos | obrigatório | obrigatório | obrigatório | obrigatório |
| CI/config compartilhada | obrigatório | obrigatório | obrigatório | obrigatório |

Uma alteração em um consumidor nunca força a suíte unitária de suas
dependências; uma alteração em uma biblioteca de base sempre seleciona seus
consumidores.

## Regras

- `libs/docstruct/**` → docstruct, SDK, core, aplicação.
- `libs/sdk/**` → SDK, core, aplicação.
- `libs/core/**` → core, aplicação.
- `backend/**`, `frontend/**`, `tests/**` → aplicação.
- `docs/**` e `*.md` → aplicação (os guardas de documentação, links e português
  vivem na suíte da aplicação).
- `.github/**`, `infra/**`, `schemas/**`, `scripts/**`, `deploy/**`, `Makefile`,
  `pyproject.toml`, `uv.lock`, `.python-version`, arquivos Docker Compose →
  todas as suítes. Arquivos aninhados em `libs/*` não são transversais, a menos
  que batam com uma regra de biblioteca.
- Um caminho sob `schemas/` de topo ou um nome de arquivo contendo
  `toolbox-contract`/`capability_contract` define `contracts_required` além da
  seleção de suítes.
- `integration_required` é definido para `backend/**`, `frontend/**`,
  `libs/core/**`, `libs/sdk/**`, `libs/docstruct/**`, o teste focado
  `tests/test_provider_choice_methods.py` e seu suporte compartilhado
  (`conftest.py`, `judge_support.py`, `core_config_support.py`,
  `toolbox_render_fake.py`, `pyproject.toml`, `uv.lock`, workflow de CI). Isso
  espelha o gatilho do job `app integration` para eventos de caminho em pull
  requests; o seletor é case-insensitive e seus fallbacks são supersets. Os
  globs vivem em `INTEGRATION_GLOBS`, e um teste de workflow os compara com o
  filtro da CI.
- Caminhos desconhecidos, diff vazio ou falha no `git diff` → todas as suítes,
  a flag conservadora e `integration_required`. Caminhos desconhecidos definem
  `unclassified_changed` em vez de fingir que são infraestrutura.

O script reporta indicadores separados
(`docstruct_changed`, `sdk_changed`, `core_changed`, `app_changed`,
`contracts_changed`, `infrastructure_changed`, `unclassified_changed`,
`integration_changed`) para que as regras possam ser auditadas sem ler a lista
de caminhos.

## Modo observação

O job do workflow roda apenas em `pull_request`:

```bash
python scripts/tests/select_suites.py \
  --base-ref origin/develop --head-ref HEAD \
  --output var/selection.json \
  --summary "$GITHUB_STEP_SUMMARY"
```

O job exige `fetch-depth: 0` e busca a branch base antes do diff de três pontos.
Nenhum job depende dele; o gate de entrega não o inclui. Os passos de fetch e
seleção usam `continue-on-error`, então a indisponibilidade da evidência não
deixa o pull request vermelho.

Localmente:

```bash
python scripts/tests/select_suites.py \
  --changed-file libs/core/src/acessilia_core/config.py

python scripts/tests/select_suites.py \
  --changed-file backend/api/app.py --changed-file libs/sdk/README.md
```

## Critérios de adoção

O seletor se torna um gate somente depois que as observações mostrarem, em um
conjunto representativo de pull requests:

- nenhuma regressão que a suíte completa teria pego foi omitida;
- guardas de contrato e arquitetura continuam obrigatórios;
- alterações transversais selecionam consistentemente todas as suítes;
- a economia de tempo de parede e de runner-minutes justifica o job extra;
- a matriz é atualizada quando um componente ou uma aresta de dependência nova
  aparece.

Até lá, a suíte completa é obrigatória e este job é apenas evidência.

## Limitações

- A matriz é um modelo estático, não um grafo de dependências em tempo de
  execução. Um import novo que cruze a fronteira de um componente precisa ser
  refletido aqui e em `dependencies.md`.
- Um seletor por caminho não vê arquivos gerados que não são versionados.
- Deleções e renomeações são expandidas (`--no-renames`, `ACMRDT`) para
  classificar os dois lados.
- Alterações de documentação são enviadas conservadoramente para a suíte da
  aplicação.
- O `git diff` é de três pontos: uma base desatualizada ou um checkout raso
  aciona o fallback conservador.
