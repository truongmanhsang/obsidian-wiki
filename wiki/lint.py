
"""Lint and orphan-fixing helpers."""
from __future__ import annotations
import re
from pathlib import Path
from .links import WIKILINK_RE, _alias_map, _out_links
from .frontmatter import FRONTMATTER_RE
from .normalize import _normalize
from .frontmatter import _parse_aliases_list

def _hub_for_orphan(vault, orphan_rel: str, title: str = "", ptype: str = "") -> str:
    if not ptype:
        from .vault import DIR_TYPES
        try:
            ptype = DIR_TYPES.get(orphan_rel.split("/", 1)[0], "")
        except Exception:
            ptype = ""
    hub_by_type = {
        "entity": "concepts/obsidian-wiki-memory-system.md",
        "person": "concepts/obsidian-wiki-memory-system.md",
        "concept": "concepts/obsidian-wiki-memory-system.md",
        "decision": "concepts/obsidian-wiki-memory-system.md",
        "answer": "concepts/obsidian-wiki-memory-system.md",
        "preference": "concepts/obsidian-wiki-memory-system.md",
        "environment": "environment/obsidian-vault.md",
        "source": "concepts/obsidian-wiki-memory-system.md",
    }
    hub = hub_by_type.get(ptype, "concepts/obsidian-wiki-memory-system.md")
    if not (vault.root / hub).exists():
        fallback = "environment/obsidian-vault.md"
        if (vault.root / fallback).exists():
            return fallback
        return "concepts/obsidian-wiki-memory-system.md"
    return hub

def lint(vault) -> dict:
    from .vault import VALID_TYPES
    pages = vault.load_pages()
    stems = _alias_map(pages)
    problems = {"orphans": [], "missing_frontmatter": [], "broken_links": [], "stale_claims": []}
    inbound: dict[str, set[str]] = {p["rel"]: set() for p in pages}
    for page in pages:
        if page["ptype"] == "source":
            continue
        body_text = re.sub(r"\n## Linked from\n(?:\n|- .*\n?)*", "\n", page["text"])
        for link in WIKILINK_RE.findall(body_text):
            link_stem = link.strip().split("/")[-1].strip()
            link_stem = re.sub(r"\.md$", "", link_stem, flags=re.IGNORECASE)
            target = link_stem.lower()
            hit = stems.get(target)
            path_part = re.split(r"[|#]", link.strip(), maxsplit=1)[0].strip()
            if path_part.endswith(".md"):
                path_part = path_part[:-3]
            mismatch = False
            if hit is not None and "/" in path_part:
                want_dir = path_part.split("/", 1)[0].lower()
                have_dir = hit.split("/", 1)[0]
                mismatch = want_dir != have_dir
            if hit is None or mismatch:
                problems["broken_links"].append(f"{page['rel']}: [[{link.strip()}]]")
                continue
            if hit != page["rel"]:
                inbound[hit].add(page["rel"])
    log_dates: dict[str, str] = {}
    try:
        # Prefer DB
        use_db = False
        rows = []
        try:
            if (vault.root / "log.db").exists():
                import sqlite3
                conn = sqlite3.connect(str(vault.root / "log.db"), timeout=5)
                cur = conn.execute("SELECT date, kind, message, is_auto FROM logs ORDER BY id ASC;")
                rows = cur.fetchall()
                conn.close()
                use_db = len(rows) > 0
        except Exception:
            use_db = False
        if use_db:
            for _d, _k, _msg, _auto in rows:
                line = f"- {_d} {_k}{' (auto)' if _auto else ''}: {_msg}"
                m = re.match(r"^- (\d{4}-\d{2}-\d{2}) \w+(?:\s*\(auto\))?: (.*)$", line)
                if not m:
                    continue
                day, desc = m.groups()
                for stem, rel in stems.items():
                    if stem in desc.lower():
                        log_dates[rel] = max(log_dates.get(rel, ""), day)
        else:
            for line in vault.log_path.read_text(encoding="utf-8").splitlines():
                m = re.match(r"^- (\d{4}-\d{2}-\d{2}) \w+(?:\s*\(auto\))?: (.*)$", line)
                if not m:
                    continue
                day, desc = m.groups()
                for stem, rel in stems.items():
                    if stem in desc.lower():
                        log_dates[rel] = max(log_dates.get(rel, ""), day)
    except OSError:
        pass
    for page in pages:
        if not page["meta"]:
            problems["missing_frontmatter"].append(page["rel"])
            continue
        if page["ptype"] not in VALID_TYPES:
            problems["missing_frontmatter"].append(f"{page['rel']} (bad type '{page['ptype']}')")
        referrers = inbound[page["rel"]] - {"index.md"}
        if not referrers:
            problems["orphans"].append(page["rel"])
        last_touch = log_dates.get(page["rel"], "")
        if (last_touch and page["updated"] and last_touch > page["updated"]):
            problems["stale_claims"].append(f"{page['rel']} updated {page['updated']} but log shows {last_touch}")
    real_orphans = [o for o in problems["orphans"] if not o.startswith("sources/")]
    problems["orphans"] = real_orphans
    missing_fm = []
    for page in pages:
        fm_body = ""
        m = FRONTMATTER_RE.match(page["text"])
        if m:
            fm_body = m.group(0)
        missing = [f for f in ("type", "tags", "aliases") if not re.search(rf"(?m)^{f}:", fm_body)]
        if missing:
            missing_fm.append(f"{page['rel']} ({', '.join(missing)})")
    if missing_fm:
        problems["missing_frontmatter"] = missing_fm
    try:
        if (vault.root / "log.db").exists():
            try:
                import sqlite3
                conn = sqlite3.connect(str(vault.root / "log.db"), timeout=5)
                cur = conn.execute("SELECT date, kind, message, is_auto FROM logs ORDER BY id DESC LIMIT 500;")
                rows = cur.fetchall()
                conn.close()
                rows = list(reversed(rows))
                log_content = "\n".join(f"- {d} {k}{' (auto)' if a else ''}: {m}" for d,k,m,a in rows)
            except Exception:
                log_content = vault.log_path.read_text(encoding="utf-8")
        else:
            log_content = vault.log_path.read_text(encoding="utf-8")
    except OSError:
        log_content = ""
    aliases_wiped: list[str] = []
    for page in pages:
        if page["ptype"] == "source":
            continue
        aliases_val = page["meta"].get("aliases")
        is_empty = False
        if isinstance(aliases_val, list):
            is_empty = len(aliases_val) == 0
        else:
            s = str(aliases_val).strip() if aliases_val is not None else ""
            is_empty = not s or s == "[]"
        if not is_empty:
            continue
        stem_low = page["stem"].lower()
        rel_low = page["rel"].lower()
        logged = stem_low in log_content.lower() or rel_low in log_content.lower()
        has_guard_warning = "preserving aliases" in log_content.lower() and stem_low in log_content.lower()
        if has_guard_warning:
            aliases_wiped.append(f"{page['rel']} (aliases empty but log shows guard preserved prior aliases)")
        elif logged and page["ptype"] == "person":
            aliases_wiped.append(f"{page['rel']} (person page has empty aliases but log shows prior activity)")
    if "preserving aliases" in log_content.lower():
        for line in log_content.splitlines():
            if "preserving aliases" in line.lower():
                m_path = re.search(r"for\s+([^\s]+\.md)", line)
                if m_path:
                    rel_guess = m_path.group(1)
                    try:
                        p = Path(rel_guess)
                        if p.is_absolute():
                            try:
                                rel_guess = p.relative_to(vault.root).as_posix()
                            except ValueError:
                                rel_guess = p.name
                    except Exception:
                        pass
                    entry = f"{rel_guess} (frontmatter guard triggered; aliases were preserved)"
                    if entry not in aliases_wiped:
                        aliases_wiped.append(entry)
    if aliases_wiped:
        problems["aliases_wiped"] = sorted(set(aliases_wiped))
    stem_to_rel = {p["stem"].lower(): p["rel"] for p in pages}
    weak = []
    for page in pages:
        if page["ptype"] == "source":
            continue
        rel = page["rel"]
        stripped = dict(page)
        stripped["text"] = re.sub(r"\n## Linked from\n(?:\n|- .*\n?)*", "\n", page["text"])
        resolved_out = {stem_to_rel[t] for t in _out_links(stripped) if t in stem_to_rel and stem_to_rel[t] != rel}
        degree = len(inbound.get(rel, set())) + len(resolved_out)
        if degree < 2:
            weak.append(f"{rel} (degree {degree})")
    if weak:
        problems["weak_connectivity"] = weak
    dup_groups = vault.detect_duplicates()
    if dup_groups:
        by_rel = {p["rel"]: p for p in pages}
        formatted: list[str] = []
        for grp in dup_groups:
            sig_map: dict[str, set[str]] = {}
            alias_map: dict[str, set[str]] = {}
            for rel in grp:
                pg = by_rel.get(rel)
                if not pg:
                    continue
                stem_n = _normalize(pg["stem"])
                title_n = _normalize(pg["title"])
                alist = _parse_aliases_list(pg)
                a_norms = { _normalize(a) for a in alist if _normalize(a) }
                s = set()
                if stem_n:
                    s.add(stem_n)
                if title_n:
                    s.add(title_n)
                s |= a_norms
                sig_map[rel] = s
                alias_map[rel] = a_norms
            token_counts: dict[str, int] = {}
            for s in sig_map.values():
                for tok in s:
                    token_counts[tok] = token_counts.get(tok, 0) + 1
            shared = [t for t, c in token_counts.items() if c > 1]
            if shared:
                max_c = max(token_counts[t] for t in shared)
                candidates = [t for t in shared if token_counts[t] == max_c]
                hint_token = sorted(candidates)[0]
                in_alias = any(hint_token in alias_map.get(r, set()) for r in grp)
                if in_alias:
                    label = f"alias: {hint_token}"
                else:
                    in_stem = any(_normalize(by_rel[r]["stem"]) == hint_token for r in grp if r in by_rel)
                    in_title = any(_normalize(by_rel[r]["title"]) == hint_token for r in grp if r in by_rel)
                    if in_stem and not in_title:
                        label = f"stem: {hint_token}"
                    elif in_title:
                        label = f"title: {hint_token}"
                    else:
                        label = f"alias: {hint_token}"
            else:
                label = "alias: ?"
            entry = " ~ ".join(grp) + f" ({label})"
            formatted.append(entry)
        problems["duplicates"] = sorted(formatted)
        problems["duplicates_hint"] = ["Run with --fix or manually merge: keep canonical page, add aliases, delete duplicate; use allow_duplicate=True if intentional."]
    result = {"pages_scanned": len(pages), "problems": {k: v for k, v in problems.items() if v}, "clean": not any(problems.values())}
    if dup_groups:
        result["fix_hint"] = "Duplicates found. Merge groups: keep one canonical file, add aliases [Sang, ...] to it, delete duplicates. Or run `obsidian_wiki lint --fix` / `vault.fix_duplicates()` if available. Use allow_duplicate=True to override write guard."
    return result

def fix_orphans(vault, dry_run: bool = False) -> dict:
    from .index import first_summary_line
    from .links import WIKILINK_RE
    lint_res = lint(vault)
    orphans = lint_res.get("problems", {}).get("orphans", []) or []
    if not orphans:
        return {"orphans": 0, "fixed": 0, "dry_run": dry_run, "plan": [], "hubs": {}}
    pages = vault.load_pages()
    by_rel = {p["rel"]: p for p in pages}
    hub_groups = {}
    plan = []
    for rel in sorted(orphans):
        pg = by_rel.get(rel, {})
        title = pg.get("title") or Path(rel).stem
        ptype = pg.get("ptype") or ""
        body = pg.get("body") or ""
        summary = first_summary_line(body) if body else "(auto-linked orphan)"
        hub = _hub_for_orphan(vault, rel, title=title, ptype=ptype)
        if hub == rel:
            hub = "concepts/obsidian-wiki-memory-system.md"
        if not (vault.root / hub).exists():
            fallback = "concepts/obsidian-wiki-memory-system.md"
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
