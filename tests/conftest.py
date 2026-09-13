"""Shared pytest fixtures for the Obsidian Wiki test suite."""

import pytest

from tests.support import PLUGIN_DIR, _load_module


@pytest.fixture(autouse=True)
def disable_live_navigation_llm(monkeypatch):
    """Keep repository tests deterministic and free of external model calls."""
    try:
        from agent import oneshot
    except ImportError:
        return

    def fail(_prompt, **_kwargs):
        raise RuntimeError("live navigation LLM disabled in tests")

    monkeypatch.setattr(oneshot, "run_oneshot", fail)


@pytest.fixture()
def provider(tmp_path):
    if not PLUGIN_DIR.is_dir():
        pytest.skip("obsidianwiki plugin not installed")
    mod = _load_module()
    instance = mod.ObsidianWikiMemoryProvider({
        "vault_path": str(tmp_path / "v"),
        "access_mode": "direct",
    })
    instance.initialize(session_id="test")
    return instance

