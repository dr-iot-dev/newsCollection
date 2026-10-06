"""Persist sanitized AI validation conditions without storing rejected responses."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261002_0005"
down_revision = "20261001_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_runs",
        sa.Column(
            "validation_errors_json", sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
        ),
    )


def downgrade() -> None:
    with op.batch_alter_table("ai_runs") as batch:
        batch.drop_column("validation_errors_json")
