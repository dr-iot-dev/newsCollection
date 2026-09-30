from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    app_name: str = "AI/IoT News Collection"
    app_env: Literal["development", "test", "staging", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_url: PostgresDsn = Field(
        default=PostgresDsn("postgresql+psycopg://news:news@localhost:5432/news")
    )
    sources_config_path: Path = Path("config/sources.yaml")
    ready_check_database: bool = True
    github_token: SecretStr | None = Field(default=None, repr=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
