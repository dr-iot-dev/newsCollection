import signal
from datetime import UTC, datetime

import structlog
from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy import or_, select

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.infrastructure.db.models import LegalStatus, Publication, Source
from app.infrastructure.db.session import SessionLocal
from app.modules.acquisition.service import collect_source
from app.orchestration.editorial import process_editorial_outbox, process_facts_outbox
from app.orchestration.editorial_jobs import process_editorial_jobs
from app.orchestration.phase2 import process_phase2
from app.orchestration.publication import PublicationService
from app.orchestration.research import process_comparison_research

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

    try:
        with SessionLocal.begin() as session:
            counts = process_phase2(session)
        with SessionLocal.begin() as session:
            fact_count = process_facts_outbox(session, settings)
        with SessionLocal.begin() as session:
            job_count = process_editorial_jobs(session, settings)
        for consumer in ("selection", "comparison"):
            with SessionLocal.begin() as session:
                process_editorial_outbox(session, settings, consumer)
        with SessionLocal.begin() as session:
            process_comparison_research(session, settings)
        for consumer in ("writing", "verification"):
            with SessionLocal.begin() as session:
                process_editorial_outbox(session, settings, consumer)
        if fact_count or job_count:
            logger.info("phase3_processed", facts=fact_count, jobs=job_count)
        if any(counts.values()):
            logger.info("phase2_processed", **counts)
    except Exception:
        logger.error("phase2_processing_error", error_code="PROCESSING_ERROR")


def reconcile_wordpress() -> None:
    settings = get_settings()
    if not settings.wordpress_enabled:
        return
    with SessionLocal() as session:
        ids = list(
            session.scalars(
                select(Publication.id)
                .where(Publication.state != "legacy")
                .order_by(Publication.updated_at)
                .limit(100)
            )
        )
    for publication_id in ids:
        try:
            with SessionLocal() as session:
                PublicationService(session, settings).reconcile(publication_id)
        except Exception:
            logger.error(
                "wordpress_reconcile_error",
                publication_id=str(publication_id),
                error_code="RECONCILE_FAILED",
            )


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
    scheduler.add_job(
        reconcile_wordpress,
        trigger="interval",
        minutes=30,
        id="reconcile-wordpress",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    signal.signal(signal.SIGTERM, lambda *_: scheduler.shutdown(wait=False))
    logger.info("scheduler_started")
    scheduler.start()


if __name__ == "__main__":
    main()
