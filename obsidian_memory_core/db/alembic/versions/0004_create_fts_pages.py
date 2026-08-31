"""Create the SQLite FTS5 virtual table used by lexical search."""
from alembic import op

revision = "fts_pages_virtual_table"
down_revision = "fts_embedding_cache"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """CREATE VIRTUAL TABLE IF NOT EXISTS fts_pages USING fts5(
            path UNINDEXED, title, body, search_projection,
            ptype UNINDEXED, updated UNINDEXED,
            tokenize='porter unicode61'
        )"""
    )


def downgrade():
    op.execute("DROP TABLE IF EXISTS fts_pages")
