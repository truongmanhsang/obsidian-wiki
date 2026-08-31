"""Rebuild legacy FTS indexes for normalized search projection."""
from alembic import op

revision = "fts_search_projection"
down_revision = "fts_baseline"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {row[1] for row in bind.exec_driver_sql("PRAGMA table_info(fts_pages)")}
    if columns and "search_projection" not in columns:
        op.execute("DROP TABLE fts_pages")


def downgrade():
    pass
