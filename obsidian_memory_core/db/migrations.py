"""Alembic entry point for the wiki SQLite databases."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine


MIGRATION_DIR = Path(__file__).with_name("alembic")


def upgrade(conn: sqlite3.Connection) -> None:
    """Upgrade the supplied SQLite connection to the current Alembic head."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATION_DIR))
    engine = create_engine("sqlite://", creator=lambda: conn)
    with engine.connect() as sqlalchemy_conn:
        config.attributes["connection"] = sqlalchemy_conn
        command.upgrade(config, "head")
        sqlalchemy_conn.commit()
    # The engine wraps a caller-owned sqlite3 connection via ``creator``.
    # Do not dispose it here; disposal would close the caller's connection.
