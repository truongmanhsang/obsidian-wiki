#!/usr/bin/env python3
"""Post-turn wiki ingest hook - runs after EVERY session turn.

Wired via the `hooks.on_session_end` shell-hook bridge in config.yaml.
Hermes pipes a JSON payload to stdin (session_id, completed, platform, ...);
this script:

1. Captures the CURRENT session's new turns into sources/sessions/ (fast,
   pure sqlite read + file write).
2. Fires the LLM extract step ONLY when the turn actually completed, and
   only for sessions with enough dialogue. Extraction is skipped when:
   - the env var WIKI_INGEST_DISABLE is set
   - the vault is missing
   - another extract is already running (flock on a lockfile)
3. Never raises into the agent path: every failure logs to stderr and
   exits 0 (hooks fail-open by design).

The LLM call takes ~1-3 min; it runs detached (nohup) when triggered from
the hook so Hermes' turn finalizer never waits for it.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"
PLUGIN_DIR = HERMES_HOME / "plugins" / "obsidianwiki"
CAPTURE = PLUGIN_DIR / "scripts" / "wiki_session_capture.py"
EXTRACT = PLUGIN_DIR / "scripts" / "wiki_session_extract.py"
LOCK = HERMES_HOME / "cache" / "wiki-extract.lock"
LOGDIR = HERMES_HOME / "logs"

MIN_TURNS_FOR_EXTRACT = 4


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def safe_session_filename(session_id: str) -> str:
    """Return a bounded filename component with no path separators."""
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", session_id).strip(".")
    return (safe or "adhoc")[:120]


def main() -> int:
    if os.environ.get("WIKI_INGEST_DISABLE"):
        return 0

    try:
        payload = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    except Exception:
        payload = {}

    # Shell-hook serialization keeps non-standard lifecycle fields under
    # `extra`; support both wire shapes so completion is not lost.
    extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
    session_id = str(payload.get("session_id", "") or "")
    completed = bool(payload.get("completed", extra.get("completed", False)))
    platform = str(payload.get("platform", extra.get("platform", "")) or "")

    # Cron transcripts are operational runs and must never enter the wiki.
    # Check both the stable session-id prefix and the hook platform metadata.
    if session_id.startswith("cron_") or platform == "cron":
        return 0

    # 1. Capture this session now (cheap, synchronous).
    captured = False
    try:
        cmd = [sys.executable, str(CAPTURE), "--min-chars", "300"]
        if session_id:
            cmd += ["--session", session_id]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        captured = r.returncode == 0 and '"captured": [' in r.stdout
    except Exception as e:
        log(f"wiki-hook capture failed: {e}")

    if not completed:
        return 0

    # 2. Extract - detached so the turn finalizer never blocks on the LLM.
    LOGDIR.mkdir(parents=True, exist_ok=True)
    stamp = safe_session_filename(session_id)
    out_log = LOGDIR / f"wiki-extract-{stamp}.log"
    detached_cmd = [
        sys.executable, "-c",
        (
            "import fcntl, runpy, sys\n"
            f"h = open({str(LOCK)!r}, 'w')\n"
            "try:\n"
            "    fcntl.flock(h, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
            "except Exception:\n"
            "    sys.exit(3)  # another extract already running\n"
            "sys.argv = ['wiki_session_extract.py', '--apply']\n"
            f"runpy.run_path({str(EXTRACT)!r}, run_name='__main__')\n"
        ),
    ]
    try:
        out_fh = open(out_log, "w", encoding="utf-8")
        os.chmod(out_log, 0o600)
        subprocess.Popen(
            detached_cmd,
            stdin=subprocess.DEVNULL,
            stdout=out_fh,
            stderr=out_fh,
            start_new_session=True,
        )
        log(f"wiki-hook: extract launched in background (log: {out_log})")
    except Exception as e:
        log(f"wiki-hook could not launch extract: {e}")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # hooks must never break the agent
        log(f"wiki-hook fatal (ignored): {e}")
        sys.exit(0)
