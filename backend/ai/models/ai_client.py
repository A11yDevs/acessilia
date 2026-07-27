from backend.config.settings import settings




def get_agno_model():
    """Retorna a instância de modelo do Agno correspondente às configurações."""
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
            extra_headers=extra_headers if extra_headers else None,
            timeout=float(settings.request_timeout),
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

        return Ollama(
            id=settings.ollama_model,
            host=host,
            options=options,
            api_key=settings.ollama_api_key or "not-needed",
            timeout=float(settings.request_timeout),
        )
