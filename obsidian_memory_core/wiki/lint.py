"""Lint and root-index orphan-fixing helpers."""
from __future__ import annotations

import re
from pathlib import Path

from .links import WIKILINK_RE
from .intent import normalize_search


INDEX_REL = "index.md"


def lint(vault) -> dict:
    """Compatibility wrapper for WikiVault's canonical lint implementation."""
    return vault._lint_impl()


def _canonical_target(raw_link: str) -> str:
    """Normalize a wikilink target for comparison with a vault-relative path."""
    target = re.split(r"[|#]", raw_link.strip(), maxsplit=1)[0].strip()
    target = target.replace("\\", "/").lstrip("./").lower()
    if target.endswith(".md"):
        target = target[:-3]
    return target


def _link_matches_page(raw_link: str, page_rel: str) -> bool:
    target = _canonical_target(raw_link)
    page = page_rel[:-3] if page_rel.lower().endswith(".md") else page_rel
    page = page.replace("\\", "/").lower()
    if "/" in target:
        return target == page
    return target == Path(page).stem.lower()


def _navigation_links(text: str):
    """Yield links that are actual navigation bullets, not quoted summaries."""
    for line in text.splitlines():
        if not re.match(r"^\s*(?:[-*+] |\d+[.)] )", line):
            continue
        links = WIKILINK_RE.findall(line)
        if links:
            yield links[0]


def _index_inbound(vault, inbound: dict[str, set[str]], stems: dict[str, str]) -> None:
    """Count valid root-index links as inbound navigation edges."""
    try:
        index_text = vault.index_path.read_text(encoding="utf-8")
    except OSError:
        return
    for raw_link in _navigation_links(index_text):
        target = _canonical_target(raw_link)
        hit = stems.get(normalize_search(target.split("/")[-1]))
        if hit is None:
            continue
        if "/" in target:
            want_dir = target.split("/", 1)[0]
            have_dir = hit.split("/", 1)[0].lower()
            if want_dir != have_dir:
                continue
        inbound[hit].add(INDEX_REL)


def _insert_index_entries(text: str, entries: list[dict]) -> tuple[str, int]:
    """Insert missing orphan bullets into a generated navigation section."""
    missing: list[str] = []
    for entry in entries:
        if any(_link_matches_page(link, entry["orphan"]) for link in _navigation_links(text)):
            continue
        rel_no_md = entry["orphan"][:-3] if entry["orphan"].lower().endswith(".md") else entry["orphan"]
        missing.append(f"- [[{rel_no_md}|{entry['title']}]] - {entry['summary']}")
    if not missing:
        return text, 0

    section = "## Auto-linked"
    bullets = "\n".join(missing)
    if section in text:
        start = text.index(section)
        content_start = text.find("\n", start)
        content_start = len(text) if content_start == -1 else content_start + 1
        next_heading = re.search(r"\n## ", text[content_start:])
        end = content_start + next_heading.start() if next_heading else len(text)
        before = text[:end].rstrip()
        after = text[end:].lstrip("\n")
        separator = "\n" if after else ""
        updated = f"{before}\n{bullets}\n{separator}{after}"
    else:
        updated = text.rstrip() + f"\n\n{section}\n\n{bullets}\n"
    return updated, len(missing)


def fix_orphans(vault, dry_run: bool = False) -> dict:
    """Link orphan pages from the root ``index.md`` without LLM routing."""
    lint_res = lint(vault)
    orphans = lint_res.get("problems", {}).get("orphans", []) or []
    base = {
        "orphans": len(orphans),
        "fixed": 0,
        "dry_run": dry_run,
        "plan": [],
        "index_updated": False,
    }
    if not orphans:
        base["lint_after"] = lint_res
        base["broken_links_after"] = len(lint_res.get("problems", {}).get("broken_links", []))
        return base

    pages = {page["rel"]: page for page in vault.load_pages()}
    plan = []
    for rel in sorted(orphans):
        page = pages.get(rel, {})
        body = page.get("body", "")
        plan.append({
            "orphan": rel,
            "title": page.get("title") or Path(rel).stem,
            "summary": first_summary_line(body),
            "index": INDEX_REL,
        })
    base["plan"] = plan
    if dry_run:
        return base

    if not vault.index_path.exists():
        vault.rebuild_index()
    try:
        original = vault.index_path.read_text(encoding="utf-8")
    except OSError:
        base["lint_after"] = lint(vault)
        base["broken_links_after"] = len(base["lint_after"].get("problems", {}).get("broken_links", []))
        return base
    from .vault import _atomic_write_text

    updated, fixed = _insert_index_entries(original, plan)
    if fixed:
        _atomic_write_text(vault.index_path, updated)
        vault.append_log(
            "LINT",
            f"auto-linked {fixed} orphan page(s) to {INDEX_REL}",
            quiet=True,
        )
        base["index_updated"] = True
    base["fixed"] = fixed
    base["lint_after"] = lint(vault)
    base["broken_links_after"] = len(
        base["lint_after"].get("problems", {}).get("broken_links", [])
    )
    return base


def first_summary_line(body: str) -> str:
    """Return a compact summary for generated index bullets."""
    for line in body.splitlines():
        value = line.strip()
        if not value or value.startswith(("#", ">", "---", "!", "|")):
            continue
        return (value[:140] + "...") if len(value) > 140 else value
    return "(empty page)"
