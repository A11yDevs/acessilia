# 🐛 Conteúdo das tabelas do Docling é descartado (tabela chega vazia ao documento acessível)

## Identificação
| Campo | Valor |
|---|---|
| **ID** | BUG-0005 |
| **Data** | 2026-09-08 |
| **Reportado por** | Pedro Alano |
| **Severidade** | 🔴 Alta (perda total de conteúdo tabular na saída acessível) |
| **Status** | ✅ **Corrigido e verificado** na branch `fix/docling-table-ast` (commit `8ce4e39`) |
| **Link da issue** | <preencher ao abrir no GitHub> |

## Ambiente
| Item | Valor |
|---|---|
| Branch avaliada | `release/0.1.0` @ `7a5e70f` |
| Estruturador | docling (também afeta o caminho legacy) |
| Documentos | `acessilia-dataset/input/004.pdf` e `007.pdf` |

## Resumo
O Docling **extrai as tabelas corretamente** (linhas, colunas, células e marcação de cabeçalho), mas a Acessilia **não lê esses dados**: o elemento de tabela chega ao manifesto **vazio** (`text=None`, sem `table_ast`). O conteúdo tabular é **perdido** na saída acessível.

## Passos para reproduzir
1. Rodar o extrator estrutural em `acessilia-dataset/input/007.pdf` (página cujo conteúdo **é** uma tabela).
2. Inspecionar os elementos do manifesto do tipo `table`.

## Resultado esperado
Elemento de tabela com `table_ast` preenchido (linhas, colunas e cabeçalho).

## Resultado obtido (antes da correção)
```
--- TABELA id=element-000003 raw_label='table'
  text (0 chars): None
  metadata keys: ['content_layer', 'docling_class']
    docling_class = 'TableItem'
```
No `007.pdf`, o manifesto inteiro ficou com **73 caracteres** — apenas o título. Como a página é uma tabela, **~100% do conteúdo foi perdido**. No `004.pdf`, o texto diz *"Na tabela abaixo, estão os tamanhos de cada tipo primitivo"* e a tabela vem vazia.

## Evidência de que o Docling extrai corretamente
Chamando o Docling diretamente nos mesmos arquivos:

| Documento | Tabelas | Estrutura extraída pelo Docling |
|---|---|---|
| `007.pdf` | 1 | `num_rows=8, num_cols=3`, 22 células, `column_header=True` na linha 0 |
| `004.pdf` | 2 | `9x8` (53 células) e `9x2` (18 células), com cabeçalhos |

➡️ **O problema não é o DLA.** O dado existe; o adaptador é que o descarta.

## Causa raiz
`backend/core/manifest/builder.py::_extract_table_ast` procurava os atributos `table_ast`, `table`, `table_data`, `grid`, `rows` e `cells` **no próprio item**. Mas o Docling guarda a tabela em **`item.data.table_cells`** — e nem `data` (atributo) nem `data` (chave do dump) estavam na lista de candidatos. Nenhum candidato batia → `table_ast = None`.

## Correção aplicada
Nova função `_table_ast_from_docling(item)`, chamada **primeiro** em `_extract_table_ast`:
- lê `item.data.table_cells`;
- agrupa por `start_row_offset_idx`, ordena por `start_col_offset_idx`;
- usa `column_header` / `row_header` para separar `header` de `body` e definir `scope`;
- propaga `row_span` / `col_span` como `rowspan` / `colspan`.

**Mudança puramente aditiva:** +75 linhas em 1 arquivo, nenhuma remoção.

## Verificação (depois da correção)
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

**Suíte de testes:** `136 passed`, sem regressão.

## Impacto em testes / regressão
- **Coberto por teste?** Não havia teste que exercitasse a extração real de tabela do Docling.
- **Sugestão para o CI/CD:** teste que rode o extrator num PDF com tabela do dataset e valide `table_row_count`, `table_column_count` e `table_has_header` — travando a regressão.

## Observação para a equipe
Este achado **corrige a hipótese** de que a falha em tabelas seria limitação do DLA. Ela também **explica** o sintoma relatado na apresentação (numeração de slides "1/15" interpretada como fração): sem os dados estruturados, o pipeline cai na interpretação **visual** (OCR/VLM), que passa a adivinhar. A meta nº 3 do 1.0.0 (tabelas) pode estar bem mais próxima do que se supunha.
