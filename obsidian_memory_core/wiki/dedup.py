
"""Duplicate detection helpers."""
from __future__ import annotations
from .normalize import _normalize
from .frontmatter import _parse_aliases_list

def detect_duplicates(vault) -> list[list[str]]:
    pages = [p for p in vault.load_pages() if p.get("ptype") != "source"]
    if len(pages) < 2:
        return []
    sigs: list[set[str]] = []
    alias_norms: list[set[str]] = []
    for pg in pages:
        stem_n = _normalize(pg["stem"])
        title_n = _normalize(pg["title"])
        alist = _parse_aliases_list(pg)
        a_norms = { _normalize(a) for a in alist if _normalize(a) }
        s: set[str] = set()
        if stem_n:
            s.add(stem_n)
        if title_n:
            s.add(title_n)
        s |= a_norms
        sigs.append(s)
        alias_norms.append(a_norms)
    token_to_indices: dict[str, list[int]] = {}
    for idx, s in enumerate(sigs):
        for tok in s:
            token_to_indices.setdefault(tok, []).append(idx)
    parent = list(range(len(pages)))
    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
    for indices in token_to_indices.values():
        if len(indices) > 1:
            first = indices[0]
            for other in indices[1:]:
                union(first, other)
    groups: dict[int, list[str]] = {}
    for idx, pg in enumerate(pages):
        root = find(idx)
        groups.setdefault(root, []).append(pg["rel"])
    result = [sorted(g) for g in groups.values() if len(g) > 1]
    result.sort(key=lambda g: g[0].lower())
    return result
