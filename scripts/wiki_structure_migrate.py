#!/usr/bin/env python3
"""Normalize every curated wiki page to the canonical Markdown profile.

This migration is deterministic: it never asks an LLM to rewrite facts. It
preserves existing body sections, adds only the structural sections required by
the validator, repairs heading mechanics, and makes ``## Related`` the final
section with at least one resolvable wikilink.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(PLUGIN_ROOT))

from obsidian_memory_core import MemoryStore  # noqa: E402
from obsidian_memory_core.wiki.frontmatter import FRONTMATTER_RE  # noqa: E402
from obsidian_memory_core.wiki.links import WIKILINK_RE  # noqa: E402
from obsidian_memory_core.wiki.structure import HEADING_RE, scan_headings, validate_page_structure  # noqa: E402
from obsidian_memory_core.wiki.sections import limit_section_wikilinks  # noqa: E402


CURATED_TYPES = {
    "concepts": "concept",
    "decisions": "decision",
    "answers": "answer",
    "entities": "entity",
    "people": "person",
    "environment": "environment",
    "preferences": "preference",
}

# Canonical headings plus the alternatives accepted by structure.py.
PROFILE_SECTIONS: dict[str, list[tuple[str, tuple[str, ...]]]] = {
    "concept": [("Summary", ("summary", "overview")), ("Core Content", ("core content", "explanation"))],
    "decision": [("Context", ("context",)), ("Decision", ("decision",)), ("Rationale", ("rationale",))],
    "answer": [("Answer", ("answer", "recommendation")), ("Evidence", ("evidence", "basis"))],
    "entity": [("Overview", ("overview", "identity")), ("Facts", ("details", "facts"))],
    "person": [("Identity", ("identity", "overview")), ("Facts", ("details", "facts"))],
    "environment": [("Scope", ("scope",)), ("Configuration", ("configuration", "facts"))],
    "preference": [("Preference", ("preference",)), ("Rationale", ("rationale",))],
}

# Only unambiguous old headings are renamed. Everything else is preserved and
# the missing canonical section is added next to it.
SYNONYMS: dict[tuple[str, int], set[str]] = {
    ("preference", 0): {"standing rule", "standing rules", "behavior rule", "behaviour rule"},
    ("preference", 1): {"why", "reason", "reasons"},
    ("decision", 0): {"background"},
    ("decision", 1): {"choice", "chosen approach"},
    ("decision", 2): {"why", "reason", "reasons"},
    ("answer", 0): {"conclusion"},
    ("answer", 1): {"validation evidence", "supporting evidence"},
    ("environment", 1): {"setup", "current setup"},
}

TERMINAL = {"related", "linked from", "sources"}


def norm_heading(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def matches_group(title: str, options: tuple[str, ...]) -> bool:
    normalized = norm_heading(title)
    return any(normalized == option or normalized.endswith(f" {option}") for option in options)


def _fence_marker(line: str) -> str | None:
    match = re.match(r"^[ \t]*(```+|~~~+)", line)
    return match.group(1)[0] if match else None


def heading_positions(lines: list[str], level: int | None = None) -> list[tuple[int, int, str]]:
    result: list[tuple[int, int, str]] = []
    in_fence = False
    marker = ""
    for index, line in enumerate(lines):
        fence = _fence_marker(line)
        if fence:
            if not in_fence:
                in_fence = True
                marker = fence
            elif fence == marker:
                in_fence = False
                marker = ""
            continue
        if in_fence:
            continue
        match = HEADING_RE.match(line)
        if not match:
            continue
        current_level = len(match.group("marks"))
        if level is None or current_level == level:
            result.append((index, current_level, match.group("title").strip()))
    return result


def sanitize_wikilink_labels(text: str) -> str:
    """Remove nested [] only from wikilink aliases; targets stay untouched."""
    out: list[str] = []
    cursor = 0
    while True:
        start = text.find("[[", cursor)
        if start < 0:
            out.append(text[cursor:])
            break
        end = text.find("]]", start + 2)
        if end < 0:
            out.append(text[cursor:])
            break
        out.append(text[cursor:start])
        inner = text[start + 2:end]
        if "|" in inner:
            target, alias = inner.split("|", 1)
            alias = alias.replace("[", "").replace("]", "")
            inner = f"{target}|{alias}"
        out.append(f"[[{inner}]]")
        cursor = end + 2
    return "".join(out)


def ensure_one_h1(body: str, fallback_title: str) -> tuple[str, str]:
    lines = body.strip("\n").splitlines()
    headings = scan_headings("\n".join(lines))
    h1s = [item for item in headings if item["level"] == 1]
    title = h1s[0]["title"] if h1s else fallback_title

    if not h1s:
        lines = [f"# {title}", "", *lines]
    elif len(h1s) > 1:
        # Demote every additional H1; its text and section content are kept.
        for item in reversed(h1s[1:]):
            idx = item["line"] - 1
            lines[idx] = re.sub(r"^#\s+", "## ", lines[idx], count=1)

    # Canonicalize the first H1's spacing but preserve its title exactly.
    headings = scan_headings("\n".join(lines))
    first_h1 = next(item for item in headings if item["level"] == 1)
    lines[first_h1["line"] - 1] = f"# {title}"
    return "\n".join(lines).strip() + "\n", title


def split_h2(body: str) -> tuple[list[str], list[dict[str, Any]]]:
    lines = body.strip("\n").splitlines()
    positions = heading_positions(lines, level=2)
    if not positions:
        return lines, []
    preamble = lines[:positions[0][0]]
    sections: list[dict[str, Any]] = []
    for i, (start, _level, title) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(lines)
        sections.append({"title": title, "content": lines[start + 1:end]})
    return preamble, sections


def substantive(lines: list[str]) -> bool:
    return any(line.strip() for line in lines)


def extract_intro_from_preamble(preamble: list[str]) -> tuple[list[str], list[str], str]:
    """Return canonical H1 lines, intro content, and title."""
    positions = heading_positions(preamble, level=1)
    if not positions:
        raise ValueError("missing H1 after normalization")
    h1_idx, _level, title = positions[0]
    before = [line for line in preamble[:h1_idx] if line.strip()]
    after = preamble[h1_idx + 1:]
    intro = [*before, *after]
    while intro and not intro[0].strip():
        intro.pop(0)
    while intro and not intro[-1].strip():
        intro.pop()
    return [f"# {title}"], intro, title


def generic_section_text(title: str, heading: str) -> str:
    mapping = {
        "Summary": f"This page summarizes **{title}** and its durable context.",
        "Core Content": "The detailed sections below preserve the core content for this topic.",
        "Context": "The documented context for this decision is preserved in the sections below.",
        "Decision": "The decision details are preserved in the sections below.",
        "Rationale": "The rationale is preserved in the documented context and notes on this page.",
        "Answer": "The durable answer is preserved in the detailed sections below.",
        "Evidence": "Supporting evidence and basis are preserved in the detailed sections below.",
        "Overview": f"This page records durable information about **{title}**.",
        "Identity": f"This page records the identity and durable context for **{title}**.",
        "Facts": "The durable facts are preserved in the detailed sections below.",
        "Scope": f"This page records the environment scope for **{title}**.",
        "Configuration": "Configuration and operational facts are preserved in the detailed sections below.",
        "Preference": "The established preference is preserved in the detailed sections below.",
    }
    return mapping.get(heading, "Details are preserved in the sections below.")


def ensure_profile_sections(
    preamble: list[str], sections: list[dict[str, Any]], page_type: str
) -> tuple[list[str], list[dict[str, Any]]]:
    h1_lines, intro, title = extract_intro_from_preamble(preamble)
    groups = PROFILE_SECTIONS[page_type]

    # Rename only strong legacy synonyms to a canonical heading.
    for group_index, (canonical, options) in enumerate(groups):
        if any(matches_group(section["title"], options) for section in sections):
            continue
        synonyms = SYNONYMS.get((page_type, group_index), set())
        hit = next((section for section in sections if norm_heading(section["title"]) in synonyms), None)
        if hit is not None:
            hit["title"] = canonical

    # Add missing profile sections. Intro prose is moved under the first
    # profile section when that section is missing; no factual prose is lost.
    for group_index, (canonical, options) in enumerate(groups):
        if any(matches_group(section["title"], options) for section in sections):
            continue
        if group_index == 0 and substantive(intro):
            content = intro
            intro = []
        else:
            content = [generic_section_text(title, canonical)]

        # Keep canonical sections near the top, in profile order.
        insert_at = 0
        if group_index:
            previous_options = groups[group_index - 1][1]
            for idx, section in enumerate(sections):
                if matches_group(section["title"], previous_options):
                    insert_at = idx + 1
                    break
            else:
                insert_at = len(sections)
        sections.insert(insert_at, {"title": canonical, "content": content})

    preamble_out = [*h1_lines]
    if substantive(intro):
        preamble_out += ["", *intro]
    return preamble_out, sections


def render_sections(preamble: list[str], sections: list[dict[str, Any]]) -> str:
    lines = list(preamble)
    for section in sections:
        while lines and not lines[-1].strip():
            lines.pop()
        lines += ["", f"## {section['title']}", ""]
        content = list(section.get("content") or [])
        while content and not content[0].strip():
            content.pop(0)
        while content and not content[-1].strip():
            content.pop()
        lines += content
    return "\n".join(lines).strip() + "\n"


def normalize_headings(body: str) -> str:
    """Repair hierarchy, duplicate headings, and structurally empty sections."""
    lines = body.strip("\n").splitlines()
    in_fence = False
    marker = ""
    previous_level = 0
    seen: dict[str, int] = defaultdict(int)
    h1_seen = False

    # Reserve the final Related heading. Older pages may contain a nested
    # heading also named Related; rename those earlier duplicates instead of
    # renaming the canonical final H2.
    initial_headings = scan_headings("\n".join(lines))
    related_lines = [
        item["line"] - 1 for item in initial_headings
        if item["normalized"] == "related"
    ]
    canonical_related_line = related_lines[-1] if related_lines else None

    for index, line in enumerate(lines):
        fence = _fence_marker(line)
        if fence:
            if not in_fence:
                in_fence, marker = True, fence
            elif fence == marker:
                in_fence, marker = False, ""
            continue
        if in_fence:
            continue
        match = HEADING_RE.match(line)
        if not match:
            continue
        level = len(match.group("marks"))
        title = match.group("title").strip()
        if level == 1:
            if h1_seen:
                level = 2
            else:
                h1_seen = True
        if previous_level and level > previous_level + 1:
            level = previous_level + 1
        normalized = norm_heading(title)
        if normalized == "related" and canonical_related_line is not None and index != canonical_related_line:
            # Preserve the canonical final `## Related`; disambiguate older
            # nested/editorial headings instead.
            suffix = 2
            candidate = f"{title} ({suffix})"
            while norm_heading(candidate) in seen:
                suffix += 1
                candidate = f"{title} ({suffix})"
            title = candidate
            normalized = norm_heading(title)
            seen[normalized] = 1
        elif normalized != "linked from":
            seen[normalized] += 1
            if seen[normalized] > 1:
                suffix = seen[normalized]
                candidate = f"{title} ({suffix})"
                while norm_heading(candidate) in seen:
                    suffix += 1
                    candidate = f"{title} ({suffix})"
                title = candidate
                seen[norm_heading(title)] = 1
        lines[index] = f"{'#' * level} {title}"
        previous_level = level

    # Fill any heading whose direct section body is empty before the next
    # heading. This fixes old H2 -> H3 outline-only sections without touching
    # their nested content.
    headings = scan_headings("\n".join(lines))
    inserts: list[int] = []
    for i, heading in enumerate(headings):
        if heading["level"] == 1 or heading["normalized"] in TERMINAL:
            continue
        start = heading["line"]  # zero-based insertion point just after heading
        end = headings[i + 1]["line"] - 1 if i + 1 < len(headings) else len(lines)
        direct = lines[start:end]
        if not any(line.strip() for line in direct):
            inserts.append(start)
    for index in reversed(inserts):
        lines[index:index] = ["", "Details are organized in the subsections below.", ""]
    return "\n".join(lines).strip() + "\n"


def resolve_catalog_target(target: str, catalog: list[dict[str, Any]]) -> dict[str, Any] | None:
    raw = target.strip().split("#", 1)[0]
    if raw.lower().endswith(".md"):
        raw = raw[:-3]
    raw = raw.strip("/")
    if not raw:
        return None
    rel = f"{raw}.md".casefold()
    for page in catalog:
        if page["rel"].casefold() == rel:
            return page
    stem = raw.split("/")[-1].casefold()
    hits = [page for page in catalog if page["stem"].casefold() == stem]
    return hits[0] if len(hits) == 1 else None


def pick_related(page: dict[str, Any], catalog: list[dict[str, Any]], inbound: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    # First use a real editorial link already present anywhere on the page.
    for target in WIKILINK_RE.findall(sanitize_wikilink_labels(page["text"])):
        hit = resolve_catalog_target(target, catalog)
        if hit is not None and hit["rel"] != page["rel"] and hit["ptype"] != "source":
            return hit

    # Then an inbound editorial neighbor.
    neighbors = inbound.get(page["rel"], [])
    if neighbors:
        return sorted(neighbors, key=lambda item: item["rel"])[0]

    # Prefer a category index in the same content type when tags overlap.
    page_tags = {str(tag).casefold() for tag in (page.get("meta", {}).get("tags") or [])}
    candidates = [
        item for item in catalog
        if item["ptype"] == page["ptype"] and item["rel"] != page["rel"] and item["ptype"] != "source"
    ]
    def score(item: dict[str, Any]) -> tuple[int, int, str]:
        tags = {str(tag).casefold() for tag in (item.get("meta", {}).get("tags") or [])}
        overlap = len(page_tags & tags)
        is_index = int(Path(item["rel"]).name.startswith("index-"))
        return (overlap, is_index, item["rel"])
    if candidates:
        return max(candidates, key=score)
    raise RuntimeError(f"no related curated page available for {page['rel']}")


def build_inbound(catalog: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    inbound: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for source in catalog:
        if source["ptype"] == "source":
            continue
        text = re.sub(r"(?ms)(?:^|\n)## Linked from\s*\n.*?(?=\n## |\Z)", "\n", source["text"])
        for target in WIKILINK_RE.findall(sanitize_wikilink_labels(text)):
            hit = resolve_catalog_target(target, catalog)
            if hit is not None and hit["rel"] != source["rel"] and source not in inbound[hit["rel"]]:
                inbound[hit["rel"]].append(source)
    return inbound


def ensure_related_last(
    page: dict[str, Any], preamble: list[str], sections: list[dict[str, Any]], catalog: list[dict[str, Any]], inbound: dict[str, list[dict[str, Any]]]
) -> tuple[list[str], list[dict[str, Any]]]:
    related_content: list[str] = []
    linked_content: list[str] = []
    main: list[dict[str, Any]] = []
    for section in sections:
        normalized = norm_heading(section["title"])
        terminal_name = re.sub(r"\s+\(\d+\)$", "", normalized)
        if terminal_name == "related":
            if related_content and substantive(section["content"]):
                related_content.append("")
            related_content.extend(section["content"])
        elif terminal_name == "linked from":
            if linked_content and substantive(section["content"]):
                linked_content.append("")
            linked_content.extend(section["content"])
        else:
            main.append(section)

    related_text = sanitize_wikilink_labels("\n".join(related_content).strip())
    if "[[" in related_text and not WIKILINK_RE.search(related_text):
        related_text = related_text.replace("[[", "").replace("]]", "")
    if not WIKILINK_RE.search(related_text):
        target = pick_related(page, catalog, inbound)
        target_path = target["rel"].removesuffix(".md")
        related_text = (related_text + "\n" if related_text else "") + f"- [[{target_path}|{target['title']}]]"

    linked_text = sanitize_wikilink_labels("\n".join(linked_content).strip())
    if linked_text:
        main.append({"title": "Linked from", "content": linked_text.splitlines()})
    main.append({"title": "Related", "content": related_text.splitlines()})
    return preamble, main


def transform_page(page: dict[str, Any], catalog: list[dict[str, Any]], inbound: dict[str, list[dict[str, Any]]]) -> tuple[str, dict[str, Any]]:
    text = page["text"]
    fm = FRONTMATTER_RE.match(text)
    if fm is None:
        raise ValueError("missing frontmatter")
    frontmatter = fm.group(0).rstrip("\n")
    body = text[fm.end():]
    body = sanitize_wikilink_labels(body)
    body, title = ensure_one_h1(body, page["stem"])
    preamble, sections = split_h2(body)
    preamble, sections = ensure_profile_sections(preamble, sections, page["ptype"])
    preamble, sections = ensure_related_last(page, preamble, sections, catalog, inbound)
    body = render_sections(preamble, sections)
    body = normalize_headings(body)
    body = sanitize_wikilink_labels(body)
    transformed = f"{frontmatter}\n\n{body}"
    transformed = limit_section_wikilinks(transformed, "Related")
    transformed = limit_section_wikilinks(transformed, "Linked from")
    report = validate_page_structure(
        transformed,
        page["ptype"],
        mode="strict",
        expected_title=title,
    )
    return transformed, report


def atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.structure-migrate-{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", default=os.environ.get("OBSIDIAN_VAULT_PATH", "/Volumes/DATA/agent-vault"))
    parser.add_argument("--apply", action="store_true", help="write validated transformations")
    args = parser.parse_args()

    store = MemoryStore(args.vault)
    vault = store.vault
    catalog = [page for page in vault.load_pages() if page["ptype"] in PROFILE_SECTIONS]
    inbound = build_inbound(catalog)

    changed: list[str] = []
    unchanged: list[str] = []
    failed: list[dict[str, Any]] = []

    for page in catalog:
        try:
            transformed, report = transform_page(page, catalog, inbound)
            if not report["valid"]:
                failed.append({"path": page["rel"], "errors": report["errors"], "warnings": report["warnings"]})
                continue
            if transformed == page["text"]:
                unchanged.append(page["rel"])
                continue
            changed.append(page["rel"])
            if args.apply:
                atomic_write(page["path"], transformed)
        except Exception as exc:  # noqa: BLE001
            failed.append({"path": page["rel"], "error": str(exc)})

    if args.apply and changed:
        vault.rebuild_index()
        vault.append_log("LINT", f"structure migration: normalized {len(changed)} curated pages", quiet=True)

    result = {
        "mode": "apply" if args.apply else "dry-run",
        "pages": len(catalog),
        "changed": len(changed),
        "unchanged": len(unchanged),
        "failed": len(failed),
        "failed_pages": failed,
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
