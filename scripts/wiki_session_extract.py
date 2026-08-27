#!/usr/bin/env python3
"""Extract durable knowledge from captured session sources into the wiki.

Pipeline step 2: reads sources/sessions/*.md pages, asks a cheap LLM
(hermes auxiliary oneshot) to identify durable knowledge (entities,
concepts, lessons), then MERGES the proposals into existing pages or
CREATEs new ones. Dedup is enforced two ways:

  1. The LLM sees the current index + matching page contents and must mark
     each proposal create vs update against them.
  2. Post-LLM, a token-overlap check drops proposals whose title nearly
     matches an existing page (safety net against LLM duplicates).

Everything is dry-run by default: pass --apply to actually write.
A capture/extract run is recorded in log.md for auditability.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from datetime import date
from pathlib import Path

HERMES_SRC = Path(os.environ.get("HERMES_SRC", str(Path.home() / ".hermes" / "hermes-agent")))
PLUGIN_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_DIR))
sys.path.insert(0, str(HERMES_SRC))

from obsidian_memory_core.wiki import WikiVault  # noqa: E402
from obsidian_memory_core import MemoryStore  # noqa: E402
from obsidian_memory_core.config import vault_path  # noqa: E402

EXTRACT_INSTRUCTIONS = """You maintain a personal knowledge wiki for an AI agent. Below are raw \
conversation transcripts (source documents) and the current wiki state. Extract DURABLE knowledge worth keeping long-term.

Types: entities/=EAs-projects-tools; people/=specific humans worth remembering (family, colleagues); decisions/=settled choices WITH reasons ("we chose X over Y because Z"); environment/=machine/server/path facts; concepts/=lessons-workflows; preferences/=standing behavior rules.

Durable means: facts about entities (EAs, projects, tools, people, companies), lessons learned, workflows, and STANDING PREFERENCES (rules for how the agent should behave - response style, formatting, trading safety criteria, what to never do). NOT durable: small talk, transient task state, file paths that will change, anything already fully covered by an existing page.

When the user states or corrects a behavioral rule ("always X", "never Y", "I prefer Z"), that is a preference: put it under preferences/ (create) or merge into the matching preferences/ page (update).

Return ONLY a JSON array (no markdown fence). Each item:
{
  "action": "create" | "update",
  "page": "entities/slug | people/slug | decisions/slug | environment/slug | concepts/slug | preferences/slug | answers/slug",
  "title": "Page Title",
  "summary": "one-line summary for the index",
  "tags": ["2-4", "lowercase", "topic-tags"],
  "content": "full Obsidian-flavored markdown page body in ENGLISH. For update: the COMPLETE new page content (you get the old content below - merge, do not lose still-valid sections). Keep frontmatter out - it is generated. ALWAYS include a '## Related' section with [[wikilinks]] to related existing pages (mandatory - pages must be linked into the web).",
  "reason": "why this is durable knowledge"
}

Rules:
- update ONLY pages listed below; create only when no existing page covers it
- max 6 items per batch; quality over quantity; empty array [] if nothing durable
- English only
- wikilinks use full path form: [[entities/GoldReaper|GoldReaper]]
"""

MAX_SOURCE_CHARS = 24000      # per session fed to the LLM
MAX_PAGE_CHARS = 3000         # per candidate page shown for merge context
MIN_DIALOGUE_CHARS = 200      # ignore greetings/small talk even when called directly
AUDIT_LOG = Path(os.environ.get("WIKI_AUDIT_LOG", str(Path.home() / ".hermes" / "logs" / "wiki-extract-audit.jsonl")))
AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
try:
    if AUDIT_LOG.exists():
        os.chmod(AUDIT_LOG, 0o600)
except OSError:
    pass


def audit(event: str, **fields) -> None:
    """Append machine-readable lifecycle events without breaking extraction."""
    try:
        from datetime import datetime, timezone
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        record = {"event": event, **fields, "timestamp": datetime.now(timezone.utc).isoformat()}
        if not AUDIT_LOG.exists():
            AUDIT_LOG.touch(mode=0o600)
        with AUDIT_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def load_state(vault: WikiVault):
    index = vault.index_path.read_text(encoding="utf-8")[:6000]
    return index


def pick_pages_for_sources(vault: WikiVault, sources: list[dict], limit: int = 4) -> list[dict]:
    """Pages whose tokens overlap the source text most (merge context)."""
    from wiki import TOKEN_RE, STOPWORDS

    scored = []
    all_text = " ".join(s["text"] for s in sources).lower()
    tokens = set(t for t in TOKEN_RE.findall(all_text) if t not in STOPWORDS)
    for page in vault.load_pages():
        if page["ptype"] == "source":
            continue
        low = page["text"].lower()
        score = sum(1 for t in tokens if t in low)
        if score:
            scored.append((score, page))
    scored.sort(key=lambda x: -x[0])
    return [p for _, p in scored[:limit]]


def build_user_input(source_texts: list[str], candidates: list[dict]) -> str:
    parts = ["=== CURRENT INDEX ===", ""]
    parts.append("Existing pages (do NOT create duplicates of these):")
    for p in candidates:
        parts.append(f"- {p['rel']} ({p['ptype']}): {p['title']}")
    parts.append("")
    parts.append("=== CANDIDATE PAGE CONTENTS (for updates/merges) ===")
    for p in candidates:
        parts.append(f"\n--- {p['rel']} ---")
        parts.append(p["text"][:MAX_PAGE_CHARS])
    parts.append("\n=== SOURCE TRANSCRIPTS ===")
    for st in source_texts:
        parts.append("\n--- transcript ---")
        parts.append(st[:MAX_SOURCE_CHARS])
    return "\n".join(parts)


def dialogue_chars(text: str) -> int:
    """Count transcript dialogue, excluding frontmatter and extraction report."""
    parts = text.split("---", 2)
    body = parts[2] if len(parts) >= 3 else text
    body = re.split(r"\n## LLM Extraction\n", body, maxsplit=1)[0]
    body = re.sub(r"(?m)^# Session.*$", "", body)
    body = re.sub(r"(?m)^> Started:.*$", "", body)
    body = re.sub(r"(?m)^## (?:User|Assistant)(?: \([^\n]*\))?\s*$", "", body)
    return len(body.strip())


def parse_proposals(raw: str) -> list[dict]:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.DOTALL)
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        data = json.loads(text[start:end + 1])
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def _extraction_report(report: dict | None) -> str:
    """Render the latest LLM extraction result for the session source note."""
    report = report or {}
    lines = [
        "## LLM Extraction",
        "",
        f"- Status: `{report.get('extract_status', 'unknown')}`",
        f"- Extracted: {date.today().isoformat()}",
    ]
    applied = report.get("applied") or []
    if applied:
        lines += ["", "### Pages updated"]
        for item in applied:
            page = str(item.get("page", "")).removesuffix(".md")
            title = str(item.get("title") or page.rsplit("/", 1)[-1])
            summary = str(item.get("summary", "")).strip()
            status = str(item.get("status", "written"))
            link = f"[[{page}|{title}]]"
            line = f"- `{status}` {link}"
            if summary:
                line += f" — {summary}"
            lines.append(line)
    else:
        lines += ["", "No durable knowledge was extracted."]
    rejected = report.get("rejected_dedup") or []
    if rejected:
        lines += ["", f"- Duplicate/invalid proposals rejected: {len(rejected)}"]
    return "\n".join(lines) + "\n"


def update_extract_status(path: Path, status: str, report: dict | None = None, store: MemoryStore | None = None) -> None:
    """Update extraction bookkeeping and replace the report at note end."""
    if store is not None:
        store.update_ingest_status(str(path.relative_to(store.root)), status)
        if report is None:
            return
    text = path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    if len(parts) < 3:
        return
    fm, body = parts[1], parts[2]
    if re.search(r"(?m)^extract_status:", fm):
        fm = re.sub(r"(?m)^extract_status:.*$", f"extract_status: {status}", fm, count=1)
    else:
        fm = re.sub(r"(?m)^(aliases:[^\n]*)$", rf"\1\nextract_status: {status}", fm, count=1)
    if status in {"success", "skip"} and not re.search(r"(?m)^extracted:", fm):
        fm += f"\nextracted: {date.today().isoformat()}"
    body = re.split(r"\n## LLM Extraction\n", body, maxsplit=1)[0].rstrip() + "\n\n"
    path.write_text(f"---{fm}\n---{body}{_extraction_report(report)}", encoding="utf-8")


def norm_title(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def dedup_proposals(proposals: list[dict], vault: WikiVault) -> tuple[list[dict], list[dict]]:
    """Split into valid vs rejected (duplicate-title safety net)."""
    existing_stems = {norm_title(p["stem"]) for p in vault.load_pages()}
    valid, rejected = [], []
    for prop in proposals:
        action = prop.get("action", "")
        page = str(prop.get("page", "")).strip()
        if action == "create":
            stem = page.rstrip("/").split("/")[-1].replace(".md", "")
            if norm_title(stem) in existing_stems:
                rejected.append({"proposal": prop, "why": "title matches existing page"})
                continue
            folder = page.split("/")[0]
            if folder not in (
                "entities", "people", "decisions", "environment",
                "concepts", "answers", "preferences",
            ):
                rejected.append({"proposal": prop, "why": f"create into '{folder}' not allowed"})
                continue
        elif action != "update":
            rejected.append({"proposal": prop, "why": f"bad action '{action}'"})
            continue
        else:
            try:
                vault.safe_resolve(page)
            except Exception:
                rejected.append({"proposal": prop, "why": "invalid update path"})
                continue
        if not str(prop.get("content", "")).strip() or len(prop.get("content", "")) < 40:
            rejected.append({"proposal": prop, "why": "content too short"})
            continue
        valid.append(prop)
    return valid, rejected


def apply_proposals(vault: WikiVault, proposals: list[dict], store: MemoryStore | None = None) -> list[dict]:
    applied = []
    for prop in proposals:
        try:
            content = str(prop["content"])
            tags = prop.get("tags") or []
            if tags and isinstance(tags, list):
                tag_values = [str(t).lower().strip() for t in tags[:4]]
                tag_block = "tags:\n" + "\n".join(
                    "  - '" + t.replace("'", "''") + "'" for t in tag_values
                )
                if "---\n" in content:
                    # inject/replace tags line inside provided frontmatter
                    import re as _re
                    m2 = _re.match(r"^---\n(.*?)\n---\n", content, _re.DOTALL)
                    if m2:
                        fm = m2.group(1)
                        if _re.search(r"(?m)^tags:", fm):
                            fm = _re.sub(
                                r"(?ms)^tags:.*?(?=^[A-Za-z_][A-Za-z0-9_-]*:|\Z)",
                                tag_block + "\n", fm, count=1,
                            )
                        else:
                            fm += f"\n{tag_block}"
                        content = f"---\n{fm}\n---\n" + content[m2.end():]
                else:
                    # tags ONLY - write_page generates type/updated/aliases
                    content = f"---\n{tag_block}\n---\n\n{content}"
            if store is not None:
                expected_revision = None
                if prop.get("action") == "update":
                    expected_revision = store.read(prop["page"])["revision"]
                result = store.write(
                    prop["page"], content,
                    note=f"extract: {prop.get('reason', '')[:100]}",
                    expected_revision=expected_revision,
                    allow_duplicate=False,
                )
            else:
                result = vault.write_page(
                    prop["page"], content,
                    note=f"extract: {prop.get('reason', '')[:100]}",
                    quiet_log=True,
                )
            applied.append({
                "page": prop["page"],
                "action": prop.get("action", ""),
                "status": result["status"],
                "title": prop.get("title", ""),
                "summary": prop.get("summary", ""),
                "reason": prop.get("reason", ""),
            })
        except Exception as e:
            applied.append({
                "page": prop["page"],
                "action": prop.get("action", ""),
                "status": "error",
                "title": prop.get("title", ""),
                "error": str(e)[:150],
            })
    return applied



def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sessions", nargs="*", help="session slugs under sources/sessions (default: newest uncaptured-by-extract)")
    ap.add_argument("--apply", action="store_true", help="write changes (default dry-run)")
    ap.add_argument("--max-chars", type=int, default=MAX_SOURCE_CHARS * 2)
    args = ap.parse_args()
    run_id = uuid.uuid4().hex[:12]

    store = MemoryStore(vault_path())
    vault = store.vault
    if not vault.exists():
        print(json.dumps({"error": "vault missing"}))
        return 1

    sess_root = vault.root / "sources" / "sessions"
    if args.sessions:
        hits = []
        for s in args.sessions:
            rel = Path(s if s.endswith(".md") else f"{s}.md")
            candidate = (sess_root / rel).resolve()
            # Jobs submit a session ID, while captured sources live below a
            # YYYY/MM/DD tree. Accept both a relative source path and a bare
            # session ID without falling back to unrelated newest sources.
            if not candidate.is_file():
                matches = list(sess_root.rglob(rel.name))
                candidate = matches[0].resolve() if len(matches) == 1 else candidate
            if candidate.is_file() and sess_root.resolve() in candidate.parents:
                hits.append(candidate)
        src_paths = list(dict.fromkeys(hits))
    else:
        # newest un-extracted transcripts across the whole date tree
        src_paths = []
        for p in sorted(sess_root.rglob("*.md"), key=lambda x: x.stat().st_mtime)[-8:]:
            meta, _ = vault.parse_frontmatter(p.read_text(encoding="utf-8"))
            if not meta.get("extracted"):
                src_paths.append(p)
    src_paths = [p for p in src_paths if p.exists()]
    if not src_paths:
        audit("nothing_to_do", run_id=run_id)
        print(json.dumps({"status": "nothing-to-do", "run_id": run_id}))
        return 0

    sources = []
    skipped_small = []
    for p in src_paths:
        text = p.read_text(encoding="utf-8")
        if dialogue_chars(text) < MIN_DIALOGUE_CHARS:
            skipped_small.append(p)
            continue
        sources.append({"path": p, "text": text})
    if skipped_small:
        audit("sources_skipped_small", run_id=run_id,
              sessions=[p.stem for p in skipped_small],
              min_dialogue_chars=MIN_DIALOGUE_CHARS)
        if args.apply:
            for p in skipped_small:
                update_extract_status(p, "skip", store=store)
    if not sources:
        audit("nothing_durable_to_extract", run_id=run_id,
              sessions=[p.stem for p in src_paths],
              min_dialogue_chars=MIN_DIALOGUE_CHARS)
        print(json.dumps({"status": "skipped-too-small", "run_id": run_id,
                          "skipped": [p.stem for p in skipped_small]}))
        return 0
    joined_len = sum(len(s["text"]) for s in sources)
    audit("extract_started", run_id=run_id, sessions=[p.stem for p in src_paths], source_chars=joined_len)

    candidates = pick_pages_for_sources(vault, sources)
    user_input = build_user_input([s["text"] for s in sources], candidates)
    user_input = user_input[:args.max_chars]

    from agent.oneshot import run_oneshot
    import time as _time

    raw = None
    for attempt in range(3):
        try:
            raw = run_oneshot(
                instructions=EXTRACT_INSTRUCTIONS,
                user_input=user_input,
                task="title_generation",
                max_tokens=4000,
                temperature=0.2,
                timeout=240,
            )
            if raw and str(raw).strip():
                break
        except Exception as e:
            if attempt == 2:
                if args.apply:
                    for p in src_paths:
                        update_extract_status(p, "fail", store=store)
                audit("extract_failed", run_id=run_id, error=str(e), attempts=3)
                print(json.dumps({"error": f"LLM failed after 3 attempts: {e}", "run_id": run_id}))
                return 1
            _time.sleep(5 * (attempt + 1))
    if not raw or not str(raw).strip():
        if args.apply:
            for p in src_paths:
                update_extract_status(p, "fail", store=store)
        audit("extract_failed", run_id=run_id, error="empty LLM response after retries")
        print(json.dumps({"error": "empty LLM response after retries", "run_id": run_id}))
        return 1
    proposals = parse_proposals(raw)
    valid, rejected = dedup_proposals(proposals, vault)

    report = {
        "run_id": run_id,
        "sessions": [p.stem for p in src_paths],
        "source_chars": joined_len,
        "proposals_raw": len(proposals),
        "rejected_dedup": [{"why": r["why"], "page": r["proposal"].get("page")} for r in rejected],
        "dry_run": not args.apply,
    }

    if args.apply:
        report["applied"] = apply_proposals(vault, valid, store) if valid else []
        applied = report["applied"]
        try:
            lint_result = vault.lint()
            report["wiki_health"] = {
                "clean": lint_result["clean"],
                "problems": lint_result["problems"],
            }
        except Exception as exc:
            report["wiki_health_error"] = str(exc)[:200]
        successful = [x for x in applied if x.get("status") != "error"]
        failed = [x for x in applied if x.get("status") == "error"]
        extract_status = "fail" if failed else ("success" if successful else "skip")
        report["extract_status"] = extract_status
        for source in sources:
            update_extract_status(source["path"], extract_status, report, store)
        vault.append_log(
            "REFLECT",
            f"extract from {len(src_paths)} session(s): "
            f"{len(report['applied'])} page(s) written; status={extract_status}"
        )
        audit("extract_finished", run_id=run_id, sessions=report["sessions"],
              status=extract_status, proposals_raw=report["proposals_raw"],
              rejected_dedup=len(report["rejected_dedup"]), applied=report["applied"])
    elif valid:
        report["would_write"] = [
            {"action": v["action"], "page": v["page"], "title": v.get("title", ""),
             "summary": v.get("summary", "")[:120]}
            for v in valid
        ]

    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
