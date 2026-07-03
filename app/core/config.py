from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Central app config, loaded from environment variables / .env.
    Never hardcode secrets here — everything comes from the environment.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    composio_api_key: str
    composio_webhook_secret: str
    openai_api_key: str
    openai_extraction_model: str = "gpt-5.5"
    supabase_url: str  # e.g. https://xxxxx.supabase.co — used to build the JWKS endpoint
    app_env: str = "development"


settings = Settings()
