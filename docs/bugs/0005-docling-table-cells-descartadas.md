# 🐛 Conteúdo das tabelas do Docling é descartado (tabela chega vazia ao documento acessível)

## Identificação
| Campo | Valor |
|---|---|
| **ID** | BUG-0005 |
| **Data** | 2026-09-08 |
| **Reportado por** | Pedro Alano (teste/homologação) |
| **Severidade** | 🔴 Alta (perda total de conteúdo tabular na saída acessível) |
| **Status** | 🔎 **Causa raiz confirmada** · **correção sugerida** (não aplicada — a cargo do time de desenvolvimento) |
| **Link da issue** | <preencher ao abrir no GitHub> |

## Ambiente
| Item | Valor |
|---|---|
| Branch avaliada | `release/0.1.0` @ `7a5e70f` |
| Estruturador | docling (o caminho legacy também não extrai células) |
| Documentos | `acessilia-dataset/input/004.pdf` e `007.pdf` |

## Resumo
O Docling **extrai as tabelas corretamente** (linhas, colunas, células e marcação de cabeçalho), mas a Acessilia **não lê esses dados**: o elemento de tabela chega ao manifesto **vazio** (`text=None`, sem `table_ast`). O conteúdo tabular é **perdido** na saída acessível.

## Passos para reproduzir
1. Rodar o extrator estrutural em `acessilia-dataset/input/007.pdf` (página cujo conteúdo **é** uma tabela).
2. Inspecionar os elementos do manifesto do tipo `table`.

## Resultado esperado
Elemento de tabela com `table_ast` preenchido (linhas, colunas e cabeçalho).

## Resultado obtido
```
--- TABELA id=element-000003 raw_label='table'
  text (0 chars): None
  metadata keys: ['content_layer', 'docling_class']
    docling_class = 'TableItem'
```
No `007.pdf`, o manifesto inteiro ficou com **73 caracteres** — apenas o título. Como a página é uma tabela, **~100% do conteúdo foi perdido**. No `004.pdf`, o texto diz *"Na tabela abaixo, estão os tamanhos de cada tipo primitivo"* e a tabela vem vazia.

## Evidência: o Docling extrai corretamente
Chamando o Docling diretamente nos mesmos arquivos:

| Documento | Tabelas | Estrutura extraída pelo Docling |
|---|---|---|
| `007.pdf` | 1 | `num_rows=8, num_cols=3`, 22 células, `column_header=True` na linha 0 |
| `004.pdf` | 2 | `9x8` (53 células) e `9x2` (18 células), com cabeçalhos |

➡️ **O problema não está no DLA.** O dado existe; ele é descartado no adaptador.

## Causa raiz (confirmada)
`backend/core/manifest/builder.py::_extract_table_ast` procura os atributos `table_ast`, `table`, `table_data`, `grid`, `rows` e `cells` **no próprio item**. Mas o Docling guarda a tabela em **`item.data.table_cells`** — e nem `data` (atributo) nem `data` (chave do dump) constam na lista de candidatos. Nenhum candidato bate, então `table_ast` fica `None`.

## Correção sugerida (para avaliação do time de desenvolvimento)
Ler o formato do Docling **antes** dos candidatos genéricos. Esboço da lógica:

- ler `item.data.table_cells`;
- agrupar as células por `start_row_offset_idx` e ordenar por `start_col_offset_idx`;
- usar `column_header` (e `row_header`) para separar `header` de `body` e definir o `scope`;
- propagar `row_span` / `col_span` como `rowspan` / `colspan`;
- devolver no formato `{"header": [...], "body": [...]}` já aceito por `normalize_table_ast`.

E, no início de `_extract_table_ast`, tentar esse conversor primeiro, caindo nos candidatos genéricos se ele não se aplicar.

A sugestão é **puramente aditiva** (~75 linhas, 1 arquivo, sem remoções). O restante do pipeline **já suporta** o formato: `table_ast_from_block`, `split_header_and_body`, `linearize_table_for_text` e o renderizador HTML já existem e são testados.

## Validação da hipótese (protótipo local, descartado)
Apenas para **confirmar o diagnóstico**, a lógica acima foi testada localmente. O protótipo **não foi versionado nem submetido** — a implementação definitiva fica a cargo do time.

| Documento | Manifesto | HTML gerado |
|---|---|---|
| `007.pdf` | 1 tabela `8x3`, cabeçalho ✅ | `<table>`×1, `<thead>`×1, `<th scope=>`×3, `<td>`×19 |
| `004.pdf` | 2 tabelas `9x8` e `9x2`, cabeçalho ✅ | `<table>`×2, `<thead>`×2, `<th scope=>`×10, `<td>`×61 |

Texto linearizado (o que o leitor de tela e o MP3 entregam):
```
Linha 1: TIPO: boolean; TAMANHO: 1 bit
Linha 1: Grandeza física de base: comprimento (l); Unidade de base: metro (m); Definição: 1 m é o comprimento...
```
Cada célula associada ao seu cabeçalho — exatamente o exigido para acessibilidade de tabelas.

**Suíte de testes com a alteração experimental:** `136 passed`, sem regressão.

## Impacto em testes / regressão
- **Coberto por teste?** Não há teste que exercite a extração real de tabela do Docling.
- **Sugestão para o CI/CD:** teste que rode o extrator num PDF com tabela do dataset e valide `table_row_count`, `table_column_count` e `table_has_header`.

## Observação para a equipe
Este achado **revisa a hipótese** de que a falha em tabelas seria limitação do DLA, e **explica** o sintoma relatado na apresentação (numeração "1/15" lida como fração): sem os dados estruturados, o pipeline recai na interpretação **visual** (OCR/VLM), que passa a adivinhar. A meta nº 3 do 1.0.0 (tabelas) pode estar mais próxima do que se supunha.
