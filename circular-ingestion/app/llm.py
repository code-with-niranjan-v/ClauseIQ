from app.config import Settings


class ConfigurationError(RuntimeError):
    """The worker cannot start with the current settings."""


def require_key(settings: Settings) -> str:
    if not settings.openai_api_key:
        raise ConfigurationError("OPENAI_API_KEY is not set. It is required for extraction, gap analysis and embeddings.")
    return settings.openai_api_key


def build_chat_model(settings: Settings):
    from langchain_openai import ChatOpenAI

    options: dict = {"model": settings.llm_model, "api_key": require_key(settings),
                     "temperature": settings.llm_temperature, "timeout": 120, "max_retries": 2}
    if settings.llm_base_url:
        options["base_url"] = settings.llm_base_url
    return ChatOpenAI(**options)
