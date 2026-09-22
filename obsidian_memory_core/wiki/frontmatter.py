"""Safe YAML frontmatter parsing and serialization helpers."""

from __future__ import annotations

from datetime import date, datetime
import re
from typing import Any

import yaml


FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
MANAGED_KEYS = ("type", "updated", "tags", "aliases")


def _normalize_yaml_value(value: Any) -> Any:
    """Convert YAML date objects to the string values used by the wiki API."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _normalize_yaml_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_yaml_value(item) for item in value]
    return value


def _legacy_parse(fm_block: str) -> dict[str, Any]:
    """Best-effort parser for old or malformed scalar/list frontmatter."""
    meta: dict[str, Any] = {}
    current_list_key: str | None = None
    for line in fm_block.splitlines():
        if not line.strip():
            continue
        if current_list_key is not None:
            match = re.match(r"^\s*-\s*(.*)$", line)
            if match is not None:
                item = match.group(1).strip().strip("'\"")
                if item:
                    if not isinstance(meta.get(current_list_key), list):
                        meta[current_list_key] = []
                    meta[current_list_key].append(item)
                continue
            if ":" in line and not line.startswith((" ", "\t", "-")):
                current_list_key = None
            elif line.startswith((" ", "\t")):
                continue
            else:
                current_list_key = None
        if ":" not in line or line.startswith((" ", "-", "\t")):
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if key in ("tags", "aliases"):
            if value in ("", "[]"):
                meta[key] = []
                current_list_key = key if value == "" else None
            elif value.startswith("[") and value.endswith("]"):
                inner = value[1:-1].strip()
                meta[key] = [
                    part.strip().strip("'\"")
                    for part in inner.split(",")
                    if part.strip()
                ] if inner else []
                current_list_key = None
            else:
                meta[key] = [value.strip("'\"")] if value else []
                current_list_key = None
        else:
            meta[key] = value.strip("'\"") if value else ""
            current_list_key = None
    return meta


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Return a safe YAML metadata mapping and body without frontmatter.

    Valid YAML mappings are parsed with ``safe_load``. Legacy scalar/list
    syntax remains readable when a page contains malformed YAML, but arbitrary
    YAML constructors are never enabled.
    """
    body = text
    match = FRONTMATTER_RE.match(text)
    if match is None:
        return {}, body
    body = text[match.end():]
    fm_block = match.group(1)
    try:
        loaded = yaml.safe_load(fm_block)
    except yaml.YAMLError:
        return _legacy_parse(fm_block), body
    if not isinstance(loaded, dict):
        return _legacy_parse(fm_block), body
    return _normalize_yaml_value(loaded), body


def _yaml_single_quote(value: object) -> str:
    """Render one managed list scalar without allowing punctuation to alter YAML."""
    return "'" + str(value).replace("'", "''") + "'"


def _format_yaml_list(key: str, values: list[Any]) -> str:
    """Render tags/aliases as the established readable block list."""
    lines = [f"{key}:"]
    lines.extend(f"  - {_yaml_single_quote(value)}" for value in values)
    return "\n".join(lines)


def serialize_frontmatter(meta: dict[str, Any]) -> str:
    """Serialize metadata while keeping managed keys stable and extras intact."""
    normalized = _normalize_yaml_value(meta)
    keys = [key for key in MANAGED_KEYS if key in normalized]
    keys.extend(key for key in normalized if key not in MANAGED_KEYS)
    lines = ["---"]
    for key in keys:
        value = normalized[key]
        if key in ("tags", "aliases") and isinstance(value, list):
            lines.append(_format_yaml_list(key, value))
            continue
        if key == "type" and isinstance(value, str):
            lines.append(f"type: {value}")
            continue
        if key == "updated" and isinstance(value, str):
            lines.append(f"updated: {value}")
            continue
        rendered = yaml.safe_dump(
            {key: value},
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        ).rstrip("\n")
        lines.extend(rendered.splitlines())
    lines.append("---")
    return "\n".join(lines)


def _parse_aliases_list(page: dict) -> list[str]:
    """Extract aliases from a loaded page dict, including legacy strings."""
    raw = page.get("meta", {}).get("aliases")
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    if isinstance(raw, str) and raw.strip():
        value = raw.strip()
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            if not inner:
                return []
            return [part.strip().strip("'\"") for part in inner.split(",") if part.strip()]
        return [part.strip().strip("'\"") for part in value.split(",") if part.strip()]
    try:
        fm_meta, _ = parse_frontmatter(page.get("text", ""))
        aliases = fm_meta.get("aliases")
        if isinstance(aliases, list):
            return [str(x).strip() for x in aliases if str(x).strip()]
    except Exception:
        pass
    return []


def page_title(body: str, fallback: str) -> str:
    for line in body.splitlines():
        if line.startswith("# ") and len(line) > 2:
            return line[2:].strip()
    return fallback
