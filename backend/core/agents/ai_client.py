from backend.core.config import ModelConfig, ToolboxConfig




def get_agno_model(
    models: ModelConfig,
    toolbox: ToolboxConfig,
    *,
    max_tokens: int | None = None,
    timeout_seconds: int | None = None,
    max_retries: int | None = None,
    reasoning_enabled: bool | None = None,
):
    """Build the Agno model instance of the run's ``models`` (ADR-0016, step 3).

    The provider is chosen by ``models.ai_client``: the value ``"toolbox"`` sends the chats
    to the Toolbox VLM gateway, which relays them to its VLM provider under the provider's
    concurrency limit; ``"openrouter"`` selects the OpenRouter hosted-API client, and any other
    value selects the local Ollama client, so the returned model is always the one the rest of
    the runtime expects for the configured backend.

    Args:
        models (ModelConfig): The run's model configuration: the client, its endpoint, model and keys, and the default budgets.
        toolbox (ToolboxConfig): The run's Toolbox, whose first endpoint and key carry the chats with ``ai_client == "toolbox"``.
        max_tokens (int | None): Output token cap for this client; when None, ``OPENROUTER_MAX_TOKENS`` applies to the OpenRouter and Toolbox clients alike (``num_predict`` for Ollama).
        timeout_seconds (int | None): Per-call HTTP timeout for this client; when None, ``MODEL_CALL_TIMEOUT_SECONDS`` applies. Callers whose answers can legitimately run long (the DataAgent transcribing tables on a local Ollama) pass their own, larger budget explicitly.
        max_retries (int | None): HTTP-level retries the provider SDK may run on its own; when None, the SDK default applies (Agno drops ``None`` client params before building the SDK client). A caller that owns its retry policy passes ``0`` so one call is one attempt: the OpenAI SDK's default of 2 retries applies the full timeout again on every try and re-sends the whole image, which can triple the wait a caller already bounds.
        reasoning_enabled (bool | None): Explicit thinking policy for a bounded recovery request; None leaves the provider default unchanged. OpenRouter and Ollama receive it; the Toolbox client does not, since the gateway relays the body to a model server with no portable thinking switch, so there only the token cap applies.

    Returns:
        Any: The configured Agno client instance; an ``OpenAILike`` model aimed at the Toolbox
        when ``models.ai_client == "toolbox"``, an ``OpenRouter`` model when
        ``models.ai_client == "openrouter"`` or an ``Ollama`` model otherwise, ready to be passed to an Agno agent.
    """
    timeout = (
        timeout_seconds
        if timeout_seconds is not None
        else models.model_call_timeout_seconds
    )
    if models.ai_client == "toolbox":
        from agno.models.openai.like import OpenAILike

        from acessilia_sdk.toolbox import vlm_gateway_base_url
        from backend.core.toolbox.toolbox_client import toolbox_vlm_endpoint

        # The model id is the Toolbox provider id and the key the Toolbox's own:
        # the VLM server's key stays with the Toolbox. The timeout also covers
        # the wait for one of the provider's slots.
        endpoint = toolbox_vlm_endpoint(toolbox)
        return OpenAILike(
            id=models.toolbox_vlm_provider,
            api_key=endpoint.api_key or toolbox.api_key or "not-needed",
            base_url=vlm_gateway_base_url(endpoint),
            max_tokens=(
                max_tokens
                if max_tokens is not None
                else models.openrouter_max_tokens
            ),
            timeout=float(timeout),
            max_retries=max_retries,
        )
    if models.ai_client == "openrouter":
        from agno.models.openrouter import OpenRouter

        base_url = models.openrouter_base_url.replace("/chat/completions", "").rstrip("/")
        extra_headers = {}
        if models.openrouter_site_url:
            extra_headers["HTTP-Referer"] = models.openrouter_site_url
        if models.openrouter_app_name:
            extra_headers["X-Title"] = models.openrouter_app_name

        reasoning_options = (
            {"extra_body": {"reasoning": {"enabled": reasoning_enabled}}}
            if reasoning_enabled is not None else {}
        )
        return OpenRouter(
            id=models.openrouter_model,
            api_key=models.openrouter_api_key,
            base_url=base_url,
            max_tokens=(
                max_tokens
                if max_tokens is not None
                else models.openrouter_max_tokens
            ),
            extra_headers=extra_headers if extra_headers else None,
            timeout=float(timeout),
            max_retries=max_retries,
            **reasoning_options,
        )
    else:
        from agno.models.ollama import Ollama

        host = models.ollama_base_url.replace("/api/chat", "").rstrip("/")
        options = {
            "temperature": 1.0,
            "top_p": 0.95,
            "top_k": 64,
            "seed": 42,
        }
        if max_tokens is not None:
            options["num_predict"] = max_tokens

        reasoning_options = (
            {"request_params": {"think": reasoning_enabled}}
            if reasoning_enabled is not None else {}
        )
        return Ollama(
            id=models.ollama_model,
            host=host,
            options=options,
            api_key=models.ollama_api_key or "not-needed",
            timeout=float(timeout),
            **reasoning_options,
        )


def active_model_name(models: ModelConfig) -> str:
    """Model id the active client asks for, as cache keys and the health route report it."""
    if models.ai_client == "toolbox":
        return models.toolbox_vlm_provider
    if models.ai_client == "openrouter":
        return models.openrouter_model
    return models.ollama_model
