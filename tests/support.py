"""Shared test helpers for the Obsidian Wiki test suite."""

import importlib.util
import json
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


def _call(provider, **args):
    return json.loads(provider.handle_tool_call("obsidian_wiki", args))

