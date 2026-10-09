from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

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

    app_name: str = "News Weave"
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
    comparison_auto_research: bool = True
    comparison_min_sources: int = Field(default=3, ge=1, le=21)
    research_refresh_sources: bool = True
    research_max_candidates: int = Field(default=100, ge=1, le=500)
    research_max_fact_checks: int = Field(default=6, ge=1, le=20)
    research_max_sources_per_attempt: int = Field(default=6, ge=1, le=20)
    research_max_attempts: int = Field(default=3, ge=1, le=5)
    research_retry_seconds: int = Field(default=60, ge=10, le=3600)
    review_require_four_eyes: bool = True
    review_required: bool = False
    featured_images_enabled: bool = True
    ai_image_model: str = "gpt-image-1.5"
    ai_image_quality: Literal["low", "medium", "high"] = "medium"
    ai_image_size: Literal["1536x1024", "1024x1024", "1024x1536"] = "1536x1024"
    wordpress_enabled: bool = False
    wordpress_base_url: str = ""
    wordpress_post_type: str = Field(default="post", pattern=r"^[a-z0-9_-]{1,20}$")
    wordpress_rest_base: str | None = Field(
        default=None, pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$"
    )
    wordpress_username: str = ""
    wordpress_application_password: SecretStr | None = Field(default=None, repr=False)
    wordpress_category_map: dict[str, Annotated[int, Field(ge=1, strict=True)]] = Field(
        default_factory=dict
    )
    wordpress_tag_map: dict[str, Annotated[int, Field(ge=1, strict=True)]] = Field(
        default_factory=dict
    )

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
