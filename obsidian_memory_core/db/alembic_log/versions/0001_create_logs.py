"""Create the operation log schema."""
from alembic import op

revision = "log_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            kind TEXT NOT NULL,
            message TEXT NOT NULL,
            is_auto INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )"""
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_logs_date_kind ON logs(date, kind)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_logs_kind_auto ON logs(kind, is_auto)")


def downgrade():
    op.execute("DROP TABLE IF EXISTS logs")
