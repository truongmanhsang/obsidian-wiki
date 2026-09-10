"""LLM proposals for missing wiki navigation artifacts."""
from __future__ import annotations

import json
import re
from pathlib import PurePosixPath
from typing import Any, Callable

import yaml

from .frontmatter import FRONTMATTER_RE
from .links import WIKILINK_RE


RunLLM = Callable[[str], object]


def _default_run_llm(prompt: str) -> object:
    """Use Hermes' configured one-shot runtime without importing it at module load."""
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


def _hub_prompt(context: dict[str, Any]) -> str:
    return (
        "Generate one missing Obsidian Wiki semantic hub. Return JSON only with "
        "string fields path, title, body; an array keywords; and integer priority. "
        "The path must be a new relative concepts/<slug>-hub.md path. Include a "
        "minimal useful Markdown body, but do not invent facts beyond the supplied "
        "page context. Mark the resulting page with lint_hub=true in its frontmatter.\n\n"
        f"Context JSON:\n{json.dumps(context, ensure_ascii=False, sort_keys=True)}"
    )


def _index_prompt(manifest: list[dict[str, Any]]) -> str:
    return (
        "Generate an Obsidian Wiki index as JSON with one string field content. "
        "The content must be Markdown with valid index frontmatter and links only "
        "to paths in the supplied authoritative manifest. Include every manifest "
        "page exactly once and do not invent paths or facts.\n\n"
        f"Manifest JSON:\n{json.dumps(manifest, ensure_ascii=False, sort_keys=True)}"
    )


def _safe_hub_path(path: object, existing_paths: set[str]) -> str | None:
    if not isinstance(path, str):
        return None
    normalized = path.strip().replace("\\", "/")
    candidate = PurePosixPath(normalized)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        return None
    if not re.fullmatch(r"concepts/[a-z0-9][a-z0-9_-]*\.md", normalized):
        return None
    if normalized in existing_paths:
        return None
    return normalized


def _keywords(value: object) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("[") and text.endswith("]"):
            text = text[1:-1]
        value = text.split(",")
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        keyword = str(item).strip().lower()
        if keyword and keyword not in seen:
            seen.add(keyword)
            result.append(keyword)
    return result


def generate_hub_proposal(
    context: dict[str, Any],
    run_llm: RunLLM | None = None,
) -> dict[str, Any]:
    """Return a validated hub proposal or a stable error code."""
    payload = _run(_hub_prompt(context), run_llm)
    if payload is None:
        return _error("llm_unavailable")
    existing = {
        str(path).strip().replace("\\", "/")
        for path in context.get("existing_paths", [])
    }
    path = _safe_hub_path(payload.get("path"), existing)
    if path is None:
        return _error("invalid_path")
    title = str(payload.get("title", "")).strip()
    body = str(payload.get("body", "")).strip()
    keywords = _keywords(payload.get("keywords"))
    if not title:
        return _error("invalid_title")
    if not body:
        return _error("invalid_body")
    if not keywords:
        return _error("invalid_keywords")
    try:
        priority = int(payload.get("priority", 0))
    except (TypeError, ValueError):
        return _error("invalid_priority")
    return {
        "path": path,
        "title": title,
        "body": body,
        "keywords": keywords,
        "priority": priority,
    }


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
    """Return a validated index proposal or a stable error code."""
    payload = _run(_index_prompt(manifest), run_llm)
    if payload is None:
        return _error("llm_unavailable")
    return _validate_index(payload.get("content"), manifest)


__all__ = ["generate_hub_proposal", "generate_index_proposal"]
