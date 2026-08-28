#!/usr/bin/env python3
"""Submit completed Hermes sessions to the central memory MCP server.

This hook is intentionally a thin client. It never writes the vault directly;
the single memory-server process owns capture, extraction, locking, and writes.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
MCP_URL = os.environ.get("OBSIDIAN_MEMORY_MCP_URL", "http://127.0.0.1:8765/mcp")


def log(message: str) -> None:
    print(f"wiki-hook: {message}", file=sys.stderr)


def append_audit(message: str) -> None:
    """Keep hook diagnostics durable when stderr is not retained by launchd."""
    try:
        path = os.path.expanduser("~/.hermes/logs/obsidianwiki-ingest-hook.log")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(message + "\n")
    except Exception:
        pass


async def submit(session_id: str) -> None:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(MCP_URL) as (read, write, _):
        async with ClientSession(read, write) as client:
            await client.initialize()
            await client.call_tool(
                "memory_ingest_submit",
                {
                    "request_id": f"{session_id}:completed",
                    "session_id": session_id,
                },
            )


def main() -> int:
    # Ingest is enabled by default for every completed non-cron session.
    try:
        payload = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    except Exception:
        payload = {}
    extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
    session_id = str(payload.get("session_id", "") or "")
    completed = bool(payload.get("completed", extra.get("completed", False)))
    platform = str(payload.get("platform", extra.get("platform", "")) or "")
    if not completed or session_id.startswith("cron_") or platform == "cron":
        return 0
    event = f"session={session_id} platform={platform or 'unknown'}"
    append_audit(f"boundary received {event}")
    try:
        asyncio.run(submit(session_id))
        message = f"ingest job submitted {event}"
        log(message)
        append_audit(message)
    except Exception as exc:
        # Hooks fail open: an unavailable server must not break Hermes.
        message = f"ingest submit failed {event}: {exc}"
        log(message)
        append_audit(message)
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["main", "submit"]
