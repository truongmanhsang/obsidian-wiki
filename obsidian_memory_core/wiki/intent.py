"""Data-driven query features.

There is deliberately no relationship or attribute dictionary here.  Pages
teach the index their own vocabulary through aliases and optional
``search_terms`` metadata, so adding a new entity/domain is a content change,
not a code change.
"""
from __future__ import annotations

import re

TOKEN_RE = re.compile(r"[^\W_]{2,}", flags=re.UNICODE)


def query_tokens(query: str) -> list[str]:
    return TOKEN_RE.findall(" ".join(str(query).casefold().split()))


def _phrases(tokens: list[str]) -> list[str]:
    return [
        " ".join(tokens[i:i + size])
        for size in range(min(4, len(tokens)), 1, -1)
        for i in range(len(tokens) - size + 1)
    ]


def analyze_query(query: str) -> dict[str, object]:
    tokens = query_tokens(query)
    return {"tokens": tokens, "phrases": _phrases(tokens)}


def page_search_text(page: dict) -> str:
    """Build a searchable representation from all curated page fields."""
    meta = page.get("meta", {})
    structured = []
    for key, value in meta.items():
        if key not in {"updated", "tags"}:
            structured.extend([str(key), str(value)])
    return " ".join(
        [page.get("title", ""), page.get("stem", ""), page.get("body", ""), *structured]
    ).casefold()


def page_anchor_score(page: dict, query: str) -> float:
    """Score exact phrase/token anchors found in the page itself."""
    text = page_search_text(page)
    tokens = query_tokens(query)
    phrases = _phrases(tokens)
    # Longer page-declared phrases are anchors.  This supports arbitrary
    # relationships/attributes without a hard-coded ontology.
    meta = page.get("meta", {})
    declared = meta.get("search_terms", [])
    if isinstance(declared, str):
        declared = [declared]
    declared = [str(term).casefold().strip() for term in declared if str(term).strip()]
    anchors = set(declared)
    anchors.update(str(value).casefold().strip() for value in meta.get("aliases", []) if str(value).strip())
    phrase_score = sum(0.18 for phrase in phrases if phrase in text or phrase in anchors)
    token_score = sum(0.025 for token in tokens if token in text)
    return min(0.55, phrase_score + token_score)