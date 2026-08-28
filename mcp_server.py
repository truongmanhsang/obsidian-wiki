"""Obsidian memory MCP adapter.

Run over stdio by default. For HTTP, use: fastmcp run mcp_server.py:mcp
"""
from __future__ import annotations

import os
import argparse
from typing import Any

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastmcp import FastMCP

from obsidian_memory_core import IngestJobManager, MemoryStore, RevisionConflict
from obsidian_memory_core.config import vault_path


def _run_reflection(query: str, pages: list[dict[str, Any]]) -> str:
    """Synthesize retrieved curated pages with Hermes' configured LLM."""
    from agent.oneshot import run_oneshot

    context = "\n\n".join(
        f"SOURCE: {page['path']}\n{page['content']}" for page in pages
    )
    instructions = (
        "You are the reflection layer for an Obsidian knowledge wiki. "
        "Answer the user's question only from the supplied sources. "
        "Synthesize across sources, distinguish facts from uncertainty, and "
        "say when the sources do not establish an answer. Be concise. "
        "Do not invent citations or facts."
    )
    return run_oneshot(
        instructions=instructions,
        user_input=f"Question:\n{query}\n\nSources:\n{context}",
        task="memory_reflection",
        max_tokens=1200,
        temperature=0.2,
        timeout=90.0,
    )

mcp = FastMCP("obsidian-memory")
_manager: IngestJobManager | None = None


_SERVER_VAULT_PATH: str | None = None


def _store(prepare: bool = False) -> MemoryStore:
    path = _SERVER_VAULT_PATH or vault_path()
    store = MemoryStore(path)
    if prepare:
        store.ensure_ready()
    return store


def _ingest_manager() -> IngestJobManager:
    global _manager
    if _manager is None:
        _manager = IngestJobManager(_store(prepare=True))
        # Recover session_reset boundaries missed while Hermes or this server
        # was restarting. Recovery is idempotent and runs once per process.
        try:
            _manager.recover_unsubmitted_boundaries()
        except Exception:
            pass
    return _manager


@mcp.tool()
def memory_search(query: str, limit: int = 5) -> dict[str, Any]:
    """Search durable project, people, decision, and concept memory."""
    return _store().search(query, max(1, min(limit, 50)))


@mcp.tool()
def memory_reflect(query: str, limit: int = 8) -> dict[str, Any]:
    """Synthesize relevant curated wiki pages into a grounded answer."""
    query = (query or "").strip()
    if not query:
        return {"error": "reflect requires a query"}
    store = _store()
    hits = store.search(query, max(1, min(limit, 20))).get("results", [])
    pages = []
    for hit in hits:
        try:
            page = store.read(hit["path"])
            pages.append({"path": hit["path"], "content": page["content"]})
        except Exception:
            continue
    if not pages:
        return {"query": query, "reflection": "No relevant wiki pages found.", "sources": []}
    try:
        reflection = _run_reflection(query, pages)
    except Exception as exc:
        return {"error": "reflection_failed", "message": str(exc), "sources": [p["path"] for p in pages]}
    return {"query": query, "reflection": reflection, "sources": [{"path": p["path"]} for p in pages]}


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
    global _SERVER_VAULT_PATH
    parser = argparse.ArgumentParser(description="Obsidian Wiki memory MCP server")
    parser.add_argument(
        "--vault-path",
        help="vault path; otherwise use OBSIDIAN_VAULT_PATH or ~/Documents/agent-vault",
    )
    args = parser.parse_args()
    if args.vault_path:
        _SERVER_VAULT_PATH = args.vault_path
    mcp.run()


if __name__ == "__main__":
    main()
