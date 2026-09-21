"""JSON HTTP adapter for the Obsidian memory web workspace."""

from __future__ import annotations

import argparse
import json
from typing import Any

import uvicorn
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from obsidian_memory_core import MemoryStore
from obsidian_memory_core.config import vault_path as configured_vault_path
from obsidian_memory_core.store import MemoryWriteError


def _run_reflection(query: str, pages: list[dict[str, str]]) -> str:
    """Load the MCP reflection provider only when a reflection is requested."""
    from mcp_server import _run_reflection as run_reflection

    return run_reflection(query, pages)


def _error(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse({"error": code, "message": message}, status_code=status)


def _limit(value: str | None, default: int, maximum: int) -> int:
    if value in (None, ""):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be an integer") from exc
    if parsed < 1:
        raise ValueError("limit must be at least 1")
    return min(parsed, maximum)


def _store(request: Request) -> MemoryStore:
    return request.app.state.store


async def health_endpoint(request: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


async def search_endpoint(request: Request) -> JSONResponse:
    query = request.query_params.get("q", "").strip()
    if not query:
        return _error("invalid_query", "search requires a non-empty q parameter", 400)
    try:
        limit = _limit(request.query_params.get("limit"), 5, 50)
    except ValueError as exc:
        return _error("invalid_limit", str(exc), 400)
    filters: dict[str, Any] = {}
    page_type = request.query_params.get("type")
    tag = request.query_params.get("tag")
    if page_type:
        filters["type"] = page_type
    if tag:
        filters["tags"] = [tag]
    return JSONResponse(_store(request).search(query, limit, filters=filters or None))


async def pages_endpoint(request: Request) -> JSONResponse:
    try:
        limit = _limit(request.query_params.get("limit"), 50, 500)
    except ValueError as exc:
        return _error("invalid_limit", str(exc), 400)
    return JSONResponse(_store(request).list(limit))


async def page_endpoint(request: Request) -> JSONResponse:
    page_path = request.path_params.get("page_path", "")
    try:
        return JSONResponse(_store(request).read(page_path))
    except MemoryWriteError as exc:
        message = str(exc)
        status = 404 if message.startswith("page not found:") else 400
        return _error("page_not_found" if status == 404 else "invalid_page", message, status)


async def reflect_endpoint(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _error("invalid_json", "request body must be valid JSON", 400)
    if not isinstance(payload, dict):
        return _error("invalid_json", "request body must be a JSON object", 400)
    query = str(payload.get("query", "")).strip()
    if not query:
        return _error("invalid_query", "reflect requires a non-empty query", 400)
    try:
        limit = _limit(str(payload["limit"]) if "limit" in payload else None, 8, 20)
    except ValueError as exc:
        return _error("invalid_limit", str(exc), 400)

    store = _store(request)
    hits = store.search(query, limit).get("results", [])
    pages: list[dict[str, str]] = []
    for hit in hits:
        try:
            page = store.read(hit["path"])
        except MemoryWriteError:
            continue
        pages.append({"path": hit["path"], "content": page["content"]})
    if not pages:
        return JSONResponse({"query": query, "reflection": "No relevant wiki pages found.", "sources": []})
    try:
        reflection = _run_reflection(query, pages)
    except Exception as exc:
        return _error("reflection_failed", str(exc), 500)
    return JSONResponse({
        "query": query,
        "reflection": reflection,
        "sources": [{"path": page["path"]} for page in pages],
    })


def create_web_app(vault_path: str | None = None) -> Starlette:
    app = Starlette(
        routes=[
            Route("/api/health", health_endpoint, methods=["GET"]),
            Route("/api/search", search_endpoint, methods=["GET"]),
            Route("/api/pages", pages_endpoint, methods=["GET"]),
            Route("/api/pages/{page_path:path}", page_endpoint, methods=["GET"]),
            Route("/api/reflect", reflect_endpoint, methods=["POST"]),
        ]
    )
    app.state.store = MemoryStore(vault_path or configured_vault_path())
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET", "POST"],
        allow_headers=["content-type"],
    )
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Obsidian memory web API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--vault-path")
    args = parser.parse_args()
    uvicorn.run(create_web_app(args.vault_path), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
