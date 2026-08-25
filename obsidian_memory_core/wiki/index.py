
"""Index maintenance helpers."""
from __future__ import annotations
import re
from datetime import date
from pathlib import Path

INDEX_HEADER = """---
title: Agent Vault Index
type: index
updated: {today}
tags:
  - wiki
  - index
---

# Index - Wiki Map

> [!info] Rule number 1
> Read this file BEFORE querying to know what the wiki contains. The index is
> the only map, no vector search needed. This file is maintained automatically
> by the obsidianwiki memory plugin after every page write.

"""

def first_summary_line(body: str) -> str:
    for line in body.splitlines():
        s = line.strip()
        if not s or s.startswith(("#", ">", "---", "!", "|")):
            continue
        return (s[:140] + "...") if len(s) > 140 else s
    return "(empty page)"

def _existing_summaries(vault) -> dict[str, str]:
    try:
        text = vault.index_path.read_text(encoding="utf-8")
    except OSError:
        return {}
    result = {}
    for match in re.finditer(r"^- \[\[([^\]|]+)\|[^\]]+\]\] - (.+)$", text, re.MULTILINE):
        result[match.group(1).strip()] = match.group(2).strip()
    return result

def rebuild_index(vault) -> None:
    from .frontmatter import parse_frontmatter
    # Import constants lazily to avoid cycle
    from .vault import TYPE_DIRS, VALID_TYPES, SECTION_TITLES  # type: ignore
    old_summaries = _existing_summaries(vault)
    pages = vault.load_pages()
    by_type = {t: [] for t in VALID_TYPES}
    for page in pages:
        by_type.setdefault(page["ptype"], []).append(page)
    counts = {t: len(by_type[t]) for t in VALID_TYPES}
    total = sum(counts.values()) + 1
    parts = [
        INDEX_HEADER.format(today=date.today().isoformat()),
        "## Stats",
        "- Pages: {} ({})".format(
            total,
            " - ".join(f"{k} {counts[k]}" for k in VALID_TYPES if counts[k]) or "empty",
        ),
        f"- Updated: {date.today().isoformat()}",
        "",
    ]
    intros = {
        "entity": "Concrete things: projects, companies, tools, systems.",
        "person": "People: individuals relevant to your work - colleagues, collaborators, contacts.",
        "decision": "Settled decisions with reasons and evidence - never re-litigate without new facts.",
        "environment": "Machine + infrastructure facts: paths, servers, OS quirks, gateways.",
        "concept": "Lessons learned, workflows, patterns.",
        "source": "Raw ingested documents. Grouped by subfolder - browse the folder, individual files are NOT listed.",
        "answer": "High-quality answers saved back for reuse.",
        "preference": "Standing rules for how the agent should behave and respond.",
    }
    for ptype in VALID_TYPES:
        parts.append(f"## {SECTION_TITLES[ptype]}")
        parts.append(intros[ptype])
        parts.append("")
        plist = sorted(by_type[ptype], key=lambda p: p["title"].lower())
        if not plist:
            parts.append("- (no pages yet)")
        elif ptype == "source":
            groups: dict[str, list] = {}
            for page in plist:
                rel_parts = Path(page["rel"]).parts
                group_parts = rel_parts[:-1][:4]
                group = "/".join(group_parts)
                groups.setdefault(group, []).append(page)
            for group in sorted(groups):
                members = groups[group]
                newest = max((p["updated"] for p in members if p["updated"]), default="?")
                parts.append(f"- `{group}/` - {len(members)} file(s), newest {newest}. Browse the folder directly.")
        else:
            for page in plist:
                key = page["rel"]
                summary = old_summaries.get(key) or first_summary_line(page["body"])
                parts.append(f"- [[{key}|{page['title']}]] - {summary}")
        parts.append("")
    vault.index_path.write_text("\n".join(parts), encoding="utf-8")
