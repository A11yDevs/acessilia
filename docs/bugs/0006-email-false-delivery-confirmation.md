# 🐛 Falso aviso de e-mail enviado e ausência de alternativa

## Identificação

| Campo | Valor |
|---|---|
| **ID** | BUG-0006 |
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
| Motor (`PIPELINE_ENGINE`) | Não executado; verificação do serviço de e-mail e do polling Telegram |
| Estruturador (`STRUCTURER`) | Não utilizado; o cenário parte de um resultado pronto |
| IA (`AI_CLIENT` + modelo) | Não utilizada; indisponibilidade de SMTP e confirmação de entrega são verificadas sem modelo |
| Interface | Telegram / e-mail |

## Resumo

Falso aviso de e-mail enviado e ausência de alternativa. Usuário fica sem acesso ao resultado pelo fluxo seguido. Há ainda uma janela em que o worker marca `done` antes de aguardar o envio do resultado.

## Entrada usada (qual arquivo/imagem)

- **Entrada:** E-mail teste@example.invalid; SMTP desabilitado.
- **Observação:** cenário reproduzido com dados sintéticos; não depende de dados de usuários.

## Passos para reproduzir

1. Usar `release/0.1.0` no commit indicado em Ambiente, com as dependências instaladas.
2. Informar e-mail, deixar SMTP ausente, finalizar job e consultar via polling.

## Resultado esperado

Relatar o estado real de entrega e oferecer o link quando o envio não é confirmado.

## Resultado obtido

Zero chamadas de envio e mensagem “Link de download enviado”, sem URL.

```json
{
  "id": "BUG-0006",
  "smtp_calls": 0,
  "telegram_message": "✅ Link de download enviado para teste@example.invalid!"
}
```

## Causa raiz (se identificada)

[email_service.py](../../backend/services/email_service.py) retorna sem sinalizar falha quando SMTP não está configurado e captura erros de envio. [document.py](../../frontend/telegram/handlers/document.py), `_poll_job`, considera a presença do endereço de e-mail suficiente para afirmar que o link foi enviado; nesse ramo não fornece o próprio link.

## Correção sugerida (se houver)

Persistir resultado da notificação e não deduzi-lo apenas do e-mail fornecido.

## Rastreabilidade

- **Revalidação:** permanece em `release/0.1.0` @ `7a5e70f4809dd4bae29cfb772042d12784fc48b6`, verificado em 2026-09-06.

- **Introdução rastreada:** `c7bbbf2` (2026-07-04), inclusão da confirmação textual de envio sem confirmação de entrega e sem exibir o link alternativo.
- A reprodução observa que o fluxo com e-mail não preserva a URL de download como alternativa verificável.

## Evidências

- Serviço de e-mail sem credenciais SMTP e handler Telegram com resposta de job simulada; nenhuma mensagem externa foi enviada.
- Verificação executada em 2026-09-06 sobre o commit da release indicado em Ambiente, com assertions dos resultados.
- Dados desta execução registrados no bloco JSON acima.
