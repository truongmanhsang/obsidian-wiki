
"""Search and prefetch helpers."""
from __future__ import annotations

from datetime import date
import re
from collections.abc import Mapping
from typing import TypedDict

from .links import TOKEN_RE, _alias_map
from .intent import normalize_search, query_tokens


class SearchFilters(TypedDict):
    """Normalized filters consumed by every search stage."""

    type: str | None
    tags: frozenset[str]
    updated_after: str | None
    path_prefix: str | None
    include_sources: bool


def _as_text_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = value.strip().strip("[]")
        if not value:
            return []
        values = value.split(",")
    else:
        values = value if isinstance(value, (list, tuple, set, frozenset)) else [value]
    return [str(item).strip().strip("'\"") for item in values if str(item).strip()]


def _normalize_path_prefix(value) -> str | None:
    if value is None:
        return None
    prefix = str(value).strip().replace("\\", "/").strip("/")
    if prefix.startswith("./"):
        prefix = prefix[2:]
    return prefix or None


def normalize_search_filters(filters: Mapping | None = None) -> SearchFilters:
    """Normalize supported search filters into a stable internal shape."""
    if filters is None:
        filters = {}
    if not isinstance(filters, Mapping):
        raise TypeError("search filters must be a mapping")

    raw_type = filters.get("type")
    page_type = str(raw_type).strip().casefold() if raw_type is not None else None
    page_type = page_type or None
    tags = {
        normalize_search(tag)
        for tag in _as_text_list(filters.get("tags"))
        if normalize_search(tag)
    }
    updated_after = filters.get("updated_after")
    if updated_after is not None:
        updated_after = str(updated_after).strip()
        if updated_after:
            try:
                date.fromisoformat(updated_after)
            except ValueError as exc:
                raise ValueError("updated_after must be an ISO date (YYYY-MM-DD)") from exc
        else:
            updated_after = None

    return {
        "type": page_type,
        "tags": frozenset(tags),
        "updated_after": updated_after,
        "path_prefix": _normalize_path_prefix(filters.get("path_prefix")),
        "include_sources": bool(filters.get("include_sources", False)),
    }


def page_matches_filters(page: Mapping, filters: Mapping | None = None) -> bool:
    """Return whether a loaded page satisfies all supported search filters."""
    normalized = normalize_search_filters(filters)
    page_type = str(page.get("ptype") or page.get("type") or "").casefold()
    if not normalized["include_sources"] and page_type == "source":
        return False
    if normalized["type"] and page_type != normalized["type"]:
        return False

    metadata = page.get("meta") or {}
    page_tags = {
        normalize_search(tag)
        for tag in _as_text_list(metadata.get("tags"))
        if normalize_search(tag)
    }
    if not normalized["tags"].issubset(page_tags):
        return False

    updated_after = normalized["updated_after"]
    if updated_after:
        try:
            if date.fromisoformat(str(page.get("updated") or "")) < date.fromisoformat(updated_after):
                return False
        except ValueError:
            return False

    prefix = normalized["path_prefix"]
    if prefix:
        rel = str(page.get("rel") or page.get("path") or "").replace("\\", "/").lstrip("/")
        if not (rel == prefix or rel.startswith(prefix + "/")):
            return False
    return True


def _identity_candidates(page: Mapping) -> list[str]:
    metadata = page.get("meta") or {}
    aliases = _as_text_list(metadata.get("aliases"))
    title = str(page.get("title") or "")
    stem = str(page.get("stem") or "")
    return [title, stem.replace("-", " ").replace("_", " "), *aliases]


def exact_page_match(page: Mapping, query: str) -> bool:
    """Return true when query exactly identifies a page title, stem, or alias."""
    normalized_query = normalize_search(query)
    if len(normalized_query) < 3:
        return False
    return any(
        normalized_query == normalize_search(candidate)
        for candidate in _identity_candidates(page)
        if candidate.strip()
    )


def search(vault, query: str, limit: int = 5, filters: Mapping | None = None) -> list[dict]:
    from .vault import VALID_TYPES  # noqa
    query_low = normalize_search(query)
    # TOKEN_RE is intentionally ASCII-oriented for wikilinks, but memory
    # search must also handle names and facts written with Unicode (e.g.
    # Vietnamese diacritics).  Keep the old regex as a fallback only for
    # compatibility; \w with the UNICODE flag preserves those words.
    tokens = query_tokens(query)
    results = []
    # Raw session transcripts are private source material, not ordinary searchable memory.
    normalized_filters = normalize_search_filters(filters)
    all_pages = [p for p in vault.load_pages() if page_matches_filters(p, normalized_filters)]
    aliases = _alias_map(all_pages)
    alias_tokens = [a for a in re.findall(r"[^\W_]{2,}", query_low, flags=re.UNICODE)
                    if a in aliases and a not in vault.STOPWORDS]
    if not tokens and not alias_tokens:
        return []
    for page in all_pages:
        low = normalize_search(page["text"])
        my_aliases = {normalize_search(a) for a, rel in aliases.items() if rel == page["rel"]} - {normalize_search(page["stem"])}
        title_hits = sum(1 for t in tokens if t in normalize_search(page["stem"]))
        title_hits += sum(5 for t in alias_tokens if aliases.get(t) == page["rel"])
        title_hits += sum(1 for t in tokens if any(t in a for a in my_aliases))
        body_hits = sum(low.count(t) for t in tokens)
        # A full phrase/name match is a stronger signal than scattered token
        # matches and prevents a common person's page from being buried by
        # unrelated pages mentioning words such as "birth" or "date".
        phrase_hits = 0
        phrase = " ".join(tokens)
        if len(tokens) >= 2 and phrase in low:
            phrase_hits = 12
        tags_val = page["meta"].get("tags", [])
        aliases_val = page["meta"].get("aliases", [])
        if isinstance(tags_val, list):
            tags_parts = [normalize_search(x) for x in tags_val]
        else:
            tags_parts = [normalize_search(p) for p in str(tags_val).replace("[","").replace("]","").split(",") if p.strip()]
        if isinstance(aliases_val, list):
            alias_parts = [normalize_search(x) for x in aliases_val]
        else:
            alias_parts = [normalize_search(p) for p in str(aliases_val).replace("[","").replace("]","").split(",") if p.strip()]
        tag_text = " ".join(tags_parts) + " " + normalize_search(page["meta"].get("type", "")) + " " + " ".join(alias_parts)
        tag_hits = sum(1 for t in tokens if t and t in tag_text)
        score = title_hits * 3 + body_hits + tag_hits * 2 + phrase_hits
        if score <= 0:
            continue
        snippet = ""
        for line in page["body"].splitlines():
            line_low = normalize_search(line)
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
