"""LLM proposals for the wiki's root navigation index."""
from __future__ import annotations

import json
import re
from typing import Any, Callable

import yaml

from .frontmatter import FRONTMATTER_RE
from .links import WIKILINK_RE


RunLLM = Callable[[str], object]


def _default_run_llm(prompt: str) -> object:
    """Use Hermes' configured one-shot runtime without importing it at load time."""
    from agent.oneshot import run_oneshot

    return run_oneshot(
        instructions=prompt,
        user_input="",
        task="memory_navigation_generation",
        max_tokens=1800,
        temperature=0.2,
        timeout=90.0,
    )


def _payload(raw: object) -> dict[str, Any] | None:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _error(code: str) -> dict[str, Any]:
    return {"error": code}


def _run(prompt: str, run_llm: RunLLM | None) -> dict[str, Any] | None:
    try:
        return _payload((run_llm or _default_run_llm)(prompt))
    except Exception:
        return None


def _index_prompt(manifest: list[dict[str, Any]]) -> str:
    return (
        "Generate an Obsidian Wiki index as JSON with one string field content. "
        "The content must be Markdown with valid index frontmatter and links only "
        "to paths in the supplied authoritative manifest. Include every manifest "
        "page exactly once and do not invent paths or facts.\n\n"
        f"Manifest JSON:\n{json.dumps(manifest, ensure_ascii=False, sort_keys=True)}"
    )


def _canonical_link(link: str) -> str:
    path = re.split(r"[|#]", link.strip(), maxsplit=1)[0].strip()
    path = path.replace("\\", "/")
    if path.endswith(".md"):
        path = path[:-3]
    return f"{path}.md"


def _validate_index(content: object, manifest: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(content, str) or not content.strip():
        return _error("invalid_content")
    match = FRONTMATTER_RE.match(content)
    if match is None:
        return _error("invalid_frontmatter")
    try:
        metadata = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return _error("invalid_frontmatter")
    if not isinstance(metadata, dict) or str(metadata.get("type", "")).lower() != "index":
        return _error("invalid_frontmatter")
    required = ("title", "updated", "tags")
    if any(not str(metadata.get(key, "")).strip() for key in required):
        return _error("invalid_frontmatter")
    manifest_paths = {
        _canonical_link(str(page.get("path", "")))
        for page in manifest
        if page.get("path")
    }
    link_paths = [_canonical_link(link) for link in WIKILINK_RE.findall(content)]
    links = set(link_paths)
    unknown = sorted(link for link in links if link not in manifest_paths)
    if unknown:
        return _error("invalid_link")
    duplicates = sorted({link for link in links if link_paths.count(link) > 1})
    if duplicates:
        return _error("duplicate_link")
    if manifest_paths - links:
        return _error("missing_page")
    return {"content": content}


def generate_index_proposal(
    manifest: list[dict[str, Any]],
    run_llm: RunLLM | None = None,
) -> dict[str, Any]:
    """Return a validated root-index proposal or a stable error code."""
    payload = _run(_index_prompt(manifest), run_llm)
    if payload is None:
        return _error("llm_unavailable")
    return _validate_index(payload.get("content"), manifest)


__all__ = ["generate_index_proposal"]
