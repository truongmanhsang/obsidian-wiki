"""Create the embedding cache table."""
from alembic import op

revision = "fts_embedding_cache"
down_revision = "fts_search_projection"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """CREATE TABLE IF NOT EXISTS embedding_pages (
            path TEXT PRIMARY KEY,
            content_hash TEXT NOT NULL,
            model TEXT NOT NULL,
            vector TEXT NOT NULL
        )"""
    )


def downgrade():
    op.execute("DROP TABLE IF EXISTS embedding_pages")
