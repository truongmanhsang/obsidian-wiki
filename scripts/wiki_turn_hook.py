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
    print(message, file=sys.stderr)


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
    try:
        asyncio.run(submit(session_id))
        log("wiki-hook: ingest job submitted to central memory server")
    except Exception as exc:
        # Hooks fail open: an unavailable server must not break Hermes.
        log(f"wiki-hook could not submit ingest job: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["main", "submit"]
