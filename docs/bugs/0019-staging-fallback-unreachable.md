# 🐛 Fallback de atualização não cobre falha HTTP ou rede

## Identificação

| Campo | Valor |
|---|---|
| **ID** | BUG-0019 |
| **Data** | 2026-09-06 |
| **Reportado por** | Wryel Teodoro |
| **Severidade** | 🟡 Média |
| **Status** | Aberto · reproduzido em ambiente isolado |

## Ambiente

| Item | Valor |
|---|---|
| SO | Linux |
| Python | Bash; sem execução de Python no script auditado |
| Branch / commit | [release/0.1.0](https://github.com/A11yDevs/acessilia/tree/release/0.1.0) @ `7a5e70f4809dd4bae29cfb772042d12784fc48b6` |
| Motor (`PIPELINE_ENGINE`) | Não aplicável; tratamento de falha HTTP no script de staging |
| Estruturador (`STRUCTURER`) | Não aplicável ao fluxo de atualização |
| IA (`AI_CLIENT` + modelo) | Não aplicável; falha HTTP simulada na consulta de atualização, sem provedor de IA |
| Interface | Script de homologação |

## Resumo

Uma falha de curl encerra o script antes do fallback de atualização anunciado no próprio código.

## Entrada usada (qual arquivo/imagem)

- **Entrada:** curl simulado com exit status 22; Docker simulado para detectar eventual chamada de fallback.
- **Observação:** reprodução isolada com dados sintéticos, sem acesso a dados de usuários ou serviços externos reais.

## Passos para reproduzir

1. Executar `scripts/staging-update.sh` em diretório temporário, com curl substituído por um comando que termina com código 22.
2. Manter o comportamento de `set -euo pipefail` do script real.
3. Conferir o exit status e se algum comando Docker foi chamado.

## Resultado esperado

Tratar explicitamente a falha da consulta e executar a política de fallback anunciada.

## Resultado obtido

O script termina com código 22 e não chama Docker.

```json
{
  "id": "BUG-0019",
  "curl_exit": 22,
  "script_exit": 22,
  "fallback_docker_called": false
}
```

## Causa raiz (se identificada)

[scripts/staging-update.sh](../../scripts/staging-update.sh) usa `LATEST_SHA=$(curl -fsS ... | jq ...)` com `set -euo pipefail`. O pipeline malsucedido encerra o script antes do `if` que testa SHA vazio ou nulo.

## Correção sugerida (se houver)

Capturar o status da consulta em uma condição tratada e encaminhar a falha para a política de fallback.

## Rastreabilidade

- **Revalidação:** permanece em `release/0.1.0` @ `7a5e70f4809dd4bae29cfb772042d12784fc48b6`, verificado em 2026-09-06.

- **Origem rastreada:** O fluxo de consulta ao GitHub e fallback está rastreado a `d23a7fe` (2026-08-31). A execução do script atual confirma que erro HTTP não alcança esse fallback.
- **Auditoria anterior:** `AUD-21`; restaurado com o ID `BUG-0019` na sequência dos registros atuais.

## Evidências

- Script de staging real executado com curl controlado retornando 22; saída 22 sem chamar o fallback Docker.
- Verificação executada em 2026-09-06 sobre o commit da release indicado em Ambiente, com assertions dos resultados.
- Dados desta execução registrados no bloco JSON acima.
