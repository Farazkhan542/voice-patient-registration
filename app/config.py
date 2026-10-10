"""Environment-driven settings. Nothing secret lives in source control."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1"
GEMINI_OPENAI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/openai/"


def _llm_settings() -> tuple[str, str, list[str]]:
    """(api_key, base_url, models). OpenRouter wins if its key is set, else Gemini direct.
    Both are OpenAI-compatible, so LLM_BASE_URL / LLM_MODEL can point anywhere else too.

    `models` is tried in order: the first is the primary, the rest are fallbacks used
    when a model is rate-limited or failing. Gemini's free tier has a separate
    per-minute quota for each model, so the fallbacks add real headroom there."""
    if os.getenv("OPENROUTER_API_KEY"):
        key, base_url = os.environ["OPENROUTER_API_KEY"], OPENROUTER_ENDPOINT
        model, fallbacks = "google/gemini-2.5-flash", ""
    else:
        key, base_url = os.getenv("GEMINI_API_KEY", ""), GEMINI_OPENAI_ENDPOINT
        model, fallbacks = "gemini-3.5-flash-lite", "gemini-3.1-flash-lite,gemini-2.5-flash-lite"
    model = os.getenv("LLM_MODEL") or model
    fallbacks = os.getenv("LLM_FALLBACK_MODELS", fallbacks)
    models = [model] + [m.strip() for m in fallbacks.split(",") if m.strip() and m.strip() != model]
    return key, os.getenv("LLM_BASE_URL") or base_url, models


def _database_url() -> str:
    url = os.getenv("DATABASE_URL", "sqlite:///./data/patients.db")
    # Railway/Heroku hand out postgres:// URLs; SQLAlchemy needs an explicit driver.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


@dataclass(frozen=True)
class Settings:
    database_url: str
    seed_data: bool
    llm_api_key: str
    llm_base_url: str
    llm_model: str
    llm_fallback_models: tuple[str, ...]
    public_base_url: str
    vapi_api_key: str
    vapi_webhook_secret: str
    vapi_assistant_id: str
    vapi_phone_number_id: str
    vapi_voice_provider: str
    vapi_voice_id: str
    vapi_transcriber_language: str


def load_settings() -> Settings:
    llm_api_key, llm_base_url, llm_models = _llm_settings()
    return Settings(
        database_url=_database_url(),
        seed_data=os.getenv("SEED_DATA", "true").lower() == "true",
        llm_api_key=llm_api_key,
        llm_base_url=llm_base_url,
        llm_model=llm_models[0],
        llm_fallback_models=tuple(llm_models[1:]),
        public_base_url=os.getenv("PUBLIC_BASE_URL", "").rstrip("/"),
        vapi_api_key=os.getenv("VAPI_API_KEY", ""),
        vapi_webhook_secret=os.getenv("VAPI_WEBHOOK_SECRET", ""),
        vapi_assistant_id=os.getenv("VAPI_ASSISTANT_ID", ""),
        vapi_phone_number_id=os.getenv("VAPI_PHONE_NUMBER_ID", ""),
        vapi_voice_provider=os.getenv("VAPI_VOICE_PROVIDER", ""),
        vapi_voice_id=os.getenv("VAPI_VOICE_ID", ""),
        vapi_transcriber_language=os.getenv("VAPI_TRANSCRIBER_LANGUAGE", "en"),
    )


settings = load_settings()
