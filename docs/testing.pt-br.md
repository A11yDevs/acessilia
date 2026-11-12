# Fluxo local de testes

Você também pode ler esta documentação em **inglês**: [English](testing.md).

Esta página descreve o ciclo local de editar–testar–corrigir. Os comandos são
wrappers finos em volta do pytest; a CI continua executando as suítes completas
antes do merge. A issue [#448](https://github.com/A11yDevs/acessilia/issues/448)
acompanha o trabalho restante: execução paralela limitada (PR 2), o experimento
opcional de análise de impacto (PR 3), otimização da CI (PR 4) e monitoramento
(PR 5).

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

## Comandos

| Comando | O que executa |
|---|---|
| `make test-file F=tests/test_example.py` | Um arquivo ou um node id (`tests/test_api.py::test_health`), sem E2E |
| `make test-failed` | As falhas registradas nos caches do core, docstruct e SDK |
| `make test-all` | As suítes do core, docstruct e SDK sem E2E, sequencialmente |

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
resultado do core. Hoje ele é sequencial; a PR 2 da #448 adiciona paralelismo
limitado (`-n 4 --dist worksteal`) depois das correções de isolamento.

A suíte do core roda com `-m "not e2e"`; use `uv run pytest -m e2e` diretamente
para alcançar um ambiente real, como descrito no
[README dos testes](../tests/README.pt-br.md).

## Timeouts

O `pytest-timeout` reprova um teste travado com o nome dele, em vez de deixá-lo
consumir o timeout de 30 minutos do job da CI. A suíte do core usa um limite de
180 segundos, bem acima do teste mais lento atual (cerca de 11s). Um teste que
legitimamente precise de mais tempo sobrescreve o limite localmente:

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

A CI executa as mesmas suítes com `--durations=25` e publica os relatórios JUnit
mesmo quando uma etapa falha: `test-reports` para as suítes do core, docstruct e
SDK, e `sdk-isolated-report` para o job isolado do SDK.

## Ambientes suportados

- **macOS e Linux.** O `make` vem com as ferramentas de linha de comando do
  Xcode no macOS e está presente nas distribuições Linux comuns.
- **`uv`** precisa estar instalado ([documentação](https://docs.astral.sh/uv/)).
  Os comandos rodam a partir da raiz do repositório; as bibliotecas são pacotes
  separados e são chamadas com `uv run --extra dev pytest` em seus diretórios.

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
