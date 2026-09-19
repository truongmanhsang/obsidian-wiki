"""Pure Markdown structure validation for Obsidian Wiki pages."""

from __future__ import annotations

import re
from typing import Any

from .frontmatter import FRONTMATTER_RE, parse_frontmatter
from .links import WIKILINK_RE


HEADING_RE = re.compile(r"^(?P<marks>#{1,6})[ \t]+(?P<title>\S(?:.*\S)?)\s*$")
FENCE_RE = re.compile(r"^[ \t]*(```+|~~~+)")
INLINE_LINK_START_RE = re.compile(r"\[\[")

PROFILES: dict[str, tuple[tuple[str, ...], ...]] = {
    "concept": (("summary", "overview"), ("core content", "explanation")),
    "decision": (("context",), ("decision",), ("rationale",)),
    "answer": (("answer", "recommendation"), ("evidence", "basis")),
    "entity": (("overview", "identity"), ("details", "facts")),
    "person": (("identity", "overview"), ("details", "facts")),
    "environment": (("scope",), ("configuration", "facts")),
    "preference": (("preference",), ("rationale",)),
    "source": (),
}

TERMINAL_HEADINGS = {"related", "sources", "linked from"}
REQUIRED_FRONTMATTER = ("type", "updated", "tags", "aliases")


def _normalize_heading(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def _issue(code: str, message: str, line: int | None = None) -> dict[str, Any]:
    return {"code": code, "message": message, "line": line}


def _frontmatter_line_count(content: str) -> int:
    match = FRONTMATTER_RE.match(content)
    if not match:
        return 0
    return match.group(0).count("\n")


def scan_headings(body: str) -> list[dict[str, Any]]:
    """Return Markdown headings outside fenced code blocks."""
    headings: list[dict[str, Any]] = []
    in_fence = False
    fence_marker = ""
    for offset, line in enumerate(body.splitlines(), start=1):
        fence = FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)[0]
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif marker == fence_marker:
                in_fence = False
                fence_marker = ""
            continue
        if in_fence:
            continue
        match = HEADING_RE.match(line)
        if match:
            headings.append(
                {
                    "level": len(match.group("marks")),
                    "title": match.group("title").strip(),
                    "normalized": _normalize_heading(match.group("title")),
                    "line": offset,
                }
            )
    return headings


def _section_content(body: str, headings: list[dict[str, Any]], index: int) -> str:
    lines = body.splitlines()
    start = headings[index]["line"]
    end = headings[index + 1]["line"] if index + 1 < len(headings) else len(lines) + 1
    return "\n".join(lines[start:end - 1]).strip()


def add_frontmatter_issues(meta: dict[str, Any], errors: list[dict[str, Any]]) -> None:
    for key in REQUIRED_FRONTMATTER:
        if key not in meta:
            errors.append(_issue("missing_frontmatter", f"missing frontmatter field: {key}"))
    if "updated" in meta and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(meta["updated"]).strip()):
        errors.append(_issue("invalid_frontmatter", "updated must use YYYY-MM-DD format"))


def add_heading_issues(
    headings: list[dict[str, Any]],
    body: str,
    expected_title: str | None,
    errors: list[dict[str, Any]],
    *,
    source: bool = False,
) -> None:
    if source:
        return
    h1 = [heading for heading in headings if heading["level"] == 1]
    if not h1:
        errors.append(_issue("missing_h1", "curated pages require exactly one level-one heading"))
    elif len(h1) > 1:
        for heading in h1[1:]:
            errors.append(_issue("multiple_h1", "curated pages may contain only one level-one heading", heading["line"]))

    if expected_title and h1:
        expected = _normalize_heading(expected_title)
        if expected and h1[0]["normalized"] != expected:
            errors.append(_issue(
                "title_mismatch",
                f"level-one heading '{h1[0]['title']}' does not match expected title '{expected_title}'",
                h1[0]["line"],
            ))

    previous_level = 0
    seen: dict[str, dict[str, Any]] = {}
    for heading in headings:
        level = heading["level"]
        if previous_level and level > previous_level + 1:
            errors.append(_issue(
                "heading_level_skip",
                f"heading level jumps from H{previous_level} to H{level}",
                heading["line"],
            ))
        previous_level = level

        normalized = heading["normalized"]
        if normalized == "linked from":
            continue
        if normalized in seen:
            errors.append(_issue(
                "duplicate_heading",
                f"heading '{heading['title']}' duplicates line {seen[normalized]['line']}",
                heading["line"],
            ))
        else:
            seen[normalized] = heading

    for index, heading in enumerate(headings):
        if heading["level"] == 1 or heading["normalized"] in TERMINAL_HEADINGS:
            continue
        if not _section_content(body, headings, index):
            errors.append(_issue(
                "empty_section",
                f"section '{heading['title']}' has no content",
                heading["line"],
            ))


def _heading_matches_group(normalized: str, options: tuple[str, ...]) -> bool:
    return any(
        normalized == option or normalized.endswith(f" {option}")
        for option in options
    )


def add_profile_issues(
    page_type: str,
    headings: list[dict[str, Any]],
    body: str,
    mode: str,
    errors: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> None:
    if page_type not in PROFILES:
        target = errors if mode != "lint" else warnings
        target.append(_issue("unknown_page_type", f"unknown page type: {page_type}"))
        return
    if page_type == "source":
        return

    normalized_headings = [heading["normalized"] for heading in headings]
    intro = ""
    if headings:
        h1_index = next(
            (index for index, heading in enumerate(headings) if heading["level"] == 1),
            None,
        )
        if h1_index is not None:
            intro = _section_content(body, headings, h1_index)

    for index, options in enumerate(PROFILES[page_type]):
        found = any(_heading_matches_group(heading, options) for heading in normalized_headings)
        if index == 0 and not found and intro:
            found = True
        if found:
            continue
        names = " or ".join(options)
        target = errors if mode != "lint" else warnings
        target.append(_issue(
            "missing_profile_section",
            f"{page_type} pages require section: {names}",
        ))

    if "related" not in normalized_headings:
        target = errors if mode != "lint" else warnings
        target.append(_issue("missing_related", "curated pages require a ## Related section"))


def add_link_syntax_issues(body: str, errors: list[dict[str, Any]]) -> None:
    unmatched = body.count("[[") - len(WIKILINK_RE.findall(body))
    if unmatched > 0:
        errors.append(_issue("invalid_wikilink", "one or more wikilinks are not closed with ]]"))


def validate_page_structure(
    content: str,
    page_type: str,
    *,
    mode: str = "strict",
    expected_title: str | None = None,
) -> dict[str, Any]:
    """Validate Markdown structure without reading or mutating a vault."""
    if mode not in {"strict", "legacy", "lint"}:
        raise ValueError(f"unsupported structure validation mode: {mode}")
    if not isinstance(content, str):
        return {
            "valid": False,
            "mode": mode,
            "errors": [_issue("invalid_structure", "page content must be text")],
            "warnings": [],
        }

    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    match = FRONTMATTER_RE.match(content)
    if not match:
        errors.append(_issue("missing_frontmatter", "page must begin with YAML frontmatter"))
        meta, body = {}, content
    else:
        meta, body = parse_frontmatter(content)

    add_frontmatter_issues(meta, errors)
    if meta.get("type") and str(meta["type"]).casefold() != str(page_type).casefold():
        errors.append(_issue(
            "type_mismatch",
            f"frontmatter type '{meta['type']}' conflicts with page type '{page_type}'",
        ))

    headings = scan_headings(body)
    add_heading_issues(
        headings,
        body,
        expected_title,
        errors,
        source=page_type == "source",
    )
    add_profile_issues(page_type, headings, body, mode, errors, warnings)
    add_link_syntax_issues(body, errors)

    return {
        "valid": not errors,
        "mode": mode,
        "errors": errors,
        "warnings": warnings,
    }
