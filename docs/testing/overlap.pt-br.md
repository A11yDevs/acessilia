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
make test-overlap

# O alvo grava var/overlap/app.json, app.md, redundancy.json e redundancy.md;
# o snapshot versionado é a cópia desses arquivos para cá.
cp var/overlap/app.json docs/testing/overlap-app.json
cp var/overlap/app.md docs/testing/overlap-app.md
cp var/overlap/redundancy.json docs/testing/redundancy-app.json
cp var/overlap/redundancy.md docs/testing/redundancy-app.md
```

O alvo executa a suíte da aplicação com `--cov-context=test`, grava
`var/overlap/context/.coverage` e `var/overlap/app-results.xml` e chama os dois
scripts de análise com `--extra dev`.

O primeiro script calcula a similaridade de Jaccard
`|A ∩ B| / |A ∪ B|` para cada par que compartilha pelo menos cinco linhas e
sinaliza pares a partir de `0,8`. Uma linha coberta por mais de 50 testes é
usada apenas para *propor* pares candidatos; toda interseção, união, `only_a`,
`only_b` e Jaccard relatados são recalculados a partir dos conjuntos completos.
O teto limita a busca, não a métrica.

A subsunção de cobertura é calculada separadamente a partir dos conjuntos
completos e não depende do limiar de Jaccard: um teste pequeno pode estar contido
em um muito maior com similaridade baixa. Testes com a mesma assinatura de
cobertura são agrupados, então o relatório mostra relações entre assinaturas e o
tamanho dos grupos, em vez de milhões de pares duplicados.

O segundo script acrescenta durações, ordena os candidatos de subsunção de
cobertura, separa variantes parametrizadas e informa quantos exemplos de cada
tabela são exibidos. `--junit` lê relatórios JUnit completos; `--baseline` é o
baseline opcional do PR 1 e só é usado pelas listas de testes mais lentos. Ele
nunca edita, remove ou pula um teste.

## Resultados

A suíte da aplicação executou 3.197 testes sobre 3.559 linhas medidas.

| Medida | Valor |
|---|---:|
| Pares com Jaccard >= 0,8 e >= 5 linhas compartilhadas | 1.995 |
| Pares exatos (Jaccard = 1,0) | 735 |
| Similaridade média dos pares relatados | 0,951 |
| Famílias parametrizadas analisadas | 288 |
| Famílias com cobertura de linhas idêntica | 247 |
| Relações de subsunção entre assinaturas | 1.250 |
| · subconjuntos estritos | 1.151 |
| · grupos com cobertura idêntica | 99 |
| Testes que compartilham uma assinatura idêntica | 2.914 |
| Testes sem linha de produção exclusiva | 3.085 de 3.197 |

A suíte tem sobreposição substancial, mas a conclusão não é uma lista de remoção.
A análise de subconjuntos encontra **1.250 relações de cobertura entre
assinaturas únicas**, incluindo 1.151 subconjuntos estritos. Isso contradiz a
formulação anterior de que nenhum subconjunto existia: um teste pequeno pode
estar contido em um muito maior com Jaccard baixo, por isso a subsunção precisa
ser calculada sem o limiar de similaridade. A folha de revisão ordena os
exemplos pelos segundos medidos; ela não remove nenhum teste.

### Onde está a sobreposição

| Agrupamento | Exemplo | Jaccard | Compartilhadas | Só A | Só B |
|---|---|---:|---:|---:|---:|
| Nomes de saída longos | `test_long_filename_can_be_exported_and_downloaded[long-ascii]` ↔ `[long-cjk]` | 1,000 | 605 | 0 | 0 |
| Correções pendentes | `test_email_delivery_status_does_not_lose_download[False]` ↔ `[None]` | 0,993 | 455 | 3 | 0 |
| Executor de chamadas de modelo | `test_pending_calls_are_removed_and_never_start_late[False]` ↔ `test_running_deadline_retains_capacity_and_default_executor_stays_available` | 0,924 | 98 | 8 | 0 |
| Matriz de clientes do benchmark | variantes de `test_the_harness_configures_clients_like_the_core[...]` | — | 273 | — | — |

Esses agrupamentos compartilham a infraestrutura de requisição/resposta de um
cenário. Alguns pares são subconjuntos estritos de cobertura; outros ainda cobrem
linhas que o vizinho não cobre. A cobertura sozinha não mostra se as asserções,
contratos ou modos de falha são duplicados, então a folha de revisão é a entrada
para o experimento de mutação do PR 3.

### Famílias parametrizadas

246 das 288 famílias analisadas têm **cobertura de linhas idêntica** entre suas
variantes. Os exemplos mais fortes são a matriz de clientes do benchmark, os
estados de recibo do painel web e as permutações de locale do Telegram. Isso é
esperado: uma parametrização normalmente varia entradas e asserções esperadas,
não o caminho de produção. Cobertura de linhas igual não é comportamento
duplicado; as variantes podem falhar por motivos diferentes.

O relatório de sobreposição lista as famílias e seus grupos de assinatura; a
folha de revisão lista os testes candidatos e os pares. Ela classifica
`identical-parameterization` separadamente e nunca propõe uma variante como
remoção.

### Testes sem linha de produção exclusiva

3.085 dos 3.197 testes não cobrem nenhuma linha que nenhum outro teste cobre.
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
| Similaridade de cobertura entre testes | Jaccard por par, 1.995 pares em 0,8 |
| Conjuntos com alta sobreposição | agrupamentos de saída longa, correções pendentes, executor de modelo e benchmark |
| Contribuição exclusiva de cada teste | por par e por suíte; 3.085 testes não têm nenhuma em linhas de produção |
| Subsunção de cobertura | 1.250 relações entre assinaturas (1.151 estritas, 99 idênticas), independentes de Jaccard |
| Casos parametrizados possivelmente equivalentes | 246 famílias com cobertura de linhas idêntica; nenhuma removida automaticamente |
| Duplicação entre testes unitários, de integração e de contrato | 1.250 assinaturas de subsunção; o PR 3 compara detecção |
| Fixtures caras compartilhadas por testes semelhantes | a duração vem do JUnit; o relatório ordena candidatos por segundos |
| Classificação e risco dos candidatos | nenhum candidato automático; a folha de revisão exige análise de contrato |

## Limitações

- **Cobertura de linhas, não de desvios, por teste.** O Coverage.py expõe
  contextos por linha, não por arco. A cobertura de desvios continua sendo
  coletada nos totais, mas os conjuntos por teste são baseados em linhas.
- **Os testes ficam fora da cobertura.** Desvios que existem só nas asserções
  não aparecem; é por isso que "nenhuma linha exclusiva" é evidência fraca e
  por isso o PR 3 é necessário.
- **Linhas comuns apenas podam a busca de pares.** Linhas cobertas por mais de
  50 testes não são usadas para propor pares; as métricas relatadas e a análise
  de subconjuntos usam os conjuntos completos. O conjunto de candidatos ainda
  pode perder um par cujas todas as linhas sejam infraestrutura compartilhada,
  o que é documentado pelos totais.
- **Uma revisão e uma execução.** Os contextos vêm de uma execução que passou
  no commit do snapshot; um refactor posterior pode mudar qual helper um teste
  alcança.
- **Nenhuma análise semântica.** Dois testes podem cobrir as mesmas linhas e
  verificar valores diferentes. O relatório diz isso explicitamente.

## Comandos para as suítes das bibliotecas

```bash
# docstruct
COVERAGE_FILE="$PWD/var/context/docstruct/.coverage" \
  uv run --extra dev --project "$PWD" python -m pytest libs/docstruct/tests \
  --cov=docstruct --cov-branch --cov-context=test \
  --cov-config="$PWD/pyproject.toml" --cov-report=
uv run --extra dev python scripts/tests/coverage_overlap.py \
  --coverage-file var/context/docstruct/.coverage \
  --include libs/docstruct/src/docstruct \
  --output var/overlap/docstruct.json
```

O mesmo padrão funciona para `acessilia_sdk` e `acessilia_core`. Os relatórios
versionados são da execução da aplicação, a maior e mais diversa das suítes.
