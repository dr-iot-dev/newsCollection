"""Durable comparison search outcomes and retry diagnostics."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261002_0006"
down_revision = "20261002_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "module_messages",
        sa.Column("result_json", sa.JSON().with_variant(postgresql.JSONB(), "postgresql")),
    )


def downgrade() -> None:
    with op.batch_alter_table("module_messages") as batch:
        batch.drop_column("result_json")
