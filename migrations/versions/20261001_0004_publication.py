"""Phase 4 durable publication intent and separately recorded publish approval."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261001_0004"
down_revision = "20261001_0003"
branch_labels = None
depends_on = None
JSON_STORAGE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("publications") as batch:
        batch.add_column(sa.Column("package_json", JSON_STORAGE))
        batch.add_column(sa.Column("payload_json", JSON_STORAGE))
        batch.add_column(sa.Column("remote_hash", sa.String(71)))
        batch.add_column(sa.Column("state", sa.String(30), nullable=False, server_default="legacy"))
    op.create_table(
        "publish_approvals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("publication_id", sa.Uuid(), sa.ForeignKey("publications.id"), nullable=False),
        sa.Column("review_id", sa.Uuid(), sa.ForeignKey("reviews.id"), nullable=False),
        sa.Column("publisher_id", sa.Uuid(), sa.ForeignKey("api_users.id"), nullable=False),
        sa.Column("item_version", sa.Integer(), nullable=False),
        sa.Column("payload_hash", sa.String(71), nullable=False),
        sa.Column("remote_hash", sa.String(71), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("publication_id"),
    )


def downgrade() -> None:
    op.drop_table("publish_approvals")
    with op.batch_alter_table("publications") as batch:
        batch.drop_column("state")
        batch.drop_column("remote_hash")
        batch.drop_column("payload_json")
        batch.drop_column("package_json")
