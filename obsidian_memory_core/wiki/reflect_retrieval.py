"""Broad, independent retrieval and bounded excerpt selection for Reflect."""
from __future__ import annotations

import re
from collections import defaultdict

from .intent import normalize_search, page_anchor_score, query_tokens
from .search import exact_page_match, normalize_search_filters, page_matches_filters

_MIN_SECTION_LEXICAL_SCORE = 0.45


def reciprocal_rank_fusion(
    ranked_lists: list[list[dict]], *, limit: int,
    pages_by_path: dict[str, dict] | None = None, rrf_k: int = 60,
    query: str = "",
) -> list[dict]:
    """Fuse ranked result lists without comparing their unrelated raw scores."""
    fused: dict[str, dict] = {}
    for ranked in ranked_lists:
        seen: set[str] = set()
        for rank, item in enumerate(ranked, 1):
            path = item.get("path")
            if not path or path in seen:
                continue
            seen.add(path)
            record = fused.setdefault(path, {**item, "path": path, "rrf_score": 0.0})
            record["rrf_score"] += 1.0 / (rrf_k + rank)
            if item.get("_phrase") or item.get("match") == "phrase":
                record["_phrase"] = True
    pages_by_path = pages_by_path or {}
    for path, item in fused.items():
        page = pages_by_path.get(path, {})
        item["_exact"] = bool(page and exact_page_match(page, query))
        item["_anchor"] = page_anchor_score(page, query) if page else 0.0
    return sorted(
        fused.values(),
        key=lambda item: (
            -int(item.get("_exact", False)),
            -int(item.get("_phrase", False)),
            -float(item.get("_anchor", 0.0)),
            -item["rrf_score"],
            str(item.get("title", "")).casefold(),
            item["path"].casefold(),
        ),
    )[:max(0, limit)]


def split_markdown_sections(page: dict, *, max_chars: int) -> list[dict]:
    """Split Markdown by headings outside fences, bounded at paragraph breaks."""
    body = str(page.get("body", page.get("content", "")) or "")
    path, title = page.get("rel", page.get("path", "")), page.get("title", "")
    sections: list[dict] = []
    heading = ""
    lines: list[str] = []
    fence: str | None = None

    def emit():
        raw = "\n".join(lines).strip()
        if not raw and not heading and body.strip():
            return
        prefix = f"## {heading}\n\n" if heading else ""
        available = max(1, max_chars - len(prefix))
        paragraphs = re.split(r"\n\s*\n", raw) if raw else [""]
        fact_blocks: list[str] = []
        for paragraph in paragraphs:
            # Keep fenced examples intact; elsewhere, list entries are commonly
            # independent facts and should be ranked independently.
            if "```" in paragraph or "~~~" in paragraph:
                fact_blocks.append(paragraph)
                continue
            current: list[str] = []
            for line in paragraph.splitlines():
                is_list_item = re.match(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)", line)
                if is_list_item and current:
                    fact_blocks.append("\n".join(current).strip())
                    current = [line]
                else:
                    current.append(line)
            if current:
                fact_blocks.append("\n".join(current).strip())
        chunks: list[str] = []
        current = ""
        for paragraph in fact_blocks:
            if re.match(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)", paragraph):
                if current:
                    chunks.append(current)
                    current = ""
                while len(paragraph) > available:
                    chunks.append(paragraph[:available])
                    paragraph = paragraph[available:]
                if paragraph:
                    chunks.append(paragraph)
                continue
            while len(paragraph) > available:
                if current:
                    chunks.append(current)
                    current = ""
                chunks.append(paragraph[:available])
                paragraph = paragraph[available:]
            candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
            if len(candidate) > available and current:
                chunks.append(current)
                current = paragraph
            else:
                current = candidate
        if current or not chunks:
            chunks.append(current)
        for chunk in chunks:
            content = (prefix + chunk).strip()
            sections.append({"path": path, "title": title, "heading": heading,
                             "content": content[:max_chars]})

    for line in body.splitlines():
        marker = re.match(r"^\s*(```+|~~~+)", line)
        if marker:
            char = marker.group(1)[0]
            if fence is None:
                fence = char
            elif fence == char:
                fence = None
        match = re.match(r"^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$", line) if fence is None else None
        if match:
            emit()
            heading = match.group(1).strip()
            lines = []
        else:
            lines.append(line)
    emit()
    return sections


def _lexical_score(query: str, text: str) -> float:
    tokens = query_tokens(query)
    if not tokens:
        return 0.0
    normalized = normalize_search(text)
    coverage = sum(token in normalized for token in tokens) / len(tokens)
    phrase = " ".join(tokens)
    return min(1.0, coverage * 0.7 + (0.3 if len(tokens) > 1 and phrase in normalized else 0.0))


def select_reflect_excerpts(
    query: str, pages: list[dict], *, embedder=None,
    max_sections_per_page: int | None = None, max_excerpt_chars: int = 1800,
    max_total_chars: int = 12000,
) -> list[dict]:
    sections = []
    section_limit_per_page = max(8, min(16, 768 // max(1, len(pages))))
    for page in pages:
        # Allocate a bounded, fair chunk budget across candidates so large
        # early-ranked pages cannot consume the entire batch before later
        # candidates (including a relevant section deep in a long page) are
        # seen. Even sampling preserves coverage across each page's full depth.
        page_sections = split_markdown_sections(page, max_chars=max_excerpt_chars)
        if len(page_sections) > section_limit_per_page:
            last = len(page_sections) - 1
            indexes = sorted({round(i * last / (section_limit_per_page - 1))
                              for i in range(section_limit_per_page)})
            page_sections = [page_sections[i] for i in indexes]
        sections.extend(page_sections)
    if not sections:
        return []
    if embedder is None:
        try:
            from .fts import _get_embedder
            embedder = _get_embedder()
        except Exception:
            embedder = None
    semantic = [0.0] * len(sections)
    semantic_available = False
    if embedder is not None and embedder is not False:
        try:
            import numpy as np
            vectors = list(embedder.embed([query, *(item["content"] for item in sections)]))
            qv = np.asarray(vectors[0], dtype=float)
            qnorm = np.linalg.norm(qv)
            for index, vector in enumerate(vectors[1:]):
                sv = np.asarray(vector, dtype=float)
                denom = qnorm * np.linalg.norm(sv)
                semantic[index] = float(np.dot(qv, sv) / denom) if denom else 0.0
            semantic_available = True
        except Exception:
            semantic = [0.0] * len(sections)
    by_page: dict[str, list[tuple[float, int, dict]]] = defaultdict(list)
    for index, section in enumerate(sections):
        lexical = _lexical_score(query, section["content"])
        semantic_score = max(0.0, min(1.0, semantic[index])) if semantic_available else 0.0
        if lexical < _MIN_SECTION_LEXICAL_SCORE and (
            not semantic_available or semantic_score <= 0.0
        ):
            continue
        score = 0.6 * semantic_score + 0.4 * lexical if semantic_available else lexical
        by_page[section["path"]].append((score, index, section))
    ranked_pages = []
    for path, ranked in by_page.items():
        chosen = sorted(ranked, key=lambda value: (-value[0], value[1]))
        if max_sections_per_page is not None:
            chosen = chosen[:max_sections_per_page]
        chosen.sort(key=lambda value: value[1])
        ranked_pages.append((max((value[0] for value in chosen), default=0.0), path, chosen))
    ranked_pages.sort(key=lambda value: (-value[0], value[1].casefold()))
    if not ranked_pages and len(pages) == 1 and not str(pages[0].get("body", pages[0].get("content", ""))).strip():
        return [{"path": pages[0].get("rel", pages[0].get("path", "")), "content": ""}]
    output: list[dict] = []
    total = 0
    for _, path, chosen in ranked_pages:
        contents = []
        page_remaining = max_excerpt_chars
        for _, _, section in chosen:
            separator_size = 2 if contents else 0
            remaining = min(max_total_chars - total - separator_size, page_remaining)
            if remaining <= 0:
                break
            content = section["content"][:min(max_excerpt_chars, remaining)]
            contents.append(content)
            total += separator_size + len(content)
            page_remaining -= len(content)
        if contents:
            output.append({"path": path, "content": "\n\n".join(contents)})
        if total >= max_total_chars:
            break
    return output


def retrieve_reflect_excerpts(
    vault, query: str, *, candidate_limit: int = 48, result_limit: int = 8,
    filters: dict | None = None,
) -> list[dict]:
    from .fts import _embedding_search, ensure_fresh, search_fts

    normalized_filters = normalize_search_filters(filters)
    pages = [page for page in vault.load_pages() if page_matches_filters(page, normalized_filters)]
    if not pages:
        return []
    eligible = {page["rel"] for page in pages}
    pages_by_path = {page["rel"]: page for page in pages}
    try:
        ensure_fresh(vault)
    except Exception:
        # FTS may be unavailable or corrupt; keyword and vector channels can
        # still produce useful candidates independently.
        pass
    channels = []
    try:
        channels.append(search_fts(vault, query, limit=candidate_limit, pages=pages))
    except Exception:
        channels.append([])
    try:
        channels.append([item for item in vault._keyword_search(
            query, limit=candidate_limit * 2, pages=pages
        )
                         if item.get("path") in eligible][:candidate_limit])
    except Exception:
        channels.append([])
    try:
        # Reflect needs recall, not Search's calibrated precision cutoff: low
        # cosine candidates may be the only bridge between a question and a
        # fact page that uses different vocabulary. Rank by similarity and let
        # RRF + excerpt relevance decide whether they reach the model.
        channels.append(_embedding_search(
            vault, query, limit=candidate_limit, threshold=0.0, pages=pages
        ))
    except Exception:
        channels.append([])
    candidates = reciprocal_rank_fusion(
        channels, limit=candidate_limit, pages_by_path=pages_by_path, query=query,
    )
    candidate_pages = [pages_by_path[item["path"]] for item in candidates if item["path"] in pages_by_path]
    return select_reflect_excerpts(query, candidate_pages[:candidate_limit])[:result_limit]
