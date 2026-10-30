# 0012. Os agentes podem chegar ao modelo de visão pelo gateway VLM da Toolbox

Você também pode ler esta documentação em **inglês**: [English](0012-agents-reach-the-vlm-through-the-toolbox.md)

- **Status:** Aceito
- **Data:** 2026-10-29
- **Componentes:** core, SDK, Toolbox
- **Issues:** [#331](https://github.com/A11yDevs/acessilia/pull/331), [acessilia-toolbox#113](https://github.com/A11yDevs/acessilia-toolbox/pull/113), [acessilia-toolbox#112](https://github.com/A11yDevs/acessilia-toolbox/pull/112)

## Contexto

Os agentes do core (VisionAgent, DataAgent e os agentes do AgentOS) conversam com um modelo de visão por um modelo Agno construído por `get_agno_model()` (`backend/ai/models/ai_client.py`). Até agora o modelo era o Ollama ou um servidor compatível com OpenAI acessado como OpenRouter, e o core guardava o endereço e a chave desse servidor.

Na homologação, `OPENROUTER_BASE_URL` apontava direto para o llama-server que também atende as capacidades VLM da própria Toolbox (`document.ocr.page`, `document.adjudicate.*`, `table.recognize`). O servidor tem duas vagas paralelas, num host só com CPU. As chamadas do core e as da Toolbox, cada uma limitada do seu lado, juntas passaram dessas vagas e travaram o servidor.

Opções consideradas:

1. **Limitar também as chamadas do core do lado dele.** Dois limitadores que não se enxergam continuam somando além das vagas.
2. **Transformar cada prompt de agente numa capacidade da Toolbox.** Os prompts, schemas e retentativas dos agentes são lógica de negócio do core (ADR-0002), e uma capacidade por prompt os congelaria no contrato da Toolbox.
3. **Um gateway na Toolbox** que repassa chats compatíveis com OpenAI para um dos seus providers VLM, sob o limite de concorrência desse provider (acessilia-toolbox#113).

## Decisão

- **Um novo modo de execução, `AI_CLIENT=toolbox`.** Os agentes enviam seus chats ao gateway VLM da Toolbox, `POST {base}/v1/vlm/chat/completions`, com a chave de API da Toolbox e o id do provider como `model` (`TOOLBOX_VLM_PROVIDER`, padrão `qwen3-vl-8b`). A Toolbox repassa cada chat ao servidor desse provider sob o limite do provider, de modo que as vagas são divididas entre todos os chamadores do VLM. Neste modo, o core não deve guardar o endereço nem a chave do servidor do modelo.
- **O gateway é uma rota da Toolbox, não uma capacidade.** O prompt, o schema e o que fazer com a resposta ficam no core; a Toolbox só faz a chamada e a limita. Não há capacidade, `ArtifactRef` nem versão de contrato de capacidade envolvidos.
- **O SDK é dono das rotas.** `acessilia_sdk.toolbox.vlm` monta a URL base do gateway (`vlm_gateway_base_url`) e lê `GET {base}/v1/providers/{id}/health` (`vlm_provider_healthy`). O core não monta essas URLs por conta própria (ADR-0004).
- **O id do provider é verificado como os providers das capacidades.** O padrão fica em `ROUTE_PROVIDER_DEFAULTS` (`acessilia_sdk/toolbox/capabilities.py`), e `scripts/check_capability_contract.py` falha quando a Toolbox não o registra.
- **Um endpoint, sem failover.** Um modelo Agno recebe uma única URL base, então os chats vão ao primeiro endpoint da Toolbox (`TOOLBOX_BASE_URLS`, ou `TOOLBOX_BASE_URL` na falta dele). `/api/v1/health` sonda esse mesmo endpoint, então `model_reachable` informa o que os agentes vão encontrar. A disponibilidade vem das réplicas atrás dele (ADR-0006).
- **Sem fallback silencioso.** Se o gateway falha, a chamada do agente falha como qualquer chamada ao modelo (timeout ou erro HTTP), e a região degrada como hoje. O core não tenta de novo direto no servidor do modelo.

## Consequências

- **A rota do gateway fica fora do contrato de capacidades publicado.** A verificação de contrato confere o id do provider, mas não vê se a Toolbox atende `/v1/vlm`; uma Toolbox sem acessilia-toolbox#113 responde 404 a todo chat de agente. A Toolbox precisa ser implantada antes, e `model_reachable` em `/api/v1/health` é a verificação depois da implantação. Publicar o gateway no contrato da Toolbox permitiria que a CI pegasse isso; é trabalho futuro na Toolbox.
- **`MODEL_CALL_TIMEOUT_SECONDS` também cobre a espera por uma vaga.** Uma chamada na fila da Toolbox conta no mesmo timeout que a resposta do modelo.
- **`OPENROUTER_MAX_TOKENS` é também o teto de saída do cliente toolbox**, quando o agente não define um. As demais variáveis `OPENROUTER_*` e as `OLLAMA_*` não são lidas neste modo.
- **As chaves de cache levam o id do provider, não os pesos.** O cache de regiões de visão (`_region_cache_extra`) e o cache de processamento usam `TOOLBOX_VLM_PROVIDER`. A Toolbox nomeia os pesos servidos na `version` do provider, que essas chaves não veem, então trocar o modelo por trás do mesmo id de provider exige incrementar a `version` do cache de regiões. O cache de processamento tem a mesma lacuna para todo provider da Toolbox em que se baseia; essa lacuna é anterior a este modo. Mudar `AI_CLIENT` muda as duas chaves, então as respostas em cache são recalculadas uma vez.
- **Conformidade:** `tests/test_ai_client.py` (URL do gateway, chave, modelo, orçamento e timeout), `tests/test_api.py` (health pela Toolbox), `libs/sdk/tests/test_vlm.py`, `tests/test_toolbox_capability_registry.py` (o padrão do provider) e a verificação de contrato na CI.
