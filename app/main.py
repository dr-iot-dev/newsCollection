from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.api.routes.health import router as health_router
from app.api.routes.items import router as items_router
from app.api.routes.publications import router as publications_router
from app.core.config import get_settings
from app.core.editorial import EditorialError
from app.core.logging import configure_logging


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version="0.4.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.app_env in {"development", "test"} else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.app_env in {"development", "test"} else None,
    )

    @application.exception_handler(EditorialError)
    async def editorial_error(_: Request, exc: EditorialError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"error": {"code": exc.code}})

    @application.exception_handler(SQLAlchemyError)
    async def database_error(_: Request, exc: SQLAlchemyError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"error": {"code": "DATABASE_ERROR"}})

    application.include_router(health_router)
    application.include_router(items_router)
    application.include_router(publications_router)
    return application


app = create_app()
