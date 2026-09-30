import httpx
import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from typer.testing import CliRunner

from app import cli
from app.infrastructure.db.models import Item, JobRun, RawSnapshot
from app.jobs import scheduler
from app.modules.acquisition.service import collect_source
from tests.unit.test_acquisition_service import RSS, factory, release


@pytest.fixture
def collection_cli(
    acquisition_session: Session,
    acquisition_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> CliRunner:
    sessions = sessionmaker(bind=acquisition_engine)
    monkeypatch.setattr(cli, "SessionLocal", sessions)

    def collect(session: Session, key: str, **options: object):
        return collect_source(
            session,
            key,
            http_factory=factory(
                lambda _: httpx.Response(
                    200,
                    content=RSS,
                    headers={"Content-Type": "application/rss+xml"},
                )
            ),
            **options,
        )

    monkeypatch.setattr(cli, "collect_source", collect)
    return CliRunner()


def test_cli_dry_run_and_manual_collection(
    collection_cli: CliRunner,
    acquisition_session: Session,
) -> None:
    arguments = ["collect", "run", "--source", "vendor-official-feed", "--force"]
    preview = collection_cli.invoke(cli.app, [*arguments, "--dry-run"])
    assert preview.exit_code == 0, preview.output
    assert "created=1" in preview.output and "database unchanged" in preview.output
    assert acquisition_session.scalar(select(func.count()).select_from(Item)) == 0
    assert acquisition_session.scalar(select(func.count()).select_from(RawSnapshot)) == 0
    assert acquisition_session.scalar(select(func.count()).select_from(JobRun)) == 0
    first = collection_cli.invoke(cli.app, arguments)
    assert first.exit_code == 0, first.output
    assert "created=1" in first.output
    second = collection_cli.invoke(cli.app, arguments)
    assert second.exit_code == 0 and "unchanged=1" in second.output


def test_cli_unknown_source_returns_failure(collection_cli: CliRunner) -> None:
    result = collection_cli.invoke(cli.app, ["collect", "run", "--source", "unknown"])
    assert result.exit_code == 1
    assert "SOURCE_NOT_FOUND" in result.output
    assert "Traceback" not in result.output


def test_scheduler_collects_only_due_sources(
    acquisition_session: Session,
    acquisition_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/releases"):
            return httpx.Response(200, json=[release()])
        return httpx.Response(200, content=RSS, headers={"Content-Type": "application/rss+xml"})

    def collect(session: Session, key: str, **options: object):
        calls.append(key)
        return collect_source(session, key, http_factory=factory(handler), **options)

    monkeypatch.setattr(scheduler, "SessionLocal", sessionmaker(bind=acquisition_engine))
    monkeypatch.setattr(scheduler, "collect_source", collect)
    scheduler.poll_sources()
    assert calls == ["github-esphome", "vendor-official-feed"]
    assert acquisition_session.scalar(select(func.count()).select_from(Item)) == 2
    scheduler.poll_sources()
    assert calls == ["github-esphome", "vendor-official-feed"]


def test_cli_database_error_does_not_expose_parameters(
    collection_cli: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy.exc import SQLAlchemyError

    def fail(*args: object, **kwargs: object):
        raise SQLAlchemyError("Authorization=secret and raw article text")

    monkeypatch.setattr(cli, "collect_source", fail)
    result = collection_cli.invoke(cli.app, ["collect", "run", "--source", "vendor-official-feed"])
    assert result.exit_code == 1
    assert "DATABASE_ERROR" in result.output
    assert "secret" not in result.output and "raw article text" not in result.output
