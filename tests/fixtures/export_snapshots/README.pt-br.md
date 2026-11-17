# Linha de base de caracterização dos exports (E1.0 da #371)

[Fonte em inglês](README.md).

Estas são as saídas dos exportadores **inalterados** da docstruct 0.5.0 no
commit do Core `027b87f13bf061603d94b736a90ac62bd89b458e`. `manifest.json`
registra essa origem e as 30 chamadas. Quatro entradas sintéticas produzem
39 arquivos de referência. Nenhum provider, rede, modelo, identificador
gerado ou timestamp é necessário para renderizá-las. Os testes carregam cada
entrada novamente e verificam sua integridade após cada chamada.

| Entrada | Comportamento caracterizado |
|---|---|
| `blocks` | Os onze tipos de bloco do schema, listas ordenadas/não ordenadas, escopos e spans de linhas/colunas de tabelas, matemática com/sem fala, números de equações, descrições de imagens, escape e blocos basic/detailed/technical em seções pai e filhas |
| `sections` | Headings legados em `text` ou `title`, ids distintos de aliases, título repetido após parágrafo, nível de heading diferente, filhos aninhados/sem título e rótulos personalizados de fórmulas no TXT |
| `unknown` | Tipos de bloco desconhecidos aceitos pelos fallbacks existentes, incluindo a filtragem atual de perfis |
| `empty` | Listas de seções vazias e comportamento exato de saídas vazias/quebras de linha |

Cada caso registra TXT, HTML, Markdown e AST Pandoc para `docx` e `pdf_ua`. `blocks` também registra todos os perfis atuais de TXT/HTML
(`txt`, `html`, `pdf`, `pdf_ua`, `docx`) e o fallback existente para perfil
desconhecido. Os rótulos são entradas explícitas em inglês nas APIs.

## O que deve permanecer idêntico até E1.7

- Linhas unidas de TXT, HTML e Markdown são comparadas como bytes UTF-8 exatos:
  sem remover espaços nem normalizar conteúdo. TXT também registra o array
  de linhas, impedindo que mudanças nas divisões públicas sejam escondidas
  pela união. O comportamento existente de gravação/strip do wrapper do Core
  é uma fronteira separada.
  Marcadores de itens vazios terminam hoje em espaço; o atributo Git restrito
  aos TXT preserva esse dado intencional sem avisos de blank-at-eol na revisão.
- JSON Pandoc é comparado estruturalmente: a ordem de chaves não importa, mas
  a ordem de arrays e todo texto, metadado, atributo e matemática por destino
  permanecem.
- Cada export deve preservar sua entrada. Os testes também conferem a cobertura
  dos onze valores do enum e congelam diferenças selecionadas.

Markdown omite hoje **todo** heading igual ao título da seção; TXT, HTML e
Pandoc omitem apenas o primeiro heading legado correspondente. TXT perde o
`formula_label` personalizado ao descer para filhos. Markdown e o builder
Pandoc direto não aplicam os filtros de perfil de TXT/HTML. São comportamentos
registrados, não correções para antecipar ao introduzir o walker. Os dois
destinos Pandoc mantêm suas representações diferentes de números de equações.

A entrada `custom` falha propositalmente no enum de tipos do schema, mas é
exportada hoje. Validação estrita antecipada mudaria as entradas aceitas; isso
permanece na decisão separada de compatibilidade E1.2b. Empacotamento/injeção
do schema (E1.2a), descontinuação de tipos públicos (E1.3), walker/migração
(E1.6/E1.7), catálogo de formatos (E1.9), rótulos (E1.8) e verbosidade (E1.11)
não são implementados aqui.

## Executar o gate de paridade

Na raiz do repositório, no ambiente de desenvolvimento travado pelo lock:

```bash
uv run --locked --extra dev python -m pytest libs/docstruct/tests/test_export_characterization.py
make test-all
```

O CI também executa os testes contra o wheel isolado da docstruct e em um
contêiner de testes usando o lock da biblioteca e `--no-editable`. Suas
dependências runtime continuam vazias. Reproduza essa etapa com Docker disponível:

```bash
docker build --file tests/fixtures/export_snapshots/Dockerfile --tag acessilia-export-characterization .
docker run --rm --volume "$PWD:/workspace:ro" acessilia-export-characterization
```

A imagem contém apenas Python/uv fixados; o checkout é montado somente para
leitura. O ambiente temporário instala docstruct e suas ferramentas de
desenvolvimento travadas e executa Python em modo isolado. Não usa Toolbox
nem renderer de produção.

## Revisar uma captura sem substituir a linha de base

Os testes nunca geram saídas esperadas. `capture.py` exige um **novo diretório
externo a estas fixtures**, portanto não sobrescreve a referência commitada.
Para verificar a captura original, crie um checkout destacado da origem
registrada e use a docstruct dele com o harness deste PR:

```bash
git worktree add --detach /tmp/acessilia-export-baseline 027b87f13bf061603d94b736a90ac62bd89b458e
PYTHONPATH=/tmp/acessilia-export-baseline/libs/docstruct/src \
  .venv/bin/python tests/fixtures/export_snapshots/capture.py --output-dir /tmp/export-capture-review
diff -r tests/fixtures/export_snapshots/expected /tmp/export-capture-review
```

Manter esses arquivos inalterados em E1.6/E1.7. Uma mudança deliberada de
comportamento exige revisão própria, decisão de compatibilidade e diff explícito
dos snapshots, conforme a [revisão final da issue](https://github.com/A11yDevs/acessilia/issues/371#issuecomment-6731172790).
