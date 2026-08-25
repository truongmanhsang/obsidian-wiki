"""Obsidian memory MCP adapter.

Run over stdio by default. For HTTP, use: fastmcp run mcp_server.py:mcp
"""
from __future__ import annotations

import os
from typing import Any

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastmcp import FastMCP

from obsidian_memory_core import IngestJobManager, MemoryStore, RevisionConflict

mcp = FastMCP("obsidian-memory")
_manager: IngestJobManager | None = None


def _store(prepare: bool = False) -> MemoryStore:
    path = os.environ.get(
        "OBSIDIAN_VAULT_PATH",
        os.path.expanduser("~/Library/Mobile Documents/iCloud~md~obsidian/Documents/agent-vault"),
    )
    store = MemoryStore(path)
    if prepare:
        store.ensure_ready()
    return store


def _ingest_manager() -> IngestJobManager:
    global _manager
    if _manager is None:
        _manager = IngestJobManager(_store(prepare=True))
    return _manager


@mcp.tool()
def memory_search(query: str, limit: int = 5) -> dict[str, Any]:
    """Search durable project, people, decision, and concept memory."""
    return _store().search(query, max(1, min(limit, 50)))


@mcp.tool()
def memory_read(page: str) -> dict[str, Any]:
    """Read one wiki page and return its optimistic-concurrency revision."""
    return _store().read(page)


@mcp.tool()
def memory_list(limit: int = 50) -> dict[str, Any]:
    """List the memory catalog and page statistics."""
    return _store().list(max(1, min(limit, 500)))


@mcp.tool()
def memory_lint() -> dict[str, Any]:
    """Check broken links, orphan pages, and wiki integrity."""
    return _store().lint()


@mcp.tool()
def memory_log(limit: int = 30) -> dict[str, Any]:
    """Read recent memory operation logs."""
    return _store().log(max(1, min(limit, 200)))


@mcp.tool()
def memory_write(
    page: str,
    content: str,
    note: str = "",
    expected_revision: str | None = None,
    allow_duplicate: bool = False,
) -> dict[str, Any]:
    """Create or update a wiki page.

    Pass expected_revision from memory_read when updating an existing page.
    The server rejects stale revisions instead of overwriting another agent's
    changes. Never store credentials, API keys, tokens, or passwords.
    """
    try:
        return _store(prepare=True).write(page, content, note, expected_revision, allow_duplicate)
    except RevisionConflict as exc:
        return {"error": "revision_conflict", "message": str(exc)}


@mcp.tool()
def memory_ingest_submit(request_id: str | None = None, session_id: str | None = None) -> dict[str, Any]:
    """Queue centralized session capture and extraction; safe to retry with request_id."""
    return _ingest_manager().submit(request_id=request_id, session_id=session_id)


@mcp.tool()
def memory_ingest_status(job_id: str | None = None) -> dict[str, Any]:
    """Return the status of one ingest job or recent centralized ingest jobs."""
    return _ingest_manager().status(job_id)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
