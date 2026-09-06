# 🐛 Compose local constrói o estágio test

## Identificação

| Campo | Valor |
|---|---|
| **ID** | BUG-0017 |
| **Data** | 2026-09-06 |
| **Reportado por** | Wryel Teodoro |
| **Severidade** | 🟠 Alta |
| **Status** | Aberto · confirmado por configuração |

## Ambiente

| Item | Valor |
|---|---|
| SO | Linux |
| Python | Não aplicável à configuração |
| Branch / commit | [release/0.1.0](https://github.com/A11yDevs/acessilia/tree/release/0.1.0) @ `7a5e70f4809dd4bae29cfb772042d12784fc48b6` |
| Motor (`PIPELINE_ENGINE`) | Não aplicável; seleção do estágio de build no Compose |
| Estruturador (`STRUCTURER`) | Não aplicável à seleção do estágio de build |
| IA (`AI_CLIENT` + modelo) | Não aplicável; configuração Docker inspecionada sem inferência |
| Interface | Docker Compose local |

## Resumo

O build padrão do Compose seleciona o estágio final de testes, cujo comando executa pytest em vez de iniciar o servidor.

## Entrada usada (qual arquivo/imagem)

- **Entrada:** `docker-compose.yml` e `infra/Dockerfile` da branch atual; verificação estática, sem reconstrução de imagem.
- **Observação:** verificação de configuração, sem build ou deployment real.

## Passos para reproduzir

1. Verificar que `docker-compose.yml` não define `build.target` nem substitui `command`.
2. Inspecionar o último estágio de `infra/Dockerfile`: `FROM base AS test`, com `CMD ["pytest", "tests/", "-v"]`.
3. Para validação operacional adicional, construir uma imagem isolada pelo Compose e inspecionar seu `Config.Cmd`; esse build não foi realizado nesta revisão.

## Resultado esperado

O Compose destinado à aplicação deve selecionar o estágio de runtime e iniciar o servidor.

## Resultado obtido

A configuração seleciona o estágio final `test` com comando pytest.

```json
{
  "id": "BUG-0017",
  "verification": "static",
  "build_target": null,
  "final_stage": "test",
  "command": [
    "pytest",
    "tests/",
    "-v"
  ]
}
```

## Causa raiz (se identificada)

O [Dockerfile](../../infra/Dockerfile) termina com o estágio `test`, enquanto [docker-compose.yml](../../docker-compose.yml) deixa o alvo do build implícito. Os workflows Delivery/Release especificam `target: base`; o defeito está no build local do Compose.

## Correção sugerida (se houver)

Definir `build.target: base` no Compose ou deixar um estágio de runtime como estágio final.

## Rastreabilidade

- **Revalidação:** permanece em `release/0.1.0` @ `7a5e70f4809dd4bae29cfb772042d12784fc48b6`, verificado em 2026-09-06.

- **Origem rastreada:** O estágio final `test` foi acrescentado em `5eca119` (2026-08-05). O Compose atual continua sem alvo explícito.
- **Auditoria anterior:** `AUD-19`; restaurado com o ID `BUG-0017` na sequência dos registros atuais.

## Evidências

- Inspeção e assertions sobre Compose e Dockerfile; nenhum build de imagem foi executado.
- Verificação executada em 2026-09-06 sobre o commit da release indicado em Ambiente, com assertions dos resultados.
- Dados desta execução registrados no bloco JSON acima.
