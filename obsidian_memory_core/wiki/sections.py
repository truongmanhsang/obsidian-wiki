"""Helpers for bounded generated/editorial navigation sections."""

from __future__ import annotations

import re

MAX_SECTION_WIKILINKS = 10
_WIKILINK_TOKEN_RE = re.compile(r"\[\[[^\]\n]+\]\]")


def limit_section_wikilinks(markdown: str, heading: str, limit: int = MAX_SECTION_WIKILINKS) -> str:
    """Keep at most ``limit`` wikilink occurrences inside one H2 section.

    Order and ordinary prose are preserved. The function is intentionally a
    no-op when a section is already within the limit, so migrations only touch
    pages that actually exceed the configured cap.
    """
    if limit < 0:
        raise ValueError("limit must be non-negative")

    pattern = re.compile(
        rf"(?ms)(^## {re.escape(heading)}\s*$\n)(.*?)(?=^## |\Z)"
    )

    def replace(match: re.Match[str]) -> str:
        header = match.group(1)
        body = match.group(2)
        if len(_WIKILINK_TOKEN_RE.findall(body)) <= limit:
            return match.group(0)

        trailing_newlines = len(body) - len(body.rstrip("\n"))
        kept = 0
        output: list[str] = []
        for line in body.splitlines():
            matches = list(_WIKILINK_TOKEN_RE.finditer(line))
            if not matches:
                output.append(line)
                continue

            cursor = 0
            pieces: list[str] = []
            kept_on_line = 0
            for link_match in matches:
                pieces.append(line[cursor:link_match.start()])
                if kept < limit:
                    pieces.append(link_match.group(0))
                    kept += 1
                    kept_on_line += 1
                cursor = link_match.end()
            pieces.append(line[cursor:])
            new_line = "".join(pieces).rstrip()

            if kept_on_line:
                output.append(new_line)
                continue

            # Drop a link-only bullet after the cap; preserve explanatory text.
            prose = re.sub(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)?", "", new_line).strip()
            prose = prose.strip("-–—:;,.()[] ")
            if prose:
                output.append(new_line)

        while output and not output[-1].strip():
            output.pop()
        trailing = "\n" * max(1, trailing_newlines)
        return header + "\n".join(output) + trailing

    return pattern.sub(replace, markdown)
