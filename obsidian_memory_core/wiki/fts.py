"""SQLite FTS5 index and hybrid lexical/vector search."""
from __future__ import annotations
import math
import os
import sqlite3
import hashlib
import json
from datetime import date
from pathlib import Path
from .links import TOKEN_RE
from .search import query_tokens
from .intent import normalize_search, page_anchor_score, page_search_text
from obsidian_memory_core.db.migrations import upgrade

_EMBEDDING_MODEL = os.environ.get("OBSIDIAN_WIKI_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
_EMBEDDING_THRESHOLD = float(os.environ.get("OBSIDIAN_WIKI_EMBEDDING_THRESHOLD", "0.55"))
_EMBEDDER = None
_EMBEDDER_FAILED = False


def _get_embedder():
    """Lazy-load fastembed so normal lexical searches stay dependency-light."""
    global _EMBEDDER, _EMBEDDER_FAILED
    if _EMBEDDER is not None or _EMBEDDER_FAILED:
        return _EMBEDDER
    try:
        from fastembed import TextEmbedding
        _EMBEDDER = TextEmbedding(model_name=_EMBEDDING_MODEL)
    except Exception:
        _EMBEDDER_FAILED = True
    return _EMBEDDER


def _cosine(left, right):
    dot = sum(a * b for a, b in zip(left, right))
    norm = math.sqrt(sum(a * a for a in left) * sum(b * b for b in right))
    return dot / norm if norm else 0.0


def _page_hash(page):
    return hashlib.sha256(page["text"].encode("utf-8")).hexdigest()


def _ensure_embedding_schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS embedding_pages (
        path TEXT PRIMARY KEY,
        content_hash TEXT NOT NULL,
        model TEXT NOT NULL,
        vector TEXT NOT NULL
    )""")


def _load_or_build_embeddings(vault, pages):
    """Load cached vectors and embed only new/changed pages."""
    conn = _connect(vault)
    try:
        _ensure_embedding_schema(conn)
        wanted = {p["rel"] for p in pages}
        cached = {
            row[0]: (row[1], row[2], json.loads(row[3]))
            for row in conn.execute(
                "SELECT path,content_hash,model,vector FROM embedding_pages"
            )
        }
        stale = [
            p for p in pages
            if p["rel"] not in cached
            or cached[p["rel"]][0] != _page_hash(p)
            or cached[p["rel"]][1] != _EMBEDDING_MODEL
        ]
        if stale:
            embedder = _get_embedder()
            if embedder is None:
                return {}, conn
            vectors = list(embedder.embed([p["text"] for p in stale]))
            for page, vector in zip(stale, vectors):
                encoded = json.dumps([float(x) for x in vector], separators=(",", ":"))
                conn.execute(
                    "INSERT OR REPLACE INTO embedding_pages(path,content_hash,model,vector) VALUES (?,?,?,?)",
                    (page["rel"], _page_hash(page), _EMBEDDING_MODEL, encoded),
                )
                cached[page["rel"]] = (_page_hash(page), _EMBEDDING_MODEL, list(vector))
        for path in set(cached) - wanted:
            conn.execute("DELETE FROM embedding_pages WHERE path=?", (path,))
            cached.pop(path, None)
        conn.commit()
        return {path: value[2] for path, value in cached.items()}, conn
    except Exception:
        conn.rollback()
        conn.close()
        return {}, None


def _embedding_search(vault, query: str, limit: int = 5, threshold: float | None = None):
    embedder = _get_embedder()
    if embedder is None:
        return []
    threshold = _EMBEDDING_THRESHOLD if threshold is None else threshold
    pages = [p for p in vault.load_pages() if p["ptype"] != "source"]
    if not pages:
        return []
    try:
        query_vector = list(embedder.embed([query]))[0]
        page_vectors, conn = _load_or_build_embeddings(vault, pages)
        if conn is not None:
            conn.close()
        scored = []
        for page in pages:
            vector = page_vectors.get(page["rel"])
            if vector is None:
                continue
            similarity = _cosine(query_vector, vector)
            if similarity >= threshold:
                scored.append({
                    "path": page["rel"], "title": page["title"],
                    "type": page["ptype"], "updated": page["updated"],
                    "score": float(round(float(similarity), 4)),
                    "snippet": "", "match": "embedding",
                })
        return sorted(scored, key=lambda r: (-r["score"], r["title"].casefold()))[:limit]
    except Exception:
        return []


def _reset_embedder_for_tests():
    global _EMBEDDER, _EMBEDDER_FAILED
    _EMBEDDER = None
    _EMBEDDER_FAILED = False


SCHEMA = """CREATE VIRTUAL TABLE IF NOT EXISTS fts_pages USING fts5(
    path UNINDEXED, title, body, search_projection, ptype UNINDEXED, updated UNINDEXED,
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
        upgrade(conn)
        conn.execute(SCHEMA)
        conn.execute("DELETE FROM fts_pages")
        pages = vault.load_pages()
        rows = [(p['rel'], p['title'], p['body'], page_search_text(p), p['ptype'], p['updated']) for p in pages]
        conn.executemany("INSERT INTO fts_pages(path,title,body,search_projection,ptype,updated) VALUES (?,?,?,?,?,?)", rows)
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
    columns = set()
    try:
        row = conn.execute("SELECT value FROM fts_meta WHERE key='fingerprint'").fetchone()
        columns = {r[1] for r in conn.execute("PRAGMA table_info(fts_pages)")}
    except sqlite3.Error:
        row = None
    finally:
        conn.close()
    if not row or row[0] != current or "search_projection" not in columns:
        return build_fts_db(vault)
    return {"path": str(db), "status": "fresh"}

def _fts_rows(vault, query, limit=100):
    conn = _connect(vault)
    try:
        q = " OR ".join(query_tokens(normalize_search(query)))
        if not q: return []
        return conn.execute("SELECT path,title,body,ptype,updated,bm25(fts_pages) FROM fts_pages WHERE fts_pages MATCH ? ORDER BY bm25(fts_pages) LIMIT ?", (q, limit)).fetchall()
    finally: conn.close()

def search_fts(vault, query, limit=100):
    rows = _fts_rows(vault, query, limit)
    tokens = query_tokens(query)
    return [{"path":r[0],"title":r[1],"type":r[3],"updated":r[4],"fts_rank":-float(r[5]),"snippet":next((x.strip()[:180] for x in r[2].splitlines() if any(t in normalize_search(x) for t in tokens)),"")} for r in rows]

def _has_exact_curated_match(vault, query: str, results: list[dict]) -> bool:
    """Return true when lexical search found the requested name/alias exactly."""
    normalized = normalize_search(query)
    if len(normalized) < 3:
        return False
    for result in results:
        page = next((p for p in vault.load_pages() if p["rel"] == result["path"]), None)
        if page is None:
            continue
        candidates = [page["title"], page["stem"]]
        aliases = page["meta"].get("aliases", [])
        candidates.extend(aliases if isinstance(aliases, list) else [str(aliases)])
        for value in candidates:
            candidate = normalize_search(value)
            if candidate and (normalized == candidate or candidate in normalized):
                return True
    return False


def hybrid_search(vault, query, limit=5):
    if not isinstance(query, str) or not query.strip(): return []
    ensure_fresh(vault)
    fts = [r for r in search_fts(vault, query, limit=100) if r["type"] != "source"]
    kw = [r for r in vault._keyword_search(query, limit=100) if r["type"] != "source"]
    by_path = {r['path']: dict(r) for r in fts}
    for r in kw:
        by_path.setdefault(r['path'], {}).update(r)

    pages_by_path = {p["rel"]: p for p in vault.load_pages() if p["ptype"] != "source"}

    # First score lexical candidates. Embeddings are also consulted when the
    # lexical result is empty, weak, or lacks an exact name/alias match.
    max_fts = max((r.get('fts_rank', 0) for r in by_path.values()), default=1) or 1
    max_kw = max((r.get('score', 0) for r in by_path.values()), default=1) or 1
    today = date.today()
    for r in by_path.values():
        f = max(0.0, r.get('fts_rank', 0) / max_fts)
        k = max(0.0, r.get('score', 0) / max_kw)
        try: age = max(0, (today - date.fromisoformat(r.get('updated') or today.isoformat())).days)
        except ValueError: age = 3650
        rec = 0.5 ** (age / 180.0)
        page = pages_by_path.get(r["path"], {})
        anchor_score = page_anchor_score(page, query) if page else 0.0
        r['score'] = round(
            0.35 * f + 0.20 * k + 0.15 * rec
            + anchor_score,
            4,
        )
        if anchor_score:
            r["match"] = "anchor"
        r.pop('fts_rank', None)

    lexical = list(by_path.values())
    lexical_scores = {r['path']: r['score'] for r in lexical}
    exact = _has_exact_curated_match(vault, query, lexical)
    top_lexical = max(lexical_scores.values(), default=0.0)
    # A normalized lexical score is not evidence that the query was answered:
    # a page matching only generic words can still score 1.0.  Unless the
    # complete query is an exact title/alias, consult semantic search.
    if not exact:
        vector_results = _embedding_search(vault, query, limit=max(limit, 10))
        for vector in vector_results:
            path = vector['path']
            if path in by_path:
                # Similarity is the strongest signal, while retaining a small
                # lexical/recency tie-breaker for otherwise equal candidates.
                by_path[path].update(vector)
                by_path[path]['score'] = round(0.8 * vector['score'] + 0.2 * lexical_scores.get(path, 0.0), 4)
                # Keep the semantic provenance visible to callers.  A merged
                # lexical hit is still primarily an embedding match when the
                # vector result supplied the winning candidate.
                by_path[path]['match'] = 'embedding'
            else:
                by_path[path] = dict(vector)

        # Semantic candidates must outrank generic lexical noise. Keep the
        # lexical set for merge/tie-breaking, but cap non-semantic hits when
        # they are not exact title/alias matches.
        if vector_results:
            vector_paths = {r['path'] for r in vector_results}
            for path, result in by_path.items():
                if path not in vector_paths:
                    result['score'] = min(result.get('score', 0), 0.7)
            # Re-sort will now place strong semantic matches first while
            # retaining lexical results as fallback context.

    # Apply intent boosts after the semantic merge as well.  Vector-only
    # candidates were not present during the initial lexical scoring pass.
    # Without this second pass a semantically close preference page can outrank
    # the actual person page that explicitly states the relationship.
    for result in by_path.values():
        page = pages_by_path.get(result["path"], {})
        anchor_score = page_anchor_score(page, query) if page else 0.0
        if anchor_score:
            result["score"] = round(min(1.0, result.get("score", 0.0) + anchor_score), 4)
            result["match"] = result.get("match", "anchor")

    return sorted(by_path.values(), key=lambda r: (-r['score'], r.get('title','').lower()))[:limit]
