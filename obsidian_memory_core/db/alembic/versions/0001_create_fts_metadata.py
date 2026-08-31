"""Create FTS metadata table."""
from alembic import op

revision = "fts_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "CREATE TABLE IF NOT EXISTS fts_meta "
        "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )


def downgrade():
    op.execute("DROP TABLE IF EXISTS fts_meta")
