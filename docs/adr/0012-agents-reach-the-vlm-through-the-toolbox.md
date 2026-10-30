# 0012. The agents can reach their vision model through the Toolbox VLM gateway

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](0012-agents-reach-the-vlm-through-the-toolbox.pt-br.md)

- **Status:** Accepted
- **Date:** 2026-10-29
- **Components:** core, SDK, Toolbox
- **Issues:** [#331](https://github.com/A11yDevs/acessilia/pull/331), [acessilia-toolbox#113](https://github.com/A11yDevs/acessilia-toolbox/pull/113), [acessilia-toolbox#112](https://github.com/A11yDevs/acessilia-toolbox/pull/112)

## Context

The core's agents (VisionAgent, DataAgent and the AgentOS agents) hold a chat with a vision model through an Agno model built by `get_agno_model()` (`backend/ai/models/ai_client.py`). Until now the model was either Ollama or an OpenAI-compatible server reached as OpenRouter, and the core held that server's address and key.

On staging, `OPENROUTER_BASE_URL` pointed straight at the llama-server that also serves the Toolbox's own VLM capabilities (`document.ocr.page`, `document.adjudicate.*`, `table.recognize`). The server has two parallel slots on a CPU-only host. The core's calls and the Toolbox's, each limited on its own side, together went over those slots and stalled the server.

Options considered:

1. **Limit the core's calls on its side too.** Two limiters that do not see each other still add up past the slots.
2. **Make each agent prompt a Toolbox capability.** The agents' prompts, schemas and retries are business logic owned by the core (ADR-0002), and a capability per prompt would freeze them in the Toolbox's contract.
3. **A gateway in the Toolbox** that relays OpenAI-compatible chats to one of its VLM providers, under that provider's concurrency limit (acessilia-toolbox#113).

## Decision

- **A new execution mode, `AI_CLIENT=toolbox`.** The agents send their chats to the Toolbox VLM gateway, `POST {base}/v1/vlm/chat/completions`, with the Toolbox's API key and the provider id as `model` (`TOOLBOX_VLM_PROVIDER`, default `qwen3-vl-8b`). The Toolbox relays each chat to that provider's server under the provider's limit, so its slots are shared by every VLM caller. The core must not hold the model server's address or key in this mode.
- **The gateway is a Toolbox route, not a capability.** The prompt, the schema and what to do with the answer stay in the core; the Toolbox only places the call and limits it. No capability, `ArtifactRef` or capability contract version is involved.
- **The SDK owns the routes.** `acessilia_sdk.toolbox.vlm` builds the gateway's base URL (`vlm_gateway_base_url`) and reads `GET {base}/v1/providers/{id}/health` (`vlm_provider_healthy`). The core does not build these URLs itself (ADR-0004).
- **The provider id is checked like the capability providers.** Its default lives in `ROUTE_PROVIDER_DEFAULTS` (`acessilia_sdk/toolbox/capabilities.py`), and `scripts/check_capability_contract.py` fails when the Toolbox does not register it.
- **One endpoint, no failover.** An Agno model takes one base URL, so the chats go to the first Toolbox endpoint (`TOOLBOX_BASE_URLS`, or `TOOLBOX_BASE_URL` without it). `/api/v1/health` probes that same endpoint, so `model_reachable` reports what the agents meet. Availability comes from the replicas behind it (ADR-0006).
- **No silent fallback.** If the gateway fails, the agent call fails as any model call does (timeout or HTTP error), and the region degrades the way it does today. The core does not retry against the model server directly.

## Consequences

- **The gateway's route is outside the published capability contract.** The contract check verifies the provider id but cannot see whether the Toolbox serves `/v1/vlm`; a Toolbox without acessilia-toolbox#113 answers 404 to every agent chat. The Toolbox must be deployed first, and `model_reachable` on `/api/v1/health` is the check after a deploy. Publishing the gateway in the Toolbox's contract would let CI catch it; that is follow-up work in the Toolbox.
- **`MODEL_CALL_TIMEOUT_SECONDS` also covers the wait for a slot.** A call queued in the Toolbox counts against the same timeout as the model's answer.
- **`OPENROUTER_MAX_TOKENS` is the output cap of the toolbox client too**, when the agent sets none. The other `OPENROUTER_*` and the `OLLAMA_*` variables are not read in this mode.
- **Cache keys carry the provider id, not the weights.** The vision region cache (`_region_cache_extra`) and the processing cache key on `TOOLBOX_VLM_PROVIDER`. The Toolbox names the served weights in the provider's `version`, which these keys do not see, so a model swap behind the same provider id must bump the region cache `version`. The processing cache has the same gap for every Toolbox provider it keys on; that gap is older than this mode. Changing `AI_CLIENT` changes both keys, so cached answers are recomputed once.
- **Compliance:** `tests/test_ai_client.py` (gateway URL, key, model, budget and timeout), `tests/test_api.py` (health through the Toolbox), `libs/sdk/tests/test_vlm.py`, `tests/test_toolbox_capability_registry.py` (the provider default) and the contract check in CI.
