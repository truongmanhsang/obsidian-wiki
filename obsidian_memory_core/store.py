"""Concurrency-safe facade over the existing WikiVault implementation."""

from __future__ import annotations

import hashlib
import json
import os
import re
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
            except ImportError as exc:
                raise MemoryWriteError("exclusive file locking is unavailable on this platform") from exc
            try:
                yield
            finally:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    def _page_path(self, page: str) -> Path:
        path = self.vault.safe_resolve(page)
        if path.suffix != ".md":
            path = path.with_suffix(".md")
        relative = path.relative_to(self.root)
        allowed = {"entities", "people", "decisions", "environment", "concepts", "answers", "preferences"}
        if len(relative.parts) < 2 or relative.parts[0] not in allowed:
            raise MemoryWriteError("only wiki pages in an allowed content folder are accessible")
        return path

    def _source_path(self, page: str) -> Path:
        path = self.vault.safe_resolve(page)
        if path.suffix != ".md":
            path = path.with_suffix(".md")
        relative = path.relative_to(self.root)
        if len(relative.parts) < 2 or relative.parts[0] != "sources":
            raise MemoryWriteError("ingest pages must live under sources/")
        return path

    def _revision(self, page: str) -> str | None:
        path = self.vault.safe_resolve(page)
        if path.suffix != ".md":
            path = path.with_suffix(".md")
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
        revision = hashlib.sha256(path.read_bytes()).hexdigest()
        return {
            "path": str(path.relative_to(self.root)),
            "content": text[:20000],
            "truncated": len(text) > 20000,
            "revision": revision,
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
        if page.split('/', 1)[0] == 'sources':
            raise MemoryWriteError('sources/ is read-only')
        # MCP clients may serialize an omitted optional string as "".
        # Treat that sentinel as no revision, which is valid for creation;
        # a real revision is always a non-empty SHA-256 string.
        expected_revision = expected_revision or None
        with self._write_lock():
            current = self._revision(page)
            if current is not None and expected_revision is None:
                raise RevisionConflict(f"expected_revision is required when updating {page}")
            if expected_revision is not None and current != expected_revision:
                raise RevisionConflict(f"revision conflict for {page}; read the page again before updating")
            result = self.vault.write_page(page, content, note=note, allow_duplicate=allow_duplicate)
            result["revision"] = self._revision(page)
            return result

    def delete(self, page: str, expected_revision: str | None = None, note: str = "") -> dict[str, Any]:
        """Delete one curated page with optimistic concurrency protection."""
        if not isinstance(page, str) or not page.strip():
            raise MemoryWriteError("delete requires a page")
        if page.split('/', 1)[0] == 'sources':
            raise MemoryWriteError('sources/ is read-only')
        with self._write_lock():
            current = self._revision(page)
            if current is None:
                raise MemoryWriteError(f"page not found: {page}")
            if expected_revision is None:
                raise RevisionConflict(f"expected_revision is required when deleting {page}")
            if current != expected_revision:
                raise RevisionConflict(f"revision conflict for {page}; read the page again before deleting")
            result = self.vault.delete_page(page, note=note)
            result["revision"] = None
            return result

    def append(self, page: str, content: str, note: str = "", expected_revision: str | None = None) -> dict[str, Any]:
        """Append content to an existing curated page without replacing it."""
        if not isinstance(page, str) or not page.strip():
            raise MemoryWriteError("append requires a page")
        if not isinstance(content, str) or not content.strip():
            raise MemoryWriteError("append requires non-empty content")
        if page.split('/', 1)[0] == 'sources':
            raise MemoryWriteError('sources/ is read-only')
        expected_revision = expected_revision or None
        with self._write_lock():
            current = self._revision(page)
            if current is None:
                raise MemoryWriteError(f"page not found: {page}")
            if expected_revision is None:
                raise RevisionConflict(f"expected_revision is required when appending {page}")
            if current != expected_revision:
                raise RevisionConflict(f"revision conflict for {page}; read the page again before appending")
            path = self._page_path(page)
            previous = path.read_text(encoding="utf-8")
            previous_stripped = previous.strip()
            content_stripped = content.strip()

            # Protect against AGY accidentally sending the full page to append.
            # The existing page must not be duplicated or rewritten as an append.
            if previous_stripped and previous_stripped in content_stripped:
                raise MemoryWriteError(
                    "append content appears to contain the entire existing page; "
                    "send only the new section"
                )

            # Make repeated identical append requests idempotent. Return the
            # current revision without touching the file, index, or log.
            if content_stripped and content_stripped in previous_stripped:
                return {
                    "status": "unchanged",
                    "path": str(path),
                    "reason": "content_already_present",
                    "revision": current,
                }

            separator = "" if previous.endswith("\n\n") else "\n"
            merged = previous + separator + content.lstrip("\n")
            result = self.vault.write_page(page, merged, note=note, allow_duplicate=True)
            result["revision"] = self._revision(page)
            return result

    def write_ingest(self, page: str, content: str, note: str = "") -> dict[str, Any]:
        """Write a captured source through the shared lock and audit path."""
        if not isinstance(page, str) or not page.strip():
            raise MemoryWriteError("ingest requires a page")
        if not isinstance(content, str) or not content.strip():
            raise MemoryWriteError("ingest requires non-empty content")
        with self._write_lock():
            self._source_path(page)
            return self.vault.write_page(page, content, note=note, allow_source=True)

    def update_ingest_status(self, page: str, status: str) -> None:
        """Update capture metadata while retaining the shared write lock."""
        if status not in {"pending", "success", "skip", "fail"}:
            raise MemoryWriteError(f"invalid ingest status: {status}")
        with self._write_lock():
            path = self._source_path(page)
            if not path.exists():
                raise MemoryWriteError(f"ingest page not found: {page}")
            text = path.read_text(encoding="utf-8")
            match = re.match(r"(?s)^---\n(.*?)\n---\n?(.*)$", text)
            if not match:
                raise MemoryWriteError(f"ingest page has invalid frontmatter: {page}")
            fm, body = match.groups()
            if re.search(r"(?m)^extract_status:", fm):
                fm = re.sub(r"(?m)^extract_status:.*$", f"extract_status: {status}", fm, count=1)
            else:
                # Keep the field at YAML top level.  Appending after
                # ``aliases:`` is unsafe when aliases is a block list.
                fm = re.sub(r"(?m)^(updated:[^\n]*|session:[^\n]*)$",
                            rf"\1\nextract_status: {status}", fm, count=1)
                if not re.search(r"(?m)^extract_status:", fm):
                    fm = f"extract_status: {status}\n{fm.lstrip()}"
            # Do not route this metadata-only source update through
            # WikiVault.write_page: that canonicalizes frontmatter and drops
            # source bookkeeping fields such as extract_status.  The caller
            # already holds the exclusive lock, so an atomic replacement is
            # safe and preserves the complete source document.
            path.write_text(f"---\n{fm}\n---\n{body}", encoding="utf-8")

    def call(self, action: str, **kwargs: Any) -> dict[str, Any]:
        if action == "read": return self.read(kwargs["page"])
        if action == "search": return self.search(kwargs["query"], int(kwargs.get("limit", 5)))
        if action == "list": return self.list(int(kwargs.get("limit", 50)))
        if action == "lint": return self.lint()
        if action == "log": return self.log(int(kwargs.get("limit", 30)))
        if action == "write": return self.write(kwargs["page"], kwargs["content"], kwargs.get("note", ""), kwargs.get("expected_revision"), bool(kwargs.get("allow_duplicate", False)))
        if action == "append": return self.append(kwargs["page"], kwargs["content"], kwargs.get("note", ""), kwargs.get("expected_revision"))
        if action == "delete": return self.delete(kwargs["page"], kwargs.get("expected_revision"), kwargs.get("note", ""))
        raise MemoryWriteError(f"unknown action: {action}")


def json_result(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False)
