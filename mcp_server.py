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

import fastmcp
from fastmcp import FastMCP

from obsidian_memory_core import IngestJobManager, InvalidRevisionFormat, MemoryStore, RevisionConflict, MemoryWriteError
from obsidian_memory_core.config import vault_path



mcp = FastMCP("obsidian-memory")
# This server is used as a short-lived request/response memory adapter.  Keep
# Streamable HTTP stateless so every client initialize/DELETE cycle cannot leave
# a transport retained by the server's stateful session registry.  MCP SDK
# 1.30.0 also removes stateful transports immediately after DELETE.
fastmcp.settings.stateless_http = True
_manager: IngestJobManager | None = None


def _run_reflection(query: str, pages: list[dict[str, Any]]) -> str:
    """Synthesize retrieved curated pages with the configured provider."""
    provider = os.environ.get("OBSIDIAN_MEMORY_REFLECT_PROVIDER", "hermes").strip().lower()
    if provider in {"codex", "openai-codex"}:
        from obsidian_memory_core.reflect import CodexProvider

        return CodexProvider().reflect(query, pages)
    if provider not in {"", "hermes"}:
        raise RuntimeError(f"Unsupported reflection provider: {provider}")
    try:
        from agent.oneshot import run_oneshot
    except ImportError as exc:
        raise RuntimeError("Reflection requires Hermes agent environment with LLM configured") from exc

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
def memory_lint(fix: bool = False, dry_run: bool = True) -> dict[str, Any]:
    """Check wiki integrity and optionally fix orphan navigation."""
    store = _store(prepare=fix and not dry_run)
    if not fix:
        return store.lint()
    return {"lint": store.lint(), "fix_orphans": store.fix_orphans(dry_run=dry_run)}


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
    except InvalidRevisionFormat as exc:
        return {"error": "invalid_revision_format", "message": str(exc)}
    except MemoryWriteError as exc:
        return {"error": "write_failed", "message": str(exc)}


@mcp.tool()
def memory_append(
    page: str,
    content: str,
    note: str = "",
    expected_revision: str | None = None,
) -> dict[str, Any]:
    """Append to an existing page without replacing its previous content."""
    try:
        return _store(prepare=True).append(page, content, note, expected_revision)
    except RevisionConflict as exc:
        return {"error": "revision_conflict", "message": str(exc)}
    except InvalidRevisionFormat as exc:
        return {"error": "invalid_revision_format", "message": str(exc)}
    except MemoryWriteError as exc:
        return {"error": "append_failed", "message": str(exc)}
    except Exception as exc:
        return {"error": "append_failed", "message": str(exc)}


@mcp.tool()
def memory_delete(page: str, expected_revision: str | None = None, note: str = "") -> dict[str, Any]:
    """Delete one curated wiki page; expected_revision is mandatory."""
    try:
        return _store(prepare=True).delete(page, expected_revision, note)
    except RevisionConflict as exc:
        return {"error": "revision_conflict", "message": str(exc)}
    except InvalidRevisionFormat as exc:
        return {"error": "invalid_revision_format", "message": str(exc)}
    except MemoryWriteError as exc:
        return {"error": "delete_failed", "message": str(exc)}


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
        help="vault path; otherwise use OBSIDIAN_VAULT_PATH or the configured default",
    )
    args = parser.parse_args()
    if args.vault_path:
        _SERVER_VAULT_PATH = args.vault_path
    mcp.run()


if __name__ == "__main__":
    main()
