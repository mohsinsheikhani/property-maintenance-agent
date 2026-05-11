from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str
    openai_api_key: str = ""

    gmail_pubsub_verification_token: str = ""
    gmail_oauth_client_id: str = ""
    gmail_oauth_client_secret: str = ""

    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    app_env: str = "dev"


settings = Settings()
