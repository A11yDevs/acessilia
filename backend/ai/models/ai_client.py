from backend.config.settings import settings




def get_agno_model(
    *,
    max_tokens: int | None = None,
    timeout_seconds: int | None = None,
    max_retries: int | None = None,
):
    """Build the Agno model instance that matches the active settings configuration.

    The provider is chosen by ``settings.ai_client``: the value ``"openrouter"`` selects
    the OpenRouter hosted-API client, and any other value selects the local Ollama client, so the
    returned model is always the one the rest of the runtime expects for the configured backend.

    Args:
        max_tokens (int | None): Output token cap for this client; when None, ``OPENROUTER_MAX_TOKENS`` applies (``num_predict`` for Ollama).
        timeout_seconds (int | None): Per-call HTTP timeout for this client; when None, ``MODEL_CALL_TIMEOUT_SECONDS`` applies. Callers whose answers can legitimately run long (the DataAgent transcribing tables on a local Ollama) pass their own, larger budget explicitly.
        max_retries (int | None): HTTP-level retries the provider SDK may run on its own; when None, the SDK default applies. A caller that owns its retry policy passes ``0`` so one call is one attempt: the OpenAI SDK's default of 2 retries applies the full timeout again on every try and re-sends the whole image, which can triple the wait a caller already bounds.

    Returns:
        Any: The configured Agno client instance; an ``OpenRouter`` model when
        ``settings.ai_client == "openrouter"`` or an ``Ollama`` model otherwise, ready to be passed to an Agno agent.
    """
    timeout = (
        timeout_seconds
        if timeout_seconds is not None
        else settings.model_call_timeout_seconds
    )
    if settings.ai_client == "openrouter":
        from agno.models.openrouter import OpenRouter

        base_url = settings.openrouter_base_url.replace("/chat/completions", "").rstrip("/")
        extra_headers = {}
        if settings.openrouter_site_url:
            extra_headers["HTTP-Referer"] = settings.openrouter_site_url
        if settings.openrouter_app_name:
            extra_headers["X-Title"] = settings.openrouter_app_name

        return OpenRouter(
            id=settings.openrouter_model,
            api_key=settings.openrouter_api_key,
            base_url=base_url,
            max_tokens=(
                max_tokens
                if max_tokens is not None
                else settings.openrouter_max_tokens
            ),
            extra_headers=extra_headers if extra_headers else None,
            timeout=float(timeout),
            max_retries=max_retries,
        )
    else:
        from agno.models.ollama import Ollama

        host = settings.ollama_base_url.replace("/api/chat", "").rstrip("/")
        options = {
            "temperature": 1.0,
            "top_p": 0.95,
            "top_k": 64,
            "seed": 42,
        }
        if max_tokens is not None:
            options["num_predict"] = max_tokens

        return Ollama(
            id=settings.ollama_model,
            host=host,
            options=options,
            api_key=settings.ollama_api_key or "not-needed",
            timeout=float(timeout),
        )
