#!/usr/bin/env python3
"""Legacy Hermes session-boundary hook for plugin-owned ingest.

The installed plugin already registers on_session_end/on_session_finalize hooks,
so this script is only for Hermes installations that still use shell hooks.
It queues the same local plugin worker and never sends extraction to MCP.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from obsidian_memory_core import IngestJobManager, MemoryStore
from obsidian_memory_core.config import vault_path


def log(message: str) -> None:
    print(f"wiki-hook: {message}", file=sys.stderr)


def append_audit(message: str) -> None:
    try:
        path = os.path.expanduser("~/.hermes/logs/obsidianwiki-ingest-hook.log")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(message + "\n")
    except Exception:
        pass


def submit(session_id: str) -> dict:
    store = MemoryStore(vault_path())
    store.ensure_ready()
    manager = IngestJobManager(
        store,
        plugin_root=PLUGIN_ROOT,
        state_path=PLUGIN_ROOT / ".state" / "jobs.db",
    )
    return manager.submit(
        request_id=f"{session_id}:completed",
        session_id=session_id,
    )


def main() -> int:
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
        job = submit(session_id)
        message = f"plugin ingest queued {event} job_id={job.get('job_id', '')}"
        log(message)
        append_audit(message)
    except Exception as exc:
        message = f"plugin ingest submit failed {event}: {exc}"
        log(message)
        append_audit(message)
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["main", "submit"]
