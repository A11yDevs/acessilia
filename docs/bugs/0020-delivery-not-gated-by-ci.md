# 🐛 Publicação não aguarda os testes de CI

## Identificação

| Campo | Valor |
|---|---|
| **ID** | BUG-0020 |
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
| Motor (`PIPELINE_ENGINE`) | Não aplicável; dependência entre workflows de CI e publicação |
| Estruturador (`STRUCTURER`) | Não aplicável ao encadeamento dos workflows |
| IA (`AI_CLIENT` + modelo) | Não aplicável; a verificação trata das condições de publicação |
| Interface | CI/CD GitHub Actions |

## Resumo

O workflow de publicação inicia por push, independentemente do resultado da suíte de CI para o mesmo SHA.

## Entrada usada (qual arquivo/imagem)

- **Entrada:** `.github/workflows/ci.yml` e `delivery.yml` da revisão atual; análise estática, sem disparar publicação.
- **Observação:** verificação de configuração, sem build ou deployment real.

## Passos para reproduzir

1. Comparar os eventos de CI e Delivery para as mesmas branches.
2. Verificar que Delivery inicia em `push` e não depende da conclusão do workflow CI.
3. Conferir que os smoke tests de Delivery não executam a suíte completa nem consultam seu resultado.

## Resultado esperado

Publicar ou promover o SHA somente após os checks exigidos serem aprovados.

## Resultado obtido

Delivery possui smoke tests próprios, mas não tem dependência do resultado do CI; um commit que passe esses smoke tests pode ser publicado mesmo se reprovar a suíte.

```json
{
  "id": "BUG-0020",
  "verification": "static",
  "trigger": "push",
  "ci_dependency": false,
  "smoke_tests": true
}
```

## Causa raiz (se identificada)

[.github/workflows/delivery.yml](../../.github/workflows/delivery.yml), linhas 3–9, usa o evento `push`. Não há dependência entre os workflows nem consulta ao resultado da suíte. Proteções de PR não constituem uma dependência de execução do Delivery para todo push.

## Correção sugerida (se houver)

Condicionar a publicação ao CI aprovado, validando o sucesso e o SHA testado, por workflow reutilizável ou evento de conclusão.

## Rastreabilidade

- **Revalidação:** permanece em `release/0.1.0` @ `7a5e70f4809dd4bae29cfb772042d12784fc48b6`, verificado em 2026-09-06.

- **Origem rastreada:** O trigger foi alterado de `workflow_run` para `push` em `f8e99b4` (2026-08-30). A configuração atual mantém essa independência.
- **Auditoria anterior:** `AUD-22`; restaurado com o ID `BUG-0020` na sequência dos registros atuais.

## Evidências

- Inspeção e assertions sobre o workflow Delivery; publicação real não foi executada.
- Verificação executada em 2026-09-06 sobre o commit da release indicado em Ambiente, com assertions dos resultados.
- Dados desta execução registrados no bloco JSON acima.
