# Sobreposição de cobertura e candidatos à redundância

> [overlap.md](overlap.md). A versão em inglês é a fonte.

Este é o PR 2 da [issue #644](https://github.com/A11yDevs/acessilia/issues/644):
a análise automatizada de sobreposição e a primeira lista de candidatos. Nenhum
teste ou código de produção muda. O método e os tempos do baseline são do PR 1;
este relatório trata de quais testes exercitam o mesmo código.

- **Snapshot:** `develop` em `cd7003d2` (2026-11-23), Python 3.12.13.
- **Ferramentas:** [`scripts/tests/coverage_overlap.py`](../../scripts/tests/coverage_overlap.py)
  e [`scripts/tests/redundancy_report.py`](../../scripts/tests/redundancy_report.py).
- **Relatório legível por máquina:** [`overlap-app.json`](overlap-app.json).
- **Folha de revisão:** [`redundancy-app.json`](redundancy-app.json) (Markdown:
  [`redundancy-app.md`](redundancy-app.md)).
- **Escopo:** a suíte da aplicação (`tests/`) contra `backend/` e `frontend/`.
  As suítes das bibliotecas podem ser analisadas com o mesmo comando e outro
  `--include`.

## Método

O Coverage.py pode associar um contexto dinâmico a cada linha medida. O
pytest-cov define esse contexto como o node id do teste com
`--cov-context=test`, então o banco `.coverage` sabe qual teste executou cada
`arquivo:linha`:

```bash
COVERAGE_FILE="$PWD/var/context/app/.coverage" \
uv run pytest -m "not e2e" -n 4 --dist worksteal \
  --cov=backend --cov=frontend --cov-branch --cov-context=test \
  --cov-config="$PWD/pyproject.toml" --cov-report= \
  --junitxml=var/context/app/results.xml

uv run python scripts/tests/coverage_overlap.py \
  --coverage-file var/context/app/.coverage \
  --include backend --include frontend \
  --output docs/testing/overlap-app.json \
  --summary docs/testing/overlap-app.md

uv run python scripts/tests/redundancy_report.py \
  docs/testing/overlap-app.json \
  --junit app=var/context/app/results.xml \
  --output docs/testing/redundancy-app.json \
  --summary docs/testing/redundancy-app.md
```

O primeiro script calcula a similaridade de Jaccard
`|A ∩ B| / |A ∪ B|` para cada par que compartilha pelo menos cinco linhas e
sinaliza pares a partir de `0,8`. Uma linha coberta por mais de 50 testes é
ignorada como infraestrutura compartilhada: todos os testes importam a
aplicação, então essas linhas fariam testes não relacionados parecerem
idênticos. O limite e o teto são configuráveis.

O segundo script acrescenta durações, identifica se um teste não cobre nenhuma
linha que o outro não cobre e separa variantes parametrizadas. Ele nunca edita,
remove ou pula um teste.

## Resultados

A suíte da aplicação executou 3.192 testes sobre 3.559 linhas medidas.

| Medida | Valor |
|---|---:|
| Pares com Jaccard >= 0,8 e >= 5 linhas compartilhadas | 83 |
| Pares exatos (Jaccard = 1,0) | 0 |
| Similaridade média dos pares relatados | 0,815 |
| Famílias parametrizadas analisadas | 288 |
| Famílias com cobertura de linhas idêntica | 246 |
| Testes sem linha de produção exclusiva | 3.080 de 3.192 |

Com o limite mais frouxo de 0,6 e três linhas compartilhadas, o relatório tem
234 pares e ainda **nenhum par em que as linhas medidas de um teste sejam
subconjunto das do outro**. Esse é o resultado central deste PR: a suíte tem
sobreposição grande, mas não tem um candidato demonstrável de eliminação
par-a-par.

### Onde está a sobreposição

| Agrupamento | Exemplo | Jaccard | Compartilhadas | Só A | Só B |
|---|---|---:|---:|---:|---:|
| Fluxo de documento do Telegram | `test_document_does_not_consume_another_senders_preferences` ↔ `test_document_submits_with_mode_and_source` | 0,849 | 269 | 24 | 24 |
| Variantes de locale do Telegram | `test_pdf_ua_warning_survives_worker_and_user_locales_differing[en_US-pt_BR]` ↔ `[pt_BR-en_US]` | 0,853 | 279 | 24 | 24 |
| Recibos do painel web | `test_receipt_close_info_only_while_the_email_promise_holds[done-failed-False-False]` ↔ `test_receipt_recovers_result_after_refresh[failed]` | 0,826 | 171 | 18 | 18 |
| Matriz de clientes do benchmark | variantes de `test_the_harness_configures_clients_like_the_core[...]` | — | 273 | — | — |

Esses agrupamentos compartilham a infraestrutura de requisição/resposta de um
cenário. Cada teste ainda cobre entre 18 e 30 linhas que o vizinho não cobre,
normalmente o desvio do estado, locale ou cliente que ele verifica. Remover um
perderia a cobertura desse desvio, então nenhum é candidato apenas com
evidência de cobertura.

### Famílias parametrizadas

246 das 288 famílias analisadas têm **cobertura de linhas idêntica** entre suas
variantes. Os exemplos mais fortes são a matriz de clientes do benchmark, os
estados de recibo do painel web e as permutações de locale do Telegram. Isso é
esperado: uma parametrização normalmente varia entradas e asserções esperadas,
não o caminho de produção. Cobertura de linhas igual não é comportamento
duplicado; as variantes podem falhar por motivos diferentes.

A folha de revisão lista as famílias e os pares. Ela classifica
`identical-parameterization` separadamente e nunca propõe uma variante como
subsumida.

### Testes sem linha de produção exclusiva

3.080 dos 3.192 testes não cobrem nenhuma linha que nenhum outro teste cobre.
Esse número não é um defeito: a cobertura omite os próprios arquivos de teste,
então asserções, valores esperados parametrizados e mensagens de erro são
invisíveis para ela. Quase todo teste que exercita o mesmo ponto de entrada de
serviço compartilha todas as linhas de produção com outro teste.

É exatamente por isso que este PR **não** remove testes. Ele estreita a
pergunta para o PR 3: cobertura de produção igual pode esconder detecção
diferente, e mutation testing é o experimento que consegue distingui-las.

## Respostas às perguntas do PR 2

| Pergunta da #644 | Resultado |
|---|---|
| Matriz relacionando testes e código coberto | contextos do `.coverage`, resumidos como conjuntos `arquivo:linha` por teste |
| Similaridade de cobertura entre testes | Jaccard por par, 83 pares em 0,8 |
| Conjuntos com alta sobreposição | agrupamentos de Telegram, painel web, clientes do benchmark e recibos |
| Contribuição exclusiva de cada teste | por par e por suíte; 3.080 testes não têm nenhuma em linhas de produção |
| Casos parametrizados possivelmente equivalentes | 246 famílias com cobertura de linhas idêntica; nenhuma removida automaticamente |
| Duplicação entre testes unitários, de integração e de contrato | nenhum subconjunto par-a-par em 0,8 ou 0,6; o PR 3 compara detecção |
| Fixtures caras compartilhadas por testes semelhantes | a duração vem do JUnit; o relatório ordena candidatos por segundos |
| Classificação e risco dos candidatos | nenhum candidato automático; a folha de revisão exige análise de contrato |

## Limitações

- **Cobertura de linhas, não de desvios, por teste.** O Coverage.py expõe
  contextos por linha, não por arco. A cobertura de desvios continua sendo
  coletada nos totais, mas os conjuntos por teste são baseados em linhas.
- **Os testes ficam fora da cobertura.** Desvios que existem só nas asserções
  não aparecem; é por isso que "nenhuma linha exclusiva" é evidência fraca e
  por isso o PR 3 é necessário.
- **Linhas comuns têm um teto.** Linhas cobertas por mais de 50 testes são
  ignoradas para manter a análise significativa e rápida; aumentar o teto
  adiciona ruído e trabalho quadrático.
- **Uma revisão e uma execução.** Os contextos vêm de uma execução que passou
  no commit do snapshot; um refactor posterior pode mudar qual helper um teste
  alcança.
- **Nenhuma análise semântica.** Dois testes podem cobrir as mesmas linhas e
  verificar valores diferentes. O relatório diz isso explicitamente.

## Comandos para as suítes das bibliotecas

```bash
# docstruct
COVERAGE_FILE="$PWD/var/context/docstruct/.coverage" \
  uv run --project "$PWD" python -m pytest libs/docstruct/tests \
  --cov=docstruct --cov-branch --cov-context=test \
  --cov-config="$PWD/pyproject.toml" --cov-report=
uv run python scripts/tests/coverage_overlap.py \
  --coverage-file var/context/docstruct/.coverage \
  --include libs/docstruct/src/docstruct \
  --output var/overlap/docstruct.json
```

O mesmo padrão funciona para `acessilia_sdk` e `acessilia_core`. Os relatórios
versionados são da execução da aplicação, a maior e mais diversa das suítes.
