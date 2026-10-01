from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, PostgresDsn, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "AI/IoT News Collection"
    app_env: Literal["development", "test", "staging", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_url: PostgresDsn = Field(
        default=PostgresDsn("postgresql+psycopg://news:news@localhost:5432/news")
    )
    sources_config_path: Path = Path("config/sources.yaml")
    ready_check_database: bool = True
    ai_provider: Literal["disabled", "openai"] = "disabled"
    ai_api_key: SecretStr | None = Field(default=None, repr=False)
    ai_model_facts: str = ""
    ai_selector_model: str = ""
    ai_writer_model: str = ""
    ai_verifier_model: str = ""
    ai_require_distinct_models: bool = True
    ai_max_input_chars: int = Field(default=50000, ge=1000, le=200000)
    ai_max_output_tokens: int = Field(default=4000, ge=100, le=16000)
    ai_input_cost_per_million: float | None = Field(default=None, ge=0)
    ai_output_cost_per_million: float | None = Field(default=None, ge=0)
    review_require_four_eyes: bool = True

    @model_validator(mode="after")
    def validate_ai(self) -> "Settings":
        if (
            self.ai_require_distinct_models
            and self.ai_writer_model
            and self.ai_writer_model == self.ai_verifier_model
        ):
            raise ValueError("Writer and Verifier models must be distinct")
        if self.ai_provider == "openai" and not self.ai_api_key:
            raise ValueError("AI_API_KEY is required for the configured provider")
        return self

    github_token: SecretStr | None = Field(default=None, repr=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
