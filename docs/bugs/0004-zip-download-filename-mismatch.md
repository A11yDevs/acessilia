# 🐛 Nome do ZIP incompatível com a descoberta dos downloads

## Identificação

| Campo | Valor |
|---|---|
| **ID** | BUG-0004 |
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
| Motor (`PIPELINE_ENGINE`) | `legacy` configurado na prova; defeito no nome do ZIP produzido pelo worker |
| Estruturador (`STRUCTURER`) | `pymupdf` configurado; extração não executada |
| IA (`AI_CLIENT` + modelo) | `ollama` configurado; resposta válida simulada, sem chamada a modelo |
| Interface | API / download ZIP |

## Resumo

Nome do ZIP incompatível com a descoberta dos downloads. Download completo indisponível mesmo em conversão bem-sucedida.

## Entrada usada (qual arquivo/imagem)

- **Entrada:** documento.png; artefatos sintéticos e ZIP real.
- **Observação:** cenário reproduzido em ambiente isolado com dados sintéticos; não depende de dados de usuários.

## Passos para reproduzir

1. Usar `release/0.1.0` no commit indicado em Ambiente, com as dependências instaladas.
2. Concluir um job `documento.png` e solicitar `GET /api/v1/download/{token}/zip`.

## Resultado esperado

Baixar o pacote criado pelo worker.

## Resultado obtido

ZIP existe em disco, não aparece em `formats` e a API retorna **404**.

```json
{
  "id": "BUG-0004",
  "zip_exists": true,
  "api_zip_status": 404
}
```

## Causa raiz (se identificada)

[worker.py](../../backend/api/worker.py), linha 180, salva `documento_acessivel.zip`; [download_token_service.py](../../backend/services/download_token_service.py), `obter_info_token`, procura `documento.zip`.

## Correção sugerida (se houver)

Centralizar nomes de artefatos ou persistir o manifesto de arquivos realmente produzidos e usá-lo na consulta.

## Rastreabilidade

- **Revalidação:** permanece em `release/0.1.0` @ `7a5e70f4809dd4bae29cfb772042d12784fc48b6`, verificado em 2026-09-06.

- **Introdução rastreada:** `c7bbbf2` (2026-07-04), quando a listagem multiformato passou a procurar `<base>.zip` enquanto o painel gerava `<base>_acessivel.zip`.
- A reprodução cria o ZIP real e observa que `formats` não contém `zip`.

## Evidências

- Worker e ZIP reais com exportadores simulados; requisição à aplicação API por ASGI retorna 404 para o ZIP existente.
- Verificação executada em 2026-09-06 sobre o commit da release indicado em Ambiente, com assertions dos resultados.
- Dados desta execução registrados no bloco JSON acima.
