
"""Search and prefetch helpers."""
from __future__ import annotations
import re
from .links import TOKEN_RE, _alias_map

def search(vault, query: str, limit: int = 5) -> list[dict]:
    from .vault import VALID_TYPES  # noqa
    tokens = [t for t in TOKEN_RE.findall(query.lower()) if t not in vault.STOPWORDS]
    results = []
    # Raw session transcripts are private source material, not ordinary searchable memory.
    all_pages = [p for p in vault.load_pages() if p["ptype"] != "source"]
    aliases = _alias_map(all_pages)
    alias_tokens = [a for a in re.findall(r"[a-z0-9]{2,}", query.lower()) if a in aliases and a not in vault.STOPWORDS]
    if not tokens and not alias_tokens:
        return []
    for page in all_pages:
        low = page["text"].lower()
        my_aliases = {a for a, rel in aliases.items() if rel == page["rel"]} - {page["stem"].lower()}
        title_hits = sum(1 for t in tokens if t in page["stem"].lower())
        title_hits += sum(5 for t in alias_tokens if aliases.get(t) == page["rel"])
        title_hits += sum(1 for t in tokens if any(t in a for a in my_aliases))
        body_hits = sum(low.count(t) for t in tokens)
        tags_val = page["meta"].get("tags", [])
        aliases_val = page["meta"].get("aliases", [])
        if isinstance(tags_val, list):
            tags_parts = [str(x).lower() for x in tags_val]
        else:
            tags_parts = [p.strip().lower() for p in str(tags_val).replace("[","").replace("]","").split(",") if p.strip()]
        if isinstance(aliases_val, list):
            alias_parts = [str(x).lower() for x in aliases_val]
        else:
            alias_parts = [p.strip().lower() for p in str(aliases_val).replace("[","").replace("]","").split(",") if p.strip()]
        tag_text = " ".join(tags_parts) + " " + str(page["meta"].get("type","")).lower() + " " + " ".join(alias_parts)
        tag_hits = sum(1 for t in tokens if t and t in tag_text)
        score = title_hits * 3 + body_hits + tag_hits * 2
        if score <= 0:
            continue
        snippet = ""
        for line in page["body"].splitlines():
            line_low = line.lower()
            if any(t in line_low for t in tokens) and len(line.strip()) > 3:
                snippet = line.strip()[:180]
                break
        if page["ptype"] == "source":
            score = score / 10.0
            if score < 1:
                continue
        results.append({"path": page["rel"], "title": page["title"], "type": page["ptype"], "updated": page["updated"], "score": round(score, 1), "snippet": snippet})
    results.sort(key=lambda r: (-r["score"], r["title"].lower()))
    return results[:limit]

def prefetch_context(vault, query: str, limit: int = 3) -> str:
    if not isinstance(query, str) or len(query.strip()) < 10:
        return ""
    results = [r for r in vault.search(query, limit=limit*3) if r["type"] != "source"][:limit]
    strong = [r for r in results if r["score"] >= 1]
    if not strong:
        return ""
    lines = ["## Obsidian Wiki Context", ""]
    for r in strong:
        lines.append(f"- [[{r['path']}|{r['title']}]] (score {r['score']}) {r['snippet']}")
    lines.append("")
    lines.append("Full pages live in the vault; use the obsidian_wiki tool (action=read) for complete content.")
    return "\n".join(lines)
