"""WikiVault class - skeleton delegating to submodules."""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date
from pathlib import Path

from obsidian_memory_core.wiki.normalize import _normalize
from obsidian_memory_core.wiki.frontmatter import FRONTMATTER_RE, parse_frontmatter, _parse_aliases_list, page_title
from obsidian_memory_core.wiki.links import WIKILINK_RE, TOKEN_RE, _alias_map, _out_links, _inbound_links
from obsidian_memory_core.wiki.index import INDEX_HEADER, first_summary_line, _existing_summaries, rebuild_index as _rebuild_index_fn
from obsidian_memory_core.wiki.log import LOG_HEADER, append_log as _append_log_fn, log_tail as _log_tail_fn, migrate_log_md_to_db, _ensure_db, _iter_log_rows  # noqa: F401
from obsidian_memory_core.wiki.dedup import detect_duplicates as _detect_duplicates_fn
from obsidian_memory_core.wiki.lint import lint as _lint_fn, _hub_for_orphan as _hub_fn, fix_orphans as _fix_orphans_fn
from obsidian_memory_core.wiki.search import search as _search_fn, prefetch_context as _prefetch_fn

logger = logging.getLogger(__name__)

# Re-export for backward compat
WIKILINK_RE = WIKILINK_RE
FRONTMATTER_RE = FRONTMATTER_RE
TOKEN_RE = TOKEN_RE

TYPE_DIRS = {
    "entity": "entities",
    "person": "people",
    "decision": "decisions",
    "environment": "environment",
    "concept": "concepts",
    "source": "sources",
    "answer": "answers",
    "preference": "preferences",
}
DIR_TYPES = {v: k for k, v in TYPE_DIRS.items()}
SECTION_TITLES = {
    "entity": "Entities",
    "person": "People",
    "decision": "Decisions",
    "environment": "Environment",
    "concept": "Concepts",
    "source": "Sources",
    "answer": "Answers",
    "preference": "Preferences",
}
VALID_TYPES = tuple(TYPE_DIRS)

STOPWORDS = {
    "the", "and", "for", "with", "this", "that", "what", "how", "does",
    "did", "are", "was", "were", "has", "have", "you", "your", "our",
    "their", "its", "from", "into", "about", "can", "could", "should",
    "would", "will", "there", "here", "when", "where", "which", "who",
    "why", "not", "but", "all", "any", "get", "got", "use", "using",
}

MAX_READ_CHARS = 20000
MAX_WRITE_CHARS = 100_000

INDEX_HEADER = INDEX_HEADER
LOG_HEADER = LOG_HEADER

ENTITY_TEMPLATE = """---
type: entity
updated: YYYY-MM-DD
tags: []
aliases: []
---

# Entity Name

One-line description of what this is.

## Key facts

- fact 1

## Related

- [[Other page]]
"""
CONCEPT_TEMPLATE = """---
type: concept
updated: YYYY-MM-DD
tags: []
aliases: []
---

# Concept Name

The lesson or workflow, short and actionable.

## Core content

- main point

## Related

- [[Entity or other concept]]
"""

class WikiVaultError(Exception):
    """Raised for invalid vault operations."""


def _auto_fill_aliases_tags(ptype: str, stem: str, content: str) -> tuple[list, list]:
    """Deterministically derive aliases + tags for a page that left them empty.

    No LLM: everything is derived from the page's own H1 title, filename stem,
    and folder type. Aliases = the H1 title plus a title-cased filename (deduped).
    Tags = the folder type plus non-trivial filename keywords. This guarantees
    aliases/tags are never empty while never inventing facts outside the page.
    """
    m = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    title = m.group(1).strip() if m else ""
    # filename -> title case (keep short acronyms upper)
    ftitle = " ".join(
        p if (p.isupper() and len(p) <= 4) else (p[:1].upper() + p[1:] if p else p)
        for p in re.split(r"[-_]", stem)
    )
    aliases: list[str] = []
    seen: set[str] = set()
    for cand in (title, ftitle):
        c = cand.strip()
        if c and c.lower() not in seen:
            seen.add(c.lower())
            aliases.append(c)
    # tags: folder type + filename keywords (>2 chars, not purely numeric)
    kw = [w for w in re.split(r"[-_]", stem) if len(w) > 2 and not w.isdigit()]
    tags = [ptype]
    for w in kw:
        if w not in tags:
            tags.append(w)
    return aliases, tags


class WikiVault:
    """Deterministic, log-everything view of one Obsidian wiki vault."""

    def __init__(self, vault_path: str):
        self.root = Path(vault_path).expanduser().resolve()

    # ------------------------------------------------------------------
    # Basics
    # ------------------------------------------------------------------

    @property
    def index_path(self) -> Path:
        return self.root / "index.md"

    @property
    def log_path(self) -> Path:
        return self.root / "log.md"

    @property
    def log_db_path(self) -> Path:
        return self.root / "log.db"

    def exists(self) -> bool:
        return self.root.is_dir()

    def ensure_skeleton(self) -> None:
        """Create the vault skeleton idempotently (never overwrites content)."""
        self.root.mkdir(parents=True, exist_ok=True)
        for d in TYPE_DIRS.values():
            (self.root / d).mkdir(exist_ok=True)
        tdir = self.root / "templates"
        tdir.mkdir(exist_ok=True)
        if not (tdir / "entity-template.md").exists():
            (tdir / "entity-template.md").write_text(
                ENTITY_TEMPLATE, encoding="utf-8"
            )
        if not (tdir / "concept-template.md").exists():
            (tdir / "concept-template.md").write_text(
                CONCEPT_TEMPLATE, encoding="utf-8"
            )
        # log.db is source; migrate log.md if present
        if self.log_path.exists() and not self.log_db_path.exists():
            try:
                migrate_log_md_to_db(self)
            except Exception:
                _ensure_db(self)
        elif not self.log_db_path.exists():
            _ensure_db(self)
        else:
            # log.db is the sole log source; log.md is intentionally not recreated.
            # Existing legacy log.md is migrated above when needed.
            pass
        if not self.index_path.exists():
            self.rebuild_index()

    def safe_resolve(self, rel: str) -> Path:
        """Resolve rel inside the vault; raise on escape attempts."""
        if not isinstance(rel, str) or not rel.strip():
            raise WikiVaultError("path must be a non-empty relative path")
        rel = rel.strip().lstrip("/")
        candidate = (self.root / rel).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise WikiVaultError(f"path escapes vault root: {rel}")
        return candidate

    # ------------------------------------------------------------------
    # Frontmatter helpers
    # ------------------------------------------------------------------

    @staticmethod
    def parse_frontmatter(text: str):
        """Return ({flat keys}, body_without_frontmatter).

        Correctly parses YAML lists for tags/aliases:
        - inline: tags: [a, b]  or aliases: [Sang, Test]
        - block:
            tags:
              - wiki
              - index
            aliases:
              - Sang
              - Truong Manh Sang
        Other keys remain flat strings. List values are returned as Python lists.
        """
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
                # If we are inside a block list, check for dash items first
                if current_list_key is not None:
                    m_dash = re.match(r"^\s*-\s*(.*)$", line)
                    if m_dash is not None:
                        item = m_dash.group(1).strip().strip("'\"")
                        if item:
                            if not isinstance(meta.get(current_list_key), list):
                                meta[current_list_key] = []
                            meta[current_list_key].append(item)
                        continue
                    # Not a dash line: determine if this is a new top-level key
                    # Top-level keys start at column 0 and contain ':'
                    if ":" in line and not line.startswith((" ", "\t", "-")):
                        current_list_key = None
                        # fall through to key handling
                    else:
                        # Indented non-dash line: continuation or noise -> skip
                        if line.startswith((" ", "\t")):
                            continue
                        current_list_key = None
                # Top-level key line
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
                                    p = part.strip().strip("'\"")
                                    if p:
                                        items.append(p)
                                meta[key] = items
                            current_list_key = None
                        elif value:
                            # Single scalar value for tags/aliases -> single-item list
                            meta[key] = [value.strip().strip("'\"")]
                            current_list_key = None
                        else:
                            meta[key] = []
                            current_list_key = key
                    else:
                        meta[key] = value.strip().strip("'\"") if value else ""
                        current_list_key = None
        return meta, body

    @staticmethod
    def page_title(body: str, fallback: str) -> str:
        for line in body.splitlines():
            if line.startswith("# ") and len(line) > 2:
                return line[2:].strip()
        return fallback

    # ------------------------------------------------------------------
    # Page enumeration
    # ------------------------------------------------------------------

    def iter_pages(self):
        for d in TYPE_DIRS.values():
            dp = self.root / d
            if dp.is_dir():
                for f in sorted(dp.rglob("*.md")):
                    yield f

    @staticmethod
    def ptype_of(path: Path) -> str | None:
        """Type from the first path component (supports subfolders like
        sources/sessions/)."""
        try:
            first = path.relative_to(path.anchor and Path(path.anchor)).parts
        except Exception:
            return None
        # relative_to root handled by callers via safe_resolve; derive here:
        return None

    def load_pages(self) -> list[dict]:
        pages = []
        for path in self.iter_pages():
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as e:
                logger.debug("unreadable page %s: %s", path, e)
                continue
            meta, body = self.parse_frontmatter(text)
            rel = path.relative_to(self.root).as_posix()
            ptype = meta.get("type", "") or DIR_TYPES.get(path.relative_to(self.root).parts[0], "")
            pages.append(
                {
                    "path": path,
                    "rel": rel,
                    "stem": path.stem,
                    "title": self.page_title(body, path.stem),
                    "ptype": ptype,
                    "updated": meta.get("updated", ""),
                    "text": text,
                    "body": body,
                    "meta": meta,
                }
            )
        return pages

    def stats(self) -> dict:
        counts = {t: 0 for t in VALID_TYPES}
        for page in self.load_pages():
            if page["ptype"] in counts:
                counts[page["ptype"]] += 1
        return counts

    # ------------------------------------------------------------------
    # Write path (page + index + log kept atomic-by-convention)
    # ------------------------------------------------------------------

    def write_page(self, rel: str, content: str, note: str = "",
                   allow_source: bool = False,
                   quiet_log: bool | None = None,
                   allow_duplicate: bool = False) -> dict:
        """Write a page + rebuild index + log.

        quiet_log: True -> aggregated daily log line (bulk ops); False ->
        one explicit line (curated edits); None -> auto (True for sources/,
        False for curated folders)."""
        auto_quiet = quiet_log is None
        if not isinstance(content, str) or len(content.strip()) < 10:
            raise WikiVaultError("content too short to be a wiki page")
        if len(content) > MAX_WRITE_CHARS:
            raise WikiVaultError(
                f"content exceeds {MAX_WRITE_CHARS} chars; split the page"
            )
        path = self.safe_resolve(rel)
        if path.suffix == "":
            path = path.with_suffix(".md")
        if path.suffix != ".md":
            raise WikiVaultError("only .md pages are supported")
        rel_dir = path.relative_to(self.root).parts[0]
        ptype = DIR_TYPES.get(rel_dir)
        if ptype is None:
            raise WikiVaultError(
                "pages live in entities/, people/, decisions/, environment/, "
                "concepts/, sources/, answers/ or preferences/"
            )
        if ptype == "source" and not allow_source:
            raise WikiVaultError(
                "sources/ is read-only; ingest notes belong in concepts/"
            )
        if auto_quiet:
            quiet_log = ptype == "source"

        meta, body = self.parse_frontmatter(content)
        fm_type = meta.get("type", "")
        if fm_type and fm_type != ptype:
            raise WikiVaultError(
                f"frontmatter type '{fm_type}' conflicts with folder "
                f"'{rel_dir}' ('{ptype}')"
            )
        # --- dedup guard: check against existing pages ---
        if not allow_duplicate:
            proposed_rel = path.relative_to(self.root).as_posix()
            proposed_stem = path.stem
            proposed_title = self.page_title(body, proposed_stem)
            prop_aliases_raw = meta.get("aliases", [])
            if isinstance(prop_aliases_raw, list):
                prop_aliases = prop_aliases_raw
            elif isinstance(prop_aliases_raw, str) and prop_aliases_raw.strip():
                s = prop_aliases_raw.strip()
                if s.startswith("[") and s.endswith("]"):
                    inner = s[1:-1].strip()
                    prop_aliases = [p.strip().strip("'\"") for p in inner.split(",") if p.strip()] if inner else []
                else:
                    prop_aliases = [p.strip().strip("'\"") for p in s.split(",") if p.strip()]
            else:
                prop_aliases = []
            prop_norms: set[str] = set()
            for v in [proposed_stem, proposed_title] + prop_aliases:
                nv = _normalize(v)
                if nv:
                    prop_norms.add(nv)
            if prop_norms:
                for pg in self.load_pages():
                    if pg["rel"] == proposed_rel:
                        continue
                    if pg["ptype"] == "source":
                        continue
                    existing_norms: set[str] = set()
                    for v in [pg["stem"], pg["title"]] + _parse_aliases_list(pg):
                        nv = _normalize(v)
                        if nv:
                            existing_norms.add(nv)
                    overlap = prop_norms & existing_norms
                    if overlap:
                        token = sorted(overlap)[0]
                        raise WikiVaultError(
                            f"Duplicate detected: '{proposed_rel}' collides with existing '{pg['rel']}' on normalized token '{token}' "
                            f"(e.g. alias/stem/title '{token}'). Page '{pg['rel']}' already covers this entity. "
                            f"Use UPDATE on '{pg['rel']}' instead of CREATE, or merge aliases into the canonical page. "
                            f"If intentional, pass allow_duplicate=True."
                        )
        had_fm = bool(FRONTMATTER_RE.match(content))
        if not had_fm:
            # No frontmatter yet: derive a complete, non-empty trio from the
            # page's own title/filename/type (never empty, never invented).
            derived_aliases, derived_tags = _auto_fill_aliases_tags(ptype, path.stem, content)
            content = (
                f"---\ntype: {ptype}\n"
                f"updated: {date.today().isoformat()}\n"
                f"tags: {derived_tags}\naliases: {derived_aliases}\n---\n\n{content}"
            )
        else:
            # refresh the updated stamp on every edit
            content = FRONTMATTER_RE.sub(
                lambda m: re.sub(
                    r"(?m)^updated:.*$",
                    f"updated: {date.today().isoformat()}",
                    m.group(0),
                    count=1,
                ),
                content,
                count=1,
            )
            # Re-parse after updated bump (meta already correct due to fixed parse_frontmatter)
            meta, _ = self.parse_frontmatter(content)
            # Guard: capture existing tags/aliases from file on disk BEFORE overwrite
            existing_tags: list = []
            existing_aliases: list = []
            if path.exists():
                try:
                    prev_text = path.read_text(encoding="utf-8")
                    prev_meta, _ = self.parse_frontmatter(prev_text)
                    pt = prev_meta.get("tags", [])
                    pa = prev_meta.get("aliases", [])
                    existing_tags = pt if isinstance(pt, list) else ([pt] if pt else [])
                    existing_aliases = pa if isinstance(pa, list) else ([pa] if pa else [])
                except OSError:
                    pass
            # Enforce the required trio (type/tags/aliases): rebuild in canonical order
            # Parse raw frontmatter block with proper list extraction via parse_frontmatter
            # (not just meta.get string) — now meta lists are faithful.
            def _norm_list(v, fallback: list) -> list:
                if isinstance(v, list):
                    return v
                if isinstance(v, str) and v.strip():
                    s = v.strip()
                    if s.startswith("[") and s.endswith("]"):
                        inner = s[1:-1].strip()
                        if not inner:
                            return []
                        return [p.strip().strip("'\"") for p in inner.split(",") if p.strip()]
                    return [p.strip().strip("'\"") for p in s.split(",") if p.strip()]
                return fallback if fallback is not None else []

            # Tags: preserve faithfully; if empty, auto-fill from type/filename
            # so the required trio is never empty (deterministic, no LLM).
            tags_val = meta.get("tags", [])
            tags_list = _norm_list(tags_val, [])
            if not tags_list:
                _, tags_list = _auto_fill_aliases_tags(ptype, path.stem, content)
            # Aliases: guard against accidental wipe to [] when previous had values
            aliases_val = meta.get("aliases", [])
            aliases_list = _norm_list(aliases_val, [])
            if not aliases_list and existing_aliases:
                logger.warning(
                    "frontmatter guard: preserving aliases %s for %s (new write would have wiped to []); "
                    "if you intend to clear aliases, explicitly set allow_empty_aliases or edit file directly",
                    existing_aliases, path,
                )
                # Also record in vault log for lint visibility
                try:
                    self.append_log("LINT", f"frontmatter guard: preserving aliases {existing_aliases} for {path} (would have wiped to [])")
                except Exception:
                    pass
                aliases_list = existing_aliases
            elif not aliases_list:
                # Empty and no prior aliases: auto-fill from title/filename
                # so aliases are never empty going forward.
                aliases_list, _ = _auto_fill_aliases_tags(ptype, path.stem, content)

            fm_pairs = [
                ("type", ptype),
                ("updated", date.today().isoformat()),
                ("tags", tags_list),
                ("aliases", aliases_list),
            ]
            def _fmt(v):
                if isinstance(v, list):
                    return "[" + ", ".join(str(x) for x in v) + "]" if v else "[]"
                return str(v)
            fm_text = "---\n" + "".join(
                f"{k}: {_fmt(v)}\n" for k, v in fm_pairs
            ) + "---\n\n"
            content = FRONTMATTER_RE.sub(lambda m: fm_text, content, count=1)

        is_new = not path.exists()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

        # Auto-backlinks: maintain a "Linked from" section on every curated
        # page touched by this write - the page itself AND every page it
        # links to (their inbound sets just changed).
        if ptype != "source":

            def _refresh_backlinks(target_path: Path) -> None:
                raw = target_path.read_text(encoding="utf-8")
                m = FRONTMATTER_RE.match(raw)
                fm_text = m.group(0) if m else ""
                body = raw[m.end():] if m else raw
                stem = target_path.stem
                inbound = sorted(self._inbound_links(stem))
                header = "## Linked from"
                # strip previous auto backlink section from BODY ONLY to preserve frontmatter
                if f"\n{header}" in body:
                    idx = body.index(f"\n{header}")
                    body = body[:idx].rstrip() + "\n"
                elif body.lstrip().startswith(header):
                    h_idx = body.find(header)
                    body = body[:h_idx].rstrip() + "\n"
                if not inbound:
                    # No inbound: remove previous backlink section if it existed, preserve frontmatter
                    if f"\n{header}" in raw or header in raw:
                        if fm_text:
                            target_path.write_text(fm_text + body, encoding="utf-8")
                        else:
                            target_path.write_text(body, encoding="utf-8")
                    return
                lines = [header, ""]
                for src_rel in inbound:
                    title = src_rel.split("/")[-1].removesuffix(".md")
                    lines.append(f"- [[{src_rel}|{title}]]")
                if not body.endswith("\n"):
                    body += "\n"
                new_body = body + "\n" + "\n".join(lines) + "\n"
                if fm_text:
                    target_path.write_text(fm_text + new_body, encoding="utf-8")
                else:
                    target_path.write_text(new_body, encoding="utf-8")

            _refresh_backlinks(path)
            # resolve linked stems against ALL pages (any folder), then
            # refresh their backlink sections too
            for pg in self.load_pages():
                if pg["path"] == path or pg["ptype"] == "source":
                    continue
                if pg["stem"].lower() in {
                    re.sub(r"\.md$", "", l.strip().split("/")[-1].strip(),
                           flags=re.IGNORECASE).lower()
                    for l in WIKILINK_RE.findall(content)
                }:
                    _refresh_backlinks(pg["path"])

        inbound = self._inbound_links(path.stem, exclude=path)
        self.rebuild_index()
        # Bulk/automated writes (session capture, pipeline extract) log
        # quietly - one aggregated daily line instead of one line per page.
        self.append_log(
            "WRITE" if is_new else "UPDATE",
            note or f"{path.stem} ({ptype}); inbound links: {len(inbound)}",
            quiet=quiet_log,
        )
        # auto-heal orphans (optional, idempotent, guarded against re-entry)
        if not getattr(self, "_auto_heal_in_progress", False):
            try:
                self._auto_heal_in_progress = True
                _lint_now = self.lint()
                if _lint_now.get("problems", {}).get("orphans"):
                    self.fix_orphans(dry_run=False)
            except Exception:
                pass
            finally:
                self._auto_heal_in_progress = False
        return {
            "status": "created" if is_new else "updated",
            "path": str(path),
            "type": ptype,
            "inbound_links": sorted(inbound),
            "indexed": True,
            "logged": True,
        }

    def _inbound_links(self, stem: str, exclude: Path | None = None) -> set[str]:
        """Pages whose wikilinks resolve to `stem` (case-insensitive).
        Auto-generated backlink sections don't count (navigation UI)."""
        target = stem.lower()
        found = set()
        for page in self.load_pages():
            if exclude is not None and page["path"] == exclude:
                continue
            if page["ptype"] == "source":
                continue  # transcripts quote links; they are not endorsements
            body_text = re.sub(
                r"\n## Linked from\n(?:\n|- .*\n?)*", "\n", page["text"]
            )
            for link in WIKILINK_RE.findall(body_text):
                link_stem = link.strip().split("/")[-1].strip()
                link_stem = re.sub(r"\.md$", "", link_stem, flags=re.IGNORECASE)
                if link_stem.lower() == target:
                    found.add(page["rel"])
        return found

    # ------------------------------------------------------------------
    # Index maintenance
    # ------------------------------------------------------------------

    def rebuild_index(self) -> None:
        """Deterministically regenerate index.md from the pages on disk.

        Existing one-line summaries are preserved when a bullet for the same
        page already exists in the old index; otherwise the first meaningful
        body line becomes the summary.
        """
        old_summaries = self._existing_summaries()
        pages = self.load_pages()
        by_type = {t: [] for t in VALID_TYPES}
        for page in pages:
            by_type.setdefault(page["ptype"], []).append(page)

        counts = {t: len(by_type[t]) for t in VALID_TYPES}
        total = sum(counts.values()) + 1  # + the index itself
        parts = [
            INDEX_HEADER.format(today=date.today().isoformat()),
            "## Stats",
            "- Pages: {} ({})".format(
                total,
                " - ".join(
                    f"{k} {counts[k]}" for k in VALID_TYPES if counts[k]
                )
                or "empty",
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
                # Session/raw sources grow unboundedly - one grouped bullet
                # per subfolder keeps the index O(1) instead of O(pages).
                groups: dict[str, list] = {}
                for page in plist:
                    rel_parts = Path(page["rel"]).parts
                    # cap grouping depth at 2 sublevels (e.g.
                    # sources/sessions/2026/08) so the index stays tiny even
                    # with per-day folders
                    group_parts = rel_parts[:-1][:4]
                    group = "/".join(group_parts)
                    groups.setdefault(group, []).append(page)
                for group in sorted(groups):
                    members = groups[group]
                    newest = max(
                        (p["updated"] for p in members if p["updated"]),
                        default="?",
                    )
                    parts.append(
                        f"- `{group}/` - {len(members)} file(s), "
                        f"newest {newest}. Browse the folder directly."
                    )
            else:
                for page in plist:
                    key = page["rel"]
                    summary = old_summaries.get(key) or first_summary_line(
                        page["body"]
                    )
                    parts.append(f"- [[{key}|{page['title']}]] - {summary}")
            parts.append("")
        self.index_path.write_text("\n".join(parts), encoding="utf-8")
        self.append_log(
            "INDEX_REBUILT",
            f"pages={len(pages) + 1}; index_path={self.index_path}; status=success",
            quiet=True,
        )

    def _existing_summaries(self) -> dict[str, str]:
        try:
            text = self.index_path.read_text(encoding="utf-8")
        except OSError:
            return {}
        result = {}
        for match in re.finditer(
            r"^- \[\[([^\]|]+)\|[^\]]+\]\] - (.+)$", text, re.MULTILINE
        ):
            result[match.group(1).strip()] = match.group(2).strip()
        return result

    # ------------------------------------------------------------------
    # Log
    # ------------------------------------------------------------------

    def append_log(self, kind: str, description: str,
                   quiet: bool = False) -> None:
        return _append_log_fn(self, kind, description, quiet=quiet)

    def log_tail(self, lines: int = 30) -> str:
        return _log_tail_fn(self, lines=lines)

    # ------------------------------------------------------------------
    # Search / prefetch
    # ------------------------------------------------------------------

    def _keyword_search(self, query: str, limit: int = 5) -> list[dict]:
        tokens = [
            t for t in TOKEN_RE.findall(query.lower()) if t not in STOPWORDS
        ]
        results = []
        all_pages = self.load_pages()
        aliases = _alias_map(all_pages)
        # alias tokens may be short acronyms ("GR") - match them directly,
        # bypassing the 3-char body-token minimum
        alias_tokens = [
            a for a in re.findall(r"[a-z0-9]{2,}", query.lower())
            if a in aliases and a not in STOPWORDS
        ]
        if not tokens and not alias_tokens:
            return []
        for page in all_pages:
            low = page["text"].lower()
            my_aliases = {
                a for a, rel in aliases.items() if rel == page["rel"]
            } - {page["stem"].lower()}
            title_hits = sum(1 for t in tokens if t in page["stem"].lower())
            # exact alias match is a STRONG signal (weight x5 like direct hit)
            title_hits += sum(5 for t in alias_tokens if aliases.get(t) == page["rel"])
            title_hits += sum(
                1 for t in tokens if any(t in a for a in my_aliases)
            )
            body_hits = sum(low.count(t) for t in tokens)
            # tags/aliases may be lists (fixed parse_frontmatter) or legacy strings
            tags_val = page["meta"].get("tags", [])
            aliases_val = page["meta"].get("aliases", [])
            if isinstance(tags_val, list):
                tags_parts = [str(x).lower() for x in tags_val]
            else:
                tags_parts = [p.strip().lower() for p in str(tags_val).replace("[", "").replace("]", "").split(",") if p.strip()]
            if isinstance(aliases_val, list):
                alias_parts = [str(x).lower() for x in aliases_val]
            else:
                alias_parts = [p.strip().lower() for p in str(aliases_val).replace("[", "").replace("]", "").split(",") if p.strip()]
            tag_text = " ".join(tags_parts) + " " + str(page["meta"].get("type", "")).lower() + " " + " ".join(alias_parts)
            tag_hits = sum(1 for t in tokens if t and t in tag_text)
            score = title_hits * 3 + body_hits + tag_hits * 2
            if score <= 0:
                continue
            snippet = ""
            for line in page["body"].splitlines():
                line_low = line.lower()
                if any(t in line_low for t in tokens) and len(line.strip()) > 3:
                    snippet = line.strip()[:180]
                    break
            # raw transcripts mention everything repeatedly; divide their
            # score so curated pages always outrank them in recall
            if page["ptype"] == "source":
                score = score / 10.0
                if score < 1:
                    continue
            results.append(
                {
                    "path": page["rel"],
                    "title": page["title"],
                    "type": page["ptype"],
                    "updated": page["updated"],
                    "score": round(score, 1),
                    "snippet": snippet,
                }
            )
        results.sort(key=lambda r: (-r["score"], r["title"].lower()))
        return results[:limit]

    def search(self, query: str, limit: int = 5) -> list[dict]:
        """Hybrid FTS5 + keyword + recency search."""
        from .fts import hybrid_search
        return hybrid_search(self, query, limit=limit)

    def rebuild_fts(self) -> dict:
        from .fts import build_fts_db
        return build_fts_db(self)

    def prefetch_context(self, query: str, limit: int = 3) -> str:
        """Context block for prefetch(); empty string when nothing matches."""
        if not isinstance(query, str) or len(query.strip()) < 10:
            return ""
        results = [
            r for r in self.search(query, limit=limit * 3) if r["type"] != "source"
        ][:limit]
        strong = [r for r in results if r["score"] >= 1]
        if not strong:
            return ""
        lines = ["## Obsidian Wiki Context", ""]
        for r in strong:
            lines.append(
                f"- [[{r['path']}|{r['title']}]] (score {r['score']}) "
                f"{r['snippet']}"
            )
        lines.append("")
        lines.append(
            "Full pages live in the vault; use the obsidian_wiki tool "
            "(action=read) for complete content."
        )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Dedup detection (feature #1)
    # ------------------------------------------------------------------

    def detect_duplicates(self) -> list[list[str]]:
        """Return list of groups where pages share normalized title, alias overlap, or stem.

        Groups are sorted lists of rels; outer list sorted by first element.
        Sources are excluded; groups with single member are not returned.
        """
        pages = [p for p in self.load_pages() if p.get("ptype") != "source"]
        if len(pages) < 2:
            return []
        # Build per-page normalized signature sets
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

        # Token -> indices where token appears
        token_to_indices: dict[str, list[int]] = {}
        for idx, s in enumerate(sigs):
            for tok in s:
                token_to_indices.setdefault(tok, []).append(idx)

        # Union-Find over indices
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

    # ------------------------------------------------------------------
    # Lint
    # ------------------------------------------------------------------

    def lint(self) -> dict:
        pages = self.load_pages()
        stems = _alias_map(pages)

        problems = {"orphans": [], "missing_frontmatter": [],
                    "broken_links": [], "stale_claims": []}

        inbound: dict[str, set[str]] = {p["rel"]: set() for p in pages}
        for page in pages:
            # raw session transcripts quote wiki syntax from chat; they are
            # immutable sources, not curated pages - skip them in link lint
            if page["ptype"] == "source":
                continue
            # auto-generated backlink sections are navigation UI, not
            # editorial links - strip before counting
            body_text = re.sub(
                r"\n## Linked from\n(?:\n|- .*\n?)*", "\n", page["text"]
            )
            for link in WIKILINK_RE.findall(body_text):
                link_stem = link.strip().split("/")[-1].strip()
                link_stem = re.sub(r"\.md$", "", link_stem, flags=re.IGNORECASE)
                target = link_stem.lower()
                hit = stems.get(target)
                # a wikilink that spells out a folder path must match where
                # the target actually lives: [[entities/X]] is broken when X
                # sits in people/ - the bare stem would resolve it silently
                path_part = re.split(r"[|#]", link.strip(), maxsplit=1)[0].strip()
                if path_part.endswith(".md"):
                    path_part = path_part[:-3]
                mismatch = False
                if hit is not None and "/" in path_part:
                    want_dir = path_part.split("/", 1)[0].lower()
                    have_dir = hit.split("/", 1)[0]
                    mismatch = want_dir != have_dir
                if hit is None or mismatch:
                    problems["broken_links"].append(
                        f"{page['rel']}: [[{link.strip()}]]"
                    )
                    continue
                if hit != page["rel"]:
                    inbound[hit].add(page["rel"])

        # Build last-touch dates from the LOG, but ONLY from WRITE/UPDATE
        # rows that name the page explicitly. A page's "last touched" date must
        # come from an actual edit event, not from a stray mention in another
        # page's log line (which caused false-positive stale_claims before).
        log_dates: dict[str, str] = {}
        try:
            # Prefer DB; fallback to markdown view
            from obsidian_memory_core.wiki.log import _iter_log_rows as _lr
            rows_for_lint = []
            try:
                rows_for_lint = _lr(self)
                use_db = len(rows_for_lint) > 0 or self.log_db_path.exists()
            except Exception:
                use_db = False
            # Edit kinds that prove a real write/edit of a page.
            EDIT_KINDS = {"WRITE", "UPDATE"}
            if use_db and rows_for_lint:
                for _d, _k, _msg, _auto, _ca in rows_for_lint:
                    kind = str(_k).upper()
                    if kind not in EDIT_KINDS:
                        continue
                    # Only credit pages explicitly named in the message.
                    for stem, rel in stems.items():
                        if stem in _msg.lower() or rel.lower() in _msg.lower():
                            log_dates[rel] = max(log_dates.get(rel, ""), _d)
            else:
                import re as _re
                for line in self.log_path.read_text(encoding="utf-8").splitlines():
                    m = _re.match(r"^- (\d{4}-\d{2}-\d{2}) (\w+)(?:\(auto\))?: (.*)$", line)
                    if not m:
                        continue
                    day, kind, desc = m.groups()
                    if kind.upper() not in EDIT_KINDS:
                        continue
                    for stem, rel in stems.items():
                        if stem in desc.lower() or rel.lower() in desc.lower():
                            log_dates[rel] = max(log_dates.get(rel, ""), day)
        except OSError:
            pass

        for page in pages:
            if not page["meta"]:
                problems["missing_frontmatter"].append(page["rel"])
                continue
            if page["ptype"] not in VALID_TYPES:
                problems["missing_frontmatter"].append(
                    f"{page['rel']} (bad type '{page['ptype']}')"
                )
            referrers = inbound[page["rel"]] - {f"index.md"}
            if not referrers:
                problems["orphans"].append(page["rel"])
            last_touch = log_dates.get(page["rel"], "")
            if (
                last_touch
                and page["updated"]
                and last_touch > page["updated"]
            ):
                problems["stale_claims"].append(
                    f"{page['rel']} updated {page['updated']} but log shows "
                    f"{last_touch}"
                )

        # Raw session sources are immutable transcripts: no inbound links
        # by design, so they are not counted as orphans.
        real_orphans = [
            o for o in problems["orphans"] if not o.startswith("sources/")
        ]
        problems["orphans"] = real_orphans

        # Required frontmatter trio: every page must declare type, tags
        # and aliases (empty lists allowed for tags/aliases; the KEYS must
        # exist). Sources are exempt from tags/aliases (auto-generated).
        missing_fm = []
        for page in pages:
            # KEY PRESENCE is what matters: values may be YAML lists which
            # parse_frontmatter flattens to ''. Empty [] is allowed.
            fm_body = ""
            m = FRONTMATTER_RE.match(page["text"])
            if m:
                fm_body = m.group(0)
            missing = [
                f for f in ("type", "tags", "aliases")
                if not re.search(rf"(?m)^{f}:", fm_body)
            ]
            if missing:
                missing_fm.append(f"{page['rel']} ({', '.join(missing)})")
        if missing_fm:
            problems["missing_frontmatter"] = missing_fm

        # Frontmatter guard: warn ONLY when a page's aliases are empty RIGHT NOW
        # AND the log proves it previously held aliases that a write would have
        # wiped. We require a "preserving aliases" WRITE/UPDATE line that names
        # this exact file - an explicit guard event, not a stray mention.
        #
        # Deliberately NOT flagged:
        #   - person pages with legitimately empty aliases (no prior aliases)
        #   - any page merely "mentioned" somewhere in the log history
        # Those produced false-positive aliases_wiped that forced manual cleanup.
        try:
            if self.log_db_path.exists():
                try:
                    from obsidian_memory_core.wiki.log import _iter_log_rows as _lr
                    log_rows = list(_lr(self))
                except Exception:
                    log_rows = []
            else:
                log_rows = []
            # Collect explicit guard events (path -> True) from WRITE/UPDATE lines.
            guard_paths: set[str] = set()
            edit_kinds = {"WRITE", "UPDATE"}
            if log_rows:
                for _d, _k, _msg, _auto, _ca in log_rows:
                    if str(_k).upper() not in edit_kinds:
                        continue
                    if "preserving aliases" not in _msg.lower():
                        continue
                    m_path = re.search(r"for\s+([^\s]+\.md)", _msg)
                    if m_path:
                        try:
                            p = Path(m_path.group(1))
                            if p.is_absolute():
                                try:
                                    rel_guess = p.relative_to(self.root).as_posix()
                                except ValueError:
                                    rel_guess = p.name
                            else:
                                rel_guess = m_path.group(1)
                        except Exception:
                            rel_guess = m_path.group(1)
                        guard_paths.add(rel_guess.lower())
            else:
                try:
                    for line in self.log_path.read_text(encoding="utf-8").splitlines():
                        if "preserving aliases" not in line.lower():
                            continue
                        m_path = re.search(r"for\s+([^\s]+\.md)", line)
                        if m_path:
                            guard_paths.add(m_path.group(1).lower())
                except OSError:
                    pass
        except OSError:
            guard_paths = set()
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
            # Only flag if the log explicitly recorded a guard that preserved
            # prior aliases for THIS file (proving it used to have aliases).
            rel_low = page["rel"].lower()
            if rel_low in guard_paths or rel_low.replace("/", "__") in guard_paths:
                aliases_wiped.append(
                    f"{page['rel']} (aliases empty but log shows guard preserved prior aliases)"
                )
        if aliases_wiped:
            problems["aliases_wiped"] = sorted(set(aliases_wiped))

        # Weak connectivity: a curated page should participate in the web
        # from BOTH directions - at least one inbound OR outbound wikilink
        # is already covered by orphans; here we require total degree >= 2
        # so pages can't degrade into dead-end chain nodes.
        stem_to_rel = {p["stem"].lower(): p["rel"] for p in pages}
        weak = []
        for page in pages:
            if page["ptype"] == "source":
                continue
            rel = page["rel"]
            stripped = dict(page)
            stripped["text"] = re.sub(
                r"\n## Linked from\n(?:\n|- .*\n?)*", "\n", page["text"]
            )
            resolved_out = {
                stem_to_rel[t]
                for t in _out_links(stripped)
                if t in stem_to_rel and stem_to_rel[t] != rel
            }
            degree = len(inbound.get(rel, set())) + len(resolved_out)
            if degree < 2:
                weak.append(f"{rel} (degree {degree})")
        if weak:
            problems["weak_connectivity"] = weak

        # Duplicates by normalized title / alias / stem overlap
        dup_groups = self.detect_duplicates()
        if dup_groups:
            # Build formatted entries like 'a.md ~ b.md (alias: sang)'
            # For each group, find the most-shared normalized token to use as hint
            by_rel = {p["rel"]: p for p in pages}
            formatted: list[str] = []
            for grp in dup_groups:
                # collect per-page signatures
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
                # Find shared token(s): tokens appearing in >=2 members
                token_counts: dict[str, int] = {}
                for s in sig_map.values():
                    for tok in s:
                        token_counts[tok] = token_counts.get(tok, 0) + 1
                shared = [t for t, c in token_counts.items() if c > 1]
                if shared:
                    # pick most frequent, then alphabetically first for determinism
                    max_c = max(token_counts[t] for t in shared)
                    candidates = [t for t in shared if token_counts[t] == max_c]
                    hint_token = sorted(candidates)[0]
                    # Determine label: alias vs stem vs title
                    in_alias = any(hint_token in alias_map.get(r, set()) for r in grp)
                    if in_alias:
                        label = f"alias: {hint_token}"
                    else:
                        # check if any page's stem or title equals token
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
                    hint_token = "?"
                entry = " ~ ".join(grp) + f" ({label})"
                formatted.append(entry)
            problems["duplicates"] = sorted(formatted)
            # Add fix hint
            problems["duplicates_hint"] = ["Run with --fix or manually merge: keep canonical page, add aliases, delete duplicate; use allow_duplicate=True if intentional."]

        result = {
            "pages_scanned": len(pages),
            "problems": {k: v for k, v in problems.items() if v},
            "clean": not any(problems.values()),
        }
        # Top-level --fix hint for duplicates
        if dup_groups:
            result["fix_hint"] = "Duplicates found. Merge groups: keep one canonical file, add aliases [Sang, ...] to it, delete duplicates. Or run `obsidian_wiki lint --fix` / `vault.fix_duplicates()` if available. Use allow_duplicate=True to override write guard."
        return result


    # ------------------------------------------------------------------
    # Auto-orphan linker (feature #3)
    # ------------------------------------------------------------------

    def _hub_for_orphan(self, orphan_rel: str, title: str = "", ptype: str = "") -> str:
        """Pick generic hub parent for an orphan — type-based only, no keyword heuristics."""
        if not ptype:
            try:
                ptype = DIR_TYPES.get(orphan_rel.split("/", 1)[0], "")
            except Exception:
                ptype = ""
        # Generic type -> hub mapping. All vaults have these hubs; no domain-specific keywords.
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
        # Fallback if hub file missing (e.g. fresh vault without that hub) -> use vault root hub that always exists
        if not (self.root / hub).exists():
            fallback = "environment/obsidian-vault.md"
            if (self.root / fallback).exists():
                return fallback
            return "concepts/obsidian-wiki-memory-system.md"
        return hub

    def fix_orphans(self, dry_run: bool = False) -> dict:
        """Auto-link every orphan by inserting a bullet into its hub parent."""
        lint = self.lint()
        orphans = lint.get("problems", {}).get("orphans", []) or []
        if not orphans:
            return {"orphans": 0, "fixed": 0, "dry_run": dry_run, "plan": [], "hubs": {}}
        pages = self.load_pages()
        by_rel = {p["rel"]: p for p in pages}
        hub_groups = {}
        plan = []
        for rel in sorted(orphans):
            pg = by_rel.get(rel, {})
            title = pg.get("title") or Path(rel).stem
            ptype = pg.get("ptype") or ""
            body = pg.get("body") or ""
            summary = first_summary_line(body) if body else "(auto-linked orphan)"
            hub = self._hub_for_orphan(rel, title=title, ptype=ptype)
            if hub == rel:
                hub = "concepts/obsidian-wiki-memory-system.md"
            if not (self.root / hub).exists():
                fallback = "concepts/obsidian-wiki-memory-system.md"
                if (self.root / fallback).exists():
                    hub = fallback
                else:
                    continue
            entry = {"orphan": rel, "title": title, "summary": summary, "hub": hub}
            plan.append(entry)
            hub_groups.setdefault(hub, []).append(entry)
        if dry_run:
            return {
                "orphans": len(orphans),
                "fixed": 0,
                "dry_run": True,
                "plan": plan,
                "hubs": {h: [e["orphan"] for e in v] for h, v in hub_groups.items()},
            }
        fixed = 0
        hubs_touched = []
        for hub_rel, entries in hub_groups.items():
            hub_path = self.root / hub_rel
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
            self.rebuild_index()
        lint_after = self.lint()
        broken = lint_after.get("problems", {}).get("broken_links", [])
        return {
            "orphans_before": len(orphans),
            "fixed": fixed,
            "dry_run": False,
            "hubs_touched": sorted(hubs_touched),
            "plan": plan,
            "hubs": {h: [e["orphan"] for e in v] for h, v in hub_groups.items()},
            "lint_after": lint_after,
            "broken_links_after": len(broken),
        }


def first_summary_line(body: str) -> str:
    """First meaningful non-heading line, truncated for the index bullet."""
    for line in body.splitlines():
        s = line.strip()
        if not s or s.startswith(("#", ">", "---", "!", "|")):
            continue
        return (s[:140] + "...") if len(s) > 140 else s
    return "(empty page)"


def _alias_map(pages: list) -> dict:
    """stem -> rel for both page stems AND declared frontmatter aliases.

    Handles both inline [a, b] and block dash lists correctly via the fixed
    parse_frontmatter (which returns aliases as list). Falls back to raw block
    parsing for legacy files where meta may still be a string.
    """
    import re as _re

    m: dict = {}
    for p in pages:
        m.setdefault(p["stem"].lower(), p["rel"])
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
        # Fallback: if still empty and text has block list, parse via parse_frontmatter helper
        if not aliases_list:
            # Check if meta was empty due to legacy flattening, try robust block extraction
            fm = FRONTMATTER_RE.match(p["text"])
            if fm:
                # Use WikiVault.parse_frontmatter to correctly extract block lists
                try:
                    fm_meta, _ = WikiVault.parse_frontmatter(p["text"])
                    fm_aliases = fm_meta.get("aliases")
                    if isinstance(fm_aliases, list) and fm_aliases:
                        aliases_list = fm_aliases
                except Exception:
                    pass
        for a in aliases_list:
            key = a.strip().strip("'\"").lower()
            if key and key not in m:
                m[key] = p["rel"]
    return m


def _out_links(page: dict) -> set[str]:
    """Resolved rel-paths this page links to (deduped, case-insensitive)."""
    import re as _re

    out: set[str] = set()
    for link in WIKILINK_RE.findall(page["text"]):
        stem = link.strip().split("/")[-1].strip()
        stem = _re.sub(r"\.md$", "", stem, flags=_re.IGNORECASE)
        out.add(stem.lower())
    return out


ENTITY_TEMPLATE = """---
type: entity
updated: YYYY-MM-DD
tags: []
aliases: []
---

# Entity Name

One-line description of what this is.

## Key facts

- fact 1

## Related

- [[Other page]]
"""

CONCEPT_TEMPLATE = """---
type: concept
updated: YYYY-MM-DD
tags: []
aliases: []
---

# Concept Name

The lesson or workflow, short and actionable.

## Core content

- main point

## Related

- [[Entity or other concept]]
"""
