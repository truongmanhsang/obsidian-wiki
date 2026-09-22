"""Shared Obsidian memory core used by Hermes and MCP adapters."""

from .store import InvalidRevisionFormat, MemoryStore, MemoryWriteError, RevisionConflict
from .jobs import IngestJobManager, IngestJobReader

__all__ = ["MemoryStore", "MemoryWriteError", "RevisionConflict", "InvalidRevisionFormat", "IngestJobManager", "IngestJobReader"]

__version__ = "0.1.0"
