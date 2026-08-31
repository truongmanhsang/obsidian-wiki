"""SQLAlchemy models shared by the wiki's SQLite databases."""
from __future__ import annotations

from sqlalchemy import Boolean, Integer, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class LogEntry(Base):
    __tablename__ = "logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_auto: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class FtsMeta(Base):
    __tablename__ = "fts_meta"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)


class EmbeddingPage(Base):
    __tablename__ = "embedding_pages"

    path: Mapped[str] = mapped_column(Text, primary_key=True)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    vector: Mapped[str] = mapped_column(Text, nullable=False)


class FtsPage(Base):
    """Mapping for the SQLite FTS5 virtual table (created by FTS code)."""
    __tablename__ = "fts_pages"

    path: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    search_projection: Mapped[str] = mapped_column(Text, nullable=False)
    ptype: Mapped[str] = mapped_column(Text, nullable=False)
    updated: Mapped[str] = mapped_column(Text, nullable=False)
