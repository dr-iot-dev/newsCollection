"""Durable, race-safe ownership of a source set for writing or a CMS target."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.contracts.article_package_v1 import ArticlePackageV1
from app.core.source_set import source_set_hash
from app.infrastructure.db.models import SourceSetClaim


def package_source_set(package: ArticlePackageV1) -> str:
    return source_set_hash(str(ref.url) for ref in package.source_references if ref.url is not None)


def claim_source_set(
    session: Session, scope: str, package: ArticlePackageV1, item_id: UUID
) -> SourceSetClaim:
    key = package_source_set(package)
    query = select(SourceSetClaim).where(
        SourceSetClaim.scope == scope, SourceSetClaim.source_set_hash == key
    ).with_for_update()
    claim = session.scalar(query)
    if claim is not None:
        return claim
    # A concurrent insert waits for the first owner to commit. Only this savepoint
    # rolls back on conflict, preserving the caller's item lock and other changes.
    try:
        with session.begin_nested():
            claim = SourceSetClaim(scope=scope, source_set_hash=key, item_id=item_id)
            session.add(claim)
            session.flush()
        return claim
    except IntegrityError:
        winner = session.scalar(query)
        if winner is None:
            raise
        return winner
