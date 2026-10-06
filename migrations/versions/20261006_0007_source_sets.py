"""One generated article and one CMS publication per unordered source set."""

from uuid import UUID, uuid4

import sqlalchemy as sa
from alembic import op

from app.core.source_set import source_set_hash

revision = "20261006_0007"
down_revision = "20261002_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    claims = op.create_table(
        "source_set_claims",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("scope", sa.String(100), nullable=False),
        sa.Column("source_set_hash", sa.String(71), nullable=False),
        sa.Column("item_id", sa.Uuid(), sa.ForeignKey("items.id"), nullable=False),
        sa.Column("draft_id", sa.Uuid(), sa.ForeignKey("article_drafts.id")),
        sa.Column("publication_id", sa.Uuid(), sa.ForeignKey("publications.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.UniqueConstraint("scope", "source_set_hash"),
    )
    bind = op.get_bind()
    metadata = sa.MetaData()
    drafts = sa.Table("article_drafts", metadata, autoload_with=bind)
    packages = sa.Table("article_packages", metadata, autoload_with=bind)
    publications = sa.Table("publications", metadata, autoload_with=bind)
    used: set[tuple[str, str]] = set()

    def insert(scope, row, publication_id=None):
        refs = row["payload_json"].get("source_references", [])
        urls = [ref["url"] for ref in refs if ref.get("url")]
        if not urls:
            return
        key = source_set_hash(urls)
        if (scope, key) in used:
            return
        bind.execute(claims.insert().values(
            id=uuid4(), scope=scope, source_set_hash=key, item_id=UUID(str(row["item_id"])),
            draft_id=UUID(str(row["draft_id"])),
            publication_id=UUID(str(publication_id)) if publication_id is not None else None,
        ))
        used.add((scope, key))

    # Existing sent posts take precedence over historical unsent draft revisions.
    sent = bind.execute(sa.select(
        publications.c.id.label("publication_id"), publications.c.target,
        publications.c.created_at, publications.c.remote_post_id,
        publications.c.item_id, drafts.c.id.label("draft_id"), packages.c.payload_json,
    ).join(drafts, publications.c.draft_id == drafts.c.id)
      .join(packages, drafts.c.article_package_id == packages.c.id)
      .where(publications.c.remote_post_id.is_not(None),
             publications.c.state.not_in(["trashing", "trashed"]))
      .order_by(publications.c.created_at, publications.c.id)).mappings()
    # SQLite timestamps have second precision. WordPress post IDs provide a
    # chronological tie-break instead of randomly choosing a publication UUID.
    ordered_sent = sorted(sent, key=lambda row: (
        row["created_at"],
        int(row["remote_post_id"]) if row["remote_post_id"].isdecimal() else float("inf"),
        str(row["publication_id"]),
    ))
    for row in ordered_sent:
        insert("writing", row)
        insert(row["target"], row, row["publication_id"])
    existing = bind.execute(sa.select(
        drafts.c.item_id, drafts.c.id.label("draft_id"), packages.c.payload_json,
    ).join(packages, drafts.c.article_package_id == packages.c.id)
      .order_by(drafts.c.created_at, drafts.c.revision, drafts.c.id)).mappings()
    for row in existing:
        insert("writing", row)
    # Preserve reservations for ambiguous/in-flight sends as well.
    pending = bind.execute(sa.select(
        publications.c.id.label("publication_id"), publications.c.target,
        publications.c.item_id, drafts.c.id.label("draft_id"), packages.c.payload_json,
    ).join(drafts, publications.c.draft_id == drafts.c.id)
      .join(packages, drafts.c.article_package_id == packages.c.id)
      .where(publications.c.state.not_in(["trashing", "trashed"]))
      .order_by(publications.c.created_at, publications.c.id)).mappings()
    for row in pending:
        insert(row["target"], row, row["publication_id"])


def downgrade() -> None:
    op.drop_table("source_set_claims")
