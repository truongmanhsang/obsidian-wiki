"""Central ingest job queue for one memory-server process."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .store import MemoryStore


class IngestJobManager:
    """Serialize capture/extraction jobs and make retries idempotent."""

    def __init__(self, store: MemoryStore, plugin_root: Path | None = None):
        self.store = store
        self.plugin_root = plugin_root or Path(__file__).resolve().parents[1]
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._requests: dict[str, str] = {}
        self._running: str | None = None
        self._worker_lock = threading.Lock()

    def submit(self, request_id: str | None = None, session_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            if request_id and request_id in self._requests:
                return self._jobs[self._requests[request_id]].copy()
            job_id = f"ingest-{uuid.uuid4().hex[:12]}"
            job = {"job_id": job_id, "request_id": request_id, "session_id": session_id,
                   "status": "queued", "submitted_at": self._now()}
            self._jobs[job_id] = job
            if request_id:
                self._requests[request_id] = job_id
            threading.Thread(target=self._run, args=(job_id,), daemon=True).start()
            return job.copy()

    def status(self, job_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            if job_id:
                return self._jobs.get(job_id, {"error": "job_not_found", "job_id": job_id}).copy()
            return {"running": self._running, "jobs": list(self._jobs.values())[-50:]}

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _set(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            self._jobs[job_id].update(fields)

    def _run(self, job_id: str) -> None:
        self._worker_lock.acquire()
        job = self._jobs[job_id]
        self._set(job_id, status="running", started_at=self._now())
        with self._lock:
            self._running = job_id
        try:
            scripts = self.plugin_root / "scripts"
            env = os.environ.copy()
            env.setdefault("OBSIDIAN_VAULT_PATH", str(self.store.root))
            capture = [sys.executable, str(scripts / "wiki_session_capture.py"), "--min-chars", "300"]
            if job.get("session_id"):
                capture += ["--session", str(job["session_id"])]
            first = subprocess.run(capture, capture_output=True, text=True, timeout=120, env=env)
            if first.returncode != 0:
                raise RuntimeError((first.stderr or first.stdout or "capture failed")[-1000:])
            extract = [sys.executable, str(scripts / "wiki_session_extract.py"), "--apply"]
            second = subprocess.run(extract, capture_output=True, text=True, timeout=900, env=env)
            if second.returncode != 0:
                raise RuntimeError((second.stderr or second.stdout or "extract failed")[-1000:])
            self._set(job_id, status="completed", finished_at=self._now(), capture_output=first.stdout[-2000:], extract_output=second.stdout[-4000:])
        except Exception as exc:
            self._set(job_id, status="failed", finished_at=self._now(), error=str(exc)[:1000])
        finally:
            self._worker_lock.release()
            with self._lock:
                if self._running == job_id:
                    self._running = None


def load_manager(vault_path: str) -> IngestJobManager:
    store = MemoryStore(vault_path)
    store.ensure_ready()
    return IngestJobManager(store)


def json_status(manager: IngestJobManager) -> str:
    return json.dumps(manager.status(), ensure_ascii=False)


__all__ = ["IngestJobManager", "load_manager", "json_status"]
