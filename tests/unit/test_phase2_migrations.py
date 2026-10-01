from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Engine, inspect
from sqlalchemy.orm import Session

from app.infrastructure.db.models import Base, LegalStatus, Source, SourceType


def test_upgrade_existing_database_and_fresh_install_keep_schema_and_data(
    acquisition_engine: Engine,
) -> None:
    engine = acquisition_engine
    # This engine is exclusively the fixture's temporary file/schema.
    Base.metadata.drop_all(engine)
    config = Config("alembic.ini")
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "20260930_0001")
        assert "extraction_results" not in inspect(connection).get_table_names()
        with Session(bind=connection) as session:
            row = Source(
                key="migration-test",
                type=SourceType.RSS,
                name="Kept source",
                config={},
                enabled=False,
                legal_status=LegalStatus.PENDING,
            )
            session.add(row)
            session.flush()
            source_id = row.id
            session.commit()
        command.upgrade(config, "head")
        with Session(bind=connection) as session:
            assert session.get(Source, source_id).name == "Kept source"
            session.commit()
        assert {"extraction_results", "duplicate_decisions"} <= set(
            inspect(connection).get_table_names()
        )
        context = MigrationContext.configure(connection)
        assert compare_metadata(context, Base.metadata) == []
        command.downgrade(config, "20260930_0001")
        assert "extraction_results" not in inspect(connection).get_table_names()
        command.upgrade(config, "head")
        command.downgrade(config, "base")
        assert inspect(connection).get_table_names() == ["alembic_version"]
        command.upgrade(config, "head")
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
