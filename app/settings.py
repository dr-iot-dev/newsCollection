"""Explicit run configuration; secrets are never persisted with a run."""

import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    embedding_model: str = "text-embedding-3-small"
    generation_model: str = "gpt-4.1-mini-2025-04-14"
    verification_model: str = "gpt-4.1-2025-04-14"
    n_components: int = 15
    n_neighbors: int = 15
    min_cluster_size: int = 5
    min_samples: int = 5

    def validate(self) -> None:
        if self.generation_model == self.verification_model:
            raise ValueError("generation and verification must use different models")
        if self.n_components < 2 or self.n_neighbors < 2:
            raise ValueError("invalid UMAP parameters")
        if self.min_cluster_size < 2 or self.min_samples < 1:
            raise ValueError("invalid HDBSCAN parameters")

    def record(self) -> dict:
        self.validate()
        return asdict(self)


def database_url() -> str:
    # The connection is explicitly scoped to this pipeline.
    return os.getenv("PIPELINE_DATABASE_URL", "sqlite:///newsweave.sqlite")


def prompt_dir() -> Path:
    return Path(__file__).with_name("prompts")
