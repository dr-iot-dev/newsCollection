"""Independent generation assets and export outbox."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261012_0009"
down_revision = "20261006_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "draft_assets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("draft_id", sa.Uuid(), sa.ForeignKey("article_drafts.id"), nullable=False, unique=True),
        sa.Column("input_hash", sa.String(71), nullable=False),
        sa.Column("state", sa.String(30), nullable=False),
        sa.Column("metadata_json", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
        sa.Column("image_bytes", sa.LargeBinary()),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "draft_exports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("item_id", sa.Uuid(), sa.ForeignKey("items.id"), nullable=False),
        sa.Column("draft_id", sa.Uuid(), sa.ForeignKey("article_drafts.id"), nullable=False),
        sa.Column("artifact_revision", sa.Integer(), nullable=False),
        sa.Column("producer_id", sa.String(36), nullable=False),
        sa.Column("snapshot_json", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
        sa.Column("state", sa.String(30), nullable=False),
        sa.Column("file_path", sa.Text()),
        sa.Column("bundle_hash", sa.String(71)),
        sa.Column("last_error", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("draft_id", "artifact_revision"),
    )


def downgrade() -> None:
    op.drop_table("draft_exports")
    op.drop_table("draft_assets")
