# 🐛 Staging ignora branch do .env se token já estiver no ambiente

## Identificação

| Campo | Valor |
|---|---|
| **ID** | BUG-0018 |
| **Data** | 2026-09-06 |
| **Reportado por** | Wryel Teodoro |
| **Severidade** | 🟠 Alta |
| **Status** | Aberto · reproduzido em ambiente isolado |

## Ambiente

| Item | Valor |
|---|---|
| SO | Linux |
| Python | Bash; sem execução de Python no script auditado |
| Branch / commit | [release/0.1.0](https://github.com/A11yDevs/acessilia/tree/release/0.1.0) @ `7a5e70f4809dd4bae29cfb772042d12784fc48b6` |
| Motor (`PIPELINE_ENGINE`) | Não aplicável; carregamento de variáveis no script de staging |
| Estruturador (`STRUCTURER`) | Não aplicável ao carregamento do `.env` |
| IA (`AI_CLIENT` + modelo) | Não aplicável; `GHCR_TOKEN` autentica o registro de imagens, não um modelo de IA |
| Interface | Script de homologação / BHS |

## Resumo

Com `GHCR_TOKEN` já exportado, o script ignora `TRACK_BRANCH` definido apenas no `.env` e acompanha develop em vez da release configurada.

## Entrada usada (qual arquivo/imagem)

- **Entrada:** `.env` temporário com `TRACK_BRANCH=release/0.0.1`; token fictício no ambiente; curl e Docker substituídos por executáveis de teste.
- **Observação:** reprodução isolada com dados sintéticos, sem acesso a dados de usuários ou serviços externos reais.

## Passos para reproduzir

1. Definir `GHCR_TOKEN` no ambiente e deixar `TRACK_BRANCH` ausente dele.
2. Criar `.env` com `TRACK_BRANCH=release/0.0.1` no diretório indicado por `STAGING_DIR`.
3. Executar o script com curl/Docker simulados e verificar a branch solicitada ao GitHub.

## Resultado esperado

Consultar a branch de release indicada no `.env`.

## Resultado obtido

O script consulta `/commits/develop`.

```json
{
  "id": "BUG-0018",
  "dotenv_branch": "release/0.0.1",
  "queried_branch": "develop",
  "token_predefined": true
}
```

## Causa raiz (se identificada)

[scripts/staging-update.sh](../../scripts/staging-update.sh) só carrega `.env` dentro de `if [ -z "${GHCR_TOKEN:-}" ]`. Com token predefinido, as outras configurações desse arquivo também são ignoradas; `GITHUB_BRANCH` cai no default `develop`.

## Correção sugerida (se houver)

Carregar a configuração da branch independentemente da descoberta do token e estabelecer precedência explícita entre ambiente e arquivo.

## Rastreabilidade

- **Revalidação:** permanece em `release/0.1.0` @ `7a5e70f4809dd4bae29cfb772042d12784fc48b6`, verificado em 2026-09-06.

- **Origem rastreada:** O carregamento condicionado ao token vem de `dbf7a7a` (2026-08-31). O uso de `TRACK_BRANCH` com default develop foi introduzido em `718df00` (2026-09-04), formando o cenário reproduzido.
- **Auditoria anterior:** `AUD-20`; restaurado com o ID `BUG-0018` na sequência dos registros atuais.

## Evidências

- Script de staging real executado em diretório temporário com curl/docker substituídos por comandos controlados e token predefinido.
- Verificação executada em 2026-09-06 sobre o commit da release indicado em Ambiente, com assertions dos resultados.
- Dados desta execução registrados no bloco JSON acima.
