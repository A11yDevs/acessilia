# Fluxo de testes: feedback rápido e o gate completo

Você também pode ler esta documentação em **inglês**: [English](testing.md).

Na verificação de 2026-11-18, o projeto tem 6.339 testes: 2.926 sem E2E na suíte
principal, 1.206 em `libs/core/tests`, 1.587 em `libs/docstruct` e 620 em
`libs/sdk`. Rodar tudo depois de cada pequena
edição é caro, tanto localmente quanto na CI. Este guia explica como a suíte está
organizada, quais comandos usar em cada etapa do ciclo editar–testar–corrigir e
quais técnicas tornam o ciclo mais rápido sem enfraquecer o gate de regressão. As
mudanças vieram da issue
[#448](https://github.com/A11yDevs/acessilia/issues/448).

## O problema: suíte grande, ciclo curto

Uma execução serial completa da suíte principal leva cerca de 2m23s na máquina de
referência; o job `tests` da CI levava 1m59s. A maior parte desse tempo não tem
relação com uma edição de uma linha. Esperar minutos a cada mudança quebra a
concentração e incentiva pular testes.

A resposta não é rodar menos testes no gate de merge. É rodar os testes *certos*
durante o desenvolvimento, rodar a suíte completa antes da integração e tornar a
própria suíte completa mais rápida.

## Qual comando devo usar?

| Situação | Comando | O que acontece |
|---|---|---|
| Mudei um arquivo ou um teste | `make test-file F=tests/test_example.py` | Roda apenas esse caminho, sem E2E |
| Corrigi uma falha e quero confirmar | `make test-failed` | Reexecuta as falhas registradas nos caches da suíte principal, do docstruct, do SDK e do `libs/core` |
| Quero a confiança local completa | `make test-all` | Suíte principal com quatro workers, depois docstruct, SDK e `libs/core` |
| Quero verificar o lint (baseline do Ruff) | `make lint` | Executa o Ruff (`F`, `I`, `E` sem `E501`) via `scripts/check_ruff_baseline.py` |
| Quero verificar tipos estáticos (Mypy) | `make typecheck` | Executa o Mypy no escopo configurado de `docstruct`, `acessilia_sdk`, `acessilia_core` e `backend` |
| Quero relatórios de cobertura por componente | `make coverage` | Executa as quatro suítes com cobertura de desvios, grava `var/coverage/{app,core,sdk,docstruct}/` e exige os limites |
| Quero evidência de sobreposição de cobertura | `make test-overlap` | Executa a suíte da aplicação com contextos por teste e grava os relatórios de sobreposição/redundância em `var/overlap/` (#644) |
| Quero um experimento limitado de mutação | `make test-mutation` | Executa os mutantes AST de um módulo da docstruct e grava o relatório em `var/mutation/` (#644) |
| Quero só a suíte principal, em paralelo | `uv run pytest -m "not e2e" -n 4 --dist worksteal` | Roda a suíte principal non-E2E com quatro workers |
| Quero só a biblioteca do core | `(cd libs/core && uv run --extra dev pytest)` | Roda a suíte do core, sem o serviço |
| Preciso ver os comandos exatos do `make` | `make -n test-all` | Imprime os comandos sem executar |

`make` sem alvo imprime a lista curta de comandos.

> **Importante:** `uv run pytest` sem `-n` é **serial**. Ele também não executa
> as suítes `libs/docstruct` e `libs/sdk`. O ganho vem do `make test-all` ou de
> passar `-n 4 --dist worksteal` explicitamente.

## O que roda por padrão

### Na CI

Todo pull request e push para `develop`, `main` ou uma branch de release executa
o workflow `CI` do GitHub Actions:

- **`app tests (Python 3.12)`, `docstruct tests (Python 3.12)`,
  `sdk tests (Python 3.12)` e `core tests (Python 3.12)`** executam as quatro
  suítes em paralelo, cada uma com cobertura de desvios, seu próprio limite, sua
  própria recusa de skips e seus artefatos JUnit/cobertura. A suíte da aplicação
  mantém a execução limitada com quatro workers e exclui testes marcados como
  `integration`.
- **`app integration (Python 3.12)`** executa os testes in-process caros de
  handler/pipeline marcados como `integration` quando `backend/**`,
  `frontend/**`, `libs/core/**`, o suporte de testes compartilhado ou o teste
  focado de escolha de provider muda. Também roda em todo push para `main`,
  `develop` ou uma branch de release e em `workflow_dispatch`. O marker separa
  a cobertura de integração cara sem tratá-la como E2E real; `e2e` continua
  sendo o marker de ambiente externo.
- **`quality (Python 3.12)`** executa o Ruff contra a baseline que só diminui, o
  Mypy no escopo configurado de `docstruct`/SDK/core/backend e um passe 3.11 das
  bibliotecas (#366), o contrato de capacidades da Toolbox e o relatório da
  versão do docstruct fixada pela Toolbox (só avisos; veja abaixo), em paralelo
  com as suítes.
- **`tests (Python 3.12)`** é o agregador obrigatório. Ele falha se qualquer job
  provedor falhou ou foi pulado, baixa os quatro artefatos de cobertura e JUnit,
  aplica os limites globais e publica os resumos de tempo/cobertura
  (`test-reports-py3.12`, `coverage-reports-py3.12`,
  `timing-baseline-py3.12`).
- **`SDK alone (Python 3.12)`** instala apenas o SDK, o docstruct (a única
  dependência de projeto dele, ADR-0017) e as ferramentas de teste do SDK
  (pytest, pytest-asyncio, respx), e prova que ele funciona sem o core.
- **`docstruct alone (Python 3.12)`** instala apenas o docstruct, a partir do
  wheel dele, e o pytest, e roda a suíte só com a biblioteca padrão: o core, o SDK, a
  Toolbox e o acelerador opcional (`rapidfuzz`) não podem estar importáveis, e
  nenhum teste pode ser pulado (#470).
- `tests (Python 3.12)` e `SDK alone (Python 3.12)` são checks obrigatórios nos rulesets vivos de `main` e
  `develop`. O `docstruct alone` ainda não é: torná-lo obrigatório é uma mudança
  de ruleset, decisão de quem mantém o repositório (CONTRIBUTING.pt-br.md).
- **`core alone (Python 3.12)`** instala só o core, como wheel, a partir do
  seu próprio lock (`libs/core/uv.lock`): nem o serviço, nem os front-ends, nem
  o FastAPI, nem o pacote da Toolbox podem ser importados. Ele roda a suíte
  completa do core a partir do wheel, o teste de fumaça a partir de uma pasta
  fora do checkout e a etapa de tabelas pelo `libs/core/examples/table_stage.py`
  (ADR-0016, passo 6). Ainda não é um check obrigatório, pelo mesmo motivo do
  `docstruct alone`.
- **`planning backends (Fast Downward)`** roda o planejador interno e o Fast
  Downward sobre o domínio PDDL atual, e falha a menos que todo caso listado
  tenha passado: um caso pulado, com falha ou apagado reprova o job (#790). Ele
  alimenta o agregador, então bloqueia `tests (Python 3.12)`.
  - A imagem é fixada pelo digest em `scripts/planning/fast_downward.env`, a
    fonte única do job e de `scripts/planning/fast_downward_docker.sh`. O job
    confere a versão que esse arquivo declara.
  - A imagem (116 MB) vem do Docker Hub. O job a guarda em cache, com uma
    chave derivada desse arquivo, e repete um pull que falhou, então uma
    indisponibilidade do Docker Hub só reprova o gate antes de a imagem estar
    em cache.
  - Localmente esses testes ficam fora da seleção. Rode-os com
    `-m fast_downward` e `ACESSILIA_FAST_DOWNWARD` apontando para o script,
    que exige Docker; numa máquina ARM a imagem amd64 roda sob emulação.
- A entrega da imagem espera pelo agregador, pelos três jobs de isolamento e pelos jobs de segurança.

O check da suíte principal não tem mais uma etapa separada de coleta: a própria
execução coleta a suíte. O nome obrigatório é o literal `tests (Python 3.12)` no
agregador; os jobs de componente carregam o componente no nome, e o `UV_PYTHON`
fixa o interpretador.

### Localmente

O comando local suportado para a suíte completa é:

```bash
make test-all
```

Ele roda a suíte principal non-E2E com quatro workers e depois as suítes do
docstruct, do SDK e do `libs/core`, sequencialmente (a última tem a suíte da biblioteca do core:
fronteira, fumaça e os testes migrados do `tests/` no #613). As bibliotecas são rápidas e têm ambientes de
pacote separados, então permanecem simples. O `make test-all` executa as quatro suítes
mesmo se uma falhar e retorna status não zero se alguma falhou.

Rodar `uv run pytest` puro na raiz é outra coisa: usa os padrões do pytest,
inclui testes E2E que precisam de um ambiente real e roda serialmente.

## As técnicas, em linguagem simples

### 1. Rode só o que você está mudando

Um **node id** do pytest identifica um teste, por exemplo
`tests/test_api.py::test_health`. Rodar um arquivo ou um node é muito mais
rápido do que rodar a suíte inteira, e é o primeiro passo natural do ciclo local.

```bash
make test-file F=tests/test_api.py::test_health
make test-file F=tests/test_pddl_planning.py
```

O `make test-file` adiciona `-m "not e2e"` e `--durations=25`, então testes E2E
ficam de fora e os testes mais lentos daquele arquivo aparecem. Para um arquivo
único, iniciar quatro workers geralmente custa mais do que economiza; execuções
direcionadas continuam seriais.

### 2. Reexecute apenas as falhas

Depois de uma execução com falha, `pytest --lf` seria o próximo comando óbvio,
mas ele tem duas armadilhas neste repositório: pode cair para a suíte inteira
quando o cache está vazio e não conhece os caches separados das bibliotecas.

O `make test-failed` é o wrapper suportado. Ele:

- lê o cache `lastfailed` da suíte principal, do docstruct, do SDK e do `libs/core`;
- confere se os arquivos registrados ainda existem e coleta apenas esses
  arquivos;
- reexecuta os node ids explícitos que ainda existem;
- lista testes removidos ou renomeados em vez de cair para uma execução
  completa;
- reexecuta como arquivo um arquivo registrado com erro de coleta;
- termina com sucesso e uma mensagem quando não há nada para reexecutar.

Isso torna o ciclo “corrige uma falha, confirma, segue adiante” rápido e
previsível.

### 3. Rode a suíte principal em paralelo

A suíte principal é a grande. O `pytest-xdist` inicia vários processos workers e
distribui os testes entre eles. O Makefile e a CI usam
`-n 4 --dist worksteal`:

- **`-n 4`** inicia quatro workers, acompanhando o runner de quatro vCPUs do
  GitHub e mantendo o uso de memória limitado.
- **`--dist worksteal`** entrega um novo teste ao worker assim que ele termina
  um. Isso importa porque poucos testes são muito mais lentos que o resto; uma
  distribuição fixa por módulo deixa workers ociosos enquanto um termina a
  cauda longa.

O resultado é aproximadamente **1,9x** para a suíte principal na máquina de referência de
12 núcleos: **143s serial → 74s com quatro workers** em uma execução tranquila.
`-n 2` é mais lento (124s), `--dist load` é mais lento (178s) e `-n auto` (12
workers) foi mais lento (96s) porque o teste longo não pode ser dividido e os
processos extras disputam os mesmos núcleos. Quatro é o limite suportado, não um
ótimo universal.

### 4. O isolamento é o que torna o paralelismo seguro

Paralelismo só funciona se os testes não disputam os mesmos arquivos, bancos ou
locks. A suíte tinha dois conflitos reais:

- `tests/test_api.py` começava todos os workers no diretório compartilhado
  `var/data`. O segundo worker falhava em `runtime_lease()` porque só um worker
  de API pode ser dono daquele diretório. O cliente de sessão agora recebe a
  árvore `tmp_path_factory` do worker (`temp_dir`, `data_dir`, `logs_dir`) antes
  de a aplicação iniciar.
- O teste de exportação opcional usava um diretório de saída compartilhado, então
  um `audio.docx` de uma parametrização podia vazar para a seguinte. Ele agora
  grava entrada e saída em `tmp_path`.

O experimento com testmon também expôs uma dependência de ordem no banco de
histórico. `test_history_empty` e `test_stats_empty` agora usam um
`fresh_history_db` por teste, então a asserção de histórico vazio não depende do
que rodou antes.

Nenhum teste precisa ser marcado como serial hoje. Se um precisar, o marcador
`serial` será introduzido junto com o mecanismo que o faz rodar sozinho.

### 5. Leve os mesmos ganhos para a CI

A CI agora separa as quatro suítes em jobs de componente paralelos e mantém
`tests (Python 3.12)` como agregador obrigatório. O job da aplicação usa a mesma
execução limitada com quatro workers que o `make test-all`; docstruct, SDK e core
rodam ao lado. O job de qualidade (lint, tipos, contrato, relatório de pin) também
roda em paralelo. O agregador falha se qualquer provedor falhou ou foi pulado,
combina os artefatos JUnit e de cobertura e publica os resumos de tempo e
cobertura.

### 6. Monitore dependências de ordem e testes intermitentes

Paralelismo e ordens diferentes podem revelar um teste que depende do que outro
teste deixou para trás. O workflow `Scheduled test monitoring` roda semanalmente
(e sob demanda) para `main` e `develop`. Para cada branch, ele roda a suíte principal
serialmente e de novo com quatro workers, compara os resultados JUnit, falha em
diferença, falha, erro ou skip inesperado, e escreve um resumo com p50/p95 das
durações e os testes mais lentos. Ele também confere, de forma estrita, a
versão do docstruct fixada pela Toolbox (`scripts/check_docstruct_pin.py`): um
pin atrás da release que o docstruct do branch pede, ou que não bate com o
wheel publicado, faz a execução falhar. Os pull requests só recebem isso como
aviso, porque só a Toolbox pode mudar o pin (#470). Uma falha agendada abre ou
atualiza a issue `Scheduled test monitoring failed`.

O workflow só começa a disparar depois que o arquivo chega ao branch padrão. O
E2E é um job separado e condicional: roda apenas quando `TOOLBOX_BASE_URL` ou
`CORE_BASE_URL` está configurado, e não é um gate de merge.

### 7. A seleção automática de testes foi avaliada e rejeitada

O `pytest-testmon` seleciona testes afetados por uma mudança rastreando
cobertura. O experimento mostrou que ele não vê arquivos estáticos como
documentação, schemas e fixtures, e que o comando da raiz não executa as suítes
das bibliotecas. Uma mudança de README selecionou zero testes mesmo com um gate
estático obrigatório falhando; uma mudança central selecionou 246 testes;
reconstruir o banco de dependências levou 221s na medição tranquila (+55% sobre
a linha de base serial da suíte principal). Ele também adicionou um banco `.testmondata`
com estado e mostrou seleção instável entre execuções. Os detalhes e as medições
estão no registro do experimento da
[#448](https://github.com/A11yDevs/acessilia/issues/448).

O `pytest-testmon` **não** é dependência do projeto e o `make test-fast` não faz
parte do fluxo. Os atalhos suportados continuam sendo `test-file`, `test-failed`
e o `test-all` paralelo.

## Ganhos medidos

Máquina de referência: macOS, 12 núcleos lógicos, 16 GB de RAM, Python 3.11.15,
pytest 9.1.1. Estes números variam com a máquina, a carga e o cache de
dependências.

| Cenário | Antes | Depois |
|---|---:|---:|
| Core, serial vs quatro workers | 143s | 74s (~1,9x) |

O valor 143s → 74s é da #448, com a suíte como era na época. O baseline maior da
#644, medido depois, está em [testing/optimization.pt-br.md](testing/optimization.pt-br.md)
(890,15s serial contra 157,23s com quatro workers); use esse guia para os
números atuais.
| Etapa da suíte principal na CI | 60s + 10s de coleta | 26–43s |
| Job `tests` da CI | 1m59s | 59s–1m26s (uma execução: 1m11s) |

`--durations=25` imprime os testes mais lentos de qualquer execução, então você
pode atualizar a linha de base na sua máquina com:

```bash
make test-all
# ou apenas a suíte principal:
time uv run pytest -m "not e2e" --durations=25
time uv run pytest -m "not e2e" -n 4 --dist worksteal --durations=25
```

## Referência de comandos

### Alvos do Makefile

```bash
make help
make test-file F=tests/test_example.py
make test-file F=tests/test_api.py::test_health
make test-failed
make test-all
make lint
make typecheck
make coverage
make test-overlap
make test-mutation
```

Pisos de cobertura: aplicação **85%**, docstruct **86%**, SDK **96%**, core **82%** (branch coverage).

Não há configuração de `pre-commit`: `make lint`, `make typecheck` e o CI já rodam os mesmos gates, então um hook apenas os duplicaria sem ganho. Reavaliar se um formatador ou uma checagem local nova for introduzida.

`make -n test-all` imprime os comandos exatos sem executar.

Variáveis úteis:

| Variável | Padrão | Efeito |
|---|---|---|
| `CORE_JOBS` | `4` | Número de workers xdist para a suíte principal |
| `CORE_DIST` | `worksteal` | Estratégia de distribuição do xdist |
| `DURATIONS` | `25` | Quantidade de testes lentos impressos |
| `PYTEST` | `uv run pytest` | Comando pytest usado pelo Makefile |
| `PYTEST_FLAGS` | `-m "not e2e"` | Flags de seleção da suíte principal |

Exemplos:

```bash
make test-all CORE_JOBS=2
make test-all CORE_DIST=load
```

### Pytest direto

```bash
# Um node id
uv run pytest -m "not e2e" tests/test_api.py::test_health

# Um arquivo, serial
uv run pytest -m "not e2e" tests/test_pddl_planning.py

# Core com quatro workers
uv run pytest -m "not e2e" -n 4 --dist worksteal --durations=25

# Apenas as suítes das bibliotecas
(cd libs/docstruct && uv run --extra dev pytest)
(cd libs/sdk && uv run --extra dev pytest)
```

`uv run pytest` sem `-n` é serial. Ele também inclui a seleção E2E a menos que
você passe `-m "not e2e"`; use os alvos do Makefile no ciclo normal.

### Timeouts e marcadores

O `pytest-timeout` dá à suíte principal um limite de 180 segundos por teste. O
teste CPU-heavy do juiz VLM eleva o próprio limite para 300 segundos porque
quatro workers podem esticá-lo em uma máquina ocupada. O E2E é a outra exceção:
suas operações e esperas de job podem exceder esse limite legitimamente, então a
[receita de E2E](#preciso-de-e2e) passa `--timeout=900`. Para depurar um
travamento:

```bash
uv run pytest --timeout=0 ...
```

`-p no:timeout` **não** funciona com o `--strict-config` deste projeto, porque
desativar o plugin também remove a opção `timeout`. Um
`@pytest.mark.timeout(...)` explícito continua tendo precedência sobre
`--timeout=0`, então remova o marcador ao depurar esse teste.

O marcador `slow` identifica o teste caro conhecido do VLM. `-m slow` repete só
ele; `-m "not slow"` é um loop local mais rápido. O `make test-all` continua
executando-o, porque o gate completo não pode pular testes. Nenhum teste precisa
de execução serial hoje.

## Receitas

### Mudei um arquivo

```bash
make test-file F=tests/test_the_file.py
```

### Um teste falhou e eu corrigi

```bash
make test-failed
```

Se o cache não tiver falha real, o comando termina com sucesso e uma mensagem;
ele não roda a suíte inteira silenciosamente.

### Quero confiança local completa antes do push

```bash
make test-all
```

É o equivalente local do gate da CI: suíte principal com quatro workers, depois
docstruct, SDK e a biblioteca do core.

### Preciso investigar um teste lento ou travado

```bash
# make test-file já adiciona --durations=25
make test-file F=tests/test_the_file.py

# Desative o timeout apenas enquanto depura um node id
uv run pytest -m "not e2e" tests/test_the_file.py::test_name --timeout=0 -s
```

### Preciso de E2E

Testes E2E precisam de um ambiente real e ficam fora do ciclo normal:

```bash
TOOLBOX_BASE_URL=https://toolbox.example/toolbox \
TOOLBOX_API_KEY="$TOOLBOX_API_KEY" \
uv run pytest -m e2e -v --timeout=900
```

Passe `--timeout=900`. Os clientes E2E admitem operações isoladas de até 300
segundos, e o `CORE_JOB_TIMEOUT` tem padrão de 600 segundos por espera de
processamento; o limite global de 180 segundos da suíte interromperia um teste
válido antes do limite previsto pelo próprio teste. O job agendado de E2E usa o
mesmo valor. O caso do deck completo é manual: use `CORE_SLIDE_CASE=1`;
ele permite 4200 segundos e usa `CORE_SLIDE_TIMEOUT` (padrão 3600) para a
própria espera.

Veja o [README dos testes](../tests/README.pt-br.md#testes-end-to-end) para as
variáveis da API do Core e o corpus opcional. O E2E também é uma validação
agendada, não um gate de merge.

## Solução de problemas

**Por que `uv run pytest` continua lento?**
Porque ele é serial por padrão. Use `make test-all` ou adicione
`-n 4 --dist worksteal` ao comando da suíte principal.

**Por que quatro workers e não `-n auto`?**
Quatro acompanha o runner da CI e foi mais rápido aqui: o teste mais lento não
pode ser dividido e processos extras disputam os mesmos núcleos. Use
`CORE_JOBS` se sua máquina tiver outro formato.

**Por que não adotamos o `pytest-testmon`?**
Ele não rastreia arquivos estáticos (docs, schemas, fixtures), não roda as
suítes das bibliotecas, tem uma linha de base cara e mostrou falsos negativos. As
evidências estão no experimento da
[#448](https://github.com/A11yDevs/acessilia/issues/448).

**O que aconteceu com a etapa de coleta da CI?**
A execução de testes coleta a suíte sozinha, então a etapa separada de
`--collect-only` era redundante.

**Onde estão os relatórios de testes lentos?**
O `make` e a CI passam `--durations=25`. Os jobs de componente publicam
`test-report-<component>` e `coverage-<component>`; o agregador combina os dois
uma vez como `test-reports-py3.12` e `coverage-reports-py3.12`, e publica
`timing-baseline-py3.12`. Os relatórios de isolamento são
`sdk-isolated-report-py*` e `docstruct-isolated-report-py*`, com retenção de 7
dias.

**Onde vejo a comparação agendada?**
Depois que o workflow chega ao branch padrão, abra Actions →
`Scheduled test monitoring`. Cada execução de `main`/`develop` publica
`scheduled-test-reports-<ref>` e escreve p50/p95 e os testes mais lentos no
resumo do job.

**Por que minha execução paralela falha com erro de diretório de dados?**
A suíte agora é isolada por worker; se isso aparecer de novo, um novo teste está
compartilhando um caminho de execução. Confira os caminhos por worker em
`tests/test_api.py` e use `tmp_path`/`tmp_path_factory` para estado mutável novo.

## Onde ver os resultados

- **CI:** GitHub Actions → workflow `CI` → job `app tests (Python 3.12)` →
  step `Run app test suite`. O log mostra `created: 4/4 workers` e
  `--durations=25`; o job obrigatório `tests (Python 3.12)` é o agregador.
- **Artefatos:** `test-reports-py3.12` e `coverage-reports-py3.12`
  (combinados), os artefatos por componente `test-report-*`/`coverage-*`,
  `timing-baseline-py3.12`, `sdk-isolated-report-py*` e
  `docstruct-isolated-report-py*`.
- **Agendado:** workflow `Scheduled test monitoring`, com artefatos retidos por
  30 dias e uma issue de acompanhamento em falhas agendadas.
- **Rulesets:** `main` e `develop` exigem `tests (Python 3.12)` e
  `SDK alone (Python 3.12)`.
- **Localmente:** rode `time make test-all` e compare com o comando serial do
  suíte principal acima na mesma máquina ociosa.

## Ambientes suportados

- **macOS e Linux.** O `make` vem com as ferramentas de linha de comando do
  Xcode no macOS e está presente nas distribuições Linux comuns.
- **`uv`** é necessário ([documentação](https://docs.astral.sh/uv/)). Rode os
  comandos a partir da raiz do repositório. As bibliotecas são pacotes separados
  e são chamadas com `uv run --extra dev pytest` em seus diretórios.
- Rode `uv lock --check`, depois `uv sync --locked --extra dev` para instalar
  o `pytest-xdist` e as dependências usadas pelos alvos do Makefile e pelo CI
  a partir do lock versionado da raiz.

## Escopo e trabalhos relacionados

- A [Constituição 3.0.0](constitution.pt-br.md#3-regras-de-qualidade-arquitetural)
  define o CI como gate de testes e as verificações de build, inicialização e
  saúde da API por smoke tests da imagem de produção como validação operacional,
  resolvendo a [#190](https://github.com/A11yDevs/acessilia/issues/190).
- CI e imagem instalam a partir do `uv.lock` da raiz; os jobs de isolamento das
  bibliotecas usam os próprios locks verificados. A instalação e o cache de
  dependências foram alinhados pela
  [#405](https://github.com/A11yDevs/acessilia/issues/405) / PR #539.
- Os comandos locais, as correções de isolamento, a paralelização da CI, a
  decisão sobre o testmon e o monitoramento agendado foram entregues pelos cinco
  PRs da [#448](https://github.com/A11yDevs/acessilia/issues/448).
