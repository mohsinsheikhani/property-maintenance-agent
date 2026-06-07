from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str
    openai_api_key: str = ""

    # Model + gateway for the cost/latency bake-off. `eval_model` is the LiteLLM
    # alias (gpt-4o-mini | gemini-flash | kimi-k2). When `llm_base_url` is set the
    # nodes talk to the LiteLLM proxy; left empty, they hit OpenAI directly so the
    # default dev path is unchanged.
    eval_model: str = "gpt-4o-mini"
    llm_base_url: str = ""
    llm_api_key: str = ""

    gmail_pubsub_verification_token: str = ""
    gmail_oauth_client_id: str = ""
    gmail_oauth_client_secret: str = ""

    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    app_env: str = "dev"


settings = Settings()
