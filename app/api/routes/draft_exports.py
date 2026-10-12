"""Generation artifacts only. WordPress is operated by the independent uploader."""

from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import current_user, require_role
from app.core.config import get_settings
from app.core.editorial import EditorialError
from app.infrastructure.db.models import ApiUser, DraftExport
from app.infrastructure.db.session import get_db
from app.orchestration.draft_exports import DraftExporter
from nw_generation.protocol import digest

router = APIRouter(prefix="/api/v1", tags=["draft-exports"])
DB = Annotated[Session, Depends(get_db)]
User = Annotated[ApiUser, Depends(current_user)]


class ExportRequest(BaseModel):
    draft_id: UUID
    artifact_revision: int = Field(default=1, ge=1)


def view(row: DraftExport) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "draft_id": str(row.draft_id),
        "state": row.state,
        "last_error": row.last_error,
        "download": f"/api/v1/draft-exports/{row.id}/download" if row.file_path else None,
    }


@router.get("/items/{item_id}/draft-exports")
def list_exports(item_id: UUID, session: DB, user: User) -> list[dict[str, Any]]:
    require_role(user, "viewer")
    return [
        view(row)
        for row in session.scalars(
            select(DraftExport)
            .where(DraftExport.item_id == item_id)
            .order_by(DraftExport.created_at.desc())
        )
    ]


@router.post("/items/{item_id}/draft-exports")
def create_export(item_id: UUID, request: ExportRequest, session: DB, user: User) -> dict[str, Any]:
    require_role(user, "editor")
    from app.infrastructure.db.models import ArticleDraft

    draft = session.get(ArticleDraft, request.draft_id)
    if draft is None or draft.item_id != item_id:
        raise EditorialError("DRAFT_ITEM_MISMATCH", 404)
    return view(
        DraftExporter(session, get_settings()).export(
            request.draft_id, artifact_revision=request.artifact_revision
        )
    )


@router.get("/draft-exports/{export_id}/download")
def download_export(export_id: UUID, session: DB, user: User) -> Response:
    require_role(user, "viewer")
    row = session.get(DraftExport, export_id)
    if row is None or not row.file_path:
        raise EditorialError("EXPORT_NOT_READY", 404)
    path = Path(row.file_path).resolve()
    if not path.is_relative_to(get_settings().draft_artifact_dir.resolve()):
        raise EditorialError("EXPORT_PATH_INVALID")
    raw = path.read_bytes()
    if digest(raw) != row.bundle_hash:
        raise EditorialError("EXPORT_ARTIFACT_HASH_MISMATCH")
    return Response(
        raw,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{row.id}.nwdraft"'},
    )


class ImageApproval(BaseModel):
    expected_image_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")


@router.post("/draft-exports/{export_id}/image-approval")
def approve_image(
    export_id: UUID, request: ImageApproval, session: DB, user: User
) -> dict[str, Any]:
    require_role(user, "reviewer")
    from app.orchestration.draft_exports import approve_export_image

    return view(
        approve_export_image(
            session, get_settings(), export_id, user.id, request.expected_image_hash
        )
    )
