"""MCP server and provider adapter behavior tests."""

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
    valid_page_content,
)


def _tool_function(tool):
    """Unwrap FastMCP FunctionTool while supporting older FastMCP releases."""
    return getattr(tool, "fn", tool)


def _registered_tool_names(server):
    """Return registered tool names across supported FastMCP APIs."""
    get_tools = getattr(server, "get_tools", None)
    manager = getattr(server, "_tool_manager", None)
    if get_tools is not None:
        tools = asyncio.run(get_tools())
    else:
        manager_get_tools = getattr(manager, "get_tools", None)
        tools = asyncio.run(manager_get_tools()) if manager_get_tools is not None else {}

    # Some FastMCP releases expose an empty async result before lazy loading;
    # the registered tool map remains the reliable fallback for this contract.
    if not tools:
        tools = getattr(manager, "_tools", {})
    return set(tools)


def test_mcp_exposes_read_and_write_tools():
    from mcp_server import mcp

    names = _registered_tool_names(mcp)
    assert {"memory_search", "memory_reflect", "memory_read", "memory_write", "memory_append", "memory_ingest_submit", "memory_ingest_status"}.issubset(names)


def test_mcp_memory_write_reports_invalid_revision_format(monkeypatch, tmp_path):
    import mcp_server

    monkeypatch.setattr(mcp_server, "_SERVER_VAULT_PATH", str(tmp_path / "vault"))
    write = _tool_function(mcp_server.memory_write)
    write(
        "concepts/mcp-format",
        valid_page_content("concepts/mcp-format", "# MCP Format\n\nBody.\n"),
    )
    result = write(
        "concepts/mcp-format",
        "# Must Not Persist\n",
        expected_revision="0" * 63,
    )

    assert result == {
        "error": "invalid_revision_format",
        "message": "invalid expected_revision format; expected 64 lowercase hexadecimal characters",
    }


def test_mcp_memory_write_reports_structure_validation(monkeypatch, tmp_path):
    import mcp_server

    monkeypatch.setattr(mcp_server, "_SERVER_VAULT_PATH", str(tmp_path / "vault"))
    write = _tool_function(mcp_server.memory_write)
    result = write("concepts/invalid-structure", "# Invalid\n\nOnly an intro.\n")

    assert result["error"] == "structure_validation"
    assert result["page"] == "concepts/invalid-structure.md"
    assert "missing_profile_section" in {
        issue["code"] for issue in result["validation"]["warnings"] + result["validation"]["errors"]
    }


def test_mcp_memory_append_reports_structure_validation(monkeypatch, tmp_path):
    import mcp_server

    monkeypatch.setattr(mcp_server, "_SERVER_VAULT_PATH", str(tmp_path / "vault"))
    write = _tool_function(mcp_server.memory_write)
    append = _tool_function(mcp_server.memory_append)
    created = write(
        "concepts/append-structure",
        "# Append Structure\n\nSummary.\n\n## Core Content\n\nOriginal.\n\n## Related\n",
    )
    result = append(
        "concepts/append-structure",
        "## Core Content\n\nDuplicate heading.\n",
        expected_revision=created["revision"],
    )

    assert result["error"] == "structure_validation"
    assert "duplicate_heading" in {
        issue["code"] for issue in result["validation"]["errors"]
    }


def test_mcp_reflect_tool_returns_grounded_sources(monkeypatch, tmp_path):
    import mcp_server

    mcp_server._SERVER_VAULT_PATH = str(tmp_path / "vault")
    store = mcp_server._store(prepare=True)
    store.write("people/test-user", valid_page_content("people/test-user", "# Test User\n\nPrefers concise replies.\n"))
    monkeypatch.setattr(mcp_server, "_run_reflection", lambda query, pages: "Grounded answer")
    result = _tool_function(mcp_server.memory_reflect)("What does Test User prefer?", limit=3)
    assert result["reflection"] == "Grounded answer"
    assert result["sources"]


def test_codex_provider_reads_cli_auth_without_hermes_auth(monkeypatch, tmp_path):
    from obsidian_memory_core.reflect import CodexProvider

    auth_path = tmp_path / "codex-auth.json"
    auth_path.write_text(
        json.dumps({"tokens": {"access_token": "access", "account_id": "acct"}}),
        encoding="utf-8",
    )
    captured = {}

    class Response:
        def __iter__(self):
            yield b'event: response.output_text.delta\n'
            yield b'data: {"type":"response.output_text.delta","delta":"Codex answer"}\n'
            yield b'data: [DONE]\n'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode())
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("obsidian_memory_core.reflect.urlopen", fake_urlopen)
    provider = CodexProvider(auth_path=auth_path, model="gpt-test")
    result = provider.reflect("What is the answer?", [{"path": "p", "content": "Fact."}])

    assert result == "Codex answer"
    assert captured["url"] == "https://chatgpt.com/backend-api/codex/responses"
    assert captured["headers"]["Authorization"] == "Bearer access"
    headers = {key.lower(): value for key, value in captured["headers"].items()}
    assert headers["chatgpt-account-id"] == "acct"
    assert captured["body"]["model"] == "gpt-test"
    assert captured["body"]["store"] is False
    assert captured["body"]["stream"] is True


def test_codex_provider_rejects_missing_cli_auth(tmp_path):
    from obsidian_memory_core.reflect import CodexProvider

    with pytest.raises(RuntimeError, match="Codex CLI auth file"):
        CodexProvider(auth_path=tmp_path / "missing.json", model="gpt-test").reflect(
            "Question", []
        )


def test_reflect_returns_synthesis_from_relevant_pages(monkeypatch, tmp_path):
    mod = _load_module()
    provider = mod.ObsidianWikiMemoryProvider({"vault_path": str(tmp_path / "vault"), "access_mode": "direct"})
    provider.initialize(session_id="test")
    _call(provider, action="write", page="people/test-user", content="# Test User\n\nPrefers concise Messaging replies.\n")
    monkeypatch.setattr(mod, "_run_reflection", lambda query, pages: "Test User prefers concise Messaging replies.")
    result = _call(provider, action="reflect", query="What communication style does Test User prefer?")
    assert result["query"] == "What communication style does Test User prefer?"
    assert result["reflection"] == "Test User prefers concise Messaging replies."
    assert result["sources"][0]["path"] == "people/test-user.md"


def test_reflect_requires_query(provider):
    result = _call(provider, action="reflect", query="")
    assert result["error"]


def test_mcp_provider_filters_unrecognized_arguments(monkeypatch, tmp_path):
    mod = _load_module()
    provider = mod.ObsidianWikiMemoryProvider({"vault_path": str(tmp_path / "vault"), "access_mode": "mcp"})
    provider.initialize(session_id="test")
    captured = {}
    monkeypatch.setattr(provider, "_mcp_call", lambda tool, args: captured.update(tool=tool, args=args) or {"results": []})
    result = json.loads(provider.handle_tool_call("obsidian_wiki", {
        "action": "search", "query": "test", "limit": 5, "page": "", "content": "", "note": "", "expected_revision": ""
    }))
    assert result == {"results": []}
    assert captured == {"tool": "memory_search", "args": {"query": "test", "limit": 5}}


def test_hermes_provider_uses_shared_store_revision(tmp_path):
    mod = _load_module()
    provider = mod.ObsidianWikiMemoryProvider({"vault_path": str(tmp_path / "vault"), "access_mode": "direct"})
    provider.initialize(session_id="test")
    created = json.loads(provider.handle_tool_call("obsidian_wiki", {
        "action": "write",
        "page": "concepts/provider",
        "content": valid_page_content(
            "concepts/provider", "# Provider\n\nShared write path content.\n"
        ),
    }))
    revision = json.loads(provider.handle_tool_call("obsidian_wiki", {
        "action": "read", "page": "concepts/provider"
    })) ["revision"]
    assert created["status"] == "created"
    stale = json.loads(provider.handle_tool_call("obsidian_wiki", {
        "action": "write", "page": "concepts/provider", "content": "# Stale\n\nNo overwrite.\n", "expected_revision": "0" * 64
    }))
    assert stale["error"] == "revision_conflict"
    assert revision


def test_hermes_provider_reports_invalid_revision_format(tmp_path):
    mod = _load_module()
    provider = mod.ObsidianWikiMemoryProvider({"vault_path": str(tmp_path / "vault"), "access_mode": "direct"})
    provider.initialize(session_id="test")
    _call(provider, action="write", page="concepts/provider-format", content="# Provider Format\n\nBody.\n")
    result = json.loads(provider.handle_tool_call("obsidian_wiki", {
        "action": "write",
        "page": "concepts/provider-format",
        "content": "# Must Not Persist\n",
        "expected_revision": "0" * 63,
    }))
    assert result["error"] == "invalid expected_revision format; expected 64 lowercase hexadecimal characters"


def test_mcp_memory_lint_accepts_fix_and_dry_run(monkeypatch, tmp_path):
    import mcp_server
    from obsidian_memory_core.store import MemoryStore

    monkeypatch.setattr(mcp_server, "_SERVER_VAULT_PATH", str(tmp_path / "vault"))
    calls = []
    monkeypatch.setattr(
        MemoryStore,
        "fix_orphans",
        lambda self, dry_run=False: calls.append(dry_run) or {"fixed": 0},
    )
    result = _tool_function(mcp_server.memory_lint)(fix=True, dry_run=True)
    assert result["fix_orphans"] == {"fixed": 0}
    assert calls == [True]


def test_mcp_provider_forwards_lint_fix_arguments(monkeypatch, tmp_path):
    mod = _load_module()
    provider = mod.ObsidianWikiMemoryProvider({
        "vault_path": str(tmp_path / "vault"),
        "access_mode": "mcp",
    })
    provider.initialize(session_id="test")
    captured = {}
    monkeypatch.setattr(
        provider,
        "_mcp_call",
        lambda tool, args: captured.update(tool=tool, args=args) or {"clean": True},
    )
    result = json.loads(provider.handle_tool_call("obsidian_wiki", {
        "action": "lint", "fix": True, "dry_run": False,
    }))
    assert result == {"clean": True}
    assert captured == {
        "tool": "memory_lint",
        "args": {"fix": True, "dry_run": False},
    }


def test_direct_lint_fix_defaults_to_dry_run(monkeypatch, tmp_path):
    mod = _load_module()
    provider = mod.ObsidianWikiMemoryProvider({
        "vault_path": str(tmp_path / "vault"),
        "access_mode": "direct",
    })
    provider.initialize(session_id="test")
    calls = []
    monkeypatch.setattr(
        provider._get_vault(),
        "fix_orphans",
        lambda dry_run=False: calls.append(dry_run) or {"fixed": 0},
    )
    result = json.loads(provider.handle_tool_call("obsidian_wiki", {
        "action": "lint", "fix": True,
    }))
    assert result["fix_orphans"] == {"fixed": 0}
    assert calls == [True]
