# 🐛 Expiração não é validada na consulta do token

## Identificação

| Campo | Valor |
|---|---|
| **ID** | BUG-0015 |
| **Data** | 2026-09-06 |
| **Reportado por** | Wryel Teodoro |
| **Severidade** | 🟡 Média |
| **Status** | Aberto · reproduzido em ambiente isolado |

## Ambiente

| Item | Valor |
|---|---|
| SO | Linux |
| Python | 3.12.3 |
| Branch / commit | [release/0.1.0](https://github.com/A11yDevs/acessilia/tree/release/0.1.0) @ `7a5e70f4809dd4bae29cfb772042d12784fc48b6` |
| Motor (`PIPELINE_ENGINE`) | Não executado; consulta de token de download |
| Estruturador (`STRUCTURER`) | Não utilizado; token e saída criados diretamente para verificar expiração |
| IA (`AI_CLIENT` + modelo) | Não utilizada; a falha está na validação da data armazenada no SQLite |
| Interface | API / download |

## Resumo

Um token com mais de sete dias continua válido na consulta se seu diretório de saída ainda existir.

## Entrada usada (qual arquivo/imagem)

- **Entrada:** Token SQLite real com `criado_em` alterado para oito dias atrás e diretório contendo TXT.
- **Observação:** reprodução isolada com dados sintéticos, sem acesso a dados de usuários ou serviços externos reais.

## Passos para reproduzir

1. Criar um resultado e registrar um token.
2. Definir `criado_em=datetime("now", "-8 days")` no registro de teste.
3. Consultar o token mantendo o diretório existente.

## Resultado esperado

Rejeitar o token vencido independentemente da próxima limpeza ou reinicialização.

## Resultado obtido

`obter_info_token` retorna normalmente as informações do token vencido.

```json
{
  "id": "BUG-0015",
  "age_days": 8,
  "token_accepted": true
}
```

## Causa raiz (se identificada)

[download_token_service.py](../../backend/services/download_token_service.py), `obter_info_token`, consulta por token sem condição de idade. A remoção dos registros vencidos é chamada no início do lifespan em [backend/api/app.py](../../backend/api/app.py), mas não pela limpeza periódica. A remoção antecipada de diretórios pode ocultar a falha, porém não constitui validação de expiração.

## Correção sugerida (se houver)

Validar a idade na leitura do token e executar periodicamente a limpeza dos registros vencidos.

## Rastreabilidade

- **Revalidação:** permanece em `release/0.1.0` @ `7a5e70f4809dd4bae29cfb772042d12784fc48b6`, verificado em 2026-09-06.

- **Origem rastreada:** A consulta `SELECT output_dir, filename, formats, criado_em ... WHERE token = ?` está rastreada a `8a842eb` (2026-07-27). A reprodução atual confirma que não foi acrescentada validação de validade à leitura.
- **Auditoria anterior:** `AUD-10`; restaurado com o ID `BUG-0015` na sequência dos registros atuais.

## Evidências

- SQLite real com token de oito dias; consulta aceita o registro expirado.
- Verificação executada em 2026-09-06 sobre o commit da release indicado em Ambiente, com assertions dos resultados.
- Dados desta execução registrados no bloco JSON acima.
