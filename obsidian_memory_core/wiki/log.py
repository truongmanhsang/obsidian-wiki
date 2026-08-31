"""Log helpers - SQLite backed (log.db) with markdown view for Obsidian."""

from __future__ import annotations

import re
import os
from datetime import date, datetime, timezone
from pathlib import Path
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session
from obsidian_memory_core.db.models import LogEntry
from obsidian_memory_core.db.migrations import LOG_MIGRATION_DIR, upgrade

LOG_HEADER = """# Wiki Operation Log

Journal of every wiki operation. Each line: date - TYPE - description.
Maintained automatically by the obsidianwiki memory plugin.
"""

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _db_path(vault) -> Path:
    return vault.root / "log.db"

def _engine(vault):
    db = _db_path(vault)
    if not db.exists():
        db.parent.mkdir(parents=True, exist_ok=True)
        db.touch(mode=0o600)
    else:
        os.chmod(db, 0o600)
    engine = create_engine(
        f"sqlite:///{db}",
        connect_args={"timeout": 5, "check_same_thread": False},
    )
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _):
        for pragma in ("PRAGMA journal_mode=WAL", "PRAGMA synchronous=NORMAL", "PRAGMA busy_timeout=5000"):
            try:
                dbapi_conn.execute(pragma)
            except Exception:
                pass
    return engine

def _ensure_db(vault) -> None:
    db = _db_path(vault)
    # ensure parent exists
    db.parent.mkdir(parents=True, exist_ok=True)
    engine = _engine(vault)
    try:
        with engine.connect() as conn:
            upgrade(conn.connection, LOG_MIGRATION_DIR)
    finally:
        engine.dispose()

def _format_line(row) -> str:
    # row: (date, kind, message, is_auto)
    d, kind, msg, is_auto = row
    auto = " (auto)" if is_auto else ""
    return f"- {d} {kind}{auto}: {msg}"

def _sync_markdown_view(vault) -> None:
    """Regenerate log.md from DB (read-only view for Obsidian)."""
    _ensure_db(vault)
    engine = _engine(vault)
    try:
        with Session(engine) as session:
            rows = session.scalars(select(LogEntry).order_by(LogEntry.id.asc())).all()
            rows = [(r.date, r.kind, r.message, r.is_auto) for r in rows]
    finally:
        engine.dispose()
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
    if not md_path.exists():
        _ensure_db(vault)
        return 0
    _ensure_db(vault)
    # if DB already has data, assume already migrated (avoid double insert)
    engine = _engine(vault)
    try:
        with Session(engine) as session:
            cnt = session.scalar(select(func.count()).select_from(LogEntry))
    finally:
        engine.dispose()
    if cnt and cnt > 0:
        # still ensure markdown view is synced; if log.md is newer than bak, keep it
        # but don't re-migrate
        return 0
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
        engine = _engine(vault)
        try:
            with Session(engine) as session:
                session.add_all([LogEntry(date=d, kind=k, message=m, is_auto=bool(a), created_at=created) for d, k, m, a, created in rows])
                session.commit()
        finally:
            engine.dispose()

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
    kinds = {"SETUP", "INGEST", "QUERY", "LINT", "REFLECT", "WRITE", "UPDATE", "DELETE", "READ", "INDEX_REBUILT"}
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
            engine = _engine(vault)
            try:
                with Session(engine) as session:
                    cnt = session.scalar(select(func.count()).select_from(LogEntry))
            finally:
                engine.dispose()
            if cnt == 0:
                try:
                    migrate_log_md_to_db(vault)
                except Exception:
                    pass

    engine = _engine(vault)
    try:
        with Session(engine) as session:
            if not quiet:
                session.add(LogEntry(date=today, kind=kind, message=description, is_auto=False, created_at=now_iso))
            else:
                # quiet: aggregate into single daily auto line per kind
                entry = session.scalars(select(LogEntry).where(LogEntry.date == today, LogEntry.kind == kind, LogEntry.is_auto.is_(True)).order_by(LogEntry.id.desc()).limit(1)).first()
                if entry is not None:
                    msg = entry.message
                    m = re.search(r"\b(\d+) ops\b", msg)
                    count = int(m.group(1)) if m else 0
                    if kind == "INDEX_REBUILT":
                        new_msg = description
                    else:
                        new_msg = f"{count + 1} ops (latest: {description[:80]})"
                    entry.message, entry.created_at = new_msg, now_iso
                else:
                    session.add(LogEntry(date=today, kind=kind, message=f"1 ops (latest: {description[:80]})", is_auto=True, created_at=now_iso))
            session.commit()
    finally:
        engine.dispose()

    # keep markdown view in sync (best effort, ignore iCloud errors) — disabled per user request 2026-08-23
    pass

def log_tail(vault, lines: int = 30) -> str:
    _ensure_db(vault)
    # if DB empty but log.md exists (pre-migration), migrate
    engine = _engine(vault)
    try:
        with Session(engine) as session:
            cnt = session.scalar(select(func.count()).select_from(LogEntry))
        if cnt == 0 and vault.log_path.exists():
            # check if log_path has content beyond header
            try:
                txt = vault.log_path.read_text(encoding="utf-8")
                if "- " in txt:
                    engine.dispose()
                    try:
                        migrate_log_md_to_db(vault)
                    except Exception:
                        pass
                    engine = _engine(vault)
            except OSError:
                pass
        with Session(engine) as session:
            rows = [(r.date, r.kind, r.message, r.is_auto) for r in session.scalars(select(LogEntry).order_by(LogEntry.id.desc()).limit(lines)).all()]
    finally:
        engine.dispose()
    if not rows:
        return ""
    rows = list(reversed(rows))
    return "\n".join(_format_line(r) for r in rows)

# helper for lint - expose raw log rows
def _iter_log_rows(vault):
    _ensure_db(vault)
    engine = _engine(vault)
    try:
        with Session(engine) as session:
            rows = [(r.date, r.kind, r.message, r.is_auto, r.created_at) for r in session.scalars(select(LogEntry).order_by(LogEntry.id.asc())).all()]
    finally:
        engine.dispose()
    return rows
