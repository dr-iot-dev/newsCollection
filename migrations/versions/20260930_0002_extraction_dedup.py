"""Persist extracted content and explainable duplicate decisions."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260930_0002"
down_revision = "20260930_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    data = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.create_table(
        "extraction_results",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("item_id", sa.Uuid(), sa.ForeignKey("items.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), sa.ForeignKey("raw_snapshots.id"), nullable=False),
        sa.Column("payload_json", data, nullable=False),
        sa.Column("payload_hash", sa.String(71), nullable=False),
        sa.Column("body_sha256", sa.String(64), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("item_id", "revision"),
    )
    op.create_index("ix_extraction_body_sha", "extraction_results", ["body_sha256"])
    op.create_index("ix_extraction_url", "extraction_results", ["canonical_url"])
    op.create_table(
        "duplicate_decisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("item_id", sa.Uuid(), sa.ForeignKey("items.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), sa.ForeignKey("items.id")),
        sa.Column("candidate_revision", sa.Integer()),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("score", sa.Numeric(4, 3), nullable=False),
        sa.Column("reasons", data, nullable=False),
        sa.Column("policy_version", sa.String(50), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("item_id", "revision", "candidate_id"),
    )


def downgrade() -> None:
    op.drop_table("duplicate_decisions")
    op.drop_table("extraction_results")
