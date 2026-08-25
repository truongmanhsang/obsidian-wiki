"""Shared Obsidian memory core used by Hermes and MCP adapters."""

from .store import MemoryStore, MemoryWriteError, RevisionConflict

__all__ = ["MemoryStore", "MemoryWriteError", "RevisionConflict"]

__version__ = "0.1.0"
