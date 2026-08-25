"""Shared Obsidian memory core used by Hermes and MCP adapters."""

from .store import MemoryStore, MemoryWriteError, RevisionConflict
from .jobs import IngestJobManager

__all__ = ["MemoryStore", "MemoryWriteError", "RevisionConflict", "IngestJobManager"]

__version__ = "0.1.0"
