#!/usr/bin/env python3
"""Submit an ingest job to the central Obsidian memory MCP server."""
from __future__ import annotations

import argparse
import asyncio
import json
import os

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def submit(url: str, request_id: str | None, session_id: str | None) -> None:
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as client:
            await client.initialize()
            result = await client.call_tool(
                "memory_ingest_submit",
                {"request_id": request_id, "session_id": session_id},
            )
            print(json.dumps(result.model_dump(), ensure_ascii=False, default=str, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=os.environ.get("OBSIDIAN_MEMORY_MCP_URL", "http://127.0.0.1:8765/mcp"))
    parser.add_argument("--request-id")
    parser.add_argument("--session-id")
    args = parser.parse_args()
    asyncio.run(submit(args.url, args.request_id, args.session_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
