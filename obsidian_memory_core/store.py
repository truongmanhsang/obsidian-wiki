"""Concurrency-safe façade over the existing WikiVault implementation."""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .wiki import WikiVault, WikiVaultError


class MemoryWriteError(WikiVaultError):
    """Raised when a memory write cannot be completed safely."""


class RevisionConflict(MemoryWriteError):
    """Raised when an optimistic-concurrency revision is stale."""


class MemoryStore:
    """Stable API shared by Hermes, MCP, and future adapters."""

    def __init__(self, vault_path: str | os.PathLike[str]):
        self.root = Path(vault_path).expanduser().resolve()
        self.vault = WikiVault(str(self.root))
        self.lock_path = self.root / ".obsidian-memory.lock"

    def ensure_ready(self) -> None:
        self.vault.ensure_skeleton()

    @contextmanager
    def _write_lock(self) -> Iterator[None]:
        self.root.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as fh:
            try:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            except ImportError:
                pass
            try:
                yield
            finally:
                try:
                    import fcntl
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                except ImportError:
                    pass

    def _page_path(self, page: str) -> Path:
        path = self.vault.safe_resolve(page)
        if path.suffix != ".md":
            path = path.with_suffix(".md")
        return path

    def _revision(self, page: str) -> str | None:
        path = self._page_path(page)
        if not path.exists():
            return None
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def read(self, page: str) -> dict[str, Any]:
        path = self._page_path(page)
        if path.suffix != ".md":
            path = path.with_suffix(".md")
        if not path.exists():
            raise MemoryWriteError(f"page not found: {page}")
        text = path.read_text(encoding="utf-8")
        return {
            "path": str(path.relative_to(self.root)),
            "content": text[:20000],
            "truncated": len(text) > 20000,
            "revision": hashlib.sha256(text.encode()).hexdigest(),
        }

    def search(self, query: str, limit: int = 5) -> dict[str, Any]:
        results = self.vault.search(query, limit=limit)
        return {"results": results, "count": len(results)}

    def list(self, limit: int = 50) -> dict[str, Any]:
        pages = self.vault.load_pages()
        return {
            "stats": self.vault.stats(),
            "pages": [{"path": p["rel"], "title": p["title"], "type": p["ptype"], "updated": p["updated"]} for p in pages[:limit]],
        }

    def lint(self) -> dict[str, Any]:
        return self.vault.lint()

    def log(self, limit: int = 30) -> dict[str, Any]:
        return {"log_tail": self.vault.log_tail(limit)}

    def write(self, page: str, content: str, note: str = "", expected_revision: str | None = None, allow_duplicate: bool = False) -> dict[str, Any]:
        if not isinstance(page, str) or not page.strip():
            raise MemoryWriteError("write requires a page")
        if not isinstance(content, str) or not content.strip():
            raise MemoryWriteError("write requires non-empty content")
        with self._write_lock():
            current = self._revision(page)
            if expected_revision is not None and current != expected_revision:
                raise RevisionConflict(f"revision conflict for {page}; read the page again before updating")
            result = self.vault.write_page(page, content, note=note, allow_duplicate=allow_duplicate)
            result["revision"] = self._revision(page)
            return result

    def call(self, action: str, **kwargs: Any) -> dict[str, Any]:
        if action == "read": return self.read(kwargs["page"])
        if action == "search": return self.search(kwargs["query"], int(kwargs.get("limit", 5)))
        if action == "list": return self.list(int(kwargs.get("limit", 50)))
        if action == "lint": return self.lint()
        if action == "log": return self.log(int(kwargs.get("limit", 30)))
        if action == "write": return self.write(kwargs["page"], kwargs["content"], kwargs.get("note", ""), kwargs.get("expected_revision"), bool(kwargs.get("allow_duplicate", False)))
        raise MemoryWriteError(f"unknown action: {action}")


def json_result(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False)
