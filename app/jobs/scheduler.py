import signal
from datetime import UTC, datetime

import structlog
from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy import or_, select

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.infrastructure.db.models import LegalStatus, Source, SourceType
from app.infrastructure.db.session import SessionLocal
from app.modules.acquisition.service import collect_source

logger = structlog.get_logger()


def poll_sources() -> None:
    settings = get_settings()
    with SessionLocal() as session:
        keys = list(
            session.scalars(
                select(Source.key)
                .where(
                    Source.enabled.is_(True),
                    Source.legal_status == LegalStatus.APPROVED,
                    Source.type.in_([SourceType.RSS, SourceType.GITHUB_RELEASES]),
                    or_(Source.next_run_at.is_(None), Source.next_run_at <= datetime.now(UTC)),
                )
                .order_by(Source.key)
            )
        )
    for key in keys:
        try:
            with SessionLocal.begin() as session:
                result = collect_source(
                    session,
                    key,
                    github_token=settings.github_token.get_secret_value()
                    if settings.github_token
                    else None,
                )
            logger.info(
                "source_collection",
                source_key=key,
                status=result.status,
                created=result.created,
                updated=result.updated,
                error_code=result.error_code,
            )
        except Exception:
            # Database/driver exceptions can include connection URLs or raw SQL parameters.
            logger.error("source_collection_error", source_key=key, error_code="INTERNAL_ERROR")


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(
        poll_sources,
        trigger="interval",
        seconds=60,
        id="collect-due-sources",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    signal.signal(signal.SIGTERM, lambda *_: scheduler.shutdown(wait=False))
    logger.info("scheduler_started")
    scheduler.start()


if __name__ == "__main__":
    main()
