#!/usr/bin/env python3
"""Submit an ingest job to the plugin-owned local worker.

This utility must run in the Hermes/plugin Python environment. It never asks
the MCP server to execute extraction.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from obsidian_memory_core import IngestJobManager, MemoryStore
from obsidian_memory_core.config import vault_path as configured_vault_path

DEFAULT_JOB_DB = PLUGIN_ROOT / ".state" / "jobs.db"


def submit(
    request_id: str | None,
    session_id: str | None,
    *,
    vault_path: str | None = None,
    job_db: str | None = None,
) -> dict:
    store = MemoryStore(vault_path or configured_vault_path())
    store.ensure_ready()
    manager = IngestJobManager(
        store,
        plugin_root=PLUGIN_ROOT,
        state_path=Path(job_db).expanduser() if job_db else DEFAULT_JOB_DB,
    )
    return manager.submit(request_id=request_id, session_id=session_id)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request-id")
    parser.add_argument("--session-id")
    parser.add_argument("--vault-path")
    parser.add_argument("--job-db")
    args = parser.parse_args()
    result = submit(
        args.request_id,
        args.session_id,
        vault_path=args.vault_path,
        job_db=args.job_db,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
