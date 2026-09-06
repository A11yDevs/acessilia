# 🐛 Segundo `stem` quebra arquivos com pontos no nome

## Identificação

| Campo | Valor |
|---|---|
| **ID** | BUG-0005 |
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
| Motor (`PIPELINE_ENGINE`) | `legacy` configurado na prova; defeito na composição e consulta dos nomes de saída |
| Estruturador (`STRUCTURER`) | `pymupdf` configurado; extração não executada |
| IA (`AI_CLIENT` + modelo) | `ollama` configurado; resposta válida simulada, sem chamada a modelo |
| Interface | API / downloads |

## Resumo

Segundo `stem` quebra arquivos com pontos no nome. Nenhum formato fica disponível para esse padrão comum de nome.

## Entrada usada (qual arquivo/imagem)

- **Entrada:** relatorio.v2.pdf; nome original preservado no job.
- **Observação:** cenário reproduzido em ambiente isolado com dados sintéticos; não depende de dados de usuários.

## Passos para reproduzir

1. Usar `release/0.1.0` no commit indicado em Ambiente, com as dependências instaladas.
2. Concluir `relatorio.v2.pdf`.

## Resultado esperado

Todos os formatos produzidos serem encontrados.

## Resultado obtido

Existem `relatorio.v2.txt`, `.docx`, `.pdf`, `.html` e `.mp3`, mas `formats` é vazio.

```json
{
  "id": "BUG-0005",
  "files": [
    "relatorio.v2.docx",
    "relatorio.v2.html",
    "relatorio.v2.mp3",
    "relatorio.v2.pdf",
    "relatorio.v2.pdf_ua.pdf",
    "relatorio.v2.txt",
    "relatorio.v2_acessivel.zip"
  ],
  "advertised_formats": []
}
```

## Causa raiz (se identificada)

worker usa `Path(filename).stem` e passa `relatorio.v2` para `criar_token`. Na consulta, [download_token_service.py](../../backend/services/download_token_service.py) aplica `Path(row['filename']).stem` novamente, reduzindo o nome para `relatorio`.

## Correção sugerida (se houver)

Definir se o campo armazenado é nome completo ou base e remover extensão uma única vez. É independente do sufixo de ZIP do BUG-0004.

## Rastreabilidade

- **Revalidação:** permanece em `release/0.1.0` @ `7a5e70f4809dd4bae29cfb772042d12784fc48b6`, verificado em 2026-09-06.

- **Introdução rastreada:** `a728607` (2026-07-31), quando o worker passou a enviar ao token um nome já reduzido por `stem`, que o resolvedor reduz novamente.
- A reprodução usa `relatorio.v2` e observa que o TXT correspondente não é descoberto.

## Evidências

- Worker e consulta de token reais, com exportadores simulados; arquivos com base relatorio.v2 existem e a lista de formatos fica vazia.
- Verificação executada em 2026-09-06 sobre o commit da release indicado em Ambiente, com assertions dos resultados.
- Dados desta execução registrados no bloco JSON acima.
