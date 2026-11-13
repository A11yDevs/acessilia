# Fluxo local de testes

Você também pode ler esta documentação em **inglês**: [English](testing.md).

Esta página descreve o ciclo local de editar–testar–corrigir. Os comandos são
wrappers finos em volta do pytest; a CI continua executando as suítes completas
antes do merge. A issue [#448](https://github.com/A11yDevs/acessilia/issues/448)
acompanha o trabalho restante: otimização da CI (PR 4) e monitoramento (PR 5).
A execução paralela limitada (PR 2) está disponível no `make test-all`; a
análise de impacto de testes (PR 3) foi avaliada e não faz parte do fluxo.

## Linha de base

Medida em 2026-11-11 no commit `c3ea6d5d`, antes da inclusão dos comandos
locais:

| Suíte | Testes | Coleta | Execução completa |
|---|---|---|---|
| Core (`-m "not e2e"`) | 2800 coletados, 2740 selecionados | 10,2s | 132,0s |
| `libs/docstruct` | 1194 | 1,05s | — |
| `libs/sdk` | 427 | 0,46s | — |

Ambiente: macOS, 12 núcleos lógicos, 16 GB de RAM, Python 3.11.15, pytest 9.1.1.
O job `tests` da CI levou 1m59s na
[execução 43038402225](https://github.com/A11yDevs/acessilia/actions/runs/43038402225):
26s para instalar dependências, 12s para coletar, 65s para a suíte do core e 5s
para cada biblioteca.

Esses números são referência, não garantia: variam com a máquina, o sistema
operacional e o cache de dependências. `--durations=25` imprime os testes mais
lentos em cada execução, então uma nova linha de base está a um comando de
distância:

```bash
uv run pytest -m "not e2e" --durations=25
```

### Linha de base paralela

Depois das correções de isolamento da PR 2, com cerca de 2920 testes do core na
mesma máquina (2026-11-12):

| Execução | Tempo total |
|---|---|
| Core serial | 143s |
| Core `-n 4 --dist worksteal` | 74s (1,9x) |
| Core `-n 2 --dist worksteal` | 124s |
| Core `-n auto --dist worksteal` | 96s |
| Core `-n 4 --dist load` | 178s |

O `worksteal` ganha porque poucos testes longos dominam a cauda; o `load`
distribui módulos inteiros e deixa workers ociosos. O `-n auto` (12 workers
aqui) foi mais lento que quatro: o teste mais lento não pode ser dividido e os
processos extras disputam os mesmos núcleos. O teste mais lento sozinho leva
cerca de 20–80s conforme a carga, então ele limita o ganho. Estes números são
referência, não garantia.

## Comandos

| Comando | O que executa |
|---|---|
| `make test-file F=tests/test_example.py` | Um arquivo ou um node id (`tests/test_api.py::test_health`), sem E2E |
| `make test-failed` | As falhas registradas nos caches do core, docstruct e SDK |
| `make test-all` | O core sem E2E com quatro workers, depois docstruct e SDK sequencialmente |

`make` sem alvo imprime a mesma lista.

`test-failed` lê o cache `lastfailed` das três suítes (`.pytest_cache` na raiz
do repositório, `libs/docstruct` e `libs/sdk`) e reexecuta as falhas de cada uma
a partir do diretório do próprio projeto, com a mesma configuração e os mesmos
node ids relativos do `test-all`. Antes de executar, ele coleta apenas os
arquivos registrados e mantém os ids que ainda existem. Um teste removido ou
renomeado é listado e ignorado, em vez de fazer o `pytest --lf` cair para a
suíte inteira; um arquivo registrado com erro de coleta é reexecutado como
arquivo. Quando não há falha registrada, ou as únicas falhas são testes E2E, ele
imprime uma mensagem e termina com sucesso.

`test-all` não para na primeira suíte: executa as três e devolve o último código
de saída diferente de zero, para que uma biblioteca com falha não esconda o
resultado do core. A suíte do core usa `-n 4 --dist worksteal`; docstruct e SDK
continuam sequenciais.

A suíte do core roda com `-m "not e2e"`; use `uv run pytest -m e2e` diretamente
para alcançar um ambiente real, como descrito no
[README dos testes](../tests/README.pt-br.md).

## Execução paralela

O `make test-all` passa `-n 4 --dist worksteal` para a suíte do core. Para
ajustar o limite ou a distribuição sem editar o Makefile:

```bash
make test-all CORE_JOBS=2
make test-all CORE_DIST=load
```

A suíte é segura em paralelo porque os testes que compartilhavam caminhos de
execução agora usam caminhos por worker:

- `tests/test_api.py` aponta `settings.temp_dir`, `settings.data_dir` e
  `settings.logs_dir` para o diretório `tmp_path_factory` do worker antes de o
  `TestClient` de sessão iniciar a aplicação. Sem isso, o segundo worker falha
  no `runtime_lease()` com `RuntimeError: Only one API worker may use a data
  directory`.
- o teste de exportação opcional grava entrada e saída em `tmp_path`, então um
  `audio.docx` deixado por uma parametrização não vaza para a seguinte.

O `-n auto` não está habilitado. Ele passou na validação, mas foi mais lento
(96s) que quatro workers (74s) e usa mais memória. Mantenha-o como opção local
experimental; a CI e o `make test-all` continuam limitados.

## Análise de impacto de testes (avaliada, não adotada)

A PR 3 da #448 avaliou o `pytest-testmon` como um `make test-fast` opcional. Ele
não faz parte do fluxo: o experimento encontrou omissões que exigiriam um
fallback grande e fácil de ficar desatualizado, e o custo da linha de base
supera o ganho para esta suíte.

Medido em 2026-11-12 com `pytest-testmon 2.3.0` na mesma máquina de 12 núcleos,
que estava sob carga (a linha de base serial do core é 143s e o `make test-all`
levou cerca de 75s em uma execução tranquila):

| Cenário | Resultado |
|---|---|
| Reconstrução da linha de base (`--testmon-forceselect`, core sem E2E completo) | 603s (221s na medição tranquila anterior) |
| Sem mudanças | 2,7s (6,5s de parede incluindo a inicialização do interpretador) |
| Cinco mudanças em folhas | 1–4 testes selecionados; mediana 9,1s, máximo 16,8s (cinco amostras) |
| Mudança central (`backend/config/settings.py`) | 246 testes, 66s |
| Mudança em README (arquivo estático) | 0 testes selecionados; `test_docstruct_readme_sync` falha quando executado diretamente |
| Mudança em folha do docstruct | 2 testes do core selecionados; a suíte do docstruct não roda |
| Mudança em folha do SDK | 1 teste do core selecionado; a suíte do SDK não roda |
| Arquivos de portões estáticos da raiz | 129 testes, 6,9s |

A amostra de arquivo estático é 1/1 falso negativo; as cinco amostras de folhas
selecionaram seus testes diretos. A amostra é pequena, mas um portão obrigatório
omitido já exige um fallback.

Por que foi rejeitado:

- **Arquivos estáticos são invisíveis para o testmon.** Documentação, schemas,
  fixtures, `pyproject.toml`, `uv.lock`, `.env` e contratos compartilhados
  precisam de fallback explícito. O repositório tem portões estáticos
  obrigatórios (`test_no_portuguese`, `test_docstruct_readme_sync`,
  `test_architecture_layers`, `test_i18n`, `test_compose_config`,
  `test_docs_pr125`, além dos testes de pureza das bibliotecas), e executá-los
  em toda mudança levaria a mediana das folhas de 9,1s para cerca de 16s, acima
  da meta de 10s.
- **As bibliotecas são suítes separadas.** O comando da raiz não executa
  `libs/docstruct` nem `libs/sdk`; uma mudança nesses diretórios precisa de
  fallback para as suítes deles, que o testmon não seleciona.
- **Custo e invalidação da linha de base.** Reconstruir o `.testmondata` levou
  603s sob carga. A execução tranquila anterior foi 221s, +55% sobre a linha de
  base serial atual de 143s (era +67% sobre a linha de base de 132s registrada
  no commit anterior), e o banco precisa ser reconstruído após mudanças de
  dependências ou de ambiente.
- **Seleção com estado.** A mesma mudança em `runtime_lease.py` selecionou 3
  testes em uma execução e 4 na coleta seguinte; o banco é mais um artefato com
  estado para manter sincronizado.
- O experimento expôs uma dependência de ordem real: `test_history_empty` e
  `test_stats_empty` agora usam o fixture `fresh_history_db` por teste, então
  uma execução seletiva não vê linhas gravadas por um teste anterior.

O fluxo suportado continua sendo `make test-file`, `make test-failed` e
`make test-all` (core com quatro workers). O `pytest-testmon` não é dependência
do projeto. Apague `.testmondata*` para reconstruir a linha de base após
mudanças de dependências, interpretador ou plugins. O arquivo está no
`.gitignore`, então o experimento ainda pode ser reproduzido localmente:

```bash
rm -f .testmondata*
uv run --with pytest-testmon pytest --testmon-forceselect -m "not e2e"
```

## Timeouts

O `pytest-timeout` reprova um teste travado com o nome dele, em vez de deixá-lo
consumir o timeout de 30 minutos do job da CI. A suíte do core usa um limite de
180 segundos. O teste CPU-heavy do juiz VLM eleva o próprio limite para 300
segundos porque quatro workers podem esticá-lo para 60–80s em uma máquina
ocupada. Um teste que legitimamente precise de mais tempo sobrescreve o limite
localmente:

```python
import pytest

@pytest.mark.timeout(300)
def test_a_long_but_bounded_operation():
    ...
```

Para depurar sem o timeout padrão, passe `--timeout=0`:
`uv run pytest --timeout=0 ...`. O `-p no:timeout` não funciona com o
`--strict-config` deste projeto, porque desativar o plugin também remove a opção
`timeout`. Um `@pytest.mark.timeout(...)` explícito continua tendo precedência
sobre `--timeout=0`, então remova o marcador ao depurar esse teste.

## Artefatos da CI

A CI executa a suíte do core com `-n 4 --dist worksteal` dentro do job existente
`tests (Python 3.11)`; o nome do job não muda, então o check obrigatório
continua funcionando. A etapa separada de coleta foi removida porque a execução
já coleta a suíte. O job continua rodando as suítes do docstruct e do SDK,
recusando skips inesperados e publicando os relatórios JUnit com
`--durations=25` mesmo quando uma etapa falha: `test-reports` para as suítes do
core, docstruct e SDK, e `sdk-isolated-report` para o job isolado do SDK. A
entrega da imagem espera por `tests` e `sdk-isolated`.

## Ambientes suportados

- **macOS e Linux.** O `make` vem com as ferramentas de linha de comando do
  Xcode no macOS e está presente nas distribuições Linux comuns.
- **`uv`** precisa estar instalado ([documentação](https://docs.astral.sh/uv/)).
  Os comandos rodam a partir da raiz do repositório; as bibliotecas são pacotes
  separados e são chamadas com `uv run --extra dev pytest` em seus diretórios.
  O extra dev inclui o `pytest-xdist`, então `uv sync --extra dev` basta para o
  `make test-all`.

## Escopo e trabalhos relacionados

- A constituição e o [README dos testes](../tests/README.pt-br.md#execução)
  ainda indicam o container Docker como portão primário, mas a imagem não tem
  estágio `test`; a [#190](https://github.com/A11yDevs/acessilia/issues/190)
  acompanha a reescrita dessa regra. Até lá, a CI executa as três suítes
  nativamente e é o check exigido antes do merge.
- Instalação e cache de dependências continuam na
  [#405](https://github.com/A11yDevs/acessilia/issues/405).
- Política de E2E, execuções agendadas e monitoramento de testes intermitentes
  são a PR 5 da #448.
