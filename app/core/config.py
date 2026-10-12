import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, PostgresDsn, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def default_artifact_directory() -> Path:
    if os.name == "nt":
        return Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "NewsWeave" / "artifacts"
    return Path.home() / ".local" / "share" / "NewsWeave" / "artifacts"


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
    ai_discovery_vocabulary_model: str = ""
    ai_discovery_vocabulary_max_input_chars: int = Field(default=200000, ge=1000, le=200000)
    ai_discovery_vocabulary_max_output_tokens: int = Field(default=16000, ge=100, le=16000)
    ai_model_facts: str = ""
    ai_selector_model: str = ""
    ai_writer_model: str = ""
    ai_verifier_model: str = ""
    ai_require_distinct_models: bool = True
    ai_max_input_chars: int = Field(default=50000, ge=1000, le=200000)
    ai_max_output_tokens: int = Field(default=4000, ge=100, le=16000)
    ai_pair_keyword_max_input_chars: int = Field(default=200000, ge=1000, le=200000)
    ai_pair_keyword_max_output_tokens: int = Field(default=16000, ge=100, le=16000)
    ai_input_cost_per_million: float | None = Field(default=None, ge=0)
    ai_output_cost_per_million: float | None = Field(default=None, ge=0)
    # Explicit shadow evaluation does not participate in article publication.
    comparison_selection_mode: Literal["legacy", "shadow"] = "legacy"
    ai_comparison_planner_model: str = ""
    ai_comparison_assessor_model: str = ""
    ai_comparison_verifier_model: str = ""
    ai_embedding_model: str = ""
    ai_embedding_revision: str = "v1"
    comparison_min_products: int = Field(default=3, ge=2, le=9)
    comparison_max_evaluations: int = Field(default=8, ge=1, le=20)
    comparison_auto_research: bool = True
    comparison_min_sources: int = Field(default=3, ge=1, le=21)
    fetch_missing_sources: bool = False
    # Deprecated input: retained for migration; it cannot enable collection.
    research_refresh_sources: bool = False
    research_max_candidates: int = Field(default=100, ge=1, le=500)
    research_max_fact_checks: int = Field(default=6, ge=1, le=20)
    research_max_sources_per_attempt: int = Field(default=6, ge=1, le=20)
    research_max_attempts: int = Field(default=3, ge=1, le=5)
    research_retry_seconds: int = Field(default=60, ge=10, le=3600)
    review_require_four_eyes: bool = True
    review_required: bool = False
    featured_images_enabled: bool = True
    ai_image_model: str = "gpt-image-1.5"
    ai_image_max_attempts: int = Field(default=2, ge=1, le=10)
    ai_image_quality: Literal["low", "medium", "high"] = "medium"
    ai_image_size: Literal["1536x1024", "1024x1024", "1024x1536"] = "1536x1024"
    draft_export_enabled: bool = True
    draft_artifact_dir: Path = Field(default_factory=default_artifact_directory)
    draft_transfer_dir: Path | None = None
    draft_producer_id: str = ""

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
