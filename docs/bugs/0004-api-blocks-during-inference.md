# 🐛 API fica sem responder durante a inferência (trabalho pesado no event loop)

## Identificação
| Campo | Valor |
|---|---|
| **ID** | BUG-0004 |
| **Data** | 2026-09-01 |
| **Reportado por** | Pedro Alano |
| **Severidade** | 🟡 Média (afeta responsividade/concorrência; relevante para a VPS) |
| **Status** | Aberto · a reportar como issue |
| **Link da issue** | <preencher ao abrir no GitHub> |

## Ambiente
| Item | Valor |
|---|---|
| SO | Windows 11 · Python 3.11 |
| Branch / commit | `main` @ `5c7cf41` |
| Motor / estruturador / IA | legacy / docling / ollama `llava:7b` (CPU) |
| Interface | API REST |

## Resumo
Enquanto um job é processado (inicialização do Docling + inferência de visão em CPU), a **API não responde** a outras requisições. Chamadas de status (`GET /api/v1/jobs/{id}`) dão **timeout** durante o processamento e só voltam entre etapas ou ao concluir. Indica que trabalho bloqueante roda no **event loop** do asyncio, congelando o servidor.

## Passos para reproduzir
1. `POST /api/v1/jobs` com uma imagem.
2. Imediatamente, em paralelo, fazer `GET /api/v1/jobs/{task_id}` a cada 2s (timeout curto).
3. Durante a inferência, os GETs **estouram** (timeout); o servidor só responde quando a etapa pesada termina.

## Resultado esperado
A API responde ao status (progresso) de forma fluida enquanto o job processa.

## Resultado obtido
Durante ~22s (init do Docling) + ~56s (inferência de visão) o status ficou **sem resposta**. Foi o que **quebrou a 1ª versão** do script de teste automatizado (timeout de 10s no polling). Solução no teste: passar a monitorar o resultado **pelo disco**, o que contornou o bloqueio.

## Causa raiz (provável)
Trabalho **bloqueante** executado sem ser transferido para thread/processo:
- Inicialização/uso do Docling (CPU) no caminho de processamento.
- Chamada de visão (`VisionAgent.describe_region`) despachada via `asyncio.create_task`, mas internamente **síncrona/bloqueante** → não cede o event loop.

## Correção sugerida
- Transferir o trabalho pesado para fora do event loop (`asyncio.to_thread` / `run_in_executor`) ou um worker/processo separado.
- Garantir que as chamadas ao modelo de IA sejam realmente assíncronas (não bloqueantes).

## Impacto em testes / regressão
- **Relevante para a VPS3:** com múltiplos jobs/usuários, um job em CPU **congela a API** para todos, e o acompanhamento de progresso fica prejudicado.
- **Sugestão para o CI/CD:** teste que dispara um job e afere que `GET /health` e `GET /jobs/{id}` respondem dentro de um limite (ex.: < 2s) **durante** o processamento.

## Evidências
- 1º run do `e2e_cache_test.py`: `httpx.ReadTimeout` no `GET /api/v1/jobs/{id}` durante a inferência.
- Log do servidor: grandes intervalos sem responder entre o início da tarefa de visão e a consolidação.
