"""Frontmatter parsing helpers."""
from __future__ import annotations
import re

FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)

def parse_frontmatter(text: str):
    """Return ({flat keys}, body_without_frontmatter)."""
    meta: dict = {}
    match = FRONTMATTER_RE.match(text)
    body = text
    if match:
        body = text[match.end():]
        fm_block = match.group(1)
        lines = fm_block.splitlines()
        current_list_key: str | None = None
        for line in lines:
            if not line.strip():
                continue
            if current_list_key is not None:
                m_dash = re.match(r"^\s*-\s*(.*)$", line)
                if m_dash is not None:
                    item = m_dash.group(1).strip().strip("'\"")
                    if item:
                        if not isinstance(meta.get(current_list_key), list):
                            meta[current_list_key] = []
                        meta[current_list_key].append(item)
                    continue
                if ":" in line and not line.startswith((" ", "\t", "-")):
                    current_list_key = None
                else:
                    if line.startswith((" ", "\t")):
                        continue
                    current_list_key = None
            if ":" in line and not line.startswith((" ", "-", "\t")):
                key, _, value = line.partition(":")
                key = key.strip()
                value = value.strip()
                if key in ("tags", "aliases"):
                    if value == "":
                        meta[key] = []
                        current_list_key = key
                    elif value == "[]":
                        meta[key] = []
                        current_list_key = None
                    elif value.startswith("[") and value.endswith("]"):
                        inner = value[1:-1].strip()
                        if not inner:
                            meta[key] = []
                        else:
                            items: list[str] = []
                            for part in inner.split(","):
                                pp = part.strip().strip("'\"")
                                if pp:
                                    items.append(pp)
                            meta[key] = items
                        current_list_key = None
                    elif value:
                        meta[key] = [value.strip().strip("'\"")]
                        current_list_key = None
                    else:
                        meta[key] = []
                        current_list_key = key
                else:
                    meta[key] = value.strip().strip("'\"") if value else ""
                    current_list_key = None
    return meta, body

def _parse_aliases_list(page: dict) -> list[str]:
    """Extract aliases list from a loaded page dict (handles list or legacy string)."""
    raw = page.get("meta", {}).get("aliases")
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    if isinstance(raw, str) and raw.strip():
        s = raw.strip()
        if s.startswith("[") and s.endswith("]"):
            inner = s[1:-1].strip()
            if not inner:
                return []
            return [p.strip().strip("'\"") for p in inner.split(",") if p.strip()]
        return [p.strip().strip("'\"") for p in s.split(",") if p.strip()]
    try:
        fm = FRONTMATTER_RE.match(page.get("text", ""))
        if fm:
            fm_meta, _ = parse_frontmatter(page["text"])
            fm_aliases = fm_meta.get("aliases")
            if isinstance(fm_aliases, list):
                return fm_aliases
    except Exception:
        pass
    return []

def page_title(body: str, fallback: str) -> str:
    for line in body.splitlines():
        if line.startswith("# ") and len(line) > 2:
            return line[2:].strip()
    return fallback
