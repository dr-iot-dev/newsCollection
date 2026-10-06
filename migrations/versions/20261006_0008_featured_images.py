"""Durable image generation, media upload, and featured-image attachment."""

import sqlalchemy as sa
from alembic import op

revision = "20261006_0008"
down_revision = "20261006_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "featured_images",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("publication_id", sa.Uuid(), sa.ForeignKey("publications.id"), nullable=False),
        sa.Column("draft_id", sa.Uuid(), sa.ForeignKey("article_drafts.id"), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("input_hash", sa.String(71), nullable=False),
        sa.Column("state", sa.String(30), nullable=False),
        sa.Column("image_bytes", sa.LargeBinary()),
        sa.Column("content_hash", sa.String(71)),
        sa.Column("width", sa.Integer()),
        sa.Column("height", sa.Integer()),
        sa.Column("remote_media_id", sa.String(255)),
        sa.Column("remote_url", sa.Text()),
        sa.Column("last_error", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.UniqueConstraint("publication_id"),
    )


def downgrade() -> None:
    op.drop_table("featured_images")
