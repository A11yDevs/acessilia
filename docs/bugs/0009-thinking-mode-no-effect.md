# 🐛 Thinking mode é uma opção sem efeito no legacy

## Identificação

| Campo | Valor |
|---|---|
| **ID** | BUG-0009 |
| **Data** | 2026-09-05 |
| **Reportado por** | Wryel Teodoro |
| **Severidade** | 🟡 Média |
| **Status** | Corrigido localmente · aguardando integração |

## Ambiente

| Item | Valor |
|---|---|
| SO | Linux |
| Python | 3.12.3 (revalidação isolada) |
| Branch / commit | [release/0.1.0](https://github.com/A11yDevs/acessilia/tree/release/0.1.0) @ `7a5e70f4809dd4bae29cfb772042d12784fc48b6` |
| Motor (`PIPELINE_ENGINE`) | `legacy`; orquestrador real com `thinking_mode=false` e `true` |
| Estruturador (`STRUCTURER`) | `pymupdf` configurado; leitor simulado para isolar a propagação da opção |
| IA (`AI_CLIENT` + modelo) | `ollama` configurado; argumentos de despacho capturados sem executar modelo. O defeito é a opção não ser propagada |
| Interface | Painel avançado / motor legacy |

## Resumo

Thinking mode é uma opção sem efeito no legacy. Painel aceita preferência que não altera execução. O motor PDDL também declara ignorar prompt/thinking em log, mas não foi contado separadamente.

## Entrada usada (qual arquivo/imagem)

- **Entrada:** Arquivo sintético; thinking desligado e ligado.
- **Observação:** cenário reproduzido com dados sintéticos; não depende de dados de usuários.

## Passos para reproduzir

1. Usar `release/0.1.0` no commit indicado em Ambiente, com as dependências instaladas.
2. Executar o mesmo fluxo sem cache com thinking desligado e ligado.

## Resultado esperado

A opção anunciada produzir a configuração correspondente ou ser recusada como indisponível.

## Resultado obtido

Argumentos de `_dispatch_tasks` idênticos.

```json
{
  "id": "BUG-0009",
  "identical_arguments_with_thinking_on_and_off": true
}
```

## Causa raiz (se identificada)

A prova compara os argumentos despachados pelo código, sem avaliar inteligência, qualidade ou comportamento da resposta de um modelo.

[orchestrator.py](../../backend/agents/orchestrator.py), linhas 39–45, calcula `system_prompt` e acrescenta `<|think|>`, mas essa variável não é usada no despacho para os agentes. O booleano também não é repassado.

## Correção sugerida (se houver)

Propagar a opção até a chamada do modelo e esclarecer capacidades por motor na interface.

## Correção aplicada

No motor legacy, o prompt com o marcador `<|think|>` agora é repassado ao
despacho quando `thinking_mode` está ativo. Com a opção desligada, o fluxo
anterior de prompts permanece inalterado. Uma regressão compara os argumentos
despachados nos dois modos.

## Rastreabilidade

- **Revalidação:** permanece em `release/0.1.0` @ `7a5e70f4809dd4bae29cfb772042d12784fc48b6`, verificado em 2026-09-06.

- **Introdução rastreada:** `fbdaa45` (2026-07-14), refatoração Agno; a opção criada em `fa432f1` funcionava antes, mas o novo orquestrador passou a despachar `custom_prompt` em vez do `system_prompt` calculado.
- A reprodução compara o prompt efetivamente despachado com a opção desligada e ligada e não observa diferença.

## Evidências

- Orquestrador legacy real com cache desabilitado e leitor/despacho simulados; comparação dos argumentos com thinking desligado e ligado.
- Verificação executada em 2026-09-06 sobre o commit da release indicado em Ambiente, com assertions dos resultados.
- Dados desta execução registrados no bloco JSON acima.
