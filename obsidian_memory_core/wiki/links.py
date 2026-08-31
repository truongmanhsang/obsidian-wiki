
"""Wikilink regex and alias/inbound helpers."""
from __future__ import annotations
import re
from pathlib import Path
from .frontmatter import FRONTMATTER_RE, parse_frontmatter
from .intent import normalize_search

WIKILINK_RE = re.compile(r"\[\[([^\]\|#]+)(?:#[^\]\|]*)?(?:\|[^\]]*)?\]\]")
TOKEN_RE = re.compile(r"[a-z0-9]{3,}")

def _alias_map(pages: list) -> dict:
    m: dict = {}
    for p in pages:
        m.setdefault(normalize_search(p["stem"]), p["rel"])
        raw = p["meta"].get("aliases")
        aliases_list: list[str] = []
        if isinstance(raw, list):
            aliases_list = [str(x).strip() for x in raw if str(x).strip()]
        elif isinstance(raw, str) and raw.strip():
            s = raw.strip()
            if s.startswith("[") and s.endswith("]"):
                inner = s[1:-1].strip()
                if inner:
                    for part in inner.split(","):
                        a = part.strip().strip("'\"")
                        if a:
                            aliases_list.append(a)
            else:
                for part in s.split(","):
                    a = part.strip().strip("'\"").strip()
                    if a:
                        aliases_list.append(a)
        if not aliases_list:
            fm = FRONTMATTER_RE.match(p["text"])
            if fm:
                try:
                    fm_meta, _ = parse_frontmatter(p["text"])
                    fm_aliases = fm_meta.get("aliases")
                    if isinstance(fm_aliases, list) and fm_aliases:
                        aliases_list = fm_aliases
                except Exception:
                    pass
        for a in aliases_list:
            key = normalize_search(a.strip().strip("'\""))
            if key and key not in m:
                m[key] = p["rel"]
    return m

def _out_links(page: dict) -> set[str]:
    out: set[str] = set()
    for link in WIKILINK_RE.findall(page["text"]):
        stem = link.strip().split("/")[-1].strip()
        stem = re.sub(r"\.md$", "", stem, flags=re.IGNORECASE)
        out.add(stem.lower())
    return out

def _inbound_links(vault, stem: str, exclude: Path | None = None) -> set[str]:
    target = stem.lower()
    found = set()
    for page in vault.load_pages():
        if exclude is not None and page["path"] == exclude:
            continue
        if page["ptype"] == "source":
            continue
        body_text = re.sub(r"\n## Linked from\n(?:\n|- .*\n?)*", "\n", page["text"])
        for link in WIKILINK_RE.findall(body_text):
            link_stem = link.strip().split("/")[-1].strip()
            link_stem = re.sub(r"\.md$", "", link_stem, flags=re.IGNORECASE)
            if link_stem.lower() == target:
                found.add(page["rel"])
    return found
