"""One SQLite or PostgreSQL database for the pipeline."""

from pathlib import Path

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models import Base


def engine_for(url: str) -> Engine:
    engine = create_engine(url)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

    return engine


def initialize(engine: Engine) -> None:
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    expected = set(Base.metadata.tables)
    if existing - expected:
        raise ValueError("DATABASE_SCHEMA_MISMATCH")
    for name in existing:
        columns = {c["name"]: c["nullable"] for c in inspector.get_columns(name)}
        required = {c.name: c.nullable for c in Base.metadata.tables[name].columns}
        if columns != required:
            raise ValueError("DATABASE_SCHEMA_MISMATCH")
    Base.metadata.create_all(engine)


def open_session(url: str) -> Session:
    engine = engine_for(url)
    initialize(engine)
    return Session(engine, expire_on_commit=False)


def schema_sql(path: Path, dialect_name: str = "postgresql") -> None:
    from sqlalchemy.dialects import postgresql, sqlite
    from sqlalchemy.schema import CreateIndex, CreateTable

    dialect = postgresql.dialect() if dialect_name == "postgresql" else sqlite.dialect()
    statements = []
    for table in Base.metadata.sorted_tables:
        statements.append(str(CreateTable(table).compile(dialect=dialect)).strip() + ";")
        statements.extend(str(CreateIndex(i).compile(dialect=dialect)) + ";" for i in table.indexes)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n\n".join(statements) + "\n", encoding="utf-8")
