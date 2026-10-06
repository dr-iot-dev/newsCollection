from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import current_user, require_role
from app.contracts.wordpress_v1 import (
    PublishApprovalRequestV1,
    PublishRequestV1,
    WordPressRequestV1,
)
from app.core.config import get_settings
from app.infrastructure.db.models import ApiUser, Item, Publication, PublishApproval
from app.infrastructure.db.session import get_db
from app.orchestration.publication import PublicationService

router = APIRouter(prefix="/api/v1", tags=["internal publication"])
DB = Annotated[Session, Depends(get_db)]
User = Annotated[ApiUser, Depends(current_user)]


def publication_view(session: Session, row: Publication) -> dict[str, Any]:
    item = session.get(Item, row.item_id)
    approval = session.scalar(
        select(PublishApproval).where(PublishApproval.publication_id == row.id)
    )
    return {
        "publication_id": str(row.id),
        "draft_id": str(row.draft_id),
        "state": row.state,
        "remote_post_id": row.remote_post_id,
        "remote_url": row.remote_url,
        "remote_status": row.remote_status,
        "payload_hash": row.payload_hash,
        "last_error": row.last_error,
        "publish_approval_id": str(approval.id) if approval else None,
        "workflow_version": item.workflow_version if item else None,
    }


@router.get("/items/{item_id}/publications")
def publications(item_id: UUID, session: DB, user: User) -> list[dict[str, Any]]:
    return [
        publication_view(session, row)
        for row in session.scalars(
            select(Publication)
            .where(Publication.item_id == item_id)
            .order_by(Publication.created_at.desc())
        )
    ]


@router.post("/items/{item_id}/wordpress/draft", status_code=201)
def create_wordpress_draft(
    item_id: UUID,
    request: WordPressRequestV1,
    session: DB,
    user: User,
) -> dict[str, Any]:
    require_role(user, "editor")
    row = PublicationService(session, get_settings()).create_draft(item_id, request, user.id)
    return publication_view(session, row)


@router.post("/items/{item_id}/wordpress/publish-approval", status_code=201)
def approve_wordpress_publish(
    item_id: UUID,
    request: PublishApprovalRequestV1,
    session: DB,
    user: User,
) -> dict[str, Any]:
    require_role(user, "publisher")
    approval = PublicationService(session, get_settings()).approve_publish(
        item_id, request, user.id
    )
    item = session.get(Item, item_id)
    return {
        "publish_approval_id": str(approval.id),
        "publication_id": str(approval.publication_id),
        "workflow_version": item.workflow_version if item else None,
    }


@router.post("/items/{item_id}/wordpress/publish")
def publish_wordpress(
    item_id: UUID,
    request: PublishRequestV1,
    session: DB,
    user: User,
) -> dict[str, Any]:
    require_role(user, "publisher")
    row = PublicationService(session, get_settings()).publish(item_id, request, user.id)
    return publication_view(session, row)


@router.post("/publications/{publication_id}/reconcile")
def reconcile_wordpress(publication_id: UUID, session: DB, user: User) -> dict[str, Any]:
    require_role(user, "editor")
    row = PublicationService(session, get_settings()).reconcile(publication_id, user.id)
    return publication_view(session, row)
