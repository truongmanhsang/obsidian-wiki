
"""Lint and orphan-fixing helpers."""
from __future__ import annotations
import re
from pathlib import Path
from .links import WIKILINK_RE, _alias_map, _out_links
from .frontmatter import FRONTMATTER_RE
from .normalize import _normalize
from .frontmatter import _parse_aliases_list


def _as_bool(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _as_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip().lower() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return [item.strip().strip("'\"").lower() for item in text.split(",") if item.strip()]


def discover_hubs(vault) -> list[dict]:
    """Return existing, valid hub pages ordered by priority and path."""
    hubs = []
    for page in vault.load_pages():
        meta = page.get("meta", {})
        if not _as_bool(meta.get("lint_hub")):
            continue
        keywords = _as_list(meta.get("lint_keywords"))
        if not keywords or not page["path"].exists():
            continue
        try:
            priority = int(str(meta.get("lint_priority", "0")).strip() or "0")
        except ValueError:
            priority = 0
        hubs.append({
            "path": page["rel"],
            "keywords": keywords,
            "priority": priority,
            "page": page,
        })
    return sorted(hubs, key=lambda hub: (-hub["priority"], hub["path"].lower()))


def _hub_for_orphan(vault, orphan_rel: str, title: str = "", ptype: str = "",
                    tags: list[str] | None = None, body: str = "") -> str:
    if not ptype:
        from .vault import DIR_TYPES
        try:
            ptype = DIR_TYPES.get(orphan_rel.split("/", 1)[0], "")
        except Exception:
            ptype = ""
    haystack = " ".join([orphan_rel, title, ptype, " ".join(tags or []), body]).lower()
    for hub in discover_hubs(vault):
        if any(keyword in haystack for keyword in hub["keywords"]):
            return hub["path"]

    # Generic navigation fallback. LLM generation will replace this path when
    # no semantic hub exists and generation is available.
    return "concepts/obsidian-wiki-index.md"

def lint(vault) -> dict:
    """Compatibility wrapper for WikiVault's canonical lint implementation."""
    return vault._lint_impl()

def fix_orphans(vault, dry_run: bool = False) -> dict:
    from .index import first_summary_line
    from .links import WIKILINK_RE
    lint_res = lint(vault)
    orphans = lint_res.get("problems", {}).get("orphans", []) or []
    if not orphans:
        return {"orphans": 0, "fixed": 0, "dry_run": dry_run, "plan": [], "hubs": {}}
    pages = vault.load_pages()
    by_rel = {p["rel"]: p for p in pages}
    orphan_hub = "concepts/obsidian-wiki-index.md"
    hub_groups = {}
    plan = []
    for rel in sorted(orphans):
        if rel == orphan_hub:
            continue
        pg = by_rel.get(rel, {})
        title = pg.get("title") or Path(rel).stem
        ptype = pg.get("ptype") or ""
        body = pg.get("body") or ""
        summary = first_summary_line(body) if body else "(auto-linked orphan)"
        tags = pg.get("meta", {}).get("tags", []) if pg else []
        if not isinstance(tags, list):
            tags = [str(tags)] if tags else []
        hub = _hub_for_orphan(vault, rel, title=title, ptype=ptype,
                              tags=tags, body=body)
        if hub == rel:
            hub = "concepts/obsidian-wiki-index.md"
        if not (vault.root / hub).exists():
            fallback = "concepts/obsidian-wiki-index.md"
            if (vault.root / fallback).exists():
                hub = fallback
            else:
                continue
        entry = {"orphan": rel, "title": title, "summary": summary, "hub": hub}
        plan.append(entry)
        hub_groups.setdefault(hub, []).append(entry)
    if dry_run:
        return {"orphans": len(orphans), "fixed": 0, "dry_run": True, "plan": plan, "hubs": {h: [e["orphan"] for e in v] for h, v in hub_groups.items()}}
    fixed = 0
    hubs_touched = []
    for hub_rel, entries in hub_groups.items():
        hub_path = vault.root / hub_rel
        try:
            text = hub_path.read_text(encoding="utf-8")
        except OSError:
            continue
        original = text
        for entry in entries:
            orphan_rel = entry["orphan"]
            title = entry["title"]
            summary = entry["summary"]
            rel_no_md = orphan_rel[:-3] if orphan_rel.lower().endswith(".md") else orphan_rel
            stem_lower = Path(orphan_rel).stem.lower()
            already = False
            for existing_link in WIKILINK_RE.findall(text):
                es = existing_link.strip().split("/")[-1].strip()
                es = re.sub(r"\.md$", "", es, flags=re.IGNORECASE).lower()
                if es == stem_lower:
                    already = True
                    break
            if already:
                continue
            bullet = f"- [[{rel_no_md}|{title}]] - {summary}"
            auto_header = "## Auto-linked"
            related_header = "## Related"
            linked_header = "## Linked from"
            if auto_header in text:
                idx2 = text.index(auto_header)
                header_end = text.index("\n", idx2) + 1 if "\n" in text[idx2:] else len(text)
                next_heading = None
                for m in re.finditer(r"\n## ", text[header_end:]):
                    next_heading = header_end + m.start()
                    break
                insert_at = next_heading if next_heading is not None else len(text)
                before = text[:insert_at].rstrip()
                after_text = text[insert_at:]
                text = before + "\n" + bullet + "\n" + after_text.lstrip("\n")
            elif related_header in text:
                idx2 = text.index(related_header)
                header_end = text.index("\n", idx2) + 1 if "\n" in text[idx2:] else len(text)
                next_heading = None
                for m in re.finditer(r"\n## ", text[header_end:]):
                    next_heading = header_end + m.start()
                    break
                insert_at = next_heading if next_heading is not None else len(text)
                before = text[:insert_at].rstrip()
                after_text = text[insert_at:]
                text = before + "\n" + bullet + "\n" + after_text.lstrip("\n")
            else:
                if linked_header in text:
                    idx2 = text.index(f"\n{linked_header}")
                    text = text[:idx2].rstrip() + f"\n\n{auto_header}\n\n" + bullet + "\n" + text[idx2:]
                else:
                    if not text.endswith("\n"):
                        text += "\n"
                    text += f"\n{auto_header}\n\n" + bullet + "\n"
            fixed += 1
        if text != original:
            hub_path.write_text(text, encoding="utf-8")
            hubs_touched.append(hub_rel)
    if fixed:
        vault.rebuild_index()
    lint_after = lint(vault)
    broken = lint_after.get("problems", {}).get("broken_links", [])
    return {"orphans_before": len(orphans), "fixed": fixed, "dry_run": False, "hubs_touched": sorted(hubs_touched), "plan": plan, "hubs": {h: [e["orphan"] for e in v] for h, v in hub_groups.items()}, "lint_after": lint_after, "broken_links_after": len(broken)}
