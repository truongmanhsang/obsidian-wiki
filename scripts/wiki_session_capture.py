#!/usr/bin/env python3
"""Capture Hermes sessions into the agent-vault wiki as raw sources.

Exports user+assistant conversation turns from ~/.hermes/state.db into
sources/sessions/<session-id>.md pages in the Obsidian vault. Tool results
and session metadata are skipped; only the human-readable dialogue is kept,
verbatim, as an immutable source document.

Usage:
  python3 wiki_session_capture.py                    # all uncaptured sessions
  python3 wiki_session_capture.py --session <id>     # one specific session
  python3 wiki_session_capture.py --min-chars 200    # skip tiny sessions

Idempotent: a session already captured (page exists) is skipped unless
--force. The plugin's write path maintains index.md + log.md automatically.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

HERMES_STATE = Path(os.environ.get("HERMES_STATE_DB", str(Path.home() / ".hermes" / "state.db")))
PLUGIN_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_DIR))

from obsidian_memory_core.wiki import WikiVault  # noqa: E402
from obsidian_memory_core import MemoryStore  # noqa: E402
from obsidian_memory_core.config import vault_path  # noqa: E402


def clean_content(text: str) -> str:
    """Strip gateway noise wrappers from message content."""
    if not isinstance(text, str):
        return ""
    # OUT-OF-BAND markers keep content but drop the wrapper lines
    text = re.sub(r"\[OUT-OF-BAND USER MESSAGE[^\]]*\]", "", text)
    text = re.sub(r"\[/OUT-OF-BAND USER MESSAGE\]", "", text)
    # memory-context system notes injected into user turns are not user speech
    if "<memory-context>" in text and "</memory-context>" in text:
        text = re.sub(r"<memory-context>.*?</memory-context>", "", text, flags=re.DOTALL)
        text = re.sub(r"<available-memories>.*?</available-memories>", "", text, flags=re.DOTALL)
    text = re.sub(r"(?i)(authorization\s*:\s*bearer\s+)[^\s]+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)(api[_ -]?key\s*[:=]\s*)[^\s,]+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)(password|passwd|secret|token)\s*[:=]\s*[^\s,]+", r"\1=[REDACTED]", text)
    text = re.sub(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", "[REDACTED PRIVATE KEY]", text, flags=re.DOTALL)
    return text.strip()


def yaml_single_quote(value: str) -> str:
    """Quote a scalar safely for YAML frontmatter."""
    return "'" + str(value).replace("'", "''") + "'"


def export_session(cur, session_id: str) -> tuple[str, int, int] | None:
    """Return (markdown, n_turns) for one session, or None if empty."""
    rows = cur.execute(
        "SELECT role, content, timestamp FROM messages "
        "WHERE session_id=? AND role IN ('user','assistant') AND active=1 "
        "ORDER BY id",
        (session_id,),
    ).fetchall()

    title_row = cur.execute(
        "SELECT title, started_at FROM sessions WHERE id=?", (session_id,)
    ).fetchone()
    title = (title_row[0] if title_row and title_row[0] else session_id)
    started = title_row[1] if title_row else ""

    parts = [
        "---",
        "type: source",
        f"updated: {date.today().isoformat()}",
        f"session: {session_id}",
        "tags:",
        "  - session",
        "aliases:",
        f"  - {yaml_single_quote(title)}",
        "extract_status: pending",
        "---",
        "",
        f"# Session {title}",
        "",
    ]
    if started:
        parts.append(f"> Started: {started}")
        parts.append("")

    n_turns = 0
    dialogue_chars = 0
    for role, content, ts in rows:
        text = clean_content(content or "")
        if len(text) < 1:
            continue
        # Keep exported transcripts portable across users and deployments.
        # The database role is the stable source of truth; never bake a
        # particular person's name into the capture format.
        label = str(role).strip().capitalize() or "Unknown"
        stamp = f" ({str(ts)[:16]})" if ts else ""
        parts.append(f"## {label}{stamp}")
        parts.append("")
        parts.append(text)
        parts.append("")
        n_turns += 1
        dialogue_chars += len(text)
    if n_turns == 0:
        return None
    return "\n".join(parts), n_turns, dialogue_chars


def ensure_extract_status(path: Path, status: str = "pending") -> None:
    """Restore source-only bookkeeping stripped by WikiVault normalization."""
    text = path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    if len(parts) < 3:
        return
    fm, body = parts[1], parts[2]
    if re.search(r"(?m)^extract_status:", fm):
        fm = re.sub(r"(?m)^extract_status:.*$", f"extract_status: {status}", fm, count=1)
    else:
        fm = re.sub(r"(?m)^(aliases:[^\n]*)$", rf"\1\nextract_status: {status}", fm, count=1)
    path.write_text(f"---{fm}\n---{body}", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", help="capture one specific session id")
    ap.add_argument("--min-chars", type=int, default=300,
                    help="skip sessions with less dialogue than this")
    ap.add_argument("--force", action="store_true",
                    help="re-capture even if the page already exists")
    args = ap.parse_args()

    if not HERMES_STATE.exists():
        print(f"no state db at {HERMES_STATE}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(f"file:{HERMES_STATE}?mode=ro", uri=True)
    cur = conn.cursor()

    def is_cron_session(sid: str) -> bool:
        """Cron-generated sessions are operational noise, not user memory."""
        return sid.startswith("cron_")

    if args.session:
        sessions = [args.session] if not is_cron_session(args.session) else []
    else:
        sessions = [
            r[0] for r in cur.execute(
                "SELECT DISTINCT session_id FROM messages "
                "WHERE role IN ('user','assistant') GROUP BY session_id"
            )
            if not is_cron_session(r[0])
        ]

    store = MemoryStore(vault_path())
    vault = store.vault

    def dated_rel(sid: str) -> str:
        """sources/sessions/YYYY/MM/DD/<sid> - date from the session id.
        Handles plain ids (20260823_084543_ab12) and cron ids
        (cron_<hash>_20260628_070010) which embed the date mid-string."""
        # Session IDs are external input; keep them a single safe filename.
        safe_sid = re.sub(r"[^A-Za-z0-9._-]", "_", sid).strip(".")[:120] or "unknown"
        m = re.match(r"(\d{4})(\d{2})(\d{2})_", safe_sid)
        if not m:
            m = re.search(r"_(\d{4})(\d{2})(\d{2})_", safe_sid)
        if m:
            return f"sources/sessions/{m.group(1)}/{m.group(2)}/{m.group(3)}/{safe_sid}"
        return f"sources/sessions/unsorted/{safe_sid}"

    def target_path(sid: str) -> Path:
        return vault.root / (dated_rel(sid) + ".md")

    captured, skipped_small, skipped_exists = [], 0, 0
    for sid in sessions:
        target = target_path(sid)
        if target.exists() and not args.force:
            skipped_exists += 1
            continue
        result = export_session(cur, sid)
        if result is None:
            skipped_small += 1
            continue
        markdown, n_turns, dialogue_chars = result
        # Measure human dialogue only; YAML, headings, and timestamps must not
        # make a greeting-sized session eligible for extraction.
        if dialogue_chars < args.min_chars:
            skipped_small += 1
            continue
        store.write_ingest(
            dated_rel(sid),
            markdown,
            note=f"captured {n_turns} turns from state.db",
        )
        store.update_ingest_status(dated_rel(sid), "pending")
        captured.append((dated_rel(sid), n_turns, dialogue_chars))

    conn.close()
    print(json.dumps({
        "captured": captured,
        "already_captured": skipped_exists,
        "skipped_too_small": skipped_small,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
