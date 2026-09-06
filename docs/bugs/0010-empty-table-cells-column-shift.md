# 🐛 Células vazias eliminadas corrompem alinhamento de tabelas

## Identificação

| Campo | Valor |
|---|---|
| **ID** | BUG-0010 |
| **Data** | 2026-09-05 |
| **Reportado por** | Wryel Teodoro |
| **Severidade** | 🟠 Alta |
| **Status** | Aberto · reproduzido em ambiente isolado |

## Ambiente

| Item | Valor |
|---|---|
| SO | Linux |
| Python | 3.12.3 (revalidação isolada) |
| Branch / commit | [release/0.1.0](https://github.com/A11yDevs/acessilia/tree/release/0.1.0) @ `7a5e70f4809dd4bae29cfb772042d12784fc48b6` |
| Motor (`PIPELINE_ENGINE`) | Não executado; teste direto da conversão de tabelas em `table_ast.py` |
| Estruturador (`STRUCTURER`) | Não utilizado; a entrada já contém linhas e células estruturadas |
| IA (`AI_CLIENT` + modelo) | Não utilizada; a perda da célula vazia é determinística no código de conversão |
| Interface | Exportação / tabelas canônicas |

## Resumo

Células vazias eliminadas corrompem alinhamento de tabelas. Relação entre cabeçalho e conteúdo fica falsa, afetando leitura e acessibilidade.

## Entrada usada (qual arquivo/imagem)

- **Entrada:** Tabela Nome/Idade/Cidade, linha Ana/vazio/Recife.
- **Observação:** cenário reproduzido com dados sintéticos; não depende de dados de usuários.

## Passos para reproduzir

1. Usar `release/0.1.0` no commit indicado em Ambiente, com as dependências instaladas.
2. Cabeçalho `Nome | Idade | Cidade`, linha `Ana | vazio | Recife`.

## Resultado esperado

Preservar a célula vazia e sua posição, inclusive em DOCX/HTML e demais projeções do AST.

## Resultado obtido

Linha vira `Ana | Recife`, deslocando Recife para a coluna Idade.

```json
{
  "id": "BUG-0010",
  "input_rows": [
    [
      "Nome",
      "Idade",
      "Cidade"
    ],
    [
      "Ana",
      "",
      "Recife"
    ]
  ],
  "output_rows": [
    [
      "Nome",
      "Idade",
      "Cidade"
    ],
    [
      "Ana",
      "Recife"
    ]
  ]
}
```

## Causa raiz (se identificada)

[table_ast.py](../../backend/pipeline/table_ast.py), `table_ast_from_rows` e `rows_from_table_ast`, filtram células cujo texto é vazio. [html_renderer.py](../../backend/export/renderers/html_renderer.py), `_render_html_table_row`, também ignora células vazias.

## Correção sugerida (se houver)

Preservar células estruturais vazias; remover somente linhas/elementos comprovadamente descartáveis sem alterar geometria.

## Rastreabilidade

- **Revalidação:** permanece em `release/0.1.0` @ `7a5e70f4809dd4bae29cfb772042d12784fc48b6`, verificado em 2026-09-06.

- **Introdução rastreada:** `aa53214` (2026-08-07), criação do AST de tabelas já filtrando células vazias na entrada e na saída.
- A reprodução faz o round-trip de uma linha com célula central vazia e observa a perda da posição.

## Evidências

- Conversão real de linhas para AST de tabela e de volta; a célula vazia intermediária desaparece.
- Verificação executada em 2026-09-06 sobre o commit da release indicado em Ambiente, com assertions dos resultados.
- Dados desta execução registrados no bloco JSON acima.
