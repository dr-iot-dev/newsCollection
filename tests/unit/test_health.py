from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.routes.health import get_db
from app.core.config import Settings, get_settings
from app.main import app


def test_live_does_not_require_database() -> None:
    with TestClient(app) as client:
        response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {}}


def test_ready_can_disable_database_check() -> None:
    def settings_override() -> Settings:
        return Settings(ready_check_database=False)

    def db_override() -> Generator[Session]:
        yield None  # type: ignore[misc]

    app.dependency_overrides[get_settings] = settings_override
    app.dependency_overrides[get_db] = db_override
    try:
        with TestClient(app) as client:
            response = client.get("/health/ready")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["checks"]["database"] == "disabled"
