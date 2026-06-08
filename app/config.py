from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    app_secret_key: str = "change-me"

    redis_url: str = "redis://localhost:6379/0"

    # Optional — only required when the report worker runs
    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"

    # Ollama fallback — set USE_OLLAMA=true to bypass Groq entirely
    use_ollama: bool = False
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"

    # Optional — only required when google_places worker runs
    serpapi_key: str | None = None

    instagram_username: str = ""
    instagram_password: str = ""

    # Optional — only required when supabase_client is used
    supabase_url: str | None = None
    supabase_service_key: str | None = None

    # Optional — n8n webhook for campaign package generation
    # If not set, campaign_package_builder falls back to direct Groq call
    n8n_webhook_url: str | None = None

    @property
    def celery_broker_url(self) -> str:
        return self.redis_url

    @property
    def celery_result_backend(self) -> str:
        return self.redis_url


settings = Settings()
