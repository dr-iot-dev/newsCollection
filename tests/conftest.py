import os
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from app.infrastructure.db.models import Base
from app.sources.config import load_sources
from app.sources.service import sync_sources


@pytest.fixture(params=["sqlite", "postgresql"])
def acquisition_engine(request: pytest.FixtureRequest, tmp_path: Path) -> Generator[Engine]:
    if request.param == "sqlite":
        engine = create_engine(f"sqlite:///{tmp_path}/acquisition.db")
        Base.metadata.create_all(engine)
        yield engine
        engine.dispose()
        return
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration tests")
    schema = "test_acquisition_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        Base.metadata.create_all(engine)
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture
def acquisition_session(acquisition_engine: Engine) -> Generator[Session]:
    with Session(acquisition_engine, expire_on_commit=False) as session:
        config = load_sources(Path("config/sources.example.yaml"))
        for source in config.sources:
            source.legal.terms_reviewed_at = datetime.now(UTC)
        sync_sources(session, config, dry_run=False)
        session.commit()
        yield session
