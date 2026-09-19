"""Shared test helpers for the Obsidian Wiki test suite."""

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__import__("os").environ.get(
    "OBSIDIANWIKI_PLUGIN_DIR", str(Path(__file__).resolve().parents[1])
))


class FakeEmbedder:
    """Deterministic stand-in for fastembed in unit tests."""

    def embed(self, texts):
        vectors = []
        for text in texts:
            low = text.casefold()
            vectors.append([
                float("partner" in low or "partner" in low),
                float("trading" in low or "risk" in low),
            ])
        return vectors


def _load_module():
    if str(PLUGIN_DIR) not in sys.path:
        sys.path.insert(0, str(PLUGIN_DIR))
    spec = importlib.util.spec_from_file_location(
        "obsidianwiki_under_test", PLUGIN_DIR / "__init__.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["obsidianwiki_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_provider_for_tests(tmp_path):
    module = _load_module()
    return module.ObsidianWikiMemoryProvider({
        "vault_path": str(tmp_path / "vault"),
        "access_mode": "direct",
    })


def valid_page_content(page, content):
    """Add the smallest valid profile sections to legacy test fixtures."""
    if not isinstance(content, str) or len(content.strip()) < 10:
        return content
    if page.split("/", 1)[0] == "sources":
        return content
    body = re.sub(r"(?s)^---\n.*?\n---\n", "", content, count=1)
    if not re.search(r"(?m)^#\s+\S", body):
        return content
    page_type = {
        "entities": "entity",
        "people": "person",
        "decisions": "decision",
        "environment": "environment",
        "concepts": "concept",
        "answers": "answer",
        "preferences": "preference",
    }.get(page.split("/", 1)[0], "concept")
    requirements = {
        "concept": [("Core Content", "Core test content.")],
        "entity": [("Details", "Entity test details.")],
        "person": [("Details", "Person test details.")],
        "decision": [("Context", "Decision test context."), ("Decision", "Decision test choice."), ("Rationale", "Decision test rationale.")],
        "answer": [("Answer", "Answer test result."), ("Evidence", "Answer test evidence.")],
        "environment": [("Scope", "Environment test scope."), ("Configuration", "Environment test configuration.")],
        "preference": [("Preference", "Preference test value."), ("Rationale", "Preference test rationale.")],
    }[page_type]
    additions = []
    normalized = {re.sub(r"\s+", " ", h.casefold()) for h in re.findall(r"(?m)^##\s+(.+?)\s*$", body)}
    for heading, text in requirements:
        if heading.casefold() not in normalized and not any(
            normalized_heading.endswith(f" {heading.casefold()}")
            for normalized_heading in normalized
        ):
            additions.extend([f"## {heading}", "", text, ""])
    if "related" not in normalized:
        additions.extend(["## Related", ""])
    if not additions:
        return content
    addition = "\n".join(additions).rstrip() + "\n"
    terminal = re.search(r"(?m)^## (?:Related|Sources|Linked from)\s*$", body)
    if terminal:
        insert_at = content.find(terminal.group(0))
        return content[:insert_at].rstrip() + "\n\n" + addition + "\n" + content[insert_at:]
    return content.rstrip() + "\n\n" + addition


def _call(provider, **args):
    if args.get("action") == "write" and not args.pop("_raw_structure", False):
        args["content"] = valid_page_content(args.get("page", ""), args.get("content", ""))
    return json.loads(provider.handle_tool_call("obsidian_wiki", args))
