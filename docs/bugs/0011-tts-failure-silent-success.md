# 🐛 Falha de áudio fica invisível no resultado público

## Identificação

| Campo | Valor |
|---|---|
| **ID** | BUG-0011 |
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
| Motor (`PIPELINE_ENGINE`) | `legacy` configurado; retorno do orquestrador simulado antes das exportações |
| Estruturador (`STRUCTURER`) | `pymupdf` configurado; extração não executada |
| IA (`AI_CLIENT` + modelo) | `ollama` configurado; resposta válida simulada. Falha técnica injetada em `export_mp3`, sem avaliar voz ou modelo |
| Interface | API / worker / áudio |

## Resumo

Falha de áudio fica invisível no resultado público. Usuário que depende de áudio recebe pacote incompleto sem explicação.

## Entrada usada (qual arquivo/imagem)

- **Entrada:** Job sintético com RuntimeError no TTS.
- **Observação:** cenário reproduzido com dados sintéticos; não depende de dados de usuários.

## Passos para reproduzir

1. Usar `release/0.1.0` no commit indicado em Ambiente, com as dependências instaladas.
2. Fazer `export_mp3` levantar `RuntimeError("TTS indisponivel")`.

## Resultado esperado

Falha ou resultado parcial explicitamente informado, sem anunciar áudio disponível.

## Resultado obtido

`status=done`, `erros=[]`, ZIP sem `.mp3`.

```json
{
  "id": "BUG-0011",
  "status": "done",
  "errors": [],
  "zip_members": [
    "documento.txt",
    "documento.docx",
    "documento.pdf",
    "documento.html",
    "documento.pdf_ua.pdf"
  ]
}
```

## Causa raiz (se identificada)

A prova injeta uma exceção técnica de indisponibilidade no TTS. O defeito é a omissão dessa falha no estado público; não é uma avaliação da qualidade da voz ou da descrição.

[worker.py](../../backend/api/worker.py), linhas 173–178, apenas registra a falha em log; `_build_zip_package` inclui somente arquivos existentes e o job termina `done` sem adicionar erro.

## Correção sugerida (se houver)

Definir artefatos obrigatórios e sinalizar faltantes em estado/manifesto/notificação. Não é o caso já documentado de PDF/UA opcional ausente por dependência local.

## Rastreabilidade

- **Revalidação:** permanece em `release/0.1.0` @ `7a5e70f4809dd4bae29cfb772042d12784fc48b6`, verificado em 2026-09-06.

- **Introdução rastreada:** `a728607` (2026-07-31), primeiro worker da API; a exceção de `export_mp3` passou a ser apenas registrada em log antes do status `done`.
- A reprodução força uma falha de TTS e observa o estado `done` sem erro ou aviso explícito.

## Evidências

- Worker real com falha técnica de TTS injetada; estado público e conteúdo do ZIP verificados.
- Verificação executada em 2026-09-06 sobre o commit da release indicado em Ambiente, com assertions dos resultados.
- Dados desta execução registrados no bloco JSON acima.
