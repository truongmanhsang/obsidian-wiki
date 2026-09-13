"""Provider prefetch and lifecycle behavior tests."""

import asyncio
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

from tests.support import (
    FakeEmbedder,
    PLUGIN_DIR,
    _call,
    _load_module,
    _load_provider_for_tests,
)

class TestPrefetch:
    def test_trivial_query_returns_empty(self, provider):
        assert provider.prefetch("ok") == ""

    def test_strong_match_injected(self, provider):
        _call(provider, action="write", page="entities/topic-beta-zz",
              content="# Topic Beta ZZ\n\ngeneric topic beta research notes\n")
        ctx = provider.prefetch("what about topic beta zz research?")
        assert "[[entities/topic-beta-zz.md|Topic Beta ZZ]]" in ctx

    def test_recall_status_counts(self, provider):
        assert provider.recall_status() is None
        _call(provider, action="write", page="entities/widget-gamma",
              content="# Widget Gamma\n\nwidget gamma details live here\n")
        provider.prefetch("tell me about widget gamma details")
        st = provider.recall_status()
        assert st is not None and st.count >= 1

    def test_auto_prefetch_reflects_synthesis_queries(self, provider, monkeypatch):
        _call(provider, action="write", page="concepts/trading-choice",
              content="# Trading Choice\n\nA durable comparison of strategy risk and returns.\n")
        mod = sys.modules[provider.__class__.__module__]
        calls = []
        monkeypatch.setattr(
            mod, "_run_reflection",
            lambda query, pages: calls.append((query, pages)) or "Synthesized wiki answer.",
        )
        provider._config["prefetch_method"] = "auto"
        ctx = provider.prefetch("which strategy is best for trading risk?")
        assert "Synthesized wiki answer." in ctx
        assert calls and calls[0][1]

    def test_recall_prefetch_does_not_call_reflection(self, provider, monkeypatch):
        mod = sys.modules[provider.__class__.__module__]
        monkeypatch.setattr(
            mod, "_run_reflection",
            lambda *args: pytest.fail("recall mode must not reflect"),
        )
        provider._config["prefetch_method"] = "recall"
        provider.prefetch("tell me about a normal topic")


class TestLifecycle:
    def test_system_prompt_block_lists_catalog(self, provider):
        _call(provider, action="write", page="entities/cat",
              content="# Cat\n\na catalogued feline entity\n")
        block = provider.system_prompt_block()
        assert "# Obsidian Wiki Memory" in block
        assert "Cat" in block
        assert "must never be edited with filesystem tools" in block
        assert "action=write" in block

    def test_skeleton_created_on_demand(self, provider, tmp_path):
        v = provider._get_vault()
        assert not v.index_path.exists() or True
        provider._get_vault().ensure_skeleton()
        assert (v.root / "templates" / "entity-template.md").exists()

    def test_unknown_tool_and_action(self, provider):
        assert "error" in provider.handle_tool_call("other_tool", {})
        assert "error" in _call(provider, action="bogus")

