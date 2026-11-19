from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_ENV, extra="ignore")

    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    openrouter_api_key: str = ""
    openrouter_model: str = "openrouter/free"
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "qwen3:8b"
    provider_order: str = "groq,openrouter,ollama"
    database_url: str = "postgresql+psycopg://devpilot:devpilot@localhost:5432/devpilot"
    github_token: str = ""


settings = Settings()