"""Phase 3 immutable evidence packages, revision-aware facts and API identities."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261001_0003"
down_revision = "20260930_0002"
branch_labels = None
depends_on = None
JSON_STORAGE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "evidence_packages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("item_id", sa.Uuid(), sa.ForeignKey("items.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("payload_json", JSON_STORAGE, nullable=False),
        sa.Column("payload_hash", sa.String(71), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("item_version", sa.Integer(), nullable=False),
        sa.Column("input_hash", sa.String(71), nullable=False),
        sa.UniqueConstraint("item_id", "revision"),
        sa.UniqueConstraint("item_id", "input_hash"),
    )
    with op.batch_alter_table("items") as batch:
        batch.add_column(
            sa.Column("workflow_version", sa.Integer(), server_default="1", nullable=False)
        )
    with op.batch_alter_table("facts") as batch:
        batch.add_column(
            sa.Column("item_version", sa.Integer(), server_default="1", nullable=False)
        )
        batch.add_column(sa.Column("evidence_id", sa.Uuid()))
        batch.add_column(sa.Column("evidence_package_id", sa.Uuid()))
        batch.create_unique_constraint("uq_facts_evidence_id", ["evidence_id"])
        batch.create_foreign_key(
            "fk_facts_evidence_package", "evidence_packages", ["evidence_package_id"], ["id"]
        )
    op.create_table(
        "api_users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("roles", JSON_STORAGE, nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("api_users")
    with op.batch_alter_table("facts") as batch:
        batch.drop_constraint("fk_facts_evidence_package", type_="foreignkey")
        batch.drop_constraint("uq_facts_evidence_id", type_="unique")
        batch.drop_column("evidence_package_id")
        batch.drop_column("evidence_id")
        batch.drop_column("item_version")
    with op.batch_alter_table("items") as batch:
        batch.drop_column("workflow_version")
    op.drop_table("evidence_packages")
