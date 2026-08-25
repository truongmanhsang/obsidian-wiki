"""Log helpers - SQLite backed (log.db) with markdown view for Obsidian."""

from __future__ import annotations

import re
import os
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

LOG_HEADER = """# Wiki Operation Log

Journal of every wiki operation. Each line: date - TYPE - description.
Maintained automatically by the obsidianwiki memory plugin.
"""

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _db_path(vault) -> Path:
    return vault.root / "log.db"

def _connect(vault) -> sqlite3.Connection:
    db = _db_path(vault)
    if not db.exists():
        db.parent.mkdir(parents=True, exist_ok=True)
        db.touch(mode=0o600)
    else:
        os.chmod(db, 0o600)
    # timeout=5 handles iCloud lock; check_same_thread False for safety
    conn = sqlite3.connect(str(db), timeout=5, check_same_thread=False, isolation_level=None)
    # WAL mode + normal sync for concurrency + iCloud safety
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
    except Exception:
        pass
    return conn

def _ensure_db(vault) -> None:
    db = _db_path(vault)
    # ensure parent exists
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = _connect(vault)
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                kind TEXT NOT NULL,
                message TEXT NOT NULL,
                is_auto INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_date_kind ON logs(date, kind);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_kind_auto ON logs(kind, is_auto);")
        conn.commit()
    finally:
        conn.close()

def _format_line(row) -> str:
    # row: (date, kind, message, is_auto)
    d, kind, msg, is_auto = row
    auto = " (auto)" if is_auto else ""
    return f"- {d} {kind}{auto}: {msg}"

def _sync_markdown_view(vault) -> None:
    """Regenerate log.md from DB (read-only view for Obsidian)."""
    _ensure_db(vault)
    conn = _connect(vault)
    try:
        cur = conn.execute("SELECT date, kind, message, is_auto FROM logs ORDER BY id ASC;")
        rows = cur.fetchall()
    finally:
        conn.close()
    lines = [LOG_HEADER.rstrip(), ""]
    for r in rows:
        lines.append(_format_line(r))
    # ensure file ends with newline
    content = "\n".join(lines) + ("\n" if lines else "")
    # atomic write via temp file to avoid iCloud partial read
    tmp = vault.root / ".log.md.tmp"
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(vault.log_path)

# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

_LOG_LINE_RE = re.compile(
    r"^- (\d{4}-\d{2}-\d{2}) (\w+)(?:\(auto\)| \(auto\))?: (.*)$"
)

def migrate_log_md_to_db(vault) -> int:
    """Parse existing log.md and insert into log.db, then rename to log.md.bak.

    Returns number of rows inserted. Idempotent: if log.db already has rows, skips.
    """
    md_path = vault.log_path  # log.md
    db_path = _db_path(vault)
    if not md_path.exists():
        _ensure_db(vault)
        return 0
    _ensure_db(vault)
    # if DB already has data, assume already migrated (avoid double insert)
    conn = _connect(vault)
    try:
        cur = conn.execute("SELECT COUNT(*) FROM logs;")
        cnt = cur.fetchone()[0]
        if cnt and cnt > 0:
            # still ensure markdown view is synced; if log.md is newer than bak, keep it
            # but don't re-migrate
            return 0
    finally:
        conn.close()

    text = md_path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    rows = []
    now_iso = datetime.now(timezone.utc).isoformat()
    for line in lines:
        line = line.rstrip()
        if not line.startswith("- "):
            continue
        m = _LOG_LINE_RE.match(line)
        if not m:
            continue
        d, kind, msg = m.groups()
        # detect auto: line contains "(auto)"
        is_auto = 1 if "(auto)" in line else 0
        kind = kind.upper()
        # normalize kind to allowed set? keep as-is uppercased
        rows.append((d, kind, msg.strip(), is_auto, now_iso))

    if not rows:
        # empty vault: just ensure DB and backup
        pass
    else:
        conn = _connect(vault)
        try:
            conn.executemany(
                "INSERT INTO logs (date, kind, message, is_auto, created_at) VALUES (?, ?, ?, ?, ?);",
                rows,
            )
            conn.commit()
        finally:
            conn.close()

    # backup original
    bak = md_path.with_suffix(".md.bak")
    # if bak exists, version it
    if bak.exists():
        bak2 = md_path.with_suffix(f".md.bak.{datetime.now().strftime('%Y%m%d%H%M%S')}")
        md_path.rename(bak2)
    else:
        md_path.rename(bak)

    # regenerate read-only view
    # _sync_markdown_view disabled — log.md removed per user request 2026-08-23
    return len(rows)

# ---------------------------------------------------------------------------
# Public API (vault delegates here)
# ---------------------------------------------------------------------------

def append_log(vault, kind: str, description: str, quiet: bool = False) -> None:
    kinds = {"SETUP", "INGEST", "QUERY", "LINT", "REFLECT", "WRITE", "UPDATE", "READ", "INDEX_REBUILT"}
    kind = kind.upper() if kind.upper() in kinds else "QUERY"
    today = date.today().isoformat()
    now_iso = datetime.now(timezone.utc).isoformat()
    description = description.strip()

    # ensure DB + migrate on first run
    if not _db_path(vault).exists() and vault.log_path.exists():
        try:
            migrate_log_md_to_db(vault)
        except Exception:
            _ensure_db(vault)
    else:
        _ensure_db(vault)
        # if log.md exists but db empty, migrate (covers ensure_skeleton race)
        if vault.log_path.exists():
            conn = _connect(vault)
            try:
                cur = conn.execute("SELECT COUNT(*) FROM logs;")
                cnt = cur.fetchone()[0]
            finally:
                conn.close()
            if cnt == 0:
                try:
                    migrate_log_md_to_db(vault)
                except Exception:
                    pass

    conn = _connect(vault)
    try:
        if not quiet:
            conn.execute(
                "INSERT INTO logs (date, kind, message, is_auto, created_at) VALUES (?, ?, ?, ?, ?);",
                (today, kind, description, 0, now_iso),
            )
            conn.commit()
        else:
            # quiet: aggregate into single daily auto line per kind
            cur = conn.execute(
                "SELECT id, message FROM logs WHERE date=? AND kind=? AND is_auto=1 ORDER BY id DESC LIMIT 1;",
                (today, kind),
            )
            row = cur.fetchone()
            if row is not None:
                rid, msg = row
                m = re.search(r"\b(\d+) ops\b", msg)
                count = int(m.group(1)) if m else 0
                if kind == "INDEX_REBUILT":
                    new_msg = description
                else:
                    new_msg = f"{count + 1} ops (latest: {description[:80]})"
                conn.execute(
                    "UPDATE logs SET message=?, created_at=? WHERE id=?;",
                    (new_msg, now_iso, rid),
                )
                conn.commit()
            else:
                new_msg = f"1 ops (latest: {description[:80]})"
                conn.execute(
                    "INSERT INTO logs (date, kind, message, is_auto, created_at) VALUES (?, ?, ?, ?, ?);",
                    (today, kind, new_msg, 1, now_iso),
                )
                conn.commit()
    finally:
        conn.close()

    # keep markdown view in sync (best effort, ignore iCloud errors) — disabled per user request 2026-08-23
    pass

def log_tail(vault, lines: int = 30) -> str:
    _ensure_db(vault)
    # if DB empty but log.md exists (pre-migration), migrate
    conn = _connect(vault)
    try:
        cur = conn.execute("SELECT COUNT(*) FROM logs;")
        cnt = cur.fetchone()[0]
        if cnt == 0 and vault.log_path.exists():
            # check if log_path has content beyond header
            try:
                txt = vault.log_path.read_text(encoding="utf-8")
                if "- " in txt:
                    conn.close()
                    try:
                        migrate_log_md_to_db(vault)
                    except Exception:
                        pass
                    conn = _connect(vault)
            except OSError:
                pass
        cur = conn.execute(
            "SELECT date, kind, message, is_auto FROM logs ORDER BY id DESC LIMIT ?;",
            (lines,),
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    if not rows:
        return ""
    rows = list(reversed(rows))
    return "\n".join(_format_line(r) for r in rows)

# helper for lint - expose raw log rows
def _iter_log_rows(vault):
    _ensure_db(vault)
    conn = _connect(vault)
    try:
        cur = conn.execute("SELECT date, kind, message, is_auto, created_at FROM logs ORDER BY id ASC;")
        rows = cur.fetchall()
    finally:
        conn.close()
    return rows
