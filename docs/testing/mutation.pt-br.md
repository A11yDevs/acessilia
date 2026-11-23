# Mutation testing e subsunção de testes

> [mutation.md](mutation.md). A versão em inglês é a fonte.

Este é o PR 3 da [issue #644](https://github.com/A11yDevs/acessilia/issues/644):
um experimento limitado de mutation testing em dois módulos pequenos da
docstruct, as relações de subsunção que ele expõe e o custo-benefício da
abordagem. Ele não muda código de produção nem o gate de CI.

- **Snapshot:** `develop` em `cd7003d2` (2026-11-23), Python 3.12.13.
- **Ferramenta:** [`scripts/tests/mutation_report.py`](../../scripts/tests/mutation_report.py).
- **Módulos:** `docstruct.fusion.flood` e `docstruct.text.equations`.
- **Relatórios:** [`mutation-flood.json`](mutation-flood.json),
  [`mutation-equations.json`](mutation-equations.json).
- **Comparações de cobertura:** [`overlap-flood.json`](overlap-flood.json),
  [`overlap-equations.json`](overlap-equations.json).

## Por que um experimento limitado em vez de um novo gate

Mutation testing executa os testes uma vez por defeito artificial. Uma execução
completa da suíte do Acessilia multiplicaria uma suíte de 5 minutos por centenas
ou milhares de mutantes, o que é inaceitável como gate de pull request. O
experimento responde primeiro a uma pergunta mais estreita:

> Testes com cobertura quase idêntica detectam defeitos diferentes, e existe
> uma relação de subsunção que a cobertura sozinha não mostra?

Dois módulos pequenos e determinísticos da docstruct foram escolhidos, cada um
com um arquivo de teste focado. O harness muta o módulo com operadores de AST,
copia o pacote docstruct para um diretório temporário, executa os testes focados
contra cada mutante com `PYTHONPATH` apontando para a cópia e registra quais
testes falharam.

### Ferramentas avaliadas

| Opção | Por que não foi adotada primeiro |
|---|---|
| `mutmut` | Adiciona dependência e uma cópia de trabalho com estado; a configuração para o layout `src/` e para a seleção de cada execução teria de ser ajustada antes do primeiro resultado. Continua sendo o candidato natural para uma execução periódica maior. |
| `cosmic-ray` | Mais operadores e execução distribuída, mas um modelo operacional mais pesado do que a pergunta exige. |
| Este harness | Nenhuma dependência nova, mutações determinísticas, um módulo por vez e a matriz teste-mutante no relatório. Menos operadores que as ferramentas maduras e nenhuma detecção automática de mutantes equivalentes. |

O harness é uma prova de conceito, não um substituto para uma ferramenta
madura. Seu valor é que o experimento é reproduzível neste repositório hoje e
pode ser repetido em um job agendado.

## Método

```bash
# Gerar e inspecionar as mutações sem executá-las
uv run --extra dev python scripts/tests/mutation_report.py \
  --module libs/docstruct/src/docstruct/fusion/flood.py \
  --tests tests/test_flood.py --suite libs/docstruct \
  --source-root libs/docstruct/src --list-mutants

# Executar o experimento com classificação por cobertura e comparação de sobreposição
make test-mutation

# O experimento de equations
uv run --extra dev python scripts/tests/mutation_report.py \
  --module libs/docstruct/src/docstruct/text/equations.py \
  --tests tests/test_equation_numbers.py --suite libs/docstruct \
  --source-root libs/docstruct/src \
  --coverage-file var/coverage/docstruct/.coverage \
  --overlap docs/testing/overlap-equations.json \
  --output var/mutation/equations.json
```

Operadores: trocas de comparação (`==`/`!=`, `<`/`<=`, `>`/`>=`, `in`/`not in`,
`is`/`is not`), `and`/`or` booleano, inversão de constante booleana, remoção de
`not`, negação de condição e `+=`/`-=`. Um mutante que faz os testes falharem é
**morto**; um mutante que os deixa passando é **sobrevivente**. Um mutante
sobrevivente em uma linha que a suíte nunca executa é classificado como **não
coberto**, não como fraqueza do teste. Timeouts e execuções inválidas são
relatados separadamente. Um timeout entra no denominador do mutation score, mas
não no numerador: um travamento é um resultado separado, não uma morte.

O mutation score é `mortos / (mortos + sobreviventes + timeout)` sobre mutantes
cobertos. Mutantes equivalentes **não** são identificados automaticamente: um
mutante sobrevivente exige julgamento manual.

## Resultados

| Módulo | Mutantes | Mortos | Sobreviventes | Timeout | Não cobertos | Inválidos | Mutation score |
|---|---:|---:|---:|---:|---:|---:|---:|
| `docstruct.fusion.flood` | 17 | 14 | 3 | 0 | 0 | 0 | 82,3% |
| `docstruct.text.equations` | 28 | 28 | 0 | 0 | 0 | 0 | 100% |

Os dois experimentos levaram cerca de 15 e 26 segundos, incluindo a inicialização
do interpretador por mutante. Isso é viável para dois módulos, não para a suíte
inteira em cada pull request.

### Mutantes sobreviventes em `flood_guard`

| Mutante | Linha | Mudança | Por que sobrevive |
|---|---:|---|---|
| M005 | 50 | `na < min_blocks` → `na <= min_blocks` | Nenhum teste usa exatamente `min_blocks` blocos. |
| M011 | 57 | `len(text) <= short` → `len(text) < short` | Nenhum teste usa um bloco com exatamente `short` caracteres. |
| M016 | 63 | `len(keep) < len(a)` → `len(keep) <= len(a)` | Nenhum teste dispara o guarda sem descartar um bloco. |

São lacunas reais de fronteira, não mutantes equivalentes. O arquivo de teste
cobre 10 e 40 blocos e comprimentos de texto `2` e `40`, mas não os limites
exatos 30, 15 e o caminho "disparou, mas manteve tudo". O PR 4 pode adicionar
três testes de fronteira e repetir o mesmo experimento; o resultado esperado é
17/17.

### Subsunção

Um teste A subsume B quando todo mutante morto por B também é morto por A. Essa
é uma relação baseada em mutação, mais estrita que a similaridade de cobertura.

Para `flood_guard`, a relação mais forte é
`test_descarta_blocos_curtos_sem_palavra_do_lexico`: ele mata os sete mutantes
que `test_blocos_longos_sao_preservados`,
`test_blocos_nao_textuais_sao_preservados`,
`test_lexico_vazio_descarta_todos_os_curtos` e
`test_tag_entra_nas_stats` também matam, e mata quatro mutantes adicionais
(7 compartilhados + 4 exclusivos = 11 no seu conjunto).
`test_blocos_longos_sao_preservados` e
`test_blocos_nao_textuais_sao_preservados` têm **conjuntos iguais** de mortes.

Esses pares têm Jaccard de cobertura 1,0, então sobreposição de cobertura e
subsunção concordam aqui. A conclusão ainda não é "remover os testes menores":
eles verificam comportamentos de manter/descartar e chaves de `stats`
diferentes, e a matriz de mutação só diz quais defeitos artificiais cada um
detecta.

Para `equations`, o conjunto completo tem **410 pares direcionados de
subsunção**; o relatório registra os primeiros 50 como exemplos. Alguns pares
não têm nenhum par de cobertura de alta similaridade:
por exemplo, testes que verificam fronteiras de exportação diferentes são
subsumidos por mutação sem cobrirem o mesmo conjunto estreito de linhas. Esse é
o complemento importante: **sobreposição de cobertura não substitui a detecção
por mutação**, e subsunção por mutação sem revisão de contrato não é licença
para remover um teste.

### Mutantes detectados por exatamente um teste

| Módulo | Teste | Mutantes |
|---|---|---|
| `flood` | `test_descarta_blocos_curtos_sem_palavra_do_lexico` | M007, M013, M015, M017 |
| `flood` | `test_ratio_e_respeitado` | M006 |
| `equations` | `test_existing_number_and_idempotence` | M013 |

Esses são o oposto de redundância: o teste é o único detector de uma mutação
específica e deve permanecer mesmo que sua cobertura pareça duplicada.

## Respostas às perguntas do PR 3

| Pergunta da #644 | Resultado |
|---|---|
| Avaliar ferramentas de mutation testing para Python | `mutmut` e `cosmic-ray` avaliados; o harness limitado foi escolhido para o primeiro experimento e as ferramentas maduras continuam candidatas a execuções periódicas |
| Selecionar módulos pequenos e determinísticos da docstruct | `fusion/flood.py` e `text/equations.py` |
| Executar mutações em escopo limitado | 17 e 28 mutantes, dois arquivos de teste focados, menos de 30 segundos cada |
| Registrar quais testes detectam cada mutação | lista `killers` por mutante nos dois relatórios |
| Construir relações experimentais de subsunção | seção `subsumption`, incluindo conjuntos iguais de mortes |
| Identificar mutantes sobreviventes | 3 em `flood`, 0 em `equations` |
| Comparar com a sobreposição de cobertura | Jaccard acrescentado por par de subsunção; a relação concorda em `flood` e diverge em `equations` |
| Viabilidade para SDK e core | o harness é de nível de linguagem e independe do componente; o custo de execuções amplas é a questão aberta, não a mecânica |

## Custo e próximos passos

- **Não adicionar mutation testing a todo PR.** A inicialização do
  interpretador por mutante domina e a suíte inteira multiplicaria isso.
- **Executar módulos selecionados periodicamente.** Um job agendado pode rodar
  o mesmo comando para uma lista pequena de módulos determinísticos e publicar
  os relatórios.
- **Agir sobre mutantes sobreviventes.** As três fronteiras de `flood` são o
  alvo de validação do PR 4: adicionar os testes, repetir e comparar o score
  antes e depois.
- **Não tratar subsunção como evidência de remoção.** Um teste subsumido ainda
  pode ser o único a documentar um contrato, uma mensagem localizada ou um modo
  de falha; o conjunto de operadores também é incompleto.

O relatório completo de sobreposição da docstruct é
[`overlap-docstruct.json`](overlap-docstruct.json). Ele não é usado como entrada
de comparação de mutação dos dois módulos pequenos; é o quadro mais amplo da
suíte da biblioteca.

## Limitações

- **Conjunto limitado de operadores.** O harness mira condições e operadores
  simples, não substituições complexas de API, remoção de argumentos ou
  mudanças de valor de retorno.
- **Nenhuma detecção de mutantes equivalentes.** Um mutante sobrevivente é uma
  pergunta, não um veredito.
- **Um módulo e seu arquivo de teste focado por execução.** Defeitos de
  integração entre módulos ficam fora deste experimento.
- **O unparse de AST muda a formatação.** A cópia mutada é compilada e
  executada, mas não é o texto original; comentários e formatação não são
  preservados.
- **A classificação de cobertura vem de outra execução.** Se o arquivo de
  cobertura estiver desatualizado, um mutante não coberto pode ser classificado
  errado.
- **O limite de exemplos de subsunção.** `--max-subsumption` (padrão 50) limita
  tanto a tabela Markdown quanto a lista JSON. `summary.subsumption_total`
  registra a contagem completa; a execução de `equations` tem 410.
