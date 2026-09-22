"""JSON HTTP adapter and single-process web workspace for Obsidian memory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import uvicorn
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from obsidian_memory_core import MemoryStore
from obsidian_memory_core.config import vault_path as configured_vault_path
from obsidian_memory_core.jobs import IngestJobReader
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


def _ingest(request: Request) -> IngestJobReader:
    return request.app.state.ingest_manager


async def health_endpoint(request: Request) -> JSONResponse:
    store = _store(request)
    stats = store.list(1).get("stats", {})
    return JSONResponse(
        {
            "ok": True,
            "service": "obsidian-memory",
            "pages": sum(int(value or 0) for value in stats.values()),
        }
    )


async def search_endpoint(request: Request) -> JSONResponse:
    query = request.query_params.get("q", "").strip()
    if not query:
        return _error("invalid_query", "search requires a non-empty q parameter", 400)
    try:
        limit = _limit(request.query_params.get("limit"), 10, 50)
    except ValueError as exc:
        return _error("invalid_limit", str(exc), 400)

    filters: dict[str, Any] = {}
    page_type = request.query_params.get("type")
    tag = request.query_params.get("tag")
    updated_after = request.query_params.get("updated_after")
    path_prefix = request.query_params.get("path_prefix")
    if page_type:
        filters["type"] = page_type
    if tag:
        filters["tags"] = [tag]
    if updated_after:
        filters["updated_after"] = updated_after
    if path_prefix:
        filters["path_prefix"] = path_prefix
    if request.query_params.get("include_sources") == "true":
        filters["include_sources"] = True

    precise = request.query_params.get("precise", "true").lower() != "false"
    return JSONResponse(
        _store(request).search(query, limit, filters=filters or None, precise=precise)
    )


async def graph_endpoint(request: Request) -> JSONResponse:
    return JSONResponse(_store(request).graph())


async def pages_endpoint(request: Request) -> JSONResponse:
    try:
        limit = _limit(request.query_params.get("limit"), 25, 100)
        offset_raw = request.query_params.get("offset", "0")
        offset = int(offset_raw)
        if offset < 0:
            raise ValueError("offset must be at least 0")
    except (TypeError, ValueError) as exc:
        return _error("invalid_pagination", str(exc), 400)

    page_type = request.query_params.get("type") or None
    query = request.query_params.get("q") or None
    return JSONResponse(
        _store(request).list(limit, offset=offset, page_type=page_type, query=query)
    )


async def resolve_page_endpoint(request: Request) -> JSONResponse:
    target = request.query_params.get("target", "").strip()
    from_page = request.query_params.get("from") or None
    if not target:
        return _error("invalid_target", "resolve requires a non-empty target parameter", 400)
    try:
        return JSONResponse(_store(request).resolve_page(target, from_page=from_page))
    except MemoryWriteError as exc:
        return _error("page_not_found", str(exc), 404)


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
    hits = store.search(query, limit, precise=False).get("results", [])
    pages: list[dict[str, str]] = []
    for hit in hits:
        try:
            page = store.read(hit["path"])
        except MemoryWriteError:
            continue
        pages.append({"path": hit["path"], "content": page["content"]})

    if not pages:
        return JSONResponse(
            {"query": query, "reflection": "No relevant wiki pages found.", "sources": []}
        )

    try:
        reflection = _run_reflection(query, pages)
    except Exception as exc:
        return _error("reflection_failed", str(exc), 500)

    return JSONResponse(
        {
            "query": query,
            "reflection": reflection,
            "sources": [{"path": page["path"]} for page in pages],
        }
    )


async def logs_endpoint(request: Request) -> JSONResponse:
    try:
        limit = _limit(request.query_params.get("limit"), 50, 200)
    except ValueError as exc:
        return _error("invalid_limit", str(exc), 400)
    return JSONResponse(_store(request).log(limit))


async def ingest_status_endpoint(request: Request) -> JSONResponse:
    job_id = request.query_params.get("job_id") or None
    status = _ingest(request).status(job_id)
    if not job_id and not status.get("running"):
        active = next((job for job in status.get("jobs", []) if job.get("status") == "running"), None)
        if active:
            status["running"] = active.get("job_id")
    return JSONResponse(status)


def create_web_app(vault_path: str | None = None) -> Starlette:
    store = MemoryStore(vault_path or configured_vault_path())
    store.ensure_ready()

    routes = [
        Route("/api/health", health_endpoint, methods=["GET"]),
        Route("/api/search", search_endpoint, methods=["GET"]),
        Route("/api/pages", pages_endpoint, methods=["GET"]),
        Route("/api/graph", graph_endpoint, methods=["GET"]),
        Route("/api/resolve", resolve_page_endpoint, methods=["GET"]),
        Route("/api/pages/{page_path:path}", page_endpoint, methods=["GET"]),
        Route("/api/reflect", reflect_endpoint, methods=["POST"]),
        Route("/api/logs", logs_endpoint, methods=["GET"]),
        Route("/api/ingest/status", ingest_status_endpoint, methods=["GET"]),
    ]

    web_dist = Path(__file__).resolve().parent / "web" / "dist"
    if web_dist.is_dir():
        routes.append(Mount("/", app=StaticFiles(directory=str(web_dist), html=True), name="web"))

    app = Starlette(routes=routes)
    app.state.store = store
    app.state.ingest_manager = IngestJobReader()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET", "POST"],
        allow_headers=["content-type"],
    )
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Obsidian memory web workspace")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--vault-path")
    args = parser.parse_args()
    uvicorn.run(create_web_app(args.vault_path), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
