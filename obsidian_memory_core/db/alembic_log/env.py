"""Alembic environment for the log SQLite database."""
from alembic import context

config = context.config
connection = config.attributes.get("connection")
if connection is None:
    raise RuntimeError("log migrations require an existing database connection")

context.configure(connection=connection, target_metadata=None)
with context.begin_transaction():
    context.run_migrations()
