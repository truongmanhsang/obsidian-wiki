"""SQLite FTS5 index and embedding-free hybrid search."""
from __future__ import annotations
import sqlite3
from datetime import date
from pathlib import Path
from .links import TOKEN_RE

SCHEMA = """CREATE VIRTUAL TABLE IF NOT EXISTS fts_pages USING fts5(
    path UNINDEXED, title, body, ptype UNINDEXED, updated UNINDEXED,
    tokenize='porter unicode61'
)"""


def _connect(vault):
    conn = sqlite3.connect(str(vault.root / "fts.db"), timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _fingerprint(vault) -> str:
    """Cheap deterministic fingerprint of curated markdown files.

    It detects edits made directly in Obsidian without reading every document
    body. The database is rebuilt only when the file set or mtime/size changes.
    """
    import hashlib
    h = hashlib.sha256()
    for page in vault.load_pages():
        try:
            st = page["path"].stat()
            h.update(f"{page['rel']}:{st.st_mtime_ns}:{st.st_size}".encode())
        except OSError:
            h.update(page["rel"].encode())
    return h.hexdigest()


def build_fts_db(vault) -> dict:
    vault.root.mkdir(parents=True, exist_ok=True)
    fingerprint = _fingerprint(vault)
    conn = _connect(vault)
    try:
        conn.execute(SCHEMA)
        conn.execute("CREATE TABLE IF NOT EXISTS fts_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("DELETE FROM fts_pages")
        rows = [(p['rel'], p['title'], p['body'], p['ptype'], p['updated']) for p in vault.load_pages()]
        conn.executemany("INSERT INTO fts_pages(path,title,body,ptype,updated) VALUES (?,?,?,?,?)", rows)
        conn.execute("INSERT OR REPLACE INTO fts_meta(key,value) VALUES ('fingerprint',?)", (fingerprint,))
        conn.commit()
        return {"path": str(vault.root / "fts.db"), "pages": len(rows), "status": "rebuilt"}
    finally:
        conn.close()


def ensure_fresh(vault) -> dict:
    """Create/rebuild index automatically when vault markdown changed."""
    db = vault.root / "fts.db"
    if not db.exists():
        return build_fts_db(vault)
    current = _fingerprint(vault)
    conn = _connect(vault)
    try:
        row = conn.execute("SELECT value FROM fts_meta WHERE key='fingerprint'").fetchone()
    except sqlite3.Error:
        row = None
    finally:
        conn.close()
    if not row or row[0] != current:
        return build_fts_db(vault)
    return {"path": str(db), "status": "fresh"}

def _fts_rows(vault, query, limit=100):
    conn = _connect(vault)
    try:
        q = " OR ".join(TOKEN_RE.findall(query.lower()))
        if not q: return []
        return conn.execute("SELECT path,title,body,ptype,updated,bm25(fts_pages) FROM fts_pages WHERE fts_pages MATCH ? ORDER BY bm25(fts_pages) LIMIT ?", (q, limit)).fetchall()
    finally: conn.close()

def search_fts(vault, query, limit=100):
    rows = _fts_rows(vault, query, limit)
    return [{"path":r[0],"title":r[1],"type":r[3],"updated":r[4],"fts_rank":-float(r[5]),"snippet":next((x.strip()[:180] for x in r[2].splitlines() if any(t in x.lower() for t in TOKEN_RE.findall(query.lower()))),"")} for r in rows]

def hybrid_search(vault, query, limit=5):
    if not isinstance(query, str) or not query.strip(): return []
    ensure_fresh(vault)
    fts = search_fts(vault, query, limit=100)
    kw = vault._keyword_search(query, limit=100)
    by_path = {r['path']: dict(r) for r in fts}
    for r in kw:
        by_path.setdefault(r['path'], {}).update(r)
    if not by_path: return []
    max_fts = max((r.get('fts_rank', 0) for r in by_path.values()), default=1) or 1
    max_kw = max((r.get('score', 0) for r in by_path.values()), default=1) or 1
    today = date.today()
    for r in by_path.values():
        f = max(0.0, r.get('fts_rank', 0) / max_fts)
        k = max(0.0, r.get('score', 0) / max_kw)
        try: age = max(0, (today - date.fromisoformat(r.get('updated') or today.isoformat())).days)
        except ValueError: age = 3650
        rec = 0.5 ** (age / 180.0)
        r['score'] = round(0.5*f + 0.3*k + 0.2*rec, 4)
        r.pop('fts_rank', None)
    return sorted(by_path.values(), key=lambda r: (-r['score'], r.get('title','').lower()))[:limit]